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
from datetime import datetime
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

# ==================================================
# 🔄 STRATEGY RECOVERY & RESUME CONTROLS
# ==================================================

@router.get("/strategy/list-recoverable")
def list_recoverable_strategies(
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
):
    """
    List strategies that have open broker positions and can be recovered.
    
    Returns positions grouped by potential strategy mapping.
    User can then manually map broker positions to strategy via recover-resume.
    """
    try:
        positions = broker.get_positions() or []
        
        # Group positions by underlying symbol
        recoverable = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            
            if netqty == 0 or not symbol:
                continue
                
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
                }
        
        logger.info(f"Found {len(recoverable)} recoverable positions")
        
        return {
            "total": len(recoverable),
            "positions": list(recoverable.values()),
        }
        
    except Exception as e:
        logger.exception("Failed to list recoverable strategies")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/recover-resume")
def recover_and_resume_strategy(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    ctx=Depends(require_dashboard_auth),
):
    """
    Manually recover and resume a strategy with existing broker positions.
    
    User provides:
    - strategy_name: Name to assign for recovery
    - symbol: Broker symbol with open position
    - resume_monitoring: If true, resumes strategy monitoring (no new entry orders)
    
    This is a SAFE recovery path - user explicitly maps broker position to strategy.
    """
    try:
        strategy_name = payload.get("strategy_name")
        symbol = payload.get("symbol")
        resume_monitoring = payload.get("resume_monitoring", True)
        
        if not strategy_name or not symbol:
            raise HTTPException(
                status_code=400, 
                detail="strategy_name and symbol required"
            )
        
        # Create a recovery intent
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
            "message": "Recovery intent submitted - strategy will resume from broker position"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to submit recovery intent")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# 🔓 ORPHAN POSITION MANAGEMENT
# ==================================================
# Positions created outside of strategy system:
# - Manual trades from platform
# - External webhooks
# - System-generated orders
# User can manage these with greeks-based rules

