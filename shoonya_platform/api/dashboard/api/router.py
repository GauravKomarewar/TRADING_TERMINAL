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
from functools import lru_cache
from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from typing import List, Optional
import logging
from uuid import uuid4
from pathlib import Path
import sqlite3
import time
import json
import re

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.services.broker_service import BrokerService
from shoonya_platform.api.dashboard.services.system_service import SystemTruthService
from shoonya_platform.api.dashboard.services.symbols_utility import DashboardSymbolService
from shoonya_platform.api.dashboard.services.intent_utility import DashboardIntentService
from shoonya_platform.api.dashboard.services.supervisor_service import SupervisorService
from shoonya_platform.api.dashboard.services.option_chain_service import (
    get_active_expiries,
    get_active_symbols,
    find_nearest_option,
)
from shoonya_platform.market_data.feeds import index_tokens_subscriber

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
    StrategyEntryRequest,
)

# 🔒 Single canonical storage location (cross-platform)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = (
    _PROJECT_ROOT
    / "shoonya_platform"
    / "market_data"
    / "option_chain"
    / "data"
)

logger = logging.getLogger("DASHBOARD.INTENT.API")

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# ==================================================
# DEPENDENCY FACTORIES (CLIENT-SCOPED)
# ==================================================
def get_broker(ctx=Depends(require_dashboard_auth)):
    return BrokerService(ctx["bot"].broker_view)

def get_system(ctx=Depends(require_dashboard_auth)):
    return SystemTruthService(client_id=ctx["client_id"])

# ==================================================
# DEPENDENCY
# ==================================================
def get_intent(ctx=Depends(require_dashboard_auth)):
    return DashboardIntentService(
        client_id=ctx["client_id"],
        parent_client_id=ctx.get("parent_client_id"),
    )

@lru_cache(maxsize=1)
def get_symbols() -> DashboardSymbolService:
    return DashboardSymbolService()

@lru_cache(maxsize=1)
def get_supervisor() -> SupervisorService:
    return SupervisorService()

# ==================================================
# 🔎 SYMBOL DISCOVERY
# ==================================================

@router.get("/symbols/search", response_model=List[SymbolSearchResult])
def search_symbols(q: str = Query(..., min_length=1),ctx=Depends(require_dashboard_auth)):
    return get_symbols().search(q)

@router.get("/symbols/expiries", response_model=List[ExpiryView])
def list_expiries(exchange: str, symbol: str, ctx=Depends(require_dashboard_auth)):
    return [{"expiry": e} for e in get_symbols().get_expiries(exchange, symbol)]

@router.get("/symbols/contracts", response_model=List[ContractView])
def list_contracts(exchange: str, symbol: str, expiry: str, ctx=Depends(require_dashboard_auth)):
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

@router.post("/orders/cancel/system")
def cancel_system_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
):
    """
    Cancel a SYSTEM (intent-layer) order.
    Intent-only. Execution decided by consumer.
    """
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

@router.post("/orders/modify/system")
def modify_system_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
):
    """
    Modify a SYSTEM (intent-layer) order.
    Intent-only. No execution logic.
    """
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

@router.post("/orders/cancel/system/all")
def cancel_all_system_orders(
    intent: DashboardIntentService = Depends(get_intent),
):
    """
    Cancel ALL pending SYSTEM orders for client.
    Consumer decides exact scope.
    """
    intent_id = f"DASH-CANCEL-SYS-ALL-{uuid4().hex[:8]}"

    intent.submit_raw_intent(
        intent_id=intent_id,
        intent_type="CANCEL_ALL_SYSTEM_ORDERS",
        payload={
            "reason": "DASHBOARD_CANCEL_ALL",
        },
    )

    return {
        "accepted": True,
        "intent_id": intent_id,
    }

# ==================================================
# 🛑 BROKER ORDER CONTROLS (INTENT ONLY)
# ==================================================

