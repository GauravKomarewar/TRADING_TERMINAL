# ======================================================================
# 🔒 DASHBOARD ROUTER — PRODUCTION FROZEN
# Date    : 2026-01-30
#
# Scope:
# - Read-only broker & OMS views
# - Control-plane intent APIs
# - Strategy lifecycle controls
# - Option chain read API
#
# Guarantees:
# - Client-scoped
# - Intent-only (no execution)
# - No broker writes
# - Execution-consumer compatible
## NOTE: sqlite3 & time used only by option-chain endpoint
# DO NOT MODIFY WITHOUT FULL OMS + CONSUMER RE-AUDIT
# ======================================================================

from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from typing import List, Optional
import logging
from uuid import uuid4
from pathlib import Path
import sqlite3
import time

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.services.broker_service import BrokerService
from shoonya_platform.api.dashboard.services.system_service import SystemTruthService
from shoonya_platform.api.dashboard.services.symbols_utility import DashboardSymbolService
from shoonya_platform.api.dashboard.services.intent_utility import DashboardIntentService
from shoonya_platform.api.dashboard.services.supervisor_service import SupervisorService

from shoonya_platform.api.dashboard.api.schemas import (
    StrategyIntentRequest,
    StrategyAction,
    SymbolSearchResult,
    ExpiryView,
    ContractView,
    GenericIntentRequest,
    AdvancedIntentRequest,
    IntentResponse,
    BasketIntentRequest,
)

# 🔒 Single canonical storage location
DATA_DIR = Path(
    "/home/ec2-user/shoonya_platform/shoonya_platform/market_data/option_chain/data"
)

logger = logging.getLogger("DASHBOARD.INTENT.API")

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# ==================================================
# DEPENDENCY FACTORIES (CLIENT-SCOPED)
# ==================================================

def get_broker(ctx=Depends(require_dashboard_auth)):
    return BrokerService(client_id=ctx.client_id)

def get_system(ctx=Depends(require_dashboard_auth)):
    return SystemTruthService(client_id=ctx.client_id)

# ==================================================
# DEPENDENCY
# ==================================================
def get_intent(ctx=Depends(require_dashboard_auth)):
    return DashboardIntentService(
        client_id=ctx.client_id,
        parent_client_id=ctx.parent_client_id,
    )

_symbols_instance: Optional[DashboardSymbolService] = None
_supervisor_instance: Optional[SupervisorService] = None

def get_symbols() -> DashboardSymbolService:
    global _symbols_instance
    if _symbols_instance is None:
        _symbols_instance = DashboardSymbolService()
    return _symbols_instance


def get_supervisor() -> SupervisorService:
    global _supervisor_instance
    if _supervisor_instance is None:
        _supervisor_instance = SupervisorService()
    return _supervisor_instance

# ==================================================
# 🔎 SYMBOL DISCOVERY
# ==================================================

@router.get("/symbols/search", response_model=List[SymbolSearchResult])
def search_symbols(q: str = Query(..., min_length=1)):
    return get_symbols().search(q)

@router.get("/symbols/expiries", response_model=List[ExpiryView])
def list_expiries(exchange: str, symbol: str):
    return [{"expiry": e} for e in get_symbols().get_expiries(exchange, symbol)]

@router.get("/symbols/contracts", response_model=List[ContractView])
def list_contracts(exchange: str, symbol: str, expiry: str):
    return get_symbols().get_contracts(exchange, symbol, expiry)

# ==================================================
# 📘 ORDERBOOK — READ ONLY
# ==================================================

@router.get("/orderbook")
def get_orderbook(
    limit: int = Query(500, ge=1, le=1000),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    return {
        "system_orders": system.get_orders(limit),
        "broker_orders": broker.get_order_book(),
    }

@router.get("/orderbook/system")
def get_system_orders(
    limit: int = Query(500, ge=1, le=1000),
    system=Depends(get_system),
):
    return system.get_orders(limit)

@router.get("/orderbook/broker")
def get_broker_orders(broker=Depends(get_broker)):
    return broker.get_order_book()

# ==================================================
# 🛑 SYSTEM-LEVEL CONTROLS (INTENT ONLY)
# ==================================================

@router.post("/system/force-exit")
def force_exit_strategy(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
):
    """
    Force EXIT a running strategy via STRATEGY intent.
    """
    req = StrategyIntentRequest(
        strategy_name=payload["strategy_name"],
        action=StrategyAction.FORCE_EXIT,
        reason="DASHBOARD_FORCE_EXIT",
    )
    return intent.submit_strategy_intent(req)

# ==================================================
# 🛑 BROKER ORDER CONTROLS (INTENT ONLY)
# ==================================================

@router.post("/orders/cancel/broker")
def cancel_broker_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
):
    intent._insert_intent(
        intent_id=f"DASH-CANCEL-{payload['order_id']}",
        intent_type="CANCEL_BROKER_ORDER",
        payload={
            "broker_order_id": payload["order_id"],
            "reason": "DASHBOARD_CANCEL",
        },
    )
    return {"accepted": True}