@router.get("/orphan-positions")
def list_orphan_positions(
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """
    List all positions NOT owned by any strategy.
    
    These are "orphan" positions created by:
    - Manual trades from UI
    - External webhooks (non-strategy)
    - System-generated orders
    
    User can apply individual/combined management rules
    based on greeks, price, or combined net exposure.
    """
    try:
        # Get all broker positions
        positions = broker.get_positions() or []
        
        # Get all strategy-owned positions
        orders = system.get_orders(500) or []
        strategy_symbols = set(
            o.get("symbol") for o in orders 
            if o.get("user") and o.get("user") not in ["", None]
        )
        
        orphan_positions = []
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            
            if netqty == 0 or not symbol or symbol in strategy_symbols:
                continue
            
            # Find order details for greeks
            order = next((o for o in orders if o.get("symbol") == symbol), {})
            
            orphan_positions.append({
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(order.get("price", 0) or 0),
                "avg_price": float(pos.get("avgprc", 0) or 0),
                "ltp": float(pos.get("ltp", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
                "realized_pnl": float(pos.get("rpnl", 0) or 0),
                "greeks": {
                    "delta": float(order.get("delta", 0) or 0),
                    "gamma": float(order.get("gamma", 0) or 0),
                    "theta": float(order.get("theta", 0) or 0),
                    "vega": float(order.get("vega", 0) or 0),
                },
            })
        
        logger.info(f"Found {len(orphan_positions)} orphan positions")
        
        return {
            "total": len(orphan_positions),
            "positions": orphan_positions,
        }
        
    except Exception as e:
        logger.exception("Failed to list orphan positions")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orphan-positions/summary")
def orphan_positions_summary(
    selected_symbols: Optional[str] = Query(None, description="Comma-separated symbols to combine (e.g., 'NIFTY,BANKNIFTY')"),
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """
    Get summary of orphan positions with combined greeks.
    
    Optionally select specific symbols to see combined net greeks
    (useful for managing multiple legs as a combined position).
    
    Returns:
    - Individual position details
    - Combined net greeks (if selected)
    - Combined PnL metrics
    """
    try:
        positions = broker.get_positions() or []
        orders = system.get_orders(500) or []
        strategy_symbols = set(
            o.get("symbol") for o in orders 
            if o.get("user") and o.get("user") not in ["", None]
        )
        
        # Collect orphan positions
        orphan_map = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            
            if netqty == 0 or not symbol or symbol in strategy_symbols:
                continue
            
            order = next((o for o in orders if o.get("symbol") == symbol), {})
            
            orphan_map[symbol] = {
                "symbol": symbol,
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "delta": float(order.get("delta", 0) or 0),
                "gamma": float(order.get("gamma", 0) or 0),
                "theta": float(order.get("theta", 0) or 0),
                "vega": float(order.get("vega", 0) or 0),
                "ltp": float(pos.get("ltp", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
            }
        
        # If specific symbols selected, calculate combined greeks
        selected_list = []
        if selected_symbols:
            selected_list = [s.strip() for s in selected_symbols.split(",")]
        
        combined = None
        if selected_list:
            selected_positions = [
                orphan_map[s] for s in selected_list 
                if s in orphan_map
            ]
            if selected_positions:
                combined = {
                    "symbols": selected_list,
                    "count": len(selected_positions),
                    "combined_delta": sum(p["delta"] for p in selected_positions),
                    "combined_gamma": sum(p["gamma"] for p in selected_positions),
                    "combined_theta": sum(p["theta"] for p in selected_positions),
                    "combined_vega": sum(p["vega"] for p in selected_positions),
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


@router.post("/orphan-positions/manage")
def create_orphan_position_rule(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
    ctx=Depends(require_dashboard_auth),
):
    """
    Create management rule for orphan position(s).
    
    Rules can be:
    
    1. PRICE-BASED:
       - target: Exit when price reaches target
       - stoploss: Exit when price falls below stoploss
       - trailing: Trail stop by fixed amount
    
    2. GREEK-BASED:
       - delta_target: Exit when delta reaches value
       - theta_target: Exit when theta reaches value (for decay)
       - vega_target: Exit when vega reaches value (for volatility)
       - gamma_target: exit when gamma reaches value
    
    3. COMBINED (multiple positions):
       - Select multiple symbols
       - Combined net greeks > threshold = exit all
       - Combined PnL > target = exit all
    
    Payload:
    {
        "rule_name": "NIFTY PE Exit",
        "symbols": ["NIFTY 23000 PE"],  // single or multiple
        "rule_type": "PRICE" | "GREEK" | "COMBINED",
        "condition": "target" | "stoploss" | "trailing" | "delta" | "theta" | "combined_delta" | etc,
        "threshold": 355.5,  // exit price or greek value
        "action": "EXIT" | "REDUCE",  // EXIT = full exit, REDUCE = half
        "reduce_qty": 25  // qty to reduce when action=REDUCE
    }
    """
    try:
        rule_name = payload.get("rule_name", f"RULE-{int(time.time())}")
        symbols = payload.get("symbols", [])
        rule_type = payload.get("rule_type", "PRICE")  # PRICE, GREEK, COMBINED
        condition = payload.get("condition")  # target, stoploss, trailing, delta, theta, vega, etc
        threshold = payload.get("threshold")
        action = payload.get("action", "EXIT")  # EXIT or REDUCE
        reduce_qty = payload.get("reduce_qty")
        
        if not symbols or not condition or threshold is None:
            raise HTTPException(
                status_code=400, 
                detail="symbols, condition, and threshold required"
            )
        
        rule_id = f"ORPHAN-{'-'.join(symbols[:2])}-{int(time.time())}"
        
        # Submit to system
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


@router.get("/orphan-positions/rules")
def list_orphan_rules(
    ctx=Depends(require_dashboard_auth),
    system=Depends(get_system),
):
    """
    List all active orphan position management rules.
    
    Shows:
    - Rule ID, name, symbols
    - Condition (price/greek based)
    - Threshold value
    - Current status (active, triggered, etc)
    """
    try:
        # Query control intents for ORPHAN_POSITION_RULE type
        db = sqlite3.connect(
            str(Path(__file__).resolve().parents[4] / "shoonya_platform" / "persistence" / "data" / "orders.db"),
            timeout=5
        )
        cur = db.cursor()
        
        cur.execute(
            """
            SELECT id, payload
            FROM control_intents
            WHERE type = 'ORPHAN_POSITION_RULE'
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        
        rules = []
        for row in cur.fetchall():
            try:
                payload = json.loads(row[1])
                rules.append(payload)
            except Exception:
                pass
        
        db.close()
        
        return {
            "total": len(rules),
            "rules": rules,
        }
        
    except Exception as e:
        logger.exception("Failed to list orphan rules")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orphan-positions/rules/{rule_id}")
def delete_orphan_rule(
    rule_id: str,
    ctx=Depends(require_dashboard_auth),
):
    """
    Deactivate an orphan position management rule.
    
    The monitoring for this rule will stop.
    Existing positions will no longer be auto-managed.
    """
    try:
        logger.warning(f"🗑️ ORPHAN RULE DELETED: {rule_id}")
        
        # Mark rule as DELETED in DB
        db = sqlite3.connect(
            str(Path(__file__).resolve().parents[4] / "shoonya_platform" / "persistence" / "data" / "orders.db"),
            timeout=5
        )
        cur = db.cursor()
        
        cur.execute(
            """
            UPDATE control_intents
            SET status = 'DELETED'
            WHERE id = ? AND type = 'ORPHAN_POSITION_RULE'
            """,
            (rule_id,)
        )
        
        db.commit()
        db.close()
        
        return {
            "rule_id": rule_id,
            "status": "DELETED",
            "message": "Rule deactivated - monitoring stopped"
        }
        
    except Exception as e:
        logger.exception(f"Failed to delete rule {rule_id}")
        raise HTTPException(status_code=500, detail=str(e))

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

_VALID_SECTIONS = {"identity", "entry", "adjustment", "exit", "rms"}

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
    """List all saved strategy configs with full data."""
    configs = []
    for f in sorted(_STRATEGY_CONFIGS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            configs.append({
                "schema_version": data.get("schema_version", "1.0"),
                "name": data.get("name", f.stem),
                "id": data.get("id", f.stem),
                "description": data.get("description", ""),
                "tags": data.get("tags", []),
                "file": f.name,
                "updated_at": data.get("updated_at", ""),
                "created_at": data.get("created_at", ""),
                "status": data.get("status", "IDLE"),
                "sections": [s for s in _VALID_SECTIONS if s in data and data[s]],
                "identity": data.get("identity", {}),
                "entry": data.get("entry", {}),
                "adjustment": data.get("adjustment", {}),
                "exit": data.get("exit", {}),
                "rms": data.get("rms", {}),
            })
        except Exception:
            continue
    return {"configs": configs, "total": len(configs)}


@router.post("/strategy/config/save-all")
def save_strategy_config_all(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Save a complete strategy config (all sections at once).

    Schema v2.0 — stores identity/entry/adjustment/exit/rms plus
    description, tags, schema_version.  Files are self-contained JSON
    in strategies/saved_configs/ and can be edited directly on disk.
    """
    name = payload.get("name", "").strip()
    strat_id = payload.get("id", "").strip()

    if not name:
        raise HTTPException(400, "Strategy name is required")
    if not strat_id:
        strat_id = _slugify(name).upper()

    slug = _slugify(name)
    filepath = _STRATEGY_CONFIGS_DIR / f"{slug}.json"

    # Load existing or create new
    existing = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["schema_version"] = "2.0"
    existing["name"] = name
    existing["id"] = strat_id
    existing["description"] = payload.get("description", existing.get("description", ""))
    existing["tags"] = payload.get("tags", existing.get("tags", []))

    for section in _VALID_SECTIONS:
        if section in payload and isinstance(payload[section], dict):
            existing[section] = payload[section]

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if "created_at" not in existing:
        existing["created_at"] = now
    existing["updated_at"] = now
    existing.setdefault("status", "IDLE")

    filepath.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    logger.info("Strategy config saved (all): %s", name)

    return {"saved": True, "name": name, "id": strat_id, "file": slug + ".json"}


@router.delete("/strategy/config/{name}")
def delete_strategy_config(
    name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Delete a saved strategy config by name."""
    slug = _slugify(name)
    filepath = _STRATEGY_CONFIGS_DIR / f"{slug}.json"

    if not filepath.exists():
        raise HTTPException(404, f"Config '{name}' not found")

    filepath.unlink()
    logger.info("Strategy config deleted: %s", name)
    return {"deleted": True, "name": name}


@router.post("/strategy/config/{name}/status")
def update_strategy_status(
    name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Update the status of a saved strategy (IDLE/RUNNING/PAUSED/STOPPED)."""
    new_status = payload.get("status", "").strip().upper()
    valid_statuses = {"IDLE", "RUNNING", "PAUSED", "STOPPED"}
    if new_status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}")

    slug = _slugify(name)
    filepath = _STRATEGY_CONFIGS_DIR / f"{slug}.json"

    if not filepath.exists():
        raise HTTPException(404, f"Config '{name}' not found")

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception:
        data = {"name": name}

    data["status"] = new_status
    data["status_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    return {"updated": True, "name": name, "status": new_status}


@router.post("/strategy/config/{name}/rename")
def rename_strategy_config(
    name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Rename a saved strategy config (changes filename + internal name/id)."""
    new_name = payload.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(400, "new_name is required")

    old_slug = _slugify(name)
    new_slug = _slugify(new_name)
    old_path = _STRATEGY_CONFIGS_DIR / f"{old_slug}.json"
    new_path = _STRATEGY_CONFIGS_DIR / f"{new_slug}.json"

    if not old_path.exists():
        raise HTTPException(404, f"Config '{name}' not found")
    if new_path.exists() and old_slug != new_slug:
        raise HTTPException(409, f"Config '{new_name}' already exists")

    try:
        data = json.loads(old_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    data["name"] = new_name
    data["id"] = new_name.upper().replace(" ", "_").strip("_")
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    new_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    if old_slug != new_slug and old_path.exists():
        old_path.unlink()

    logger.info("Strategy config renamed: %s -> %s", name, new_name)
    return {"renamed": True, "old_name": name, "new_name": new_name, "file": new_slug + ".json"}


@router.post("/strategy/config/{name}/clone")
def clone_strategy_config(
    name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Clone a saved strategy config with a new name (optionally new underlying)."""
    new_name = payload.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(400, "new_name is required")

    src_slug = _slugify(name)
    dst_slug = _slugify(new_name)
    src_path = _STRATEGY_CONFIGS_DIR / f"{src_slug}.json"
    dst_path = _STRATEGY_CONFIGS_DIR / f"{dst_slug}.json"

    if not src_path.exists():
        raise HTTPException(404, f"Config '{name}' not found")
    if dst_path.exists():
        raise HTTPException(409, f"Config '{new_name}' already exists")

    try:
        data = json.loads(src_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Failed to read source: {e}")

    data["name"] = new_name
    data["id"] = new_name.upper().replace(" ", "_").strip("_")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["created_at"] = now
    data["updated_at"] = now
    data["status"] = "IDLE"
    data.pop("status_updated_at", None)

    # Apply instrument override if provided
    new_underlying = payload.get("underlying", "").strip()
    if new_underlying:
        if isinstance(data.get("identity"), dict):
            data["identity"]["underlying"] = new_underlying
        if isinstance(data.get("entry"), dict):
            data["entry"]["underlying"] = new_underlying

    dst_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Strategy config cloned: %s -> %s", name, new_name)
    return {"cloned": True, "source": name, "new_name": new_name, "file": dst_slug + ".json"}


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
def list_active_option_chain_symbols(ctx=Depends(require_dashboard_auth)):
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
    ctx=Depends(require_dashboard_auth),
):
    """
    Active option-chain expiries derived from supervisor DB files.

    Guarantees:
    - ✅ Supervisor-authoritative
    - ✅ Process-safe
    - ✅ Restart-safe
    - ✅ Auth-protected
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
    ctx=Depends(require_dashboard_auth),
):
    """
    Canonical Option Chain API (READ-ONLY)

    Guarantees:
    - ✅ Auth-protected (dashboard users only)
    - ✅ Single-writer, many-reader safe
    - ❌ No live feed interaction
    - ❌ No ScriptMaster access
    - ❌ No Greek calculation
    - ❌ No DB path exposed to frontend
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
    ctx=Depends(require_dashboard_auth),
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


# ==================================================
# 📊 ADVANCED MONITORING - LEG-WISE & STRATEGY GREEKS
# ==================================================

@router.get("/monitoring/strategy-positions")
def get_strategy_positions_detailed(
    strategy_name: Optional[str] = Query(None, description="Filter by strategy name"),
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """
    Get detailed position monitoring with leg-wise greeks.
    
    Returns:
    - Leg-wise details per position (symbol, qty, LTP, greeks)
    - Strategy-wise aggregates (combined delta, vega, theta, gamma)
    - Advanced view with full greek breakdown
    
    Ideal for:
    - Real-time position monitoring
    - Greeks tracking per leg and per strategy
    - Risk assessment at advanced level
    """
    try:
        # Get broker positions
        positions = broker.get_positions() or []
        
        # Get orders with greek data
        orders = system.get_orders(500) or []
        
        # Build leg-wise monitoring view
        legs_by_symbol = {}
        strategy_positions = {}
        
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            
            if netqty == 0 or not symbol:
                continue
            
            # Find corresponding order/greek data
            order_detail = next((o for o in orders if o.get("symbol") == symbol), {})
            
            leg_data = {
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(order_detail.get("price", 0) or 0),
                "ltp": float(pos.get("ltp", 0) or 0),
                "avg_price": float(pos.get("avgprc", 0) or 0),
                
                # Greeks (if available in order detail)
                "delta": float(order_detail.get("delta", 0) or 0),
                "gamma": float(order_detail.get("gamma", 0) or 0),
                "theta": float(order_detail.get("theta", 0) or 0),
                "vega": float(order_detail.get("vega", 0) or 0),
                
                # PnL
                "realized_pnl": float(pos.get("rpnl", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
                "total_pnl": float(pos.get("upnl", 0) or 0) + float(pos.get("rpnl", 0) or 0),
            }
            
            legs_by_symbol[symbol] = leg_data
            
            # Get strategy name from order
            strat = order_detail.get("user") or strategy_name or "UNKNOWN"
            
            if strat not in strategy_positions:
                strategy_positions[strat] = {
                    "strategy_name": strat,
                    "legs": [],
                    "combined_delta": 0.0,
                    "combined_gamma": 0.0,
                    "combined_theta": 0.0,
                    "combined_vega": 0.0,
                    "total_unrealized_pnl": 0.0,
                    "total_realized_pnl": 0.0,
                    "leg_count": 0,
                }
            
            strategy_positions[strat]["legs"].append(leg_data)
            strategy_positions[strat]["combined_delta"] += leg_data["delta"]
            strategy_positions[strat]["combined_gamma"] += leg_data["gamma"]
            strategy_positions[strat]["combined_theta"] += leg_data["theta"]
            strategy_positions[strat]["combined_vega"] += leg_data["vega"]
            strategy_positions[strat]["total_unrealized_pnl"] += leg_data["unrealized_pnl"]
            strategy_positions[strat]["total_realized_pnl"] += leg_data["realized_pnl"]
            strategy_positions[strat]["leg_count"] += 1
        
        # Filter by strategy if specified
        if strategy_name and strategy_name in strategy_positions:
            filtered_strategies = {strategy_name: strategy_positions[strategy_name]}
        else:
            filtered_strategies = strategy_positions
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_symbols": len(legs_by_symbol),
            "total_strategies": len(filtered_strategies),
            
            # Leg-wise view (flat list)
            "legs_detailed": list(legs_by_symbol.values()),
            
            # Strategy-wise view (aggregated with legs)
            "strategy_positions": list(filtered_strategies.values()),
            
            # Summary
            "summary": {
                "total_unrealized_pnl": sum(s["total_unrealized_pnl"] for s in filtered_strategies.values()),
                "total_realized_pnl": sum(s["total_realized_pnl"] for s in filtered_strategies.values()),
                "portfolio_delta": sum(s["combined_delta"] for s in filtered_strategies.values()),
                "portfolio_gamma": sum(s["combined_gamma"] for s in filtered_strategies.values()),
                "portfolio_theta": sum(s["combined_theta"] for s in filtered_strategies.values()),
                "portfolio_vega": sum(s["combined_vega"] for s in filtered_strategies.values()),
            }
        }
        
    except Exception as e:
        logger.exception("Failed to get strategy positions")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitoring/leg-greeks/{symbol}")
def get_leg_greeks(
    symbol: str,
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """
    Get detailed greeks and monitoring data for a specific leg/symbol.
    
    Returns all greek values, risk metrics, and position history.
    Useful for detailed per-leg analysis in advanced monitoring view.
    """
    try:
        positions = broker.get_positions() or []
        orders = system.get_orders(500) or []
        
        # Find position
        position = next((p for p in positions if p.get("tsym") == symbol), None)
        if not position:
            raise HTTPException(status_code=404, detail=f"Position not found: {symbol}")
        
        # Find order details
        order = next((o for o in orders if o.get("symbol") == symbol), {})
        
        netqty = int(position.get("netqty", 0))
        
        return {
            "symbol": symbol,
            "exchange": position.get("exch"),
            "position": {
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(order.get("price", 0) or 0),
                "avg_price": float(position.get("avgprc", 0) or 0),
                "ltp": float(position.get("ltp", 0) or 0),
            },
            "pnl": {
                "realized": float(position.get("rpnl", 0) or 0),
                "unrealized": float(position.get("upnl", 0) or 0),
                "total": float(position.get("upnl", 0) or 0) + float(position.get("rpnl", 0) or 0),
            },
            "greeks": {
                "delta": float(order.get("delta", 0) or 0),
                "gamma": float(order.get("gamma", 0) or 0),
                "theta": float(order.get("theta", 0) or 0),
                "vega": float(order.get("vega", 0) or 0),
                "rho": float(order.get("rho", 0) or 0),
            },
            "metadata": {
                "strategy": order.get("user", "UNKNOWN"),
                "order_count": len([o for o in orders if o.get("symbol") == symbol]),
                "updated_at": position.get("upl_time", ""),
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get leg greeks for {symbol}")
        raise HTTPException(status_code=500, detail=str(e))


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