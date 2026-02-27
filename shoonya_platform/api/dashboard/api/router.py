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
import threading  # used for _symbols_service_lock, _supervisor_service_lock, _runner_instances_lock
from fastapi import APIRouter, Depends, Query, Body, HTTPException, status, WebSocket
from typing import List, Optional, Any, Dict
import logging
from uuid import uuid4
from pathlib import Path
from datetime import datetime
import sqlite3
import time
import json
import re
from collections import deque
import os

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
from shoonya_platform.strategy_runner.config_schema import validate_config


def ensure_complete_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg or {}


def convert_v2_to_factory_format(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg or {}


def is_v2_config(cfg: Dict[str, Any]) -> bool:
    return False


def get_factory_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg or {}

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

# ✅ BUG-003 FIX: Define STRATEGY_CONFIG_DIR at module level (was previously defined ~2777
# lines below — after all the route handlers that reference it — causing globals().get()
# to miss it and silently fall back to a different path, making saved configs invisible).
STRATEGY_CONFIG_DIR = _PROJECT_ROOT / "shoonya_platform" / "strategy_runner" / "saved_configs"
STRATEGY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("DASHBOARD.INTENT.API")

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _parse_iso_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp '{value}': {e}")


def _get_historical_service(ctx: dict):
    bot = ctx.get("bot")
    svc = getattr(bot, "historical_analytics_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Historical analytics service unavailable")
    return svc

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

# BUG-027 FIX: Explicit thread-safe singletons instead of lru_cache.
# lru_cache on no-arg functions caches the SAME instance for ALL clients.
# In a multi-client deployment this leaks state between clients.
# Double-checked locking makes the lifecycle explicit and allows future keying by client_id.
_symbols_service_instance: Optional[DashboardSymbolService] = None
_symbols_service_lock = threading.Lock()

_supervisor_service_instance: Optional[SupervisorService] = None
_supervisor_service_lock = threading.Lock()

def get_symbols() -> DashboardSymbolService:
    global _symbols_service_instance
    if _symbols_service_instance is None:
        with _symbols_service_lock:
            if _symbols_service_instance is None:
                _symbols_service_instance = DashboardSymbolService()
    return _symbols_service_instance

def get_supervisor() -> SupervisorService:
    global _supervisor_service_instance
    if _supervisor_service_instance is None:
        with _supervisor_service_lock:
            if _supervisor_service_instance is None:
                _supervisor_service_instance = SupervisorService()
    return _supervisor_service_instance

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
            
            # ✅ FIX: Define suggested_strategy_name with safe fallback
            parts = symbol.split() if symbol else ["UNKNOWN"]
            underlying = parts[0] if parts else "UNKNOWN"
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
                    "suggested_name": suggested_strategy_name,  # ✅ Using the safe variable
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
        
        # BUG-026 FIX: Previously this only submitted an intent that had NO consumer —
        # the intent lived in the DB forever and recovery never actually happened.
        # Now we directly call service.handle_recover_resume() which applies the
        # recovery to the live executor state immediately, AND still emit the intent
        # for audit trail / replay purposes.

        # 1. Apply recovery directly to the running executor service
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

        # 2. Also submit intent for audit trail
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
        
        # ✅ BUG-019 FIX: `o.user` is the broker account user — always present for every
        # order. This made strategy_symbols include ALL symbols, so the orphan list was
        # always empty. Use o.strategy_name (or o.source == "STRATEGY") to identify
        # strategy-owned orders.
        orders = system.get_orders(500) or []
        strategy_symbols = set(
            o.symbol for o in orders
            if getattr(o, "strategy_name", None) or getattr(o, "source", None) == "STRATEGY"
        )
        
        orphan_positions = []
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            
            if netqty == 0 or not symbol or symbol in strategy_symbols:
                continue
            
            # Find order details
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
        # ✅ BUG-019 FIX: Same fix as /orphan-positions — use strategy_name/source, not o.user
        strategy_symbols = set(
            o.symbol for o in orders
            if getattr(o, "strategy_name", None) or getattr(o, "source", None) == "STRATEGY"
        )
        
        # Collect orphan positions
        orphan_map = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            
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
        
        # If specific symbols selected, calculate combined metrics
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
        db_path = str(Path(__file__).resolve().parents[4] / "shoonya_platform" / "persistence" / "data" / "orders.db")
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
                except Exception:
                    pass
        finally:
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
        
        return {
            "rule_id": rule_id,
            "status": "DELETED",
            "message": "Rule deactivated - monitoring stopped"
        }
        
    except HTTPException:
        raise  # Re-raise 404/409/etc. without wrapping in 500
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
    order_id = payload.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing required field: order_id")
    intent.submit_raw_intent(
        intent_id=f"DASH-CANCEL-{order_id}",
        intent_type="CANCEL_BROKER_ORDER",
        payload={
            "broker_order_id": order_id,
            "reason": "DASHBOARD_CANCEL",
        },
    )
    return {"accepted": True}

@router.post("/orders/modify/broker")
def modify_broker_order(
    payload: dict = Body(...),
    intent: DashboardIntentService = Depends(get_intent),
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

@router.post("/orders/cancel/broker/all")
def cancel_all_broker_orders(
    intent: DashboardIntentService = Depends(get_intent),
):
    """
    Cancel ALL pending BROKER orders for client.
    Consumer decides exact scope.
    """
    intent_id = f"DASH-CANCEL-BRK-ALL-{uuid4().hex[:8]}"

    intent.submit_raw_intent(
        intent_id=intent_id,
        intent_type="CANCEL_ALL_BROKER_ORDERS",
        payload={
            "reason": "DASHBOARD_CANCEL_ALL",
        },
    )

    return {
        "accepted": True,
        "intent_id": intent_id,
    }

# ==================================================
# STRATEGY DISCOVERY & MANAGEMENT  
# ==================================================

@router.get("/strategies/list")
def list_available_strategies(ctx=Depends(require_dashboard_auth)):
    """List available strategy configs from strategy_runner/saved_configs."""
    strategies = get_all_strategies()
    templates = [
        {
            "id": s["name"],
            "folder": "saved_configs",
            "file": s["filename"],
            "module": "shoonya_platform.strategy_runner.strategy_executor_service",
            "label": s["config"].get("name", s["name"]),
            "slug": s["name"],
        }
        for s in strategies
    ]
    return {
        "strategies": templates,
        "total": len(templates),
        "predefined": templates,
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
    
    Returns:
    - { "started": true, "pid": 12345 } on success
    - HTTPException with error details on failure
    """
    cfg = payload.get("config_path")
    if not cfg:
        logger.error("🔥 Strategy start failed: config_path required")
        raise HTTPException(status_code=400, detail="config_path required")
    
    try:
        svc.start(cfg)
        return {"started": True, "config_path": cfg}
    except Exception as e:
        logger.exception("Legacy strategy/start endpoint is retired | config_path=%s", cfg)
        raise HTTPException(
            status_code=410,
            detail=f"Legacy subprocess strategy start is retired: {e}",
        )


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
        logger.exception("Legacy strategy/stop endpoint failed")
        raise HTTPException(status_code=410, detail=f"Legacy subprocess strategy stop is retired: {e}")

# ==================================================
# PER-STRATEGY RUNNER CONTROL (Individual Start/Stop)
# ==================================================

@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(
    strategy_name: str,
    payload: dict = Body(default={}),
    ctx=Depends(require_dashboard_auth)
):
    """
    Start a specific strategy by name from saved_configs/
    
    Returns:
        {
            "success": true,
            "strategy_name": "NIFTY_DNSS",
            "message": "Strategy started",
            "timestamp": "2026-02-12T..."
        }
    """
    try:
        requested_key = _slugify(strategy_name)
        bot = ctx["bot"]
        service = bot.strategy_executor_service
        strategy_file = _resolve_strategy_config_file(strategy_name)

        if not strategy_file:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy config not found for '{strategy_name}'"
            )

        strategy_key = strategy_file.stem

        if strategy_key in service._strategies:
            logger.info(f"Strategy {strategy_key} already running")
            return {
                "success": False,
                "strategy_name": strategy_key,
                "message": "Strategy already running",
                "timestamp": datetime.now().isoformat()
            }

        # Default behavior is resume-safe for live reliability.
        # Fresh-cycle reset is opt-in via payload {"fresh_start": true}.
        fresh_start = bool((payload or {}).get("fresh_start", False))
        if fresh_start:
            try:
                sf = _strategy_state_file(service, strategy_key)
                if sf.exists():
                    sf.unlink()
                    logger.info("Cleared strategy state file for fresh start: %s", sf)
            except Exception as se:
                logger.warning("Could not clear state file for %s: %s", strategy_key, se)

        config = json.loads(strategy_file.read_text(encoding="utf-8"))
        bot.start_strategy_executor(strategy_name=strategy_key, config=config)
        if strategy_key not in service._strategies:
            logger.warning(
                "start-execution: strategy not registered via bot path, using direct register fallback | %s",
                strategy_key,
            )
            service.register_strategy(name=strategy_key, config_path=str(strategy_file))

        if not getattr(service, "_running", False):
            logger.warning("Strategy runner loop was stopped; restarting runner service")
            service.start()

        if strategy_key not in service._strategies:
            raise RuntimeError(f"Strategy '{strategy_key}' was not registered in executor service")

        config["status"] = "RUNNING"
        config["status_updated_at"] = datetime.now().isoformat()
        _write_json_file(strategy_file, config)

        return {
            "success": True,
            "strategy_name": strategy_key,
            "requested_strategy_name": requested_key,
            "fresh_start": fresh_start,
            "message": f"Strategy {strategy_key} started",
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting strategy execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/strategy/{strategy_name}/stop-execution")
def stop_strategy_execution(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth)
):
    """
    Stop a specific running strategy
    
    Returns:
        {
            "success": true,
            "strategy_name": "NIFTY_DNSS",
            "message": "Strategy stopped",
            "timestamp": "2026-02-12T..."
        }
    """
    try:
        requested_key = _slugify(strategy_name)
        bot = ctx["bot"]
        service = bot.strategy_executor_service
        strategy_file = _resolve_strategy_config_file(strategy_name)
        strategy_key = strategy_file.stem if strategy_file else requested_key
        logger.info(f"Stop requested for strategy: {strategy_key} (requested={requested_key})")

        was_running_in_memory = strategy_key in service._strategies

        # 1) Stop active in-memory execution (if present)
        if was_running_in_memory:
            service.unregister_strategy(strategy_key)
            with bot._live_strategies_lock:
                bot._live_strategies.pop(strategy_key, None)

        # 2) Always clear persisted executor state so stale RUNNING state cannot survive restart
        try:
            service.state_mgr.delete(strategy_key)
        except Exception as se:
            logger.warning(f"Could not clear persisted state for {strategy_key}: {se}")

        # 2b) Clear per-strategy runtime state snapshot (PerStrategyExecutor *.pkl).
        try:
            sf = _strategy_state_file(service, strategy_key)
            if sf.exists():
                sf.unlink()
                logger.info("Cleared runtime state snapshot for %s: %s", strategy_key, sf)
        except Exception as se:
            logger.warning(f"Could not clear runtime state snapshot for {strategy_key}: {se}")

        # 3) Always mark config STOPPED so UI reflects latest action
        try:
            strategy_file = STRATEGY_CONFIG_DIR / f"{strategy_key}.json"
            if strategy_file.exists():
                cfg = json.loads(strategy_file.read_text(encoding="utf-8"))
                cfg["status"] = "STOPPED"
                cfg["status_updated_at"] = datetime.now().isoformat()
                _write_json_file(strategy_file, cfg)
        except Exception as se:
            logger.warning(f"Could not update status for {strategy_key}: {se}")

        logger.info(
            "Strategy stop completed: %s (in_memory=%s)",
            strategy_key,
            was_running_in_memory,
        )
        return {
            "success": True,
            "strategy_name": strategy_key,
            "requested_strategy_name": requested_key,
            "message": f"Strategy {strategy_key} stopped",
            "in_memory_running": was_running_in_memory,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error stopping strategy execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================
# STRATEGY CONFIG — Save / Load / List
# ==================================================
_STRATEGY_CONFIGS_DIR = (
    _PROJECT_ROOT
    / "shoonya_platform" 
    / "strategy_runner" 
    / "saved_configs"
)
_STRATEGY_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

_VALID_SECTIONS = {"identity", "entry", "adjustment", "exit", "rms"}


def _get_strategy_configs_dir() -> Path:
    """
    ✅ BUG-M2 FIX: STRATEGY_CONFIG_DIR is now defined at module top-level and
    is always available.  The old globals().get() pattern + fallback to
    _STRATEGY_CONFIGS_DIR was left over from when STRATEGY_CONFIG_DIR was
    defined 2700+ lines below the route handlers (BUG-003).  That late-definition
    is gone; use the module constant directly.
    """
    STRATEGY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return STRATEGY_CONFIG_DIR

def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace a file to avoid partial/empty reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

def _write_json_file(path: Path, payload: Dict[str, Any], encoding: str = "utf-8") -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding=encoding,
    )

def _slugify(name: str) -> str:
    """Convert strategy name to safe filename slug."""
    s = name.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_') or 'unnamed'


def _resolve_strategy_config_file(strategy_name: str) -> Optional[Path]:
    """
    Resolve config by filename slug OR config metadata (id/name).
    """
    requested_slug = _slugify(strategy_name)
    direct = STRATEGY_CONFIG_DIR / f"{requested_slug}.json"
    if direct.exists():
        return direct

    for path in sorted(STRATEGY_CONFIG_DIR.glob("*.json")):
        if path.name == "STRATEGY_CONFIG_SCHEMA.json":
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue

        file_slug = _slugify(path.stem)
        id_slug = _slugify(str(cfg.get("id", ""))) if cfg.get("id") is not None else ""
        name_slug = _slugify(str(cfg.get("name", ""))) if cfg.get("name") is not None else ""
        if requested_slug in {file_slug, id_slug, name_slug}:
            return path
    return None


def _mode_from_config_dict(config: Dict[str, Any]) -> str:
    """Return LIVE/MOCK from config paper/test flags."""
    cfg = config or {}
    identity = cfg.get("identity", {}) or {}
    is_mock = bool(
        cfg.get("paper_mode")
        or identity.get("paper_mode")
        or cfg.get("is_paper")
        or cfg.get("test_mode")
        or identity.get("test_mode")
    )
    return "MOCK" if is_mock else "LIVE"


def _mode_from_saved_file(strategy_name: str) -> str:
    """
    Resolve strategy mode directly from saved config on disk.
    This avoids incorrect LIVE defaults when strategy is not loaded in memory.
    """
    try:
        path = _resolve_strategy_config_file(strategy_name)
        if not path:
            path = STRATEGY_CONFIG_DIR / f"{_slugify(strategy_name)}.json"
        if not path.exists():
            return "LIVE"
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        return _mode_from_config_dict(cfg)
    except Exception:
        return "LIVE"


def _get_runtime_running_slugs(ctx: dict) -> set[str]:
    """
    Read currently running strategy keys from StrategyExecutorService.
    Keys are stored as slug-like names.
    """
    try:
        bot = ctx.get("bot")
        svc = getattr(bot, "strategy_executor_service", None)
        if svc is None:
            return set()
        return set(list(getattr(svc, "_strategies", {}).keys()))
    except Exception:
        return set()


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
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

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

    _write_json_file(filepath, existing)
    logger.info("Strategy config saved: %s / %s", name, section)

    return {"saved": True, "name": name, "section": section, "file": slug + ".json"}


@router.get("/strategy/config/{name}")
def load_strategy_config(
    name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Load a saved strategy config by name."""
    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

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
    """List all saved strategy configs with full data and live/mock mode."""
    cfg_dir = _get_strategy_configs_dir()
    runtime_running = _get_runtime_running_slugs(ctx)
    configs = []
    parse_errors = []

    # Get executor service to query mode and position info
    bot = ctx["bot"]
    service = getattr(bot, "strategy_executor_service", None)

    for f in sorted(cfg_dir.glob("*.json")):
        if f.name == "STRATEGY_CONFIG_SCHEMA.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            slug = f.stem
            file_status = str(data.get("status", "IDLE") or "IDLE").upper()
            effective_status = "RUNNING" if slug in runtime_running else ("IDLE" if file_status == "RUNNING" else file_status)

            # ---- mode and can_change ----
            mode = _mode_from_config_dict(data)
            can_change = True
            mode_change_reason = None
            if service:
                try:
                    if hasattr(service, "_strategies") and slug in getattr(service, "_strategies", {}):
                        mode = service.get_strategy_mode(slug) if hasattr(service, "get_strategy_mode") else mode
                except Exception:
                    pass
                try:
                    if hasattr(service, "_validate_mode_change_allowed"):
                        allowed, reason = service._validate_mode_change_allowed(slug)
                        can_change = bool(allowed)
                        mode_change_reason = reason or None
                    else:
                        has_pos = service.has_position(slug) if hasattr(service, "has_position") else False
                        if has_pos:
                            can_change = False
                            mode_change_reason = "Strategy has active positions"
                except Exception:
                    pass
            # -----------------------------

            configs.append({
                "schema_version": data.get("schema_version", "1.0"),
                "name": data.get("name", f.stem),
                "id": data.get("id", f.stem),
                "type": data.get("type"),
                "strategy_type": data.get("strategy_type") or data.get("type"),
                "description": data.get("description", ""),
                "tags": data.get("tags", []),
                "file": f.name,
                "updated_at": data.get("updated_at", ""),
                "created_at": data.get("created_at", ""),
                "status": effective_status,
                "status_file": file_status,
                "status_runtime_running": slug in runtime_running,
                "sections": [s for s in _VALID_SECTIONS if s in data and data[s]],
                "identity": data.get("identity", {}),
                "entry": data.get("entry", {}),
                "adjustment": data.get("adjustment", {}),
                "exit": data.get("exit", {}),
                "rms": data.get("rms", {}),
                # mode info for frontend
                "mode": mode,
                "can_change_mode": can_change,
                "mode_change_reason": mode_change_reason,
            })
        except Exception as e:
            parse_errors.append(f"{f.name}: {e}")
            continue
    return {
        "configs": configs,
        "total": len(configs),
        "directory": str(cfg_dir),
        "parse_errors": parse_errors[:20],
    }

@router.get("/monitoring/all-strategies-status")
def get_all_strategies_execution_status(
    broker=Depends(get_broker),
    system=Depends(get_system),
    ctx=Depends(require_dashboard_auth),
):
    """
    🔍 COMPREHENSIVE VISIBILITY ENDPOINT
    
    Shows COMPLETE execution status of ALL strategies in system:
    - All saved strategy configs with their current status
    - Control intents in queue (what's pending execution)
    - Active positions per strategy (proof of execution)
    - Overall system execution state
    
    Purpose: 100% auditability - user can see:
    ✓ Which strategies are configured
    ✓ Which are currently RUNNING / PAUSED / STOPPED / IDLE
    ✓ What intents are queued in control_intents table
    ✓ Active positions across strategies
    ✓ No hidden strategies or background execution
    """
    try:
        cfg_dir = _get_strategy_configs_dir()
        runtime_running = _get_runtime_running_slugs(ctx)
        # 1. Load all saved strategies
        all_configs = []
        for f in sorted(cfg_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                slug = f.stem
                file_status = str(data.get("status", "IDLE") or "IDLE").upper()
                effective_status = "RUNNING" if slug in runtime_running else ("IDLE" if file_status == "RUNNING" else file_status)
                all_configs.append({
                    "name": data.get("name", f.stem),
                    "status": effective_status,
                    "status_file": file_status,
                    "runtime_running": slug in runtime_running,
                    "status_updated_at": data.get("status_updated_at"),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "identity": data.get("identity", {}).get("underlying", "N/A"),
                })
            except Exception:
                continue

        # 2. Get control intents (pending/executing)
        control_intents = system.get_control_intents(100) or []
        intent_by_strategy = {}
        for intent in control_intents:
            strat_name = intent.get("strategy_name", "UNKNOWN")
            if strat_name not in intent_by_strategy:
                intent_by_strategy[strat_name] = []
            intent_by_strategy[strat_name].append({
                "intent_id": intent.get("intent_id"),
                "action": intent.get("action"),
                "status": intent.get("status", "PENDING"),
                "created_at": intent.get("created_at"),
            })

        # 3. Get active positions (proof of execution)
        positions = broker.get_positions() or []
        positions_by_strategy = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))
            if netqty == 0 or not symbol:
                continue
            # Try to infer strategy from position notes or use "UNKNOWN"
            strat = "ACTIVE_POSITION"  # Grouped under this for unidentified positions
            if strat not in positions_by_strategy:
                positions_by_strategy[strat] = []
            positions_by_strategy[strat].append({
                "symbol": symbol,
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "ltp": float(pos.get("ltp", 0)),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
            })

        # 4. Merge all data with comprehensive status
        strategies_execution = []
        seen_strategies = set()
        
        # Add from saved configs
        for config in all_configs:
            name = config["name"]
            seen_strategies.add(name)
            strategies_execution.append({
                "name": name,
                "status": config["status"],  # IDLE, RUNNING, PAUSED, STOPPED
                "status_updated_at": config["status_updated_at"],
                "created_at": config["created_at"],
                "underlying": config["identity"],
                "pending_intents": intent_by_strategy.get(name, []),
                "active_positions": [],  # Will be matched below
                "intent_count": len(intent_by_strategy.get(name, [])),
                "position_count": 0,
                "is_hidden": False,  # Explicitly tracked
            })
        
        # Add any strategies with intents but no saved config (hidden execution)
        for strat_name in intent_by_strategy:
            if strat_name not in seen_strategies:
                seen_strategies.add(strat_name)
                strategies_execution.append({
                    "name": strat_name,
                    "status": "UNKNOWN",  # No saved config
                    "status_updated_at": None,
                    "created_at": None,
                    "underlying": "N/A",
                    "pending_intents": intent_by_strategy[strat_name],
                    "active_positions": positions_by_strategy.get(strat_name, []),
                    "intent_count": len(intent_by_strategy[strat_name]),
                    "position_count": len(positions_by_strategy.get(strat_name, [])),
                    "is_hidden": True,  # ⚠️ WARNING: Strategy running without saved config
                })

        # 5. Summary stats
        running_count = sum(1 for s in strategies_execution if s["status"] == "RUNNING")
        paused_count = sum(1 for s in strategies_execution if s["status"] == "PAUSED")
        pending_intents = sum(s["intent_count"] for s in strategies_execution)
        active_positions_total = sum(len(positions_by_strategy.get(s["name"], [])) for s in strategies_execution)

        # BUG-M4 FIX: `key=lambda x: x["status"] == "IDLE"` is a fragile
        # boolean sort — True > False in Python so IDLE (True=1) sorted last,
        # which was the intent ("Running first").  But it breaks silently if
        # someone adds a new status or changes the comparison.  Use an explicit
        # priority map instead.
        _STATUS_ORDER = {"RUNNING": 0, "PAUSED": 1, "STOPPED": 2, "IDLE": 3, "UNKNOWN": 4}
        return {
            "timestamp": datetime.now().isoformat(),
            "audit": {
                "total_configured_strategies": len(all_configs),
                "total_unique_strategies": len(strategies_execution),
                "strategies_running": running_count,
                "strategies_paused": paused_count,
                "strategies_idle": sum(1 for s in strategies_execution if s["status"] == "IDLE"),
                "strategies_unknown": sum(1 for s in strategies_execution if s["status"] == "UNKNOWN"),
                "pending_intents_in_queue": pending_intents,
                "active_positions_total": active_positions_total,
                "has_hidden_strategies": any(s["is_hidden"] for s in strategies_execution),
            },
            "strategies": sorted(strategies_execution, key=lambda x: _STATUS_ORDER.get(x["status"], 99)),
            "control_intents": control_intents,  # Full intent queue
        }

    except Exception as e:
        logger.exception("Failed to get strategy execution status")
        raise HTTPException(status_code=500, detail=str(e))
        

@router.post("/strategy/config/save-all")
def save_strategy_config_all(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    name = payload.get("name", "").strip()
    strat_id = payload.get("id", "").strip()

    if not name:
        raise HTTPException(400, "Strategy name is required")
    if not strat_id:
        strat_id = _slugify(name).upper()

    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    # Load existing (if any)
    existing = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # Merge the entire payload, preserving all keys
    # (but keep existing values for fields not present in payload)
    merged = {**existing, **payload}

    # Ensure backward‑compatible fields are present (optional)
    merged = ensure_complete_config(merged)

    # Validate before persisting, so this endpoint cannot bypass schema checks.
    is_valid, issues = validate_config(merged if isinstance(merged, dict) else {})
    if not is_valid:
        errors = [f"{e.path}: {e.message}" for e in issues if e.severity == "error"]
        warnings = [f"{e.path}: {e.message}" for e in issues if e.severity == "warning"]
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Strategy validation failed",
                "validation": {"valid": False, "errors": errors, "warnings": warnings},
            },
        )

    # Write back
    _write_json_file(filepath, merged)
    logger.info("Strategy config saved (all): %s", name)

    return {"saved": True, "name": name, "id": strat_id, "file": slug + ".json"}


@router.delete("/strategy/config/{name}")
def delete_strategy_config(
    name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Delete a saved strategy config by name."""
    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

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
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    if not filepath.exists():
        raise HTTPException(404, f"Config '{name}' not found")

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception:
        data = {"name": name}

    data["status"] = new_status
    data["status_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_json_file(filepath, data)

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

    _write_json_file(new_path, data)
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

    _write_json_file(dst_path, data)
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
    # 🔧 Safely get broker limits with fallback
    try:
        limits = broker.get_limits()
    except (RuntimeError, Exception) as e:
        logger.warning(f"Failed to get broker limits: {e}, returning empty limits")
        limits = {}
    
    return {
        "broker": {
            "positions": broker.get_positions(),
            "positions_summary": broker.get_positions_summary(),
            "holdings": broker.get_holdings(),
            "limits": limits,
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
    try:
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
    finally:
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
            
            # Find corresponding order/greek data (OrderRecord is a dataclass — use getattr)
            order_detail = next((o for o in orders if getattr(o, "symbol", None) == symbol), None)
            
            leg_data = {
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(getattr(order_detail, "price", 0) or 0) if order_detail else 0.0,
                "ltp": float(pos.get("ltp", 0) or 0),
                "avg_price": float(pos.get("avgprc", 0) or 0),
                
                # Greeks (if available in order detail)
                "delta": float(getattr(order_detail, "delta", 0) or 0) if order_detail else 0.0,
                "gamma": float(getattr(order_detail, "gamma", 0) or 0) if order_detail else 0.0,
                "theta": float(getattr(order_detail, "theta", 0) or 0) if order_detail else 0.0,
                "vega": float(getattr(order_detail, "vega", 0) or 0) if order_detail else 0.0,
                
                # PnL
                "realized_pnl": float(pos.get("rpnl", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
                "total_pnl": float(pos.get("upnl", 0) or 0) + float(pos.get("rpnl", 0) or 0),
            }
            
            legs_by_symbol[symbol] = leg_data
            
            # Get strategy name from order (OrderRecord is dataclass)
            strat = (getattr(order_detail, "strategy_name", None) if order_detail else None) or strategy_name or "UNKNOWN"
            
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
        
        # Find order details (OrderRecord is a dataclass — use getattr)
        order = next((o for o in orders if getattr(o, "symbol", None) == symbol), None)
        
        netqty = int(position.get("netqty", 0))
        
        return {
            "symbol": symbol,
            "exchange": position.get("exch"),
            "position": {
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(getattr(order, "price", 0) or 0) if order else 0.0,
                "avg_price": float(position.get("avgprc", 0) or 0),
                "ltp": float(position.get("ltp", 0) or 0),
            },
            "pnl": {
                "realized": float(position.get("rpnl", 0) or 0),
                "unrealized": float(position.get("upnl", 0) or 0),
                "total": float(position.get("upnl", 0) or 0) + float(position.get("rpnl", 0) or 0),
            },
            "greeks": {
                "delta": float(getattr(order, "delta", 0) or 0) if order else 0.0,
                "gamma": float(getattr(order, "gamma", 0) or 0) if order else 0.0,
                "theta": float(getattr(order, "theta", 0) or 0) if order else 0.0,
                "vega": float(getattr(order, "vega", 0) or 0) if order else 0.0,
                "rho": float(getattr(order, "rho", 0) or 0) if order else 0.0,
            },
            "metadata": {
                "strategy": getattr(order, "strategy_name", "UNKNOWN") if order else "UNKNOWN",
                "order_count": len([o for o in orders if getattr(o, "symbol", None) == symbol]),
                "updated_at": position.get("upl_time", ""),
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get leg greeks for {symbol}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitoring/live-positions-overview")
def get_live_positions_overview(
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """
    Live monitoring view for strategy page.

    Classifies each open broker position into:
    - strategy_active: linked to a strategy currently running in executor
    - strategy_inactive: linked to strategy orders, but strategy not running now
    - orphan: no strategy linkage (manual/external/orphan rule flow)
    """
    try:
        bot = ctx["bot"]
        positions = broker.get_positions() or []
        orders = system.get_orders(2000) or []

        # Active strategy names in-memory (executor/live registry).
        with bot._live_strategies_lock:
            active_strategies = set(bot._live_strategies.keys())

        def _order_ts(order_obj: Any) -> float:
            for attr in ("updated_at", "created_at"):
                value = getattr(order_obj, attr, None)
                if value is None:
                    continue
                if isinstance(value, datetime):
                    return value.timestamp()
                if isinstance(value, (int, float)):
                    return float(value)
                try:
                    return datetime.fromisoformat(str(value)).timestamp()
                except Exception:
                    continue
            return 0.0

        def _is_strategy_name(name: str) -> bool:
            if not name:
                return False
            clean = str(name).strip()
            if not clean:
                return False
            upper = clean.upper()
            if upper in {"UNKNOWN", "N/A", "NONE"}:
                return False
            if upper.startswith("ORPHAN_RULE_"):
                return False
            return True

        def _as_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value or 0)
            except Exception:
                return default

        # Keep latest known order metadata by symbol.
        latest_by_symbol: dict[str, tuple[float, str, Any]] = {}
        for order in orders:
            symbol = str(getattr(order, "symbol", "") or "").strip()
            if not symbol:
                continue
            strategy_name = str(getattr(order, "strategy_name", "") or "").strip()
            ts = _order_ts(order)
            prev = latest_by_symbol.get(symbol)
            if prev is None or ts >= prev[0]:
                latest_by_symbol[symbol] = (ts, strategy_name, order)

        classified: list[dict[str, Any]] = []
        seen_symbol_owner: set[tuple[str, str]] = set()
        for pos in positions:
            netqty = int(pos.get("netqty", 0) or 0)
            if netqty == 0:
                continue

            symbol = str(pos.get("tsym", "") or "").strip()
            if not symbol:
                continue

            mapped_strategy = ""
            order_detail = None
            if symbol in latest_by_symbol:
                mapped_strategy = latest_by_symbol[symbol][1]
                order_detail = latest_by_symbol[symbol][2]

            strategy_generated = _is_strategy_name(mapped_strategy)
            is_active = strategy_generated and mapped_strategy in active_strategies
            if is_active:
                owner_type = "strategy_active"
            elif strategy_generated:
                owner_type = "strategy_inactive"
            else:
                owner_type = "orphan"

            qty = abs(netqty)
            side = "BUY" if netqty > 0 else "SELL"
            # Shoonya payloads can vary by endpoint/session:
            # ltp may come as `ltp` or `lp`; unrealized may come as `upnl` or `urmtom`.
            ltp = float(pos.get("ltp", pos.get("lp", 0)) or 0)
            avg = float(pos.get("avgprc", pos.get("avg_price", 0)) or 0)
            rpnl = float(pos.get("rpnl", pos.get("realized_pnl", 0)) or 0)
            upnl = float(pos.get("upnl", pos.get("urmtom", 0)) or 0)
            total_pnl = rpnl + upnl

            item = {
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": qty,
                "side": side,
                "netqty": netqty,
                "position_source": "BROKER",
                "avg_price": avg,
                "ltp": ltp,
                "realized_pnl": rpnl,
                "unrealized_pnl": upnl,
                "total_pnl": total_pnl,
                "delta": _as_float(getattr(order_detail, "delta", 0) if order_detail else 0),
                "gamma": _as_float(getattr(order_detail, "gamma", 0) if order_detail else 0),
                "theta": _as_float(getattr(order_detail, "theta", 0) if order_detail else 0),
                "vega": _as_float(getattr(order_detail, "vega", 0) if order_detail else 0),
                "strategy_name": mapped_strategy if strategy_generated else None,
                "owner_type": owner_type,
                "updated_at": pos.get("upl_time") or "",
            }
            classified.append(item)
            seen_symbol_owner.add((symbol, owner_type))

        # Add virtual executor-state positions.
        # These may not be present in broker positions yet (or in MOCK mode),
        # but should still be visible in monitor.
        svc = getattr(bot, "strategy_executor_service", None)
        if svc is not None:
            exec_states = dict(getattr(svc, "_exec_states", {}) or {})
            strategy_cfgs = dict(getattr(svc, "_strategies", {}) or {})

            for strat_name, state in exec_states.items():
                try:
                    if not bool(getattr(state, "any_leg_active", False)):
                        continue
                    cfg = strategy_cfgs.get(strat_name, {})
                    mode = "LIVE"
                    try:
                        mode = "MOCK" if bool(getattr(svc, "_is_paper_mode")(cfg)) else "LIVE"
                    except Exception:
                        identity_cfg = cfg.get("identity", {}) or {}
                        mode = "MOCK" if bool(cfg.get("paper_mode") or identity_cfg.get("paper_mode") or cfg.get("test_mode") or identity_cfg.get("test_mode")) else "LIVE"

                    owner_type = "strategy_active" if strat_name in active_strategies else "strategy_inactive"
                    now_iso = datetime.now().isoformat()
                    for leg in (getattr(state, "legs", {}) or {}).values():
                        if not bool(getattr(leg, "is_active", False)):
                            continue
                        symbol = str(
                            getattr(leg, "trading_symbol", None)
                            or getattr(leg, "symbol", "")
                        ).strip()
                        lots_qty = int(getattr(leg, "qty", 0) or 0)
                        qty = lots_qty
                        try:
                            exec_obj = (getattr(svc, "_executors", {}) or {}).get(strat_name)
                            if exec_obj is not None and hasattr(exec_obj, "_lots_to_order_qty"):
                                qty = int(exec_obj._lots_to_order_qty(lots_qty, leg))
                        except Exception:
                            qty = lots_qty
                        if not symbol or lots_qty <= 0:
                            continue
                        key = (symbol, owner_type)
                        if key in seen_symbol_owner:
                            continue
                        seen_symbol_owner.add(key)

                        side_val = getattr(getattr(leg, "side", None), "value", getattr(leg, "side", ""))
                        side_s = str(side_val or "").upper()
                        delta = float(getattr(leg, "delta", 0) or 0)
                        gamma = float(getattr(leg, "gamma", 0) or 0)
                        theta = float(getattr(leg, "theta", 0) or 0)
                        vega = float(getattr(leg, "vega", 0) or 0)
                        upnl = float(getattr(leg, "pnl", 0) or 0)

                        classified.append({
                            "symbol": symbol,
                            "exchange": (cfg.get("identity", {}) or {}).get("exchange", ""),
                            "qty": qty,
                            "side": side_s,
                            "netqty": int(qty if side_s == "BUY" else -qty),
                            "position_source": "PAPER" if mode == "MOCK" else "EXECUTOR_STATE",
                            "avg_price": float(getattr(leg, "entry_price", 0) or 0),
                            "ltp": float(getattr(leg, "ltp", 0) or 0),
                            "realized_pnl": 0.0,
                            "unrealized_pnl": upnl,
                            "total_pnl": upnl,
                            "delta": delta,
                            "gamma": gamma,
                            "theta": theta,
                            "vega": vega,
                            "strategy_name": strat_name,
                            "owner_type": owner_type,
                            "updated_at": now_iso,
                        })
                except Exception as leg_err:
                    logger.debug("Skipping paper leg mapping for %s: %s", strat_name, leg_err)

        strategy_positions = [p for p in classified if p["owner_type"] != "orphan"]
        orphan_positions = [p for p in classified if p["owner_type"] == "orphan"]
        leg_snapshot: dict[str, Any] = {}
        strategy_modes: dict[str, str] = {}
        completed_strategy_groups: list[dict[str, Any]] = []
        if svc is not None:
            try:
                getter = getattr(svc, "get_strategy_leg_monitor_snapshot", None)
                if callable(getter):
                    result = getter()
                    if isinstance(result, dict):
                        leg_snapshot = result
                    else:
                        logger.debug("Leg monitor snapshot returned non-dict, ignoring")
            except Exception as snap_err:
                logger.debug("Could not fetch strategy leg monitor snapshot: %s", snap_err)
            try:
                mode_getter = getattr(svc, "get_strategy_mode", None)
                if callable(mode_getter):
                    for strat in set(list(getattr(svc, "_strategies", {}).keys()) + list((leg_snapshot or {}).keys())):
                        strategy_modes[strat] = str(mode_getter(strat) or "LIVE").upper()
            except Exception as mode_err:
                logger.debug("Could not fetch strategy modes for monitor: %s", mode_err)
            try:
                completed_getter = getattr(svc, "get_completed_strategy_monitor_history", None)
                if callable(completed_getter):
                    result = completed_getter(limit=50)
                    if isinstance(result, list):
                        for row in result:
                            if isinstance(row, dict):
                                strat_name = str(row.get("strategy_name", "") or "")
                                mode_val = str(row.get("mode", "") or "").upper()
                                if mode_val not in {"LIVE", "MOCK"} and strat_name:
                                    row["mode"] = _mode_from_saved_file(strat_name)
                        completed_strategy_groups = result
            except Exception as history_err:
                logger.debug("Could not fetch completed strategy monitor history: %s", history_err)

        def _group_mode(strategy_name: str) -> str:
            known = str(strategy_modes.get(strategy_name, "") or "").upper()
            if known in {"LIVE", "MOCK"}:
                return known
            resolved = _mode_from_saved_file(strategy_name)
            strategy_modes[strategy_name] = resolved
            return resolved

        by_strategy: dict[str, dict[str, Any]] = {}
        for p in strategy_positions:
            strat = p.get("strategy_name") or "UNKNOWN"
            if strat not in by_strategy:
                by_strategy[strat] = {
                    "strategy_name": strat,
                    "mode": _group_mode(strat),
                    "active": strat in active_strategies,
                    "adjustments_today": 0,
                    "lifetime_adjustments": 0,
                    "last_adjustment_time": None,
                    "leg_count": 0,
                    "total_qty": 0,
                    "total_pnl": 0.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "combined_delta": 0.0,
                    "combined_gamma": 0.0,
                    "combined_theta": 0.0,
                    "combined_vega": 0.0,
                    "active_legs": 0,
                    "closed_legs": 0,
                    "positions": [],
                    "all_legs": [],
                }
            by_strategy[strat]["leg_count"] += 1
            by_strategy[strat]["total_qty"] += int(p.get("qty", 0) or 0)
            by_strategy[strat]["total_pnl"] += float(p.get("total_pnl", 0) or 0)
            by_strategy[strat]["realized_pnl"] += float(p.get("realized_pnl", 0) or 0)
            by_strategy[strat]["unrealized_pnl"] += float(p.get("unrealized_pnl", 0) or 0)
            by_strategy[strat]["combined_delta"] += float(p.get("delta", 0) or 0)
            by_strategy[strat]["combined_gamma"] += float(p.get("gamma", 0) or 0)
            by_strategy[strat]["combined_theta"] += float(p.get("theta", 0) or 0)
            by_strategy[strat]["combined_vega"] += float(p.get("vega", 0) or 0)
            by_strategy[strat]["active_legs"] += 1
            by_strategy[strat]["positions"].append(p)

        # Merge full strategy leg history (active + closed) from executor snapshot.
        for strat, snap in (leg_snapshot or {}).items():
            if strat not in by_strategy:
                by_strategy[strat] = {
                    "strategy_name": strat,
                    "mode": _group_mode(strat),
                    "active": strat in active_strategies,
                    "adjustments_today": 0,
                    "lifetime_adjustments": 0,
                    "last_adjustment_time": None,
                    "leg_count": 0,
                    "total_qty": 0,
                    "total_pnl": 0.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "combined_delta": 0.0,
                    "combined_gamma": 0.0,
                    "combined_theta": 0.0,
                    "combined_vega": 0.0,
                    "active_legs": 0,
                    "closed_legs": 0,
                    "positions": [],
                    "all_legs": [],
                }
            group = by_strategy[strat]
            legs = list((snap or {}).get("legs") or [])
            # Keep latest first for UI readability.
            legs.sort(key=lambda x: str(x.get("updated_at") or x.get("opened_at") or ""), reverse=True)
            group["all_legs"] = legs
            group["active_leg_rows"] = [l for l in legs if str(l.get("status", "")).upper() == "ACTIVE"]
            group["closed_leg_rows"] = [l for l in legs if str(l.get("status", "")).upper() == "CLOSED"]
            group["active_legs"] = int((snap or {}).get("active_legs", group.get("active_legs", 0)) or 0)
            group["closed_legs"] = int((snap or {}).get("closed_legs", 0) or 0)
            group["realized_pnl"] = float((snap or {}).get("realized_pnl", group.get("realized_pnl", 0.0)) or 0.0)
            group["unrealized_pnl"] = float((snap or {}).get("unrealized_pnl", group.get("unrealized_pnl", 0.0)) or 0.0)
            group["adjustments_today"] = int((snap or {}).get("adjustments_today", group.get("adjustments_today", 0)) or 0)
            group["lifetime_adjustments"] = int((snap or {}).get("lifetime_adjustments", group.get("lifetime_adjustments", 0)) or 0)
            group["last_adjustment_time"] = (snap or {}).get("last_adjustment_time", group.get("last_adjustment_time"))
            group["total_pnl"] = float(group["realized_pnl"] + group["unrealized_pnl"])
            active_legs = list(group["active_leg_rows"])
            if active_legs:
                group["combined_delta"] = sum(float(l.get("delta", 0) or 0) for l in active_legs)
                group["combined_gamma"] = sum(float(l.get("gamma", 0) or 0) for l in active_legs)
                group["combined_theta"] = sum(float(l.get("theta", 0) or 0) for l in active_legs)
                group["combined_vega"] = sum(float(l.get("vega", 0) or 0) for l in active_legs)

            opened_ts_all = []
            closed_ts_all = []
            opened_ts_active = []
            for l in legs:
                raw_opened = l.get("opened_at")
                raw_closed = l.get("closed_at")
                status_u = str(l.get("status", "")).upper()
                try:
                    if raw_opened:
                        ts_open = datetime.fromisoformat(str(raw_opened)).timestamp()
                        opened_ts_all.append(ts_open)
                        if status_u == "ACTIVE":
                            opened_ts_active.append(ts_open)
                except Exception:
                    pass
                try:
                    if raw_closed:
                        closed_ts_all.append(datetime.fromisoformat(str(raw_closed)).timestamp())
                except Exception:
                    pass

            if group["active_legs"] > 0 and opened_ts_active:
                # Running runtime: live elapsed from oldest active leg open.
                runtime_seconds = int(max(0, time.time() - min(opened_ts_active)))
                runtime_state = "RUNNING"
            elif opened_ts_all and closed_ts_all:
                # Completed runtime: fixed elapsed from first open to last close.
                runtime_seconds = int(max(0, max(closed_ts_all) - min(opened_ts_all)))
                runtime_state = "COMPLETED"
            else:
                runtime_seconds = 0
                runtime_state = "IDLE"

            group["runtime_seconds"] = runtime_seconds
            group["runtime_state"] = runtime_state
            group["analytics"] = {
                "win_legs": len([l for l in group["closed_leg_rows"] if float(l.get("realized_pnl", 0) or 0) > 0]),
                "loss_legs": len([l for l in group["closed_leg_rows"] if float(l.get("realized_pnl", 0) or 0) < 0]),
                "flat_legs": len([l for l in group["closed_leg_rows"] if float(l.get("realized_pnl", 0) or 0) == 0]),
                "avg_realized_per_closed_leg": (
                    float(group["realized_pnl"]) / float(group["closed_legs"])
                    if float(group["closed_legs"] or 0) > 0
                    else 0.0
                ),
            }

        # Fallback for strategies without explicit leg snapshot.
        for group in by_strategy.values():
            if group.get("all_legs"):
                continue
            fallback_legs = []
            for p in group.get("positions", []):
                fallback_legs.append({
                    "strategy_name": group.get("strategy_name"),
                    "exchange": p.get("exchange"),
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "qty": int(p.get("qty", 0) or 0),
                    "entry_price": float(p.get("avg_price", 0) or 0),
                    "exit_price": None,
                    "status": "ACTIVE",
                    "source": p.get("position_source") or "BROKER",
                    "realized_pnl": float(p.get("realized_pnl", 0) or 0),
                    "unrealized_pnl": float(p.get("unrealized_pnl", 0) or 0),
                    "total_pnl": float(p.get("total_pnl", 0) or 0),
                    "delta": float(p.get("delta", 0) or 0),
                    "gamma": float(p.get("gamma", 0) or 0),
                    "theta": float(p.get("theta", 0) or 0),
                    "vega": float(p.get("vega", 0) or 0),
                    "opened_at": p.get("updated_at") or "",
                    "closed_at": None,
                    "updated_at": p.get("updated_at") or "",
                })
            group["all_legs"] = fallback_legs
            if not str(group.get("mode", "")).strip():
                group["mode"] = _group_mode(group.get("strategy_name") or "")
            group["active_leg_rows"] = [l for l in fallback_legs if str(l.get("status", "")).upper() == "ACTIVE"]
            group["closed_leg_rows"] = [l for l in fallback_legs if str(l.get("status", "")).upper() == "CLOSED"]
            group["runtime_seconds"] = 0
            group["runtime_state"] = "IDLE"
            group["analytics"] = {
                "win_legs": 0,
                "loss_legs": 0,
                "flat_legs": 0,
                "avg_realized_per_closed_leg": 0.0,
            }

        orphan_aggregate = {
            "leg_count": len(orphan_positions),
            "total_pnl": sum(float(p.get("total_pnl", 0) or 0) for p in orphan_positions),
            "realized_pnl": sum(float(p.get("realized_pnl", 0) or 0) for p in orphan_positions),
            "unrealized_pnl": sum(float(p.get("unrealized_pnl", 0) or 0) for p in orphan_positions),
            "combined_delta": sum(float(p.get("delta", 0) or 0) for p in orphan_positions),
            "combined_gamma": sum(float(p.get("gamma", 0) or 0) for p in orphan_positions),
            "combined_theta": sum(float(p.get("theta", 0) or 0) for p in orphan_positions),
            "combined_vega": sum(float(p.get("vega", 0) or 0) for p in orphan_positions),
        }

        strategy_realized = sum(float(g.get("realized_pnl", 0) or 0) for g in by_strategy.values())
        strategy_unrealized = sum(float(g.get("unrealized_pnl", 0) or 0) for g in by_strategy.values())
        portfolio_realized = strategy_realized + float(orphan_aggregate.get("realized_pnl", 0) or 0)
        portfolio_unrealized = strategy_unrealized + float(orphan_aggregate.get("unrealized_pnl", 0) or 0)

        return {
            "timestamp": datetime.now().isoformat(),
            "active_strategy_names": sorted(active_strategies),
            "summary": {
                "total_open_positions": len(classified),
                "strategy_linked_positions": len(strategy_positions),
                "orphan_positions": len(orphan_positions),
                "strategy_active_positions": len([p for p in classified if p["owner_type"] == "strategy_active"]),
                "strategy_inactive_positions": len([p for p in classified if p["owner_type"] == "strategy_inactive"]),
                "portfolio_total_pnl": float(portfolio_realized + portfolio_unrealized),
                "portfolio_realized_pnl": float(portfolio_realized),
                "portfolio_unrealized_pnl": float(portfolio_unrealized),
                "strategy_realized_pnl": float(strategy_realized),
                "strategy_unrealized_pnl": float(strategy_unrealized),
                "total_strategy_legs_tracked": sum(len(g.get("all_legs") or []) for g in by_strategy.values()),
                "total_closed_strategy_legs": sum(int(g.get("closed_legs", 0) or 0) for g in by_strategy.values()),
                "completed_strategy_runs": len(completed_strategy_groups),
                "portfolio_combined_delta": sum(float(p.get("delta", 0) or 0) for p in classified),
                "portfolio_combined_gamma": sum(float(p.get("gamma", 0) or 0) for p in classified),
                "portfolio_combined_theta": sum(float(p.get("theta", 0) or 0) for p in classified),
                "portfolio_combined_vega": sum(float(p.get("vega", 0) or 0) for p in classified),
            },
            "strategy_groups": list(by_strategy.values()),
            "completed_strategy_groups": completed_strategy_groups,
            "orphan_aggregate": orphan_aggregate,
            "orphan_positions": orphan_positions,
            "all_positions": classified,
        }
    except Exception as e:
        logger.exception("Failed to build live positions overview")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================================
# 🔥 INDEX TOKENS API
# ======================================================================

@router.get("/index-tokens/prices")
def get_index_tokens_prices(
    symbols: Optional[str] = Query(
        None,
        description="Comma-separated list (e.g., 'NIFTY,BANKNIFTY,SENSEX'). If None, returns all subscribed."
    ),
    ctx=Depends(require_dashboard_auth),
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
def list_available_indices(ctx=Depends(require_dashboard_auth)):
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


# ======================================================================
# 📊 STRATEGY MANAGEMENT ENDPOINTS (NEW)
# ======================================================================


# ======================================================================
# HISTORICAL ANALYTICS API (POSTGRESQL LAYER)
# ======================================================================

@router.get("/analytics/history/health")
def analytics_history_health(ctx=Depends(require_dashboard_auth)):
    svc = _get_historical_service(ctx)
    return svc.health()


@router.get("/analytics/history/strategy-samples")
def analytics_strategy_samples(
    strategy_name: str = Query(..., min_length=1),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(5000, ge=1, le=20000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    return {
        "strategy_name": strategy_name,
        "rows": svc.store.fetch_strategy_samples(
            strategy_name=strategy_name,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


@router.get("/analytics/history/strategy-events")
def analytics_strategy_events(
    strategy_name: str = Query(..., min_length=1),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(2000, ge=1, le=20000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    return {
        "strategy_name": strategy_name,
        "rows": svc.store.fetch_strategy_events(
            strategy_name=strategy_name,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


@router.get("/analytics/history/index-ticks")
def analytics_index_ticks(
    symbols: str = Query(..., description="Comma-separated symbol list"),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(20000, ge=1, le=50000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    syms = [s.strip().upper() for s in str(symbols).split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    return {
        "symbols": syms,
        "rows": svc.store.fetch_index_ticks(
            symbols=syms,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


@router.get("/analytics/history/option-metrics")
def analytics_option_metrics(
    exchange: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    expiry: Optional[str] = Query(None),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(5000, ge=1, le=20000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    return {
        "exchange": exchange,
        "symbol": symbol,
        "expiry": expiry,
        "rows": svc.store.fetch_option_metrics(
            exchange=(exchange.upper() if exchange else None),
            symbol=(symbol.upper() if symbol else None),
            expiry=expiry,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


class _ValidationResult:
    def __init__(self, valid: bool, errors: List[str], warnings: List[str]):
        self.valid = valid
        self.errors = errors
        self.warnings = warnings

    def to_dict(self):
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def validate_strategy(config, strategy_name):
    is_valid, issues = validate_config(config if isinstance(config, dict) else {})
    errors = [f"{e.path}: {e.message}" for e in issues if e.severity == "error"]
    warnings = [f"{e.path}: {e.message}" for e in issues if e.severity == "warning"]
    return _ValidationResult(is_valid, errors, warnings)


class _NoopStrategyLogger:
    def get_recent_logs(self, lines=100, level=None):
        return []


def get_strategy_logger(strategy_name):
    return _NoopStrategyLogger()


class _NoopLoggerManager:
    def __init__(self):
        self.loggers = {}

    def list_active_strategies(self):
        return []

    def get_logs(self, strategy_name, lines=100):
        return []

    def clear_logs(self, strategy_name):
        return True

    def clear_strategy_logs(self, strategy_name):
        return True

    def get_all_logs_combined(self, lines=500):
        return []


def get_logger_manager():
    return _NoopLoggerManager()

def get_all_strategies():
    """List all strategy JSON files from saved_configs/"""
    if not STRATEGY_CONFIG_DIR.exists():
        return []
    
    strategies = []
    for json_file in STRATEGY_CONFIG_DIR.glob("*.json"):
        if json_file.name == "STRATEGY_CONFIG_SCHEMA.json":
            continue  # Skip schema file
        try:
            with open(json_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                strategies.append({
                    "name": json_file.stem,
                    "filename": json_file.name,
                    "created": json_file.stat().st_ctime,
                    "modified": json_file.stat().st_mtime,
                    "config": config
                })
        except Exception as e:
            logger.warning(f"Failed to read strategy {json_file.name}: {e}")
    
    return strategies

def load_strategy_json(name: str):
    """Load strategy JSON by name"""
    strategy_file = STRATEGY_CONFIG_DIR / f"{name}.json"
    if not strategy_file.exists():
        return None
    
    with open(strategy_file, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def save_strategy_json(name: str, config: dict):
    """Save strategy JSON by name — ensures ALL schema fields are present."""
    STRATEGY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    strategy_file = STRATEGY_CONFIG_DIR / f"{name}.json"

    # Ensure all v2.0 schema fields are present (even if None)
    complete = ensure_complete_config(config)
    # Guarantee name/id are set
    complete["name"] = complete.get("name") or name
    complete["id"] = complete.get("id") or name.upper().replace(" ", "_").strip("_")

    import time as _t
    now = _t.strftime("%Y-%m-%dT%H:%M:%S")
    if not complete.get("created_at"):
        complete["created_at"] = now
    complete["updated_at"] = now

    _write_json_file(strategy_file, complete)

    return strategy_file

# ======================================================================
# 🎯 STRATEGY LIST
# ======================================================================

@router.get("/strategy/list")
def list_all_strategies(ctx=Depends(require_dashboard_auth)):
    """
    List all saved strategies from saved_configs/ directory
    
    Returns:
        {
            "total": 3,
            "strategies": [
                {
                    "name": "NIFTY_DNSS",
                    "filename": "NIFTY_DNSS.json",
                    "created": 1707000000.0,
                    "modified": 1707000000.0,
                    "config": {...}
                }
            ]
        }
    """
    try:
        strategies = get_all_strategies()
        return {
            "total": len(strategies),
            "strategies": strategies,
            "timestamp": datetime.now().isoformat(),
            "directory": str(STRATEGY_CONFIG_DIR)
        }
    except Exception as e:
        logger.error(f"Error listing strategies: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# 🔍 GET SINGLE STRATEGY
# ======================================================================

@router.get("/strategy/{strategy_name}")
def get_strategy_by_name(strategy_name: str, ctx=Depends(require_dashboard_auth)):
    """
    Get specific strategy by name
    
    Args:
        strategy_name: Name of strategy (without .json extension)
    
    Returns:
        {
            "name": "NIFTY_DNSS",
            "filename": "NIFTY_DNSS.json",
            "config": {...},
            "validation": {...}
        }
    """
    try:
        config = load_strategy_json(strategy_name)
        if not config:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{strategy_name}' not found"
            )
        
        # Normalize for validation (adds market_config from identity etc.)
        normalized = ensure_complete_config(config)
        validation_result = validate_strategy(normalized, strategy_name)
        
        return {
            "name": strategy_name,
            "config": config,
            "validation": validation_result.to_dict(),
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# ✅ VALIDATE STRATEGY CONFIG
# ======================================================================
@router.post("/strategy/validate")
def validate_strategy_config(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """
    Validate strategy JSON configuration BEFORE saving.
    Accepts the full strategy config as request body.
    Extracts name from payload['name'].
    """
    strategy_name = "UNKNOWN"  # ✅ Initialize before try block
    try:
        strategy_name = payload.get("name", "UNKNOWN")
        # Normalize config so validator sees all fields including market_config
        strategy_config = ensure_complete_config(payload)
        result = validate_strategy(strategy_config, strategy_name)
        return {
            **result.to_dict(),
            "name": strategy_name,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error validating strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
# ======================================================================
# ➕ CREATE STRATEGY
# ======================================================================

@router.post("/strategy/create")
def create_new_strategy(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """
    Create new strategy.
    Accepts full config as body; name extracted from payload['name'].
    Validates, ensures all fields, then saves.
    """
    try:
        strategy_name = (payload.get("name") or "").strip()
        if not strategy_name:
            raise HTTPException(400, "Strategy name is required (payload.name)")

        # Ensure complete + validate
        complete = ensure_complete_config(payload)
        validation_result = validate_strategy(complete, strategy_name)

        if not validation_result.valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Strategy validation failed",
                    "validation": validation_result.to_dict(),
                },
            )

        # Slugify for filename
        slug = _slugify(strategy_name)

        # Check if already exists
        existing = load_strategy_json(slug)
        if existing:
            raise HTTPException(409, f"Strategy '{strategy_name}' already exists")

        # Save (ensure_complete_config called again inside save_strategy_json)
        filepath = save_strategy_json(slug, complete)

        return {
            "success": True,
            "name": strategy_name,
            "filename": f"{slug}.json",
            "path": str(filepath),
            "validation": validation_result.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating strategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# ✏️ UPDATE STRATEGY
# ======================================================================

@router.put("/strategy/{strategy_name}")
def update_strategy(
    strategy_name: str,
    strategy_config: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """
    Update existing strategy — validates before saving.
    Ensures all fields are present in saved JSON.
    """
    try:
        complete = ensure_complete_config(strategy_config)
        validation_result = validate_strategy(complete, strategy_name)

        if not validation_result.valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Strategy validation failed",
                    "validation": validation_result.to_dict(),
                },
            )

        existing = load_strategy_json(strategy_name)
        if not existing:
            raise HTTPException(404, f"Strategy '{strategy_name}' not found")

        filepath = save_strategy_json(strategy_name, complete)

        return {
            "success": True,
            "name": strategy_name,
            "updated": True,
            "path": str(filepath),
            "validation": validation_result.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# 🗑️ DELETE STRATEGY
# ======================================================================

@router.delete("/strategy/{strategy_name}")
def delete_strategy(strategy_name: str, ctx=Depends(require_dashboard_auth)):
    """
    Delete strategy file from saved_configs/
    
    Args:
        strategy_name: Name of strategy to delete
    
    Returns:
        {
            "success": true,
            "name": "NIFTY_DNSS",
            "deleted": true
        }
    """
    try:
        strategy_file = STRATEGY_CONFIG_DIR / f"{strategy_name}.json"
        
        if not strategy_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{strategy_name}' not found"
            )
        
        # ✅ BUG-005 FIX: logger_mgr.loggers is always {} — it never tracked running strategies.
        # Check service._strategies which is the authoritative running-strategy registry.
        try:
            bot = ctx["bot"]
            service = bot.strategy_executor_service
            if strategy_name in service._strategies or _slugify(strategy_name) in service._strategies:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete running strategy '{strategy_name}'"
                )
        except HTTPException:
            raise
        except Exception:
            pass  # If service unavailable, fall through to file delete
        
        # Delete file
        strategy_file.unlink()
        
        # Clear any logs if existed
        get_logger_manager().clear_strategy_logs(strategy_name)
        
        return {
            "success": True,
            "name": strategy_name,
            "deleted": True,
            "path": str(strategy_file),
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# 🎮 RUNNER CONTROL
# ======================================================================

# BUG-M3 FIX: plain dict grows forever in multi-client deployments — each
# client_id entry holds a StrategyExecutorService (with market data subs,
# position state, etc.) that is never released.
# WeakValueDictionary lets entries be GC'd as soon as the service object
# has no other strong references (e.g. after a client session expires and
# the bot shuts down its executor).
from weakref import WeakValueDictionary
_runner_instances: WeakValueDictionary = WeakValueDictionary()
_runner_instances_lock = threading.Lock()

def _strategy_state_file(service: Any, strategy_key: str) -> Path:
    """Resolve per-strategy runtime state file used by PerStrategyExecutor."""
    state_db_path = getattr(service, "state_db_path", "") or ""
    base_dir = Path(state_db_path).parent if state_db_path else Path(".")
    return base_dir / f"{strategy_key}_state.pkl"

def get_runner_singleton(ctx: dict):
    """Get StrategyExecutorService singleton for the current client."""
    global _runner_instances
    client_id = ctx.get("client_id")
    if not client_id:
        raise RuntimeError("No client_id in context")
    
    with _runner_instances_lock:
        if client_id not in _runner_instances:
            logger.info(f"Initializing StrategyExecutorService for client {client_id}")
            try:
                bot = ctx["bot"]
                _runner_instances[client_id] = bot.strategy_executor_service
            except Exception as e:
                logger.error(f"Failed to initialize runner for client {client_id}: {e}")
                raise
        return _runner_instances[client_id]

@router.post("/runner/start")
def start_runner(ctx=Depends(require_dashboard_auth)):
    """
    Start the strategy runner - loads all strategies from saved_configs/
    
    Returns:
        {
            "success": true,
            "runner_started": true,
            "strategies_loaded": 3,
            "strategies": ["NIFTY_DNSS", "BANKNIFTY_THETA", "MCX_OIL"],
            "timestamp": "2026-02-12T..."
        }
    """
    try:
        bot = ctx["bot"]
        runner = get_runner_singleton(ctx)

        loaded = []
        errors = []
        for cfg_path in sorted(STRATEGY_CONFIG_DIR.glob("*.json")):
            if cfg_path.name == "STRATEGY_CONFIG_SCHEMA.json":
                continue
            name = cfg_path.stem
            if name in runner._strategies:
                loaded.append(name)
                continue
            try:
                runner.register_strategy(name=name, config_path=str(cfg_path))
                with bot._live_strategies_lock:
                    bot._live_strategies[name] = {
                        "type": "executor_service",
                        "config_path": str(cfg_path),
                        "started_at": time.time(),
                    }
                loaded.append(name)
            except Exception as e:
                logger.warning(f"Failed to load strategy {name}: {e}")
                errors.append(name)

        if not runner._running:
            runner.start()

        return {
            "success": True,
            "runner_started": True,
            "strategies_loaded": len(loaded),
            "strategies": loaded,
            "errors": errors,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error starting runner: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/runner/stop")
def stop_runner(ctx=Depends(require_dashboard_auth)):
    """
    Stop the strategy runner
    
    Returns:
        {
            "success": true,
            "runner_stopped": true,
            "strategies_stopped": 3
        }
    """
    try:
        bot = ctx["bot"]
        runner = get_runner_singleton(ctx)

        stopped_count = len(runner._strategies)
        for name in list(runner._strategies.keys()):
            runner.unregister_strategy(name)
        with bot._live_strategies_lock:
            bot._live_strategies.clear()
        runner.stop()

        return {
            "success": True,
            "runner_stopped": True,
            "strategies_stopped": stopped_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error stopping runner: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/runner/status")
def get_runner_status(ctx=Depends(require_dashboard_auth)):
    """
    Get runner status and active strategies
    
    Returns:
        {
            "runner_active": true,
            "is_running": true,
            "strategies_active": 3,
            "active_strategies": ["NIFTY_DNSS", "BANKNIFTY_THETA"],
            "timestamp": "2026-02-12T..."
        }
    """
    try:
        runner = get_runner_singleton(ctx)
        return {
            "runner_active": runner is not None,
            "is_running": bool(runner._running),
            "strategies_active": len(runner._strategies),
            "active_strategies": list(runner._strategies.keys()),
            "total_strategies_available": len(get_all_strategies()),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting runner status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# 📋 STRATEGY LOGGING
# ======================================================================

@router.get("/strategy/{strategy_name}/logs")
def get_strategy_logs(
    strategy_name: str,
    lines: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None, description="Filter by log level"),
    ctx=Depends(require_dashboard_auth)
):
    """
    Get recent logs for specific strategy
    
    Args:
        strategy_name: Name of strategy
        lines: Number of recent lines to return (1-1000)
        level: Filter by log level (DEBUG, INFO, WARNING, ERROR)
    
    Returns:
        {
            "strategy": "NIFTY_DNSS",
            "lines_returned": 50,
            "logs": [
                {
                    "timestamp": "2026-02-12 10:30:45",
                    "level": "INFO",
                    "logger": "STRATEGY.NIFTY_DNSS",
                    "message": "Entry condition met"
                }
            ]
        }
    """
    try:
        logger_obj = get_strategy_logger(strategy_name)
        logs = logger_obj.get_recent_logs(lines=lines, level=level)
        
        return {
            "strategy": strategy_name,
            "lines_returned": len(logs),
            "logs": logs,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting logs for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/runner/logs")
def get_all_runner_logs(
    lines: int = Query(50, ge=1, le=500),
    ctx=Depends(require_dashboard_auth)
):
    """
    Get recent logs from all running strategies combined
    
    Args:
        lines: Number of recent lines to return
    
    Returns:
        {
            "strategies_with_logs": 3,
            "total_lines": 75,
            "logs": [
                {
                    "strategy": "NIFTY_DNSS",
                    "timestamp": "2026-02-12 10:30:45",
                    "level": "INFO",
                    "message": "Entry condition met"
                }
            ]
        }
    """
    try:
        manager = get_logger_manager()
        combined_logs = manager.get_all_logs_combined(lines=lines)
        
        return {
            "strategies_with_logs": len(manager.loggers),
            "total_lines": len(combined_logs),
            "logs": combined_logs,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting all logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# 🔌 WEBSOCKET - LOG STREAMING (OPTIONAL - FUTURE)
# ======================================================================
@router.websocket("/runner/logs/stream")
async def websocket_log_stream(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Dashboard auth token (pass as ?token=...)"),
):
    """
    WebSocket endpoint for real-time log streaming.
    Auth: pass session token as query param ?token=<value>

    Connect to: ws://localhost:8000/dashboard/runner/logs/stream?token=<token>
    """
    # BUG-C2 FIX: authenticate before accepting the WebSocket connection.
    # Cookies are not forwarded on WS upgrades in most browsers/clients,
    # so we require the token as a query parameter instead.
    from shoonya_platform.api.dashboard.deps import verify_dashboard_token
    try:
        verify_dashboard_token(token)
    except Exception:
        await websocket.close(code=4401)  # 4xxx = application-level close codes
        return
    await websocket.accept()
    try:
        import asyncio
        manager = get_logger_manager()
        # Track how many logs we've already sent per strategy
        sent_count = {}
        
        while True:
            # Get logs from each strategy manager
            for strategy_name, logger_obj in manager.loggers.items():
                # Get a larger window and track by count sent
                logs = logger_obj.get_recent_logs(lines=50)
                
                if strategy_name not in sent_count:
                    sent_count[strategy_name] = 0
                
                total_available = len(logs)
                already_sent = sent_count[strategy_name]
                
                # Detect log rotation (new total < what we've sent)
                if total_available < already_sent:
                    already_sent = 0
                
                # Send only new logs (from the end of the list)
                new_logs = logs[already_sent:] if already_sent < total_available else []
                for log in new_logs:
                    await websocket.send_json({
                        "strategy": strategy_name,
                        "timestamp": log.get("timestamp") if isinstance(log, dict) else str(log),
                        "level": log.get("level") if isinstance(log, dict) else "INFO",
                        "message": log.get("message") if isinstance(log, dict) else str(log),
                    })
                
                sent_count[strategy_name] = total_available
            
            # Sleep before next poll
            await asyncio.sleep(1)
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

# ======================================================================
# FILE-BASED LOG VIEW (REAL RUNTIME LOGS)
# ======================================================================

def _resolve_client_log_file(ctx: dict, component: str = "application") -> Path:
    """
    Resolve client-scoped log path by component.
    Priority:
    1) logs/<client_short_id>/<file>
    2) logs/<file>
    """
    client_id = str(ctx.get("client_id", "") or "")
    short_id = client_id.split(":")[-1].strip() if client_id else ""
    log_root = _PROJECT_ROOT / "logs"
    comp = str(component or "application").strip().lower()

    filename_map = {
        "application": "application.log",
        "app": "application.log",
        "strategy_executor": "strategy_executor.log",
        "strategy": "strategy_executor.log",
        "runner": "strategy_executor.log",
    }
    filename = filename_map.get(comp, "application.log")

    if short_id:
        candidate = log_root / short_id / filename
        if candidate.exists():
            return candidate

    fallback = log_root / filename
    return fallback


@router.get("/runner/file-logs")
def get_runner_file_logs(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    lines: int = Query(300, ge=1, le=5000),
    level: Optional[str] = Query(None, description="DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    component: str = Query("application", description="application | strategy_executor"),
    ctx=Depends(require_dashboard_auth),
):
    """
    Read real runtime logs from application.log (client-scoped).
    Returns plain text lines after optional strategy + level filtering.
    """
    try:
        log_path = _resolve_client_log_file(ctx, component=component)
        if not log_path.exists():
            return {
                "path": str(log_path),
                "strategy": strategy,
                "level": level,
                "component": component,
                "lines_returned": 0,
                "lines": [],
                "timestamp": datetime.now().isoformat(),
            }

        strategy_q = (strategy or "").strip().lower()
        level_q = (level or "").strip().upper()

        # Tail efficiently
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=max(lines * 10, lines))

        filtered = []
        for raw in tail:
            line = raw.rstrip("\n")
            if strategy_q and strategy_q not in line.lower():
                continue
            if level_q and f"| {level_q} " not in line:
                continue
            filtered.append(line)

        if len(filtered) > lines:
            filtered = filtered[-lines:]

        return {
            "path": str(log_path),
            "strategy": strategy,
            "level": level_q or None,
            "component": component,
            "lines_returned": len(filtered),
            "lines": filtered,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error reading file logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================================
# 🔄 LIVE/MOCK MODE MANAGEMENT (PRODUCTION SAFE)
# ======================================================================

@router.get("/strategy/{strategy_name}/mode")
def get_strategy_mode(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth),
):
    """
    Get current execution mode (LIVE/MOCK) for a strategy.
    
    Returns:
        {
            "strategy_name": "NIFTY_DNSS",
            "mode": "LIVE" | "MOCK",
            "can_change": true/false,
            "reason": "Has active positions" (if can_change=false),
            "config": {...}
        }
    """
    try:
        slug = _slugify(strategy_name)
        config = load_strategy_json(slug)
        
        if not config:
            raise HTTPException(404, f"Strategy '{strategy_name}' not found")
        
        # Determine current mode
        identity = config.get("identity", {}) or {}
        paper_mode = bool(
            config.get("paper_mode")
            or identity.get("paper_mode")
            or config.get("is_paper")
        )
        test_mode = config.get("test_mode") or identity.get("test_mode")
        mode = _mode_from_config_dict(config)
        
        # Check if mode can be changed (no active positions)
        can_change = True
        reason = None
        position_details = {}
        
        try:
            bot = ctx["bot"]
            service = bot.strategy_executor_service
            exec_state = service._exec_states.get(slug)
            
            if bool(getattr(exec_state, "any_leg_active", False)):
                can_change = False
                reason = "Strategy has active positions - close all positions before changing mode"
                active_legs = [
                    {
                        "tag": getattr(leg, "tag", ""),
                        "symbol": getattr(leg, "trading_symbol", None) or getattr(leg, "symbol", ""),
                        "qty": getattr(leg, "qty", 0),
                        "side": getattr(getattr(leg, "side", None), "value", getattr(leg, "side", "")),
                    }
                    for leg in (getattr(exec_state, "legs", {}) or {}).values()
                    if bool(getattr(leg, "is_active", False))
                ]
                position_details = {
                    "state_type": type(exec_state).__name__,
                    "active_legs": active_legs,
                }
        except Exception as e:
            logger.warning(f"Could not check positions for {strategy_name}: {e}")
        
        return {
            "strategy_name": strategy_name,
            "mode": mode,
            "can_change": can_change,
            "reason": reason,
            "position_details": position_details,
            "config": {
                "paper_mode": paper_mode,
                "test_mode": test_mode,
            },
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting mode for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/{strategy_name}/mode")
def set_strategy_mode(
    strategy_name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """
    Change execution mode for a strategy (LIVE <-> MOCK).
    
    SAFETY: Only allowed when strategy has NO active positions.
    
    Payload:
        {
            "mode": "LIVE" | "MOCK"
        }
    """
    try:
        new_mode = str(payload.get("mode", "")).strip().upper()
        
        if new_mode not in ("LIVE", "MOCK"):
            raise HTTPException(400, "mode must be 'LIVE' or 'MOCK'")
        
        slug = _slugify(strategy_name)
        config = load_strategy_json(slug)
        
        if not config:
            raise HTTPException(404, f"Strategy '{strategy_name}' not found")
        
        # CRITICAL: Check for active positions
        bot = ctx["bot"]
        service = bot.strategy_executor_service
        
        # Use executor's validation method
        allowed, block_reason = service._validate_mode_change_allowed(slug)
        
        if not allowed:
            raise HTTPException(
                409,
                {
                    "error": "Cannot change mode with active positions",
                    "detail": block_reason,
                    "has_position": True,
                }
            )
        
        # Get current mode
        identity = config.get("identity", {}) or {}
        paper_mode = bool(
            config.get("paper_mode")
            or identity.get("paper_mode")
            or config.get("is_paper")
        )
        test_mode = config.get("test_mode") or identity.get("test_mode")
        previous_mode = _mode_from_config_dict(config)
        
        # No change needed
        if previous_mode == new_mode:
            return {
                "success": True,
                "strategy_name": strategy_name,
                "previous_mode": previous_mode,
                "new_mode": new_mode,
                "message": "Mode unchanged (already in requested mode)",
                "timestamp": datetime.now().isoformat()
            }
        
        # Update config
        if "identity" not in config:
            config["identity"] = {}
        
        if new_mode == "MOCK":
            config["paper_mode"] = True
            config["identity"]["paper_mode"] = True
            config["test_mode"] = "SUCCESS"
            config["identity"]["test_mode"] = "SUCCESS"
        else:  # LIVE
            config["paper_mode"] = False
            config["identity"]["paper_mode"] = False
            config["test_mode"] = None
            config["identity"]["test_mode"] = None
        
        # Save config
        save_strategy_json(slug, config)
        
        # If strategy is running, need to restart it
        needs_restart = slug in service._strategies
        restart_message = ""
        
        if needs_restart:
            logger.critical(
                f"⚠️ MODE CHANGE: {strategy_name} | {previous_mode} -> {new_mode} | "
                f"Strategy is running and will be restarted"
            )
            
            try:
                # Unregister
                service.unregister_strategy(slug)
                with bot._live_strategies_lock:
                    bot._live_strategies.pop(slug, None)
                
                # Re-register with new config
                strategy_file = STRATEGY_CONFIG_DIR / f"{slug}.json"
                service.register_strategy(name=slug, config_path=str(strategy_file))
                with bot._live_strategies_lock:
                    bot._live_strategies[slug] = {
                        "type": "executor_service",
                        "config_path": str(strategy_file),
                        "started_at": time.time(),
                    }
                
                restart_message = "Strategy restarted with new mode"
            except Exception as restart_err:
                logger.error(f"Failed to restart strategy: {restart_err}")
                restart_message = f"Warning: Strategy restart failed - {restart_err}"
        
        logger.critical(
            f"✓ MODE CHANGED: {strategy_name} | {previous_mode} -> {new_mode}"
        )
        
        if bot.telegram_enabled:
            mode_emoji = "⚡" if new_mode == "LIVE" else "🧪"
            bot.send_telegram(
                f"{mode_emoji} MODE CHANGE\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"Strategy: {strategy_name}\n"
                f"Previous: {previous_mode}\n"
                f"New: {new_mode}\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"{restart_message if needs_restart else 'Strategy not running'}"
            )
        
        return {
            "success": True,
            "strategy_name": strategy_name,
            "previous_mode": previous_mode,
            "new_mode": new_mode,
            "was_running": needs_restart,
            "restart_message": restart_message,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting mode for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategy/{strategy_name}/positions/active")
def check_strategy_positions(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth),
):
    """
    Check if strategy has active positions.
    """
    try:
        slug = _slugify(strategy_name)
        
        bot = ctx["bot"]
        service = bot.strategy_executor_service
        exec_state = service._exec_states.get(slug)
        
        if not exec_state:
            return {
                "strategy_name": strategy_name,
                "has_position": False,
                "message": "Strategy not found in executor",
                "timestamp": datetime.now().isoformat()
            }
        
        if not bool(getattr(exec_state, "any_leg_active", False)):
            return {
                "strategy_name": strategy_name,
                "has_position": False,
                "timestamp": datetime.now().isoformat()
            }

        legs = getattr(exec_state, "legs", {}) or {}
        active_legs = [
            {
                "tag": getattr(leg, "tag", ""),
                "symbol": getattr(leg, "trading_symbol", None) or getattr(leg, "symbol", ""),
                "qty": getattr(leg, "qty", 0),
                "side": getattr(getattr(leg, "side", None), "value", getattr(leg, "side", "")),
            }
            for leg in legs.values()
            if bool(getattr(leg, "is_active", False))
        ]
        entry_time_obj = getattr(exec_state, "entry_time", None)
        return {
            "strategy_name": strategy_name,
            "has_position": True,
            "active_legs": active_legs,
            "entry_time": entry_time_obj.isoformat() if entry_time_obj else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error checking positions for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
