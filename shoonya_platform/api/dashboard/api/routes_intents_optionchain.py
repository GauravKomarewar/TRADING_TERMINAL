# ======================================================================
# ROUTES: Intents, Dashboard Home, Option Chain, Diagnostics
# Extracted from router.py during modularisation.
# ======================================================================
from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from typing import List, Optional, Any
from uuid import uuid4
from datetime import datetime
import sqlite3
import time
import logging

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.services.intent_utility import DashboardIntentService
from shoonya_platform.api.dashboard.services.option_chain_service import (
    get_active_expiries,
    get_active_symbols,
    find_nearest_option,
)
from shoonya_platform.api.dashboard.api._shared import (
    logger,
    DATA_DIR,
    get_broker,
    get_system,
    get_intent,
)
from shoonya_platform.api.dashboard.api.schemas import (
    StrategyIntentRequest,
    StrategyAction,
    GenericIntentRequest,
    AdvancedIntentRequest,
    IntentResponse,
    BasketIntentRequest,
    StrategyEntryRequest,
)
import re as _re

sub_router = APIRouter()


def _safe_call(fn, fallback, name: str):
    """Call *fn*(); on failure log a warning and return *fallback*."""
    try:
        return fn()
    except Exception as exc:
        logger.warning("dashboard_snapshot: %s failed: %s", name, exc)
        return fallback

# ==================================================
# STRATEGY ENTRY INTENT
# ==================================================

@sub_router.post(
    "/intent/strategy/entry",
    response_model=IntentResponse,
)
def submit_strategy_entry(
    req: StrategyEntryRequest,
    service: DashboardIntentService = Depends(get_intent),
):
    intent_id = f"DASH-STRAT-ENTRY-{uuid4().hex[:8]}"
    try:
        return service.submit_raw_intent(
            intent_id=intent_id,
            intent_type="STRATEGY",
            payload={
                **req.dict(),
                "action": "ENTRY",
            },
        )
    except Exception as e:
        logger.exception("submit_strategy_entry failed")
        return IntentResponse(
            accepted=False,
            message=f"Entry intent failed: {e}",
            intent_id=intent_id,
        )

# ==================================================
# DASHBOARD SNAPSHOT (HOME)
# ==================================================