@router.post("/orders/modify/broker")
def modify_broker_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
):
    intent._insert_intent(
        intent_id=f"DASH-MODIFY-{payload['order_id']}",
        intent_type="MODIFY_BROKER_ORDER",
        payload={
            "broker_order_id": payload["order_id"],
            "order_type": payload.get("order_type"),
            "price": payload.get("price"),
            "quantity": payload.get("quantity"),
            "reason": "DASHBOARD_MODIFY",
        },
    )
    return {"accepted": True}


# ==================================================
# STRATEGY SUPERVISOR (OPTIONAL)
# ==================================================


@router.post("/strategy/start")
def start_strategy(
    payload: dict = Body(...),
    svc: SupervisorService = Depends(get_supervisor),
):
    """Start a strategy runner subprocess from dashboard.

    payload: {"config_path": "delta_neutral.configs.nifty"}
    """
    cfg = payload.get("config_path")
    if not cfg:
        raise HTTPException(status_code=400, detail="config_path required")
    try:
        res = svc.start(cfg)
        return {"started": True, "pid": res.get("pid")}
    except Exception as e:
        logger.exception("Strategy start failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/stop")
def stop_strategy(
    payload: dict = Body(...),
    svc: SupervisorService = Depends(get_supervisor),
):
    """Stop a previously started strategy. Accepts `config_path` or `pid`."""
    cfg = payload.get("config_path")
    pid = payload.get("pid")
    try:
        res = svc.stop(config_path=cfg, pid=pid)
        return {"stopped": True, **res}
    except Exception as e:
        logger.exception("Strategy stop failed")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# 🏠 DASHBOARD SNAPSHOT (HOME)
# ==================================================

@router.get("/home/status")
def dashboard_snapshot(
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    return {
        "broker": {
            "positions": broker.get_positions(),
            "positions_summary": broker.get_positions_summary(),
            "holdings": broker.get_holdings(),
            "limits": broker.get_limits(),
        },
        "system": {
            "orders": system.get_orders(200),
            "open_orders": system.get_open_orders(),
            "control_intents": system.get_control_intents(50),
            "risk": system.get_risk_state(),
            "heartbeat": system.get_option_data_heartbeat(),
            "signal": system.get_signal_activity(),
        },
    }


# ==================================================
# GENERIC INTENT
# ==================================================

@router.post(
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

@router.post(
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

@router.post(
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

        service._insert_intent(
            intent_id=intent_id,
            intent_type="ADVANCED",
            payload=payload,
        )

        return IntentResponse(
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

@router.post(
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


@router.get("/option-chain")
def get_option_chain(
    exchange: str = Query(..., description="NFO / BFO / MCX"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
    expiry: str = Query(..., description="24-FEB-2026"),
    max_age: float = Query(
        5.0,
        description="Maximum allowed snapshot age in seconds",
    ),
):
    """
    Canonical Option Chain API (READ-ONLY)

    Guarantees:
    - ❌ No live feed interaction
    - ❌ No ScriptMaster access
    - ❌ No Greek calculation
    - ❌ No DB path exposed to frontend
    - ✅ Single-writer, many-reader safe
    """

    db_file = DATA_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"

    if not db_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Option chain DB not found for {exchange}:{symbol}:{expiry}",
        )

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --------------------------------------------------
    # META
    # --------------------------------------------------
    meta_rows = cur.execute(
        "SELECT key, value FROM meta"
    ).fetchall()
    meta = {row["key"]: row["value"] for row in meta_rows}

    snapshot_ts = float(meta.get("snapshot_ts", 0))
    age = time.time() - snapshot_ts

    if age > max_age:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"Snapshot stale ({age:.1f}s old)",
        )

    # --------------------------------------------------
    # OPTION CHAIN (FULL CONTRACT)
    # --------------------------------------------------
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

    conn.close()

    return {
        "meta": meta,
        "rows": [dict(r) for r in rows],
    }