@router.post("/orders/cancel/broker")
def cancel_broker_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
):
    intent.submit_raw_intent(
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
    intent.submit_raw_intent(
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
# STRATEGY DISCOVERY & MANAGEMENT  
# ==================================================

@router.get("/strategies/list")
def list_available_strategies(ctx=Depends(require_dashboard_auth)):
    """Discover all available strategies from folder structure"""
    from shoonya_platform.strategies.strategy_registry import list_strategy_templates
    
    templates = list_strategy_templates()
    return {
        "strategies": templates,
        "total": len(templates),
        "predefined": [t for t in templates if not t["folder"].startswith("custom_")],
    }


@router.post("/strategy/start")
def start_strategy(
    payload: dict = Body(...),
    svc: SupervisorService = Depends(get_supervisor),
):
    """Start a strategy runner subprocess from dashboard.

    payload: {"config_path": "delta_neutral.configs.nifty"}
    
    LEGACY: For backward compatibility only.
    NEW: Use /intent/strategy/entry for intent-based control
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
    """Stop a previously started strategy. Accepts `config_path` or `pid`.
    
    LEGACY: For backward compatibility only.
    NEW: Use /intent/strategy with action=FORCE_EXIT
    """
    cfg = payload.get("config_path")
    pid = payload.get("pid")
    try:
        res = svc.stop(config_path=cfg, pid=pid)
        return {"stopped": True, **res}
    except Exception as e:
        logger.exception("Strategy stop failed")
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================
# STRATEGY CONFIG — Save / Load / List
# ==================================================
_STRATEGY_CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "strategies" / "saved_configs"
_STRATEGY_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

_VALID_SECTIONS = {"entry", "adjustment", "exit", "rms"}

def _slugify(name: str) -> str:
    """Convert strategy name to safe filename slug."""
    s = name.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_') or 'unnamed'


@router.post("/strategy/config/save")
def save_strategy_config(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Save a strategy config section (entry/adjustment/exit/rms).
    
    payload: { "name": "NIFTY_DELTA_NEUTRAL", "section": "entry", "config": {...} }
    Persists to JSON in strategies/saved_configs/<slug>.json
    """
    name = payload.get("name", "").strip()
    section = payload.get("section", "").strip().lower()
    config = payload.get("config")

    if not name:
        raise HTTPException(400, "Strategy name is required")
    if section not in _VALID_SECTIONS:
        raise HTTPException(400, f"Invalid section '{section}'. Must be one of: {', '.join(sorted(_VALID_SECTIONS))}")
    if not isinstance(config, dict):
        raise HTTPException(400, "config must be a JSON object")

    slug = _slugify(name)
    filepath = _STRATEGY_CONFIGS_DIR / f"{slug}.json"

    # Load existing or create new
    existing = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["name"] = name
    existing[section] = config
    existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    filepath.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    logger.info("Strategy config saved: %s / %s", name, section)

    return {"saved": True, "name": name, "section": section, "file": slug + ".json"}


@router.get("/strategy/config/{name}")
def load_strategy_config(
    name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Load a saved strategy config by name."""
    slug = _slugify(name)
    filepath = _STRATEGY_CONFIGS_DIR / f"{slug}.json"

    if not filepath.exists():
        # Return empty config — not an error, just no saved data yet
        return {"name": name, "entry": {}, "adjustment": {}, "exit": {}, "rms": {}}

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        raise HTTPException(500, f"Failed to read config: {e}")


@router.get("/strategy/configs")
def list_strategy_configs(ctx=Depends(require_dashboard_auth)):
    """List all saved strategy configs."""
    configs = []
    for f in sorted(_STRATEGY_CONFIGS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            configs.append({
                "name": data.get("name", f.stem),
                "file": f.name,
                "updated_at": data.get("updated_at", ""),
                "sections": [s for s in _VALID_SECTIONS if s in data],
            })
        except Exception:
            continue
    return {"configs": configs, "total": len(configs)}


@router.post(
    "/intent/strategy/entry",
    response_model=IntentResponse,
)
def submit_strategy_entry(
    req: StrategyEntryRequest,
    service: DashboardIntentService = Depends(get_intent),
):
    return service.submit_raw_intent(
        intent_id=f"DASH-STRAT-ENTRY-{uuid4().hex[:8]}",
        intent_type="STRATEGY",
        payload={
            **req.dict(),
            "action": "ENTRY",
        },
    )

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
            "orders": broker.get_order_book(),
        },
        "system": {
            "orders": system.get_orders(200),
            "open_orders": system.get_open_orders(),
            "control_intents": system.get_control_intents(50),
            "risk": system.get_risk_state(),
            "heartbeat": system.get_option_data_heartbeat(),
            "signal": system.get_signal_activity(),
            "telegram_messages": system.get_telegram_messages(200),
            "telegram_stats": system.get_telegram_alert_stats(500),
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

        service.submit_raw_intent(
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

# ==================================================
# � OPTION CHAIN — ACTIVE SYMBOLS (FROM DB FILES)
# ==================================================

@router.get("/option-chain/active-symbols")
def list_active_option_chain_symbols():
    """
    Active option-chain symbols derived from supervisor DB files.

    Returns list of {exchange, symbol, expiries[]} from DB filenames.
    """
    symbols = get_active_symbols()
    return symbols

# ==================================================
# �📅 OPTION CHAIN — ACTIVE EXPIRIES (SUPERVISOR TRUTH)
# ==================================================

@router.get("/option-chain/active-expiries", response_model=List[str])
def list_active_option_chain_expiries(
    exchange: str = Query(..., description="NFO / BFO"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
):
    """
    Active option-chain expiries derived from supervisor DB files.

    Guarantees:
    - ✅ Supervisor-authoritative
    - ✅ Process-safe
    - ✅ Restart-safe
    - ❌ No ScriptMaster access
    - ❌ No live feed access
    - ❌ No DB reads (filenames only)
    """
    expiries = get_active_expiries(exchange, symbol)

    if not expiries:
        raise HTTPException(
            status_code=404,
            detail=f"No active option chains for {exchange}:{symbol}",
        )

    return expiries

@router.get("/option-chain")
def get_option_chain(
    exchange: str = Query(..., description="NFO / BFO / MCX"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
    expiry: str = Query(..., description="24-FEB-2026"),
    max_age: float = Query(
        300.0,
        description="Maximum allowed snapshot age in seconds (300 = 5 min)",
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

    conn = sqlite3.connect(db_file, check_same_thread=False)
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

    # Flag staleness in meta instead of blocking with 409
    # This lets the dashboard show data (even if old) and display a warning
    meta["snapshot_age"] = round(age, 1)
    meta["is_stale"] = age > max_age

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


@router.get("/option-chain/nearest")
def get_nearest_option(
    exchange: str = Query(..., description="NFO / BFO / MCX"),
    symbol: str = Query(..., description="NIFTY / BANKNIFTY / SENSEX"),
    expiry: str = Query(..., description="24-FEB-2026"),
    target: float = Query(..., description="Target value to match (price or greek)"),
    metric: str = Query("ltp", description="Column to match: ltp, iv, delta, etc."),
    option_type: Optional[str] = Query(None, description="CE / PE or None"),
    max_age: float = Query(5.0, description="Max allowed snapshot age in seconds"),
):
    db_file = DATA_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"

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
# 🔍 DIAGNOSTICS — ORDER PIPELINE TRACKING
# ==================================================

@router.get("/diagnostics/orders")
def get_order_diagnostics(
    system=Depends(get_system),
):
    """
    Complete order diagnostics:
    - Order database contents
    - Status distribution  
    - Intent-to-broker mapping
    - Failed order tracking
    """
    all_orders = system.get_orders(limit=1000)
    
    # Count by status
    status_counts = {}
    for order in all_orders:
        status = order.status
        status_counts[status] = status_counts.get(status, 0) + 1
    
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


@router.get("/diagnostics/intent-verification")
def verify_intent_generation(
    system=Depends(get_system),
):
    """
    Verify intent generation pipeline:
    - Check database writes
    - Verify status transitions
    - Track intent->broker mapping
    """
    all_orders = system.get_orders(limit=500)
    
    # Check for orders that have broker_order_id (sent to broker)
    sent_to_broker = [o for o in all_orders if o.broker_order_id]
    
    # Check for orders with execution_type
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
    
    # Check order completeness
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


# ======================================================================
# 🔥 INDEX TOKENS API
# ======================================================================

@router.get("/index-tokens/prices")
def get_index_tokens_prices(
    symbols: Optional[str] = Query(
        None,
        description="Comma-separated list (e.g., 'NIFTY,BANKNIFTY,SENSEX'). If None, returns all subscribed."
    )
):
    """
    Get live index token prices from the live feed.
    
    Pull-based API: Returns whatever data is currently in tick_data_store.
    No guarantees on freshness - depends on whether indices are subscribed.
    
    Returns:
        {
            "subscribed": ["NIFTY", "BANKNIFTY", ...],
            "indices": {
                "NIFTY": {
                    "ltp": 25912.5,
                    "pc": 0.25,
                    "v": 12345,
                    "o": 25900,
                    "h": 25950,
                    "l": 25850,
                    "c": 25912,
                    "oi": 0,
                    "exchange": "NSE",
                    "token": "26000"
                },
                "BANKNIFTY": { ... },
                ...
            }
        }
    """
    try:
        # Parse requested symbols
        requested = []
        if symbols:
            requested = [s.strip().upper() for s in symbols.split(",")]
        
        # Get subscribed indices
        subscribed = index_tokens_subscriber.get_subscribed_indices()
        
        # Get prices
        indices_data = index_tokens_subscriber.get_index_prices(
            indices=requested if requested else None,
            include_missing=False
        )
        
        # Transform for API response
        result = {}
        for symbol, data in indices_data.items():
            if data:
                result[symbol] = {
                    "ltp": data.get("ltp"),
                    "pc": data.get("pc"),
                    "v": data.get("v"),
                    "o": data.get("o"),
                    "h": data.get("h"),
                    "l": data.get("l"),
                    "c": data.get("c"),
                    "ap": data.get("ap"),
                    "oi": data.get("oi"),
                    "tt": data.get("tt"),
                    "exchange": data.get("exchange"),
                    "token": data.get("token"),
                }
        
        return {
            "subscribed": subscribed,
            "indices": result,
            "timestamp": time.time(),
        }
        
    except Exception as e:
        logger.error(f"Error fetching index tokens: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching index prices: {str(e)}"
        )


@router.get("/index-tokens/list")
def list_available_indices():
    """
    Get list of all available index tokens.
    
    Returns:
        {
            "all": {
                "NIFTY": {"exchange": "NSE", "token": "26000", "name": "Nifty 50"},
                "BANKNIFTY": {...},
                ...
            },
            "subscribed": ["NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX"],
            "major": ["NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX"]
        }
    """
    try:
        all_indices = index_tokens_subscriber.get_all_available_indices()
        subscribed = index_tokens_subscriber.get_subscribed_indices()
        major = index_tokens_subscriber.MAJOR_INDICES
        
        # Enrich all indices with metadata
        enriched = {}
        for symbol, friendly_name in all_indices.items():
            meta = index_tokens_subscriber.get_index_metadata(symbol)
            if meta:
                enriched[symbol] = meta
        
        return {
            "all": enriched,
            "subscribed": subscribed,
            "major": major,
        }
        
    except Exception as e:
        logger.error(f"Error listing indices: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing indices: {str(e)}"
        )