# ======================================================================
# ROUTES: Symbols, Orderbook, Orders, Recovery, Orphan Positions
# Extracted from router.py during modularisation.
# ======================================================================
from fastapi import APIRouter, Depends, Query, Body, HTTPException
from typing import List, Optional
from datetime import datetime
from uuid import uuid4
import sqlite3
import json
import time
import logging
from pathlib import Path

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.api._shared import (
    logger,
    _PROJECT_ROOT,
    get_broker,
    get_system,
    get_intent,
    get_symbols,
    SymbolSearchResult,
    ExpiryView,
    ContractView,
    StrategyIntentRequest,
    StrategyAction,
    DashboardIntentService,
)

sub_router = APIRouter()

# ==================================================
# 🔎 SYMBOL DISCOVERY
# ==================================================

@sub_router.get("/symbols/search", response_model=List[SymbolSearchResult])
def search_symbols(q: str = Query(..., min_length=1), ctx=Depends(require_dashboard_auth)):
    return get_symbols().search(q)

@sub_router.get("/symbols/expiries", response_model=List[ExpiryView])
def list_expiries(exchange: str, symbol: str, ctx=Depends(require_dashboard_auth)):
    return [{"expiry": e} for e in get_symbols().get_expiries(exchange, symbol)]

@sub_router.get("/symbols/contracts", response_model=List[ContractView])
def list_contracts(exchange: str, symbol: str, expiry: str, ctx=Depends(require_dashboard_auth)):
    return get_symbols().get_contracts(exchange, symbol, expiry)

# ==================================================
# 📘 ORDERBOOK — READ ONLY
# ==================================================

@sub_router.get("/orderbook")
def get_orderbook(
    limit: int = Query(500, ge=1, le=1000),
    broker=Depends(get_broker),
    system=Depends(get_system),
    auth=Depends(require_dashboard_auth),
):
    return {
        "system_orders": system.get_orders(limit),
        "broker_orders": broker.get_order_book(),
    }

@sub_router.get("/orderbook/system")
def get_system_orders(
    limit: int = Query(500, ge=1, le=1000),
    system=Depends(get_system),
    auth=Depends(require_dashboard_auth),
):
    return system.get_orders(limit)

@sub_router.get("/orderbook/broker")
def get_broker_orders(
    broker=Depends(get_broker),
    auth=Depends(require_dashboard_auth),
):
    return broker.get_order_book()

# ==================================================
# 🛑 SYSTEM-LEVEL CONTROLS (INTENT ONLY)
# ==================================================