@sub_router.get("/home/status")
def dashboard_snapshot(
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    try:
        limits = broker.get_limits()
    except (RuntimeError, Exception) as e:
        logger.warning(f"Failed to get broker limits: {e}, returning empty limits")
        limits = {}

    return {
        "broker": {
            "positions": _safe_call(broker.get_positions, [], "broker.get_positions"),
            "positions_summary": _safe_call(broker.get_positions_summary, {}, "broker.get_positions_summary"),
            "holdings": _safe_call(broker.get_holdings, [], "broker.get_holdings"),
            "limits": limits,
            "orders": _safe_call(broker.get_order_book, [], "broker.get_order_book"),
        },
        "system": {
            "orders": _safe_call(lambda: system.get_orders(200), [], "system.get_orders"),
            "open_orders": _safe_call(system.get_open_orders, [], "system.get_open_orders"),
            "control_intents": _safe_call(lambda: system.get_control_intents(50), [], "system.get_control_intents"),
            "risk": _safe_call(system.get_risk_state, {}, "system.get_risk_state"),
            "heartbeat": _safe_call(system.get_option_data_heartbeat, {}, "system.get_option_data_heartbeat"),
            "signal": _safe_call(system.get_signal_activity, {}, "system.get_signal_activity"),
            "telegram_messages": _safe_call(lambda: system.get_telegram_messages(200), [], "system.get_telegram_messages"),
            "telegram_stats": _safe_call(lambda: system.get_telegram_alert_stats(500), {}, "system.get_telegram_alert_stats"),
        },
    }


# ==================================================
# GENERIC INTENT
# ==================================================

@sub_router.post(
    "/intent/generic",
    response_model=IntentResponse,
    status_code=status.HTTP_200_OK,
)
def submit_generic_intent(
    req: GenericIntentRequest,
    service: DashboardIntentService = Depends(get_intent),
):
    try:
        return service.submit_generic_intent(req)
    except Exception as e:
        logger.exception("Generic intent failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# STRATEGY INTENT
# ==================================================

@sub_router.post(
    "/intent/strategy",
    response_model=IntentResponse,
    status_code=status.HTTP_200_OK,
)
def submit_strategy_intent(
    req: StrategyIntentRequest,
    service: DashboardIntentService = Depends(get_intent),
):
    try:
        return service.submit_strategy_intent(req)
    except Exception as e:
        logger.exception("Strategy intent failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# ADVANCED INTENT
# ==================================================

@sub_router.post(
    "/intent/advanced",
    response_model=IntentResponse,
    status_code=status.HTTP_200_OK,
)
def submit_advanced_intent(
    req: AdvancedIntentRequest,
    service: DashboardIntentService = Depends(get_intent),
):
    try:
        intent_id = f"DASH-ADV-{uuid4().hex[:10]}"
        payload = {
            "legs": [leg.dict() for leg in req.legs],
            "tag": req.reason or "WEB_ADVANCED",
        }

        response = service.submit_raw_intent(
            intent_id=intent_id,
            intent_type="ADVANCED",
            payload=payload,
        )

        return response if response else IntentResponse(
            accepted=True,
            message="Advanced intent queued",
            intent_id=intent_id,
        )

    except Exception as e:
        logger.exception("Advanced intent failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# BASKET INTENT
# ==================================================

@sub_router.post(
    "/intent/basket",
    response_model=IntentResponse,
    status_code=status.HTTP_200_OK,
)
def submit_basket_intent(
    req: BasketIntentRequest,
    service: DashboardIntentService = Depends(get_intent),
):
    try:
        return service.submit_basket_intent(req)
    except Exception as e:
        logger.exception("Basket intent failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# OPTION CHAIN — ACTIVE SYMBOLS (FROM DB FILES)
# ==================================================

@sub_router.get("/option-chain/active-symbols")
def list_active_option_chain_symbols(ctx=Depends(require_dashboard_auth)):
    """Active option-chain symbols derived from supervisor DB files."""
    symbols = get_active_symbols()
    return symbols

# ==================================================
# OPTION CHAIN — ACTIVE EXPIRIES (SUPERVISOR TRUTH)
# ==================================================

@sub_router.get("/option-chain/active-expiries", response_model=List[str])
def list_active_option_chain_expiries(
    exchange: str = Query(..., description="NFO / BFO"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
    ctx=Depends(require_dashboard_auth),
):
    """Active option-chain expiries derived from supervisor DB files."""
    expiries = get_active_expiries(exchange, symbol)

    if not expiries:
        raise HTTPException(
            status_code=404,
            detail=f"No active option chains for {exchange}:{symbol}",
        )

    return expiries

def _validate_option_chain_input(exchange: str, symbol: str, expiry: str) -> str:
    """Validate & sanitize option chain inputs; return safe filename."""
    SUPPORTED_EXCHANGES = {"NFO", "BFO", "MCX"}
    if exchange.upper() not in SUPPORTED_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Invalid exchange '{exchange}'")
    if not _re.fullmatch(r'[A-Za-z0-9_-]{1,40}', symbol):
        raise HTTPException(status_code=400, detail=f"Invalid symbol '{symbol}'")
    if not _re.fullmatch(r'[A-Za-z0-9_-]{1,20}', expiry):
        raise HTTPException(status_code=400, detail=f"Invalid expiry '{expiry}'")
    name = f"{exchange.upper()}_{symbol}_{expiry}.sqlite"
    resolved = (DATA_DIR / name).resolve()
    if not resolved.is_relative_to(DATA_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Path traversal detected")
    return name


@sub_router.get("/option-chain")
def get_option_chain(
    exchange: str = Query(..., description="NFO / BFO / MCX"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
    expiry: str = Query(..., description="24-FEB-2026"),
    max_age: float = Query(
        300.0,
        description="Maximum allowed snapshot age in seconds (300 = 5 min)",
    ),
    ctx=Depends(require_dashboard_auth),
):
    """Canonical Option Chain API (READ-ONLY)."""

    safe_name = _validate_option_chain_input(exchange, symbol, expiry)
    db_file = DATA_DIR / safe_name

    if not db_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Option chain DB not found for {exchange}:{symbol}:{expiry}",
        )

    conn = sqlite3.connect(db_file, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        # META
        meta_rows = cur.execute(
            "SELECT key, value FROM meta"
        ).fetchall()
        meta = {row["key"]: row["value"] for row in meta_rows}

        snapshot_ts = float(meta.get("snapshot_ts", 0))
        age = time.time() - snapshot_ts

        meta["snapshot_age"] = round(age, 1)
        meta["is_stale"] = age > max_age

        # OPTION CHAIN (FULL CONTRACT)
        rows = cur.execute(
            """
            SELECT
                strike,
                option_type,

                token,
                trading_symbol,
                exchange,
                lot_size,

                ltp,
                change_pct,
                volume,
                oi,
                open,
                high,
                low,
                close,
                bid,
                ask,
                bid_qty,
                ask_qty,

                last_update,

                -- Greeks (persisted, may be NULL)
                iv,
                delta,
                gamma,
                theta,
                vega
            FROM option_chain
            ORDER BY strike ASC, option_type
            """
        ).fetchall()
    finally:
        conn.close()

    return {
        "meta": meta,
        "rows": [dict(r) for r in rows],
    }


@sub_router.get("/option-chain/nearest")
def get_nearest_option(
    exchange: str = Query(..., description="NFO / BFO / MCX"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
    expiry: str = Query(..., description="24-FEB-2026"),
    target: float = Query(..., description="Target value to match (price or greek)"),
    metric: str = Query("ltp", description="Column to match: ltp, iv, delta, etc."),
    option_type: Optional[str] = Query(None, description="CE / PE or None"),
    max_age: float = Query(5.0, description="Max allowed snapshot age in seconds"),
    ctx=Depends(require_dashboard_auth),
):
    db_file = DATA_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
    # Validate path stays inside DATA_DIR
    _validate_option_chain_input(exchange, symbol, expiry)

    if not db_file.exists():
        raise HTTPException(status_code=404, detail="Option chain DB not found")

    try:
        row = find_nearest_option(str(db_file), target=target, metric=metric, option_type=option_type, max_age=max_age)
        return row
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Nearest option lookup failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# DIAGNOSTICS — ORDER PIPELINE TRACKING
# ==================================================

@sub_router.get("/diagnostics/orders")
def get_order_diagnostics(
    system=Depends(get_system),
    auth=Depends(require_dashboard_auth),
):
    """Complete order diagnostics."""
    all_orders = system.get_orders(limit=1000)

    # Count by status
    status_counts = {}
    for order in all_orders:
        s = order.status
        status_counts[s] = status_counts.get(s, 0) + 1

    # Count by source
    source_counts = {}
    for order in all_orders:
        source = order.source
        source_counts[source] = source_counts.get(source, 0) + 1

    # Failed orders details
    failed_orders = [
        {
            "command_id": o.command_id,
            "symbol": o.symbol,
            "side": o.side,
            "qty": o.quantity,
            "created": o.created_at,
            "updated": o.updated_at,
            "source": o.source,
        }
        for o in all_orders
        if o.status == "FAILED"
    ]

    # Pending orders (not yet filled)
    pending_orders = [
        {
            "command_id": o.command_id,
            "symbol": o.symbol,
            "side": o.side,
            "qty": o.quantity,
            "status": o.status,
            "broker_id": o.broker_order_id,
            "created": o.created_at,
            "source": o.source,
        }
        for o in all_orders
        if o.status in ("CREATED", "SENT_TO_BROKER")
    ]

    # Executed orders
    executed_orders = [
        {
            "command_id": o.command_id,
            "symbol": o.symbol,
            "side": o.side,
            "qty": o.quantity,
            "broker_id": o.broker_order_id,
            "created": o.created_at,
            "updated": o.updated_at,
        }
        for o in all_orders
        if o.status == "EXECUTED"
    ]

    return {
        "summary": {
            "total_orders": len(all_orders),
            "status_breakdown": status_counts,
            "source_breakdown": source_counts,
        },
        "failed_orders": {
            "count": len(failed_orders),
            "details": failed_orders,
        },
        "pending_orders": {
            "count": len(pending_orders),
            "details": pending_orders,
        },
        "executed_orders": {
            "count": len(executed_orders),
            "details": executed_orders,
        },
    }


@sub_router.get("/diagnostics/intent-verification")
def verify_intent_generation(
    system=Depends(get_system),
    auth=Depends(require_dashboard_auth),
):
    """Verify intent generation pipeline."""
    all_orders = system.get_orders(limit=500)

    sent_to_broker = [o for o in all_orders if o.broker_order_id]

    by_execution_type = {}
    for order in all_orders:
        exec_type = order.execution_type or "UNKNOWN"
        if exec_type not in by_execution_type:
            by_execution_type[exec_type] = []
        by_execution_type[exec_type].append({
            "command_id": order.command_id,
            "symbol": order.symbol,
            "status": order.status,
        })

    incomplete_orders = []
    for order in all_orders:
        issues = []
        if not order.execution_type:
            issues.append("missing_execution_type")
        if order.status == "SENT_TO_BROKER" and not order.broker_order_id:
            issues.append("sent_to_broker_but_no_broker_id")
        if issues:
            incomplete_orders.append({
                "command_id": order.command_id,
                "issues": issues,
            })

    return {
        "intent_pipeline": {
            "total_intents": len(all_orders),
            "sent_to_broker": len(sent_to_broker),
            "by_execution_type": by_execution_type,
        },
        "data_quality": {
            "incomplete_orders": incomplete_orders,
            "missing_broker_id_count": len([o for o in all_orders if o.status == "SENT_TO_BROKER" and not o.broker_order_id]),
        },
        "recent_activity": [
            {
                "command_id": o.command_id,
                "symbol": o.symbol,
                "status": o.status,
                "source": o.source,
                "updated": o.updated_at,
            }
            for o in all_orders[:20]
        ],
    }