@sub_router.post("/system/force-exit")
def force_exit_strategy(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    """Force EXIT a running strategy via STRATEGY intent."""
    strategy_name = payload.get("strategy_name")
    if not strategy_name:
        raise HTTPException(status_code=400, detail="strategy_name is required")
    req = StrategyIntentRequest(
        strategy_name=strategy_name,
        action=StrategyAction.FORCE_EXIT,
        reason="DASHBOARD_FORCE_EXIT",
    )
    return intent.submit_strategy_intent(req)

@sub_router.post("/orders/cancel/system")
def cancel_system_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    """Cancel a SYSTEM (intent-layer) order. Intent-only."""
    command_id = payload.get("order_id")
    if not command_id:
        raise HTTPException(status_code=400, detail="order_id required")

    intent.submit_raw_intent(
        intent_id=f"DASH-CANCEL-SYS-{command_id}",
        intent_type="CANCEL_SYSTEM_ORDER",
        payload={
            "command_id": command_id,
            "reason": "DASHBOARD_CANCEL",
        },
    )
    return {"accepted": True}

# ==================================================
# 🔄 STRATEGY RECOVERY & RESUME CONTROLS
# ==================================================

@sub_router.get("/strategy/list-recoverable")
def list_recoverable_strategies(
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
):
    """List strategies that have open broker positions and can be recovered."""
    try:
        positions = broker.get_positions() or []

        recoverable = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            try:
                netqty = int(pos.get("netqty", 0))
            except (ValueError, TypeError):
                netqty = 0
            suggested_strategy_name = f"{underlying}_Recovery_{int(time.time())}"

            if symbol not in recoverable:
                recoverable[symbol] = {
                    "symbol": symbol,
                    "exchange": pos.get("exch"),
                    "product": pos.get("prd"),
                    "qty": abs(netqty),
                    "side": "BUY" if netqty > 0 else "SELL",
                    "avg_price": float(pos.get("avgprc", 0) or 0),
                    "ltp": float(pos.get("ltp", 0) or 0),
                    "unrealised_pnl": float(pos.get("upnl", 0) or 0),
                    "suggested_name": suggested_strategy_name,
                }

        logger.info(f"Found {len(recoverable)} recoverable positions")
        return {"total": len(recoverable), "positions": list(recoverable.values())}

    except Exception as e:
        logger.exception("Failed to list recoverable strategies")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.post("/strategy/recover-resume")
def recover_and_resume_strategy(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    ctx=Depends(require_dashboard_auth),
):
    """Manually recover and resume a strategy with existing broker positions."""
    try:
        strategy_name = payload.get("strategy_name")
        symbol = payload.get("symbol")
        resume_monitoring = payload.get("resume_monitoring", True)

        if not strategy_name or not symbol:
            raise HTTPException(status_code=400, detail="strategy_name and symbol required")

        applied_result = {"status": "service_not_available"}
        try:
            bot = ctx["bot"]
            service = bot.strategy_executor_service
            applied_result = service.handle_recover_resume({
                "strategy_name": strategy_name,
                "symbol": symbol,
                "resume_monitoring": resume_monitoring,
            })
        except Exception as svc_err:
            logger.error(f"Recovery service call failed: {svc_err}")
            applied_result = {"status": "service_error", "error": str(svc_err)}

        intent.submit_raw_intent(
            intent_id=f"RECOVER-{strategy_name}-{symbol}-{int(time.time())}",
            intent_type="STRATEGY_RECOVER_RESUME",
            payload={
                "strategy_name": strategy_name,
                "symbol": symbol,
                "resume_monitoring": resume_monitoring,
                "reason": "MANUAL_DASHBOARD_RECOVERY",
            },
        )

        logger.warning(
            f"♻️ RECOVERY INTENT: {strategy_name} | symbol={symbol} | monitoring={resume_monitoring}"
        )

        return {
            "accepted": True,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "resume_monitoring": resume_monitoring,
            "applied": applied_result,
            "message": "Recovery applied to executor service and intent logged for audit",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to submit recovery intent")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# 🔓 ORPHAN POSITION MANAGEMENT
# ==================================================

@sub_router.get("/orphan-positions")
def list_orphan_positions(
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """List all positions NOT owned by any strategy."""
    try:
        positions = broker.get_positions() or []
        orders = system.get_orders(500) or []
        strategy_symbols = set(
            o.symbol for o in orders
            if getattr(o, "strategy_name", None) or getattr(o, "source", None) == "STRATEGY"
        )

        orphan_positions = []
        for pos in positions:
            symbol = pos.get("tsym", "")
            try:
                netqty = int(pos.get("netqty", 0))
            except (ValueError, TypeError):
                netqty = 0

            if netqty == 0 or not symbol or symbol in strategy_symbols:
                continue

            order = next((o for o in orders if o.symbol == symbol), None)

            orphan_positions.append({
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(order.price if order else 0),
                "avg_price": float(pos.get("avgprc", 0) or 0),
                "ltp": float(pos.get("ltp", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
                "realized_pnl": float(pos.get("rpnl", 0) or 0),
                "order_type": order.order_type if order else "MARKET",
            })

        logger.info(f"Found {len(orphan_positions)} orphan positions")
        return {"total": len(orphan_positions), "positions": orphan_positions}

    except Exception as e:
        logger.exception("Failed to list orphan positions")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.get("/orphan-positions/summary")
def orphan_positions_summary(
    selected_symbols: Optional[str] = Query(None, description="Comma-separated symbols to combine"),
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """Get summary of orphan positions with combined greeks."""
    try:
        positions = broker.get_positions() or []
        orders = system.get_orders(500) or []
        strategy_symbols = set(
            o.symbol for o in orders
            if getattr(o, "strategy_name", None) or getattr(o, "source", None) == "STRATEGY"
        )

        orphan_map = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            try:
                netqty = int(pos.get("netqty", 0))
            except (ValueError, TypeError):
                netqty = 0

            if netqty == 0 or not symbol or symbol in strategy_symbols:
                continue

            order = next((o for o in orders if o.symbol == symbol), None)

            orphan_map[symbol] = {
                "symbol": symbol,
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "ltp": float(pos.get("ltp", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
            }

        selected_list = []
        if selected_symbols:
            selected_list = [s.strip() for s in selected_symbols.split(",")]

        combined = None
        if selected_list:
            selected_positions = [orphan_map[s] for s in selected_list if s in orphan_map]
            if selected_positions:
                combined = {
                    "symbols": selected_list,
                    "count": len(selected_positions),
                    "total_unrealized_pnl": sum(p["unrealized_pnl"] for p in selected_positions),
                    "positions": selected_positions,
                }

        return {
            "total_orphan": len(orphan_map),
            "all_orphans": list(orphan_map.values()),
            "combined_view": combined,
        }

    except Exception as e:
        logger.exception("Failed to get orphan positions summary")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.post("/orphan-positions/manage")
def create_orphan_position_rule(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    ctx=Depends(require_dashboard_auth),
):
    """Create management rule for orphan position(s)."""
    try:
        rule_name = payload.get("rule_name", f"RULE-{int(time.time())}")
        symbols = payload.get("symbols", [])
        rule_type = payload.get("rule_type", "PRICE")
        condition = payload.get("condition")
        threshold = payload.get("threshold")
        action = payload.get("action", "EXIT")
        reduce_qty = payload.get("reduce_qty")

        if not symbols or not condition or threshold is None:
            raise HTTPException(status_code=400, detail="symbols, condition, and threshold required")

        rule_id = f"ORPHAN-{'-'.join(symbols[:2])}-{int(time.time())}"

        intent.submit_raw_intent(
            intent_id=rule_id,
            intent_type="ORPHAN_POSITION_RULE",
            payload={
                "rule_id": rule_id,
                "rule_name": rule_name,
                "symbols": symbols,
                "rule_type": rule_type,
                "condition": condition,
                "threshold": threshold,
                "action": action,
                "reduce_qty": reduce_qty,
                "created_at": datetime.now().isoformat(),
            },
        )

        logger.warning(
            f"📋 ORPHAN RULE CREATED: {rule_name} | symbols={symbols} | "
            f"condition={condition} | threshold={threshold}"
        )

        return {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "symbols": symbols,
            "rule_type": rule_type,
            "condition": condition,
            "threshold": threshold,
            "action": action,
            "status": "ACTIVE",
            "message": "Management rule created - monitoring enabled"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to create orphan position rule")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.get("/orphan-positions/rules")
def list_orphan_rules(
    ctx=Depends(require_dashboard_auth),
    system=Depends(get_system),
):
    """List all active orphan position management rules."""
    try:
        db_path = str(_PROJECT_ROOT / "shoonya_platform" / "persistence" / "data" / "orders.db")
        db = sqlite3.connect(db_path, timeout=5)
        try:
            cur = db.cursor()
            cur.execute(
                """
                SELECT id, payload
                FROM control_intents
                WHERE type = 'ORPHAN_POSITION_RULE'
                  AND (status IS NULL OR status != 'DELETED')
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            rules = []
            for row in cur.fetchall():
                try:
                    payload = json.loads(row[1])
                    rules.append(payload)
                except (json.JSONDecodeError, Exception) as parse_err:
                    logger.warning("Skipping corrupt orphan rule row id=%s: %s", row[0], parse_err)
        finally:
            db.close()

        return {"total": len(rules), "rules": rules}

    except Exception as e:
        logger.exception("Failed to list orphan rules")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.delete("/orphan-positions/rules/{rule_id}")
def delete_orphan_rule(
    rule_id: str,
    ctx=Depends(require_dashboard_auth),
):
    """Deactivate an orphan position management rule."""
    try:
        db = sqlite3.connect(
            str(_PROJECT_ROOT / "shoonya_platform" / "persistence" / "data" / "orders.db"),
            timeout=5
        )
        rows_updated = 0
        try:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE control_intents
                SET status = 'DELETED'
                WHERE id = ? AND type = 'ORPHAN_POSITION_RULE'
                """,
                (rule_id,)
            )
            rows_updated = cur.rowcount
            db.commit()
        finally:
            db.close()
        if rows_updated == 0:
            raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")

        logger.warning(f"🗑️ ORPHAN RULE DELETED: {rule_id}")

        return {
            "rule_id": rule_id,
            "status": "DELETED",
            "message": "Rule deactivated - monitoring stopped"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to delete rule {rule_id}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================
# ORDER MANAGEMENT (MODIFY / CANCEL)
# ==================================================

@sub_router.post("/orders/modify/system")
def modify_system_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    """Modify a SYSTEM (intent-layer) order. Intent-only."""
    command_id = payload.get("order_id")
    if not command_id:
        raise HTTPException(status_code=400, detail="order_id required")

    intent.submit_raw_intent(
        intent_id=f"DASH-MODIFY-SYS-{command_id}",
        intent_type="MODIFY_SYSTEM_ORDER",
        payload={
            "command_id": command_id,
            "order_type": payload.get("order_type"),
            "price": payload.get("price"),
            "quantity": payload.get("quantity"),
            "reason": "DASHBOARD_MODIFY",
        },
    )
    return {"accepted": True}

@sub_router.post("/orders/cancel/system/all")
def cancel_all_system_orders(
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    """Cancel ALL pending SYSTEM orders for client."""
    intent_id = f"DASH-CANCEL-SYS-ALL-{uuid4().hex[:8]}"
    intent.submit_raw_intent(
        intent_id=intent_id,
        intent_type="CANCEL_ALL_SYSTEM_ORDERS",
        payload={"reason": "DASHBOARD_CANCEL_ALL"},
    )
    return {"accepted": True, "intent_id": intent_id}


@sub_router.post("/orders/cancel/broker")
def cancel_broker_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    order_id = payload.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing required field: order_id")
    intent.submit_raw_intent(
        intent_id=f"DASH-CANCEL-{order_id}",
        intent_type="CANCEL_BROKER_ORDER",
        payload={"broker_order_id": order_id, "reason": "DASHBOARD_CANCEL"},
    )
    return {"accepted": True}

@sub_router.post("/orders/modify/broker")
def modify_broker_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    order_id = payload.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing required field: order_id")
    intent.submit_raw_intent(
        intent_id=f"DASH-MODIFY-{order_id}",
        intent_type="MODIFY_BROKER_ORDER",
        payload={
            "broker_order_id": order_id,
            "order_type": payload.get("order_type"),
            "price": payload.get("price"),
            "quantity": payload.get("quantity"),
            "reason": "DASHBOARD_MODIFY",
        },
    )
    return {"accepted": True}

@sub_router.post("/orders/cancel/broker/all")
def cancel_all_broker_orders(
    intent: DashboardIntentService = Depends(get_intent),
    auth=Depends(require_dashboard_auth),
):
    """Cancel ALL pending BROKER orders for client."""
    intent_id = f"DASH-CANCEL-BRK-ALL-{uuid4().hex[:8]}"
    intent.submit_raw_intent(
        intent_id=intent_id,
        intent_type="CANCEL_ALL_BROKER_ORDERS",
        payload={"reason": "DASHBOARD_CANCEL_ALL"},
    )
    return {"accepted": True, "intent_id": intent_id}
