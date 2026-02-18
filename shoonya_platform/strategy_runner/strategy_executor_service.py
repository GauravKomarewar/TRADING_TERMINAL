#!/usr/bin/env python3
"""
STRATEGY EXECUTOR SERVICE - PRODUCTION GRADE v2.0
==================================================

âœ… ALL CRITICAL BUGS FIXED
âœ… PRODUCTION HARDENING APPLIED
âœ… COPY-TRADING READY
âœ… REAL MONEY SAFE

Integrates:
- condition_engine.py (rule evaluation)
- market_reader.py (market data) 
- config_schema.py (validation)
- ShoonyaBot OMS (execution)

CRITICAL FIXES APPLIED:
1. Position state force-synced with broker truth
2. Execution verification checks OMS + broker
3. Thread-safe state management with locks
4. Exit evaluation type handling fixed
5. Market data staleness detection
6. Startup position reconciliation
7. Config validation before load

PRODUCTION FEATURES:
- Broker is ALWAYS source of truth
- Telegram alerts for all critical mismatches
- Comprehensive error handling with recovery
- Audit logging for all state changes
- Timeout handling for async operations
- Copy-trading isolation via client_id
"""

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

# Internal imports
from shoonya_platform.strategy_runner.condition_engine import (
    StrategyState,
    RuleResult,
    evaluate_entry_rules,
    evaluate_adjustment_rules,
    evaluate_exit_rules,
    evaluate_risk_management,
)
from shoonya_platform.strategy_runner.market_reader import MarketReader
from shoonya_platform.strategy_runner.config_schema import (
    validate_config,
    coerce_config_numerics,
    LOT_SIZES,
)
from shoonya_platform.market_data.feeds import index_tokens_subscriber
from scripts.scriptmaster import requires_limit_order

logger = logging.getLogger("STRATEGY_EXECUTOR")


def _is_runner_v3_config(config: Dict[str, Any]) -> bool:
    return (
        isinstance(config, dict)
        and isinstance(config.get("basic"), dict)
        and isinstance(config.get("timing"), dict)
        and isinstance(config.get("entry"), dict)
        and isinstance(config.get("exit"), dict)
    )


def _looks_like_dashboard_v2(config: Dict[str, Any]) -> bool:
    return (
        isinstance(config, dict)
        and isinstance(config.get("identity"), dict)
        and isinstance(config.get("entry"), dict)
        and isinstance(config.get("exit"), dict)
    )


def _convert_dashboard_v2_to_runner_v3(config: Dict[str, Any], strategy_name: str) -> Dict[str, Any]:
    identity = config.get("identity", {}) or {}
    entry_v2 = config.get("entry", {}) or {}
    adjustment_v2 = config.get("adjustment", {}) or {}
    exit_v2 = config.get("exit", {}) or {}
    rms_v2 = config.get("rms", {}) or {}
    market_cfg = config.get("market_config", {}) or {}
    if not market_cfg and isinstance(identity, dict):
        # Compatibility: some dashboard save paths keep market metadata under identity.
        market_cfg = {
            "market_type": identity.get("market_type"),
            "exchange": identity.get("exchange"),
            "symbol": identity.get("underlying"),
            "db_path": identity.get("db_path"),
        }

    timing_v2 = entry_v2.get("timing", {}) or {}
    position_v2 = entry_v2.get("position", {}) or {}
    legs_v2 = entry_v2.get("legs", {}) or {}
    adj_general = adjustment_v2.get("general", {}) or {}
    adj_delta = adjustment_v2.get("delta", {}) or {}
    exit_time_cfg = exit_v2.get("time", {}) or {}
    exit_profit_cfg = exit_v2.get("profit", {}) or {}
    exit_sl_cfg = exit_v2.get("stop_loss", {}) or {}
    rms_daily = rms_v2.get("daily", {}) or {}
    rms_position = rms_v2.get("position", {}) or {}

    entry_time = str(timing_v2.get("entry_time") or "09:20")
    exit_time = str(exit_time_cfg.get("exit_time") or "15:20")
    lots = int(position_v2.get("lots") or 1)
    delta_target = float(legs_v2.get("target_entry_delta") or 0.30)
    delta_trigger = float(adj_delta.get("trigger") or 0.10)

    exit_conditions: List[Dict[str, Any]] = [
        {
            "parameter": "time_current",
            "comparator": ">=",
            "value": exit_time,
            "description": "Hard exit time",
        }
    ]

    target_rupees = exit_profit_cfg.get("target_rupees")
    if target_rupees is not None:
        exit_conditions.append(
            {
                "parameter": "combined_pnl",
                "comparator": ">=",
                "value": float(target_rupees),
                "description": "Profit target",
            }
        )

    sl_rupees = exit_sl_cfg.get("sl_rupees")
    if sl_rupees is not None:
        exit_conditions.append(
            {
                "parameter": "combined_pnl",
                "comparator": "<=",
                "value": -abs(float(sl_rupees)),
                "description": "Stop loss",
            }
        )

    converted = {
        "schema_version": "3.0",
        "name": config.get("name") or strategy_name,
        "description": config.get("description", ""),
        "basic": {
            "exchange": identity.get("exchange", "NFO"),
            "underlying": identity.get("underlying", "NIFTY"),
            "expiry_mode": identity.get("expiry_mode", "weekly_current"),
            "lots": lots,
            "enabled": bool(config.get("enabled", True)),
        },
        "timing": {
            "entry_time": entry_time,
            "exit_time": exit_time,
        },
        "market_data": {
            "source": "database",
            "db_path": market_cfg.get("db_path") or identity.get("db_path"),
        },
        "entry": {
            "rule_type": "always",
            "conditions": {},
            "action": {
                "type": "short_both",
                "target_delta": delta_target,
            },
        },
        "adjustment": {
            "enabled": bool(adj_general.get("enabled", False)),
            "check_interval_min": int(adj_general.get("check_interval_min", 5) or 5),
            "max_adjustments_per_day": int(adj_general.get("max_adj_per_day", 5) or 5),
            "cooldown_seconds": int(adj_general.get("cooldown_seconds", 60) or 60),
            "rules": [
                {
                    "priority": 1,
                    "name": "Delta rebalance",
                    "rule_type": "if_then",
                    "conditions": {
                        "parameter": "delta_diff",
                        "comparator": ">=",
                        "value": delta_trigger,
                    },
                    "action": {
                        "type": "shift_strikes",
                    },
                }
            ],
        },
        "exit": {
            "rule_type": "if_any",
            "conditions": exit_conditions,
            "action": {
                "type": "close_all_positions",
            },
        },
        "risk_management": {
            "max_loss_per_day": rms_daily.get("loss_limit"),
            "max_trades_per_day": rms_daily.get("max_trades"),
            "position_sizing": {
                "max_lots": rms_position.get("max_lots"),
            },
        },
    }

    return converted


def _normalize_config_for_runner(config: Dict[str, Any], strategy_name: str) -> Tuple[Dict[str, Any], bool]:
    if _is_runner_v3_config(config):
        return config, False
    if _looks_like_dashboard_v2(config):
        return _convert_dashboard_v2_to_runner_v3(config, strategy_name), True
    return config, False


def _inject_pnl_exit_conditions(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inject exit.target_profit and exit.stop_loss from the strategy_builder v3 schema
    into exit.conditions as proper combined_pnl conditions.

    The builder outputs these as structured blocks rather than pre-baked conditions,
    so the runner must convert them at load time.
    """
    exit_cfg = config.get("exit", {})
    if not isinstance(exit_cfg, dict):
        return config

    conditions = exit_cfg.get("conditions", {})
    if not isinstance(conditions, dict):
        conditions = {"operator": "OR", "rules": []}

    rules = conditions.get("rules", [])
    if not isinstance(rules, list):
        rules = []

    # Build a set of (parameter, comparator) already present so we don't duplicate
    existing_conds = {(r.get("parameter"), r.get("comparator")) for r in rules if isinstance(r, dict)}

    # ── Target profit injection ─────────────────────────────────────────
    target_profit = exit_cfg.get("target_profit", {}) or {}
    tp_amount = target_profit.get("amount") if isinstance(target_profit, dict) else None
    if tp_amount is not None:
        try:
            tp_val = float(tp_amount)
            if tp_val > 0 and ("combined_pnl", ">=") not in existing_conds:
                rules.append({
                    "parameter": "combined_pnl",
                    "comparator": ">=",
                    "value": tp_val,
                    "description": f"Target profit ₹{tp_val:.0f}",
                    "_source": "target_profit.amount",
                })
        except (TypeError, ValueError):
            pass

    # ── Stop loss injection ─────────────────────────────────────────────
    stop_loss = exit_cfg.get("stop_loss", {}) or {}
    sl_amount = stop_loss.get("amount") if isinstance(stop_loss, dict) else None
    if sl_amount is not None:
        try:
            sl_val = float(sl_amount)
            if sl_val != 0 and ("combined_pnl", "<=") not in existing_conds:
                rules.append({
                    "parameter": "combined_pnl",
                    "comparator": "<=",
                    "value": -abs(sl_val),
                    "description": f"Stop loss ₹{abs(sl_val):.0f}",
                    "_source": "stop_loss.amount",
                })
        except (TypeError, ValueError):
            pass

    # ── Trailing stop injection ─────────────────────────────────────────
    trailing = exit_cfg.get("trailing", {}) or {}
    trail_amount = trailing.get("trail_amount") if isinstance(trailing, dict) else None
    lock_in = trailing.get("lock_in") if isinstance(trailing, dict) else None
    if trail_amount is not None and lock_in is not None:
        # Trailing is handled separately in executor; no static condition needed.
        logger.debug("Trailing stop configured — handled dynamically in executor")

    if rules:
        conditions["rules"] = rules
        if not conditions.get("operator"):
            conditions["operator"] = "OR"
        exit_cfg["conditions"] = conditions
        config["exit"] = exit_cfg

    return config


# ===================================================================
# PERSISTENT STATE MANAGEMENT (THREAD-SAFE)
# ===================================================================

@dataclass
class ExecutionState:
    """Persistent strategy execution state (survives restarts)."""
    
    # Identity
    strategy_name: str
    run_id: str
    
    # Position tracking
    has_position: bool = False
    ce_symbol: str = ""
    ce_strike: float = 0.0
    ce_qty: int = 0
    ce_side: str = ""  # "BUY" or "SELL"
    ce_entry_price: float = 0.0
    
    pe_symbol: str = ""
    pe_strike: float = 0.0
    pe_qty: int = 0
    pe_side: str = ""
    pe_entry_price: float = 0.0
    
    # Execution tracking
    entry_timestamp: float = 0.0
    last_entry_attempt_timestamp: float = 0.0
    last_adjustment_timestamp: float = 0.0
    adjustments_today: int = 0
    total_trades_today: int = 0
    
    # P&L tracking
    cumulative_daily_pnl: float = 0.0
    peak_pnl: float = 0.0
    
    # Risk flags
    trailing_stop_active: bool = False
    trailing_stop_level: float = 0.0
    
    # Metadata
    last_sync_timestamp: float = 0.0
    last_reconcile_timestamp: float = 0.0
    state_version: int = 1


class StateManager:
    """
    Thread-safe persistent strategy state manager.
    
    CRITICAL FIX: Uses RLock to prevent race conditions.
    All save/load/delete operations are atomic.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()  # âœ… Thread-safe
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Create state table if not exists."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS strategy_execution_state (
                        strategy_name TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        state_json TEXT NOT NULL,
                        last_updated REAL NOT NULL
                    )
                """)
                conn.commit()
            finally:
                conn.close()
    
    def save(self, state: ExecutionState):
        """Thread-safe state persistence."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                state.last_sync_timestamp = time.time()
                state_json = json.dumps(asdict(state))
                
                conn.execute("""
                    INSERT OR REPLACE INTO strategy_execution_state
                    (strategy_name, run_id, state_json, last_updated)
                    VALUES (?, ?, ?, ?)
                """, (state.strategy_name, state.run_id, state_json, time.time()))
                
                conn.commit()
                logger.debug(f"ðŸ’¾ State saved: {state.strategy_name}")
            finally:
                conn.close()
    
    def load(self, strategy_name: str) -> Optional[ExecutionState]:
        """Thread-safe state load."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                row = conn.execute("""
                    SELECT state_json FROM strategy_execution_state
                    WHERE strategy_name = ?
                """, (strategy_name,)).fetchone()
                
                if row:
                    data = json.loads(row[0])
                    logger.debug(f"ðŸ“– State loaded: {strategy_name}")
                    return ExecutionState(**data)
                return None
            finally:
                conn.close()
    
    def delete(self, strategy_name: str):
        """Thread-safe state delete."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                conn.execute(
                    "DELETE FROM strategy_execution_state WHERE strategy_name = ?",
                    (strategy_name,)
                )
                conn.commit()
                logger.info(f"ðŸ—‘ï¸ State deleted: {strategy_name}")
            finally:
                conn.close()
    
    def list_all(self) -> List[str]:
        """List all persisted strategy names."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                rows = conn.execute("""
                    SELECT strategy_name FROM strategy_execution_state
                """).fetchall()
                return [row[0] for row in rows]
            finally:
                conn.close()


# ===================================================================
# BROKER RECONCILIATION (FORCE SYNC WITH BROKER TRUTH)
# ===================================================================

class BrokerReconciler:
    """
    Reconciles strategy state with broker positions.
    
    CRITICAL FIX: Broker is ALWAYS source of truth.
    Forces state sync on any mismatch.
    """
    
    def __init__(self, bot):
        self.bot = bot
    
    def get_positions_for_strategy(
        self, 
        exchange: str, 
        underlying: str
    ) -> List[Dict]:
        """Get broker positions matching strategy."""
        try:
            positions = self.bot.broker_view.get_positions() or []
            
            matching = []
            for pos in positions:
                symbol = pos.get("tsym", "")
                exch = pos.get("exch", "")
                netqty = int(pos.get("netqty", 0))
                
                if netqty == 0:
                    continue
                if exch.upper() != exchange.upper():
                    continue
                if underlying.upper() not in symbol.upper():
                    continue
                
                matching.append({
                    "symbol": symbol,
                    "exchange": exch,
                    "qty": abs(netqty),
                    "side": "BUY" if netqty > 0 else "SELL",
                    "ltp": float(pos.get("ltp", 0) or 0),
                    "avg_price": float(pos.get("avgprc", 0) or 0),
                    "unrealized_pnl": float(pos.get("upnl", 0) or 0),
                })
            
            return matching
            
        except Exception as e:
            logger.error(f"âŒ Broker position fetch failed: {e}")
            return []
    
    def reconcile(
        self, 
        state: ExecutionState, 
        exchange: str, 
        underlying: str
    ) -> Tuple[bool, str]:
        """
        CRITICAL FIX: Force state sync with broker truth.
        
        Handles 3 cases:
        1. State has position, broker has NONE â†’ Clear state (phantom position)
        2. State has NO position, broker HAS positions â†’ Reconstruct state
        3. Both have positions â†’ Verify quantities match
        
        Returns:
            (success, reason_code)
        """
        broker_positions = self.get_positions_for_strategy(exchange, underlying)
        
        # CASE 1: Phantom position (state thinks has, broker shows none)
        if state.has_position and not broker_positions:
            logger.critical(
                f"ðŸš¨ FORCE SYNC: {state.strategy_name} - clearing phantom position\n"
                f"   Strategy state: HAS POSITION\n"
                f"   CE: {state.ce_symbol} ({state.ce_qty} @ â‚¹{state.ce_entry_price})\n"
                f"   PE: {state.pe_symbol} ({state.pe_qty} @ â‚¹{state.pe_entry_price})\n"
                f"   Broker truth: NO POSITIONS\n"
                f"   Action: FORCE CLEAR STATE"
            )
            
            # FORCE CLEAR (broker is truth)
            state.has_position = False
            state.ce_symbol = ""
            state.ce_strike = 0.0
            state.ce_qty = 0
            state.ce_side = ""
            state.ce_entry_price = 0.0
            state.pe_symbol = ""
            state.pe_strike = 0.0
            state.pe_qty = 0
            state.pe_side = ""
            state.pe_entry_price = 0.0
            state.last_reconcile_timestamp = time.time()
            
            # Alert user
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"âš ï¸ POSITION MISMATCH FIXED\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"Strategy: {state.strategy_name}\n"
                    f"Issue: Phantom position in state\n"
                    f"Action: Cleared state\n"
                    f"Broker truth: NO POSITIONS\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"âœ… State synced with broker"
                )
            
            return True, "forced_state_clear"
        
        # CASE 2: Orphan positions (state thinks none, broker has positions)
        if not state.has_position and broker_positions:
            logger.critical(
                f"ðŸš¨ ORPHAN POSITIONS DETECTED: {state.strategy_name}\n"
                f"   Strategy state: NO POSITION\n"
                f"   Broker truth: {len(broker_positions)} positions\n"
                f"   Symbols: {[p['symbol'] for p in broker_positions]}\n"
                f"   Action: RECONSTRUCT STATE"
            )
            
            # Try to reconstruct state from broker
            ce_pos = next((p for p in broker_positions if 'CE' in p['symbol']), None)
            pe_pos = next((p for p in broker_positions if 'PE' in p['symbol']), None)
            
            if ce_pos or pe_pos:
                state.has_position = True
                
                if ce_pos:
                    state.ce_symbol = ce_pos['symbol']
                    state.ce_qty = ce_pos['qty']
                    state.ce_side = ce_pos['side']
                    state.ce_entry_price = ce_pos['avg_price']
                    
                    # Extract strike from symbol (e.g., "NIFTY 25000 CE")
                    try:
                        parts = ce_pos['symbol'].split()
                        state.ce_strike = float(parts[1])
                    except Exception as e:
                        logger.error(f"Cannot parse CE strike from {ce_pos['symbol']}: {e}")
                        state.ce_strike = 0.0
                
                if pe_pos:
                    state.pe_symbol = pe_pos['symbol']
                    state.pe_qty = pe_pos['qty']
                    state.pe_side = pe_pos['side']
                    state.pe_entry_price = pe_pos['avg_price']
                    
                    try:
                        parts = pe_pos['symbol'].split()
                        state.pe_strike = float(parts[1])
                    except Exception as e:
                        logger.error(f"Cannot parse PE strike from {pe_pos['symbol']}: {e}")
                        state.pe_strike = 0.0
                
                state.entry_timestamp = time.time()
                state.last_reconcile_timestamp = time.time()
                
                logger.info(f"âœ… STATE RECONSTRUCTED from broker positions")
            
            # Alert user
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"âš ï¸ ORPHAN POSITIONS RECOVERED\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"Strategy: {state.strategy_name}\n"
                    f"Issue: Broker positions without state\n"
                    f"Action: Reconstructed state\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"CE: {state.ce_symbol} ({state.ce_qty})\n"
                    f"PE: {state.pe_symbol} ({state.pe_qty})\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"âœ… State synced with broker"
                )
            
            return True, "reconstructed_from_broker"
        
        # CASE 3: Both have positions - verify quantities match
        if state.has_position and broker_positions:
            ce_broker = next((p for p in broker_positions if state.ce_symbol in p['symbol']), None)
            pe_broker = next((p for p in broker_positions if state.pe_symbol in p['symbol']), None)
            
            qty_mismatch = False
            changes = []
            
            # Check CE quantity
            if state.ce_symbol and ce_broker:
                if state.ce_qty != ce_broker['qty']:
                    logger.warning(
                        f"âš ï¸ CE QTY MISMATCH: {state.strategy_name}\n"
                        f"   State: {state.ce_qty}\n"
                        f"   Broker: {ce_broker['qty']}\n"
                        f"   Syncing to broker truth"
                    )
                    changes.append(f"CE qty: {state.ce_qty} â†’ {ce_broker['qty']}")
                    state.ce_qty = ce_broker['qty']  # Broker is truth
                    qty_mismatch = True
            
            # Check PE quantity
            if state.pe_symbol and pe_broker:
                if state.pe_qty != pe_broker['qty']:
                    logger.warning(
                        f"âš ï¸ PE QTY MISMATCH: {state.strategy_name}\n"
                        f"   State: {state.pe_qty}\n"
                        f"   Broker: {pe_broker['qty']}\n"
                        f"   Syncing to broker truth"
                    )
                    changes.append(f"PE qty: {state.pe_qty} â†’ {pe_broker['qty']}")
                    state.pe_qty = pe_broker['qty']  # Broker is truth
                    qty_mismatch = True
            
            if qty_mismatch:
                state.last_reconcile_timestamp = time.time()
                
                if self.bot.telegram_enabled:
                    self.bot.send_telegram(
                        f"â„¹ï¸ QUANTITY SYNC\n"
                        f"Strategy: {state.strategy_name}\n"
                        f"Changes:\n" + "\n".join(f"â€¢ {c}" for c in changes) +
                        f"\nâœ… Synced with broker"
                    )
                
                return True, "qty_sync_forced"
        
        # All synced
        state.last_reconcile_timestamp = time.time()
        return True, "in_sync"


# ===================================================================
# EXECUTION VERIFIER (OMS + BROKER DUAL CHECK)
# ===================================================================

class ExecutionVerifier:
    """
    Verifies orders executed via OrderRepository + broker positions.
    
    CRITICAL FIX: Checks BOTH OMS and broker for complete verification.
    """
    
    def __init__(self, bot):
        self.bot = bot
    
    def verify_entry(
        self, 
        strategy_name: str, 
        ce_symbol: str, 
        pe_symbol: str, 
        timeout_sec: int = 30
    ) -> Tuple[bool, str]:
        """
        CRITICAL FIX: Verify entry via OMS + broker dual check.
        
        Returns:
            (success, reason_code)
        """
        repo = self.bot.order_repo
        start_time = time.time()
        
        require_ce = bool(ce_symbol)
        require_pe = bool(pe_symbol)

        logger.info(
            f"ðŸ” VERIFYING ENTRY: {strategy_name}\n"
            f"   CE: {ce_symbol}\n"
            f"   PE: {pe_symbol}\n"
            f"   Timeout: {timeout_sec}s"
        )
        
        # Wait for OMS records to appear (async execution)
        ce_found = False
        pe_found = False
        
        while (time.time() - start_time) < timeout_sec:
            ce_orders = repo.get_orders_by_symbol(ce_symbol) if require_ce else []
            pe_orders = repo.get_orders_by_symbol(pe_symbol) if require_pe else []
            
            # Check if orders exist AND are executed
            ce_found = (not require_ce) or any(
                o.status == "EXECUTED" and o.strategy_name == strategy_name
                for o in ce_orders
            )
            pe_found = (not require_pe) or any(
                o.status == "EXECUTED" and o.strategy_name == strategy_name
                for o in pe_orders
            )
            
            if ce_found and pe_found:
                break
            
            time.sleep(1)
        
        # OMS check result
        oms_ok = ce_found and pe_found
        elapsed = time.time() - start_time
        
        logger.info(
            f"OMS CHECK: {strategy_name}\n"
            f"   CE: {'âœ…' if ce_found else 'âŒ'}\n"
            f"   PE: {'âœ…' if pe_found else 'âŒ'}\n"
            f"   Time: {elapsed:.1f}s"
        )
        
        # CRITICAL: Also verify with broker
        try:
            positions = self.bot.broker_view.get_positions() or []
            broker_symbols = {
                p.get("tsym") 
                for p in positions 
                if int(p.get("netqty", 0)) != 0
            }
            
            broker_ce = (not require_ce) or (ce_symbol in broker_symbols)
            broker_pe = (not require_pe) or (pe_symbol in broker_symbols)
            broker_ok = broker_ce and broker_pe
            
            logger.info(
                f"BROKER CHECK: {strategy_name}\n"
                f"   CE: {'âœ…' if broker_ce else 'âŒ'}\n"
                f"   PE: {'âœ…' if broker_pe else 'âŒ'}"
            )
            
        except Exception as e:
            logger.error(f"âŒ Broker verification failed: {e}")
            broker_ok = False
            broker_ce = False
            broker_pe = False
        
        # BOTH must match for complete verification
        if oms_ok and broker_ok:
            logger.info(f"âœ… ENTRY VERIFIED: {strategy_name} | OMS + Broker match")
            return True, "verified"
        
        # CRITICAL: Mismatch detected
        if oms_ok and not broker_ok:
            logger.critical(
                f"ðŸš¨ OMS-BROKER MISMATCH: {strategy_name}\n"
                f"   OMS: EXECUTED âœ…\n"
                f"   Broker: NO POSITIONS âŒ\n"
                f"   This should NEVER happen!\n"
                f"   Possible causes:\n"
                f"   1. Broker order rejected but OMS not updated\n"
                f"   2. Position closed immediately after entry\n"
                f"   3. OMS database corruption"
            )
            
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"ðŸš¨ CRITICAL: ENTRY MISMATCH\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"Strategy: {strategy_name}\n"
                    f"OMS: Executed âœ…\n"
                    f"Broker: No positions âŒ\n"
                    f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                    f"âš ï¸ MANUAL CHECK REQUIRED"
                )
            
            return False, "oms_broker_mismatch"
        
        if not oms_ok and broker_ok:
            logger.critical(
                f"ðŸš¨ ORPHAN ENTRY: {strategy_name}\n"
                f"   OMS: NO RECORDS âŒ\n"
                f"   Broker: POSITIONS EXIST âœ…\n"
                f"   Possible OMS database corruption!"
            )
            
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"ðŸš¨ ORPHAN ENTRY DETECTED\n"
                    f"Strategy: {strategy_name}\n"
                    f"Broker has positions but OMS has no records\n"
                    f"This may indicate OMS database issues"
                )
            
            return False, "orphan_broker_positions"
        
        # Complete failure
        logger.error(
            f"âŒ ENTRY VERIFICATION FAILED: {strategy_name}\n"
            f"   OMS: CE={ce_found}, PE={pe_found}\n"
            f"   Broker: CE={broker_ce}, PE={broker_pe}\n"
            f"   Timeout: {timeout_sec}s | Elapsed: {elapsed:.1f}s"
        )
        
        return False, "entry_failed"
    
    def verify_exit(
        self,
        strategy_name: str,
        symbols: Optional[List[str]] = None,
        timeout_sec: int = 30
    ) -> Tuple[bool, str]:
        """Verify exit completed (all positions closed)."""
        start_time = time.time()
        
        logger.info(f"ðŸ” VERIFYING EXIT: {strategy_name} | timeout={timeout_sec}s")
        
        # Wait for broker positions to clear
        while (time.time() - start_time) < timeout_sec:
            try:
                positions = self.bot.broker_view.get_positions() or []

                # If symbols are known, scope verification to this strategy symbols only.
                if symbols:
                    symbol_set = {s for s in symbols if s}
                    has_positions = any(
                        int(p.get("netqty", 0)) != 0 and p.get("tsym") in symbol_set
                        for p in positions
                    )
                else:
                    has_positions = any(
                        int(p.get("netqty", 0)) != 0
                        for p in positions
                    )
                
                if not has_positions:
                    elapsed = time.time() - start_time
                    logger.info(f"âœ… EXIT VERIFIED: {strategy_name} | {elapsed:.1f}s")
                    return True, "verified"
                
            except Exception as e:
                logger.error(f"Exit verification error: {e}")
            
            time.sleep(1)
        
        # Timeout - positions still exist
        logger.error(
            f"âŒ EXIT TIMEOUT: {strategy_name}\n"
            f"   Positions still exist after {timeout_sec}s"
        )
        
        return False, "exit_timeout"


# ===================================================================
# STRATEGY EXECUTOR SERVICE (MAIN ORCHESTRATOR)
# ===================================================================

class StrategyExecutorService:
    """
    Main strategy execution service with full production hardening.
    
    PRODUCTION FEATURES:
    - Startup position reconciliation
    - Market data staleness detection
    - Config validation before load
    - Thread-safe state management
    - Broker-truth reconciliation
    - Comprehensive error handling
    - Telegram alerts for critical events
    """
    
    def __init__(self, bot, state_db_path: str):
        self.bot = bot
        self.client_id = bot.client_identity["client_id"]
        
        # Thread-safe state management
        self.state_mgr = StateManager(state_db_path)
        
        # Utilities
        self.reconciler = BrokerReconciler(bot)
        self.verifier = ExecutionVerifier(bot)
        
        # Strategy registry
        self._strategies: Dict[str, Dict] = {}
        self._readers: Dict[str, MarketReader] = {}
        self._exec_states: Dict[str, ExecutionState] = {}
        self._engine_states: Dict[str, StrategyState] = {}
        self._leg_monitor: Dict[str, List[Dict[str, Any]]] = {}
        self._leg_monitor_seq: int = 0
        self._leg_monitor_lock = threading.RLock()
        
        # Staleness tracking
        self._stale_alerted: Set[str] = set()
        
        # Control
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        logger.info(f"âœ… StrategyExecutorService initialized | client={self.client_id}")
        
        # CRITICAL: Reconcile all persisted strategies at startup
        self._reconcile_all_strategies_at_startup()

    def _resolve_webhook_secret(self) -> str:
        """
        Resolve webhook secret used for internal process_alert() calls.

        Priority:
        1) Runtime bot config (single source of truth)
        2) WEBHOOK_SECRET_KEY env (current env contract)
        3) WEBHOOK_SECRET env (legacy fallback)
        """
        bot_cfg = getattr(self.bot, "config", None)
        bot_secret = getattr(bot_cfg, "webhook_secret", None)
        if bot_secret:
            return str(bot_secret)

        env_secret = os.getenv("WEBHOOK_SECRET_KEY") or os.getenv("WEBHOOK_SECRET")
        if env_secret:
            return env_secret

        logger.error(
            "Webhook secret not configured for StrategyExecutorService; "
            "internal alerts may fail with Invalid secret key"
        )
        return ""

    def _resolve_test_mode(self, config: Dict[str, Any]) -> Optional[str]:
        """
        Resolve OMS test_mode from strategy config.
        Supported values: SUCCESS / FAILURE / None (live mode).
        """
        identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
        entry_cfg = config.get("entry", {}) if isinstance(config.get("entry"), dict) else {}
        execution_cfg = entry_cfg.get("execution", {}) if isinstance(entry_cfg.get("execution"), dict) else {}

        if config.get("test_mode") is not None:
            raw = config.get("test_mode")
        elif identity_cfg.get("test_mode") is not None:
            raw = identity_cfg.get("test_mode")
        else:
            raw = execution_cfg.get("test_mode")

        if raw is None:
            return None

        if isinstance(raw, bool):
            return "SUCCESS" if raw else None

        value = str(raw).strip().upper()
        if value in {"SUCCESS", "FAILURE"}:
            return value
        if value in {"TRUE", "1", "YES", "TEST", "ON"}:
            return "SUCCESS"
        if value in {"FALSE", "0", "NO", "LIVE", "OFF", "NONE", ""}:
            return None

        logger.warning(f"Unknown test_mode '{raw}' - using live mode")
        return None

    def _has_paper_mode_flag(self, config: Dict[str, Any]) -> bool:
        """
        Check explicit paper mode flags in strategy config.
        """
        identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
        entry_cfg = config.get("entry", {}) if isinstance(config.get("entry"), dict) else {}
        execution_cfg = entry_cfg.get("execution", {}) if isinstance(entry_cfg.get("execution"), dict) else {}

        candidates = (
            config.get("paper_mode"),
            identity_cfg.get("paper_mode"),
            execution_cfg.get("paper_mode"),
            config.get("is_paper"),
            identity_cfg.get("is_paper"),
            execution_cfg.get("is_paper"),
        )
        return any(bool(v) for v in candidates if v is not None)

    def _is_paper_mode(self, config: Dict[str, Any]) -> bool:
        """
        Paper mode is ON if:
        - explicit paper_mode/is_paper flag is true, OR
        - test_mode is configured (SUCCESS/FAILURE).
        """
        return self._has_paper_mode_flag(config) or (self._resolve_test_mode(config) is not None)


    
    def _validate_mode_change_allowed(self, strategy_name: str) -> Tuple[bool, str]:
        """
        CRITICAL: Validate if mode change is allowed.
        Only allow when NO active positions exist.
        
        Returns:
            (allowed: bool, reason: str)
        """
        exec_state = self._exec_states.get(strategy_name)
        
        if not exec_state:
            return True, "No execution state found"
        
        if not exec_state.has_position:
            return True, "No active positions"
        
        # BLOCK: Strategy has positions
        reason = (
            f"Strategy '{strategy_name}' has active positions:
"
            f"  CE: {exec_state.ce_symbol} ({exec_state.ce_qty})
"
            f"  PE: {exec_state.pe_symbol} ({exec_state.pe_qty})
"
            f"Close all positions before changing mode."
        )
        
        logger.critical(
            f"🚫 MODE CHANGE BLOCKED: {strategy_name}
"
            f"   Reason: Active positions detected
"
            f"   CE: {exec_state.ce_symbol} ({exec_state.ce_qty})
"
            f"   PE: {exec_state.pe_symbol} ({exec_state.pe_qty})"
        )
        
        return False, reason
    
    def get_strategy_mode(self, strategy_name: str) -> str:
        """
        Get current execution mode for a strategy.
        
        Returns:
            "LIVE" or "MOCK"
        """
        config = self._strategies.get(strategy_name)
        if not config:
            return "LIVE"  # Default to LIVE for safety
        
        return "MOCK" if self._is_paper_mode(config) else "LIVE"
    
    def reload_strategy_config(self, strategy_name: str) -> bool:
        """
        Reload strategy configuration from disk.
        Used after mode changes to pick up new config.
        
        Returns:
            True if reload successful, False otherwise
        """
        try:
            config_path = Path(__file__).parent / "saved_configs" / f"{strategy_name}.json"
            
            if not config_path.exists():
                logger.error(f"Config file not found: {config_path}")
                return False
            
            with open(config_path, 'r', encoding='utf-8') as f:
                new_config = json.load(f)
            
            # Validate new config
            is_valid, errors = validate_config(new_config)
            if not is_valid:
                logger.error(f"Invalid config after reload: {errors}")
                return False
            
            # Update in memory
            self._strategies[strategy_name] = new_config
            
            logger.info(f"✓ Reloaded config for {strategy_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reload config for {strategy_name}: {e}", exc_info=True)
            return False
    def _resolve_intent_test_mode(self, config: Dict[str, Any]) -> Optional[str]:
        """
        Resolve test_mode sent to OMS intents.
        If paper mode is explicitly enabled but test_mode is absent, default to SUCCESS.
        """
        explicit = self._resolve_test_mode(config)
        if explicit:
            return explicit
        if self._has_paper_mode_flag(config):
            return "SUCCESS"
        return None


    def has_position(self, strategy_name: str) -> bool:
        """Return True if the strategy currently holds an open position."""
        exec_state = self._exec_states.get(strategy_name)
        return exec_state.has_position if exec_state else False


    def has_position(self, strategy_name: str) -> bool:
        """Return True if the strategy currently holds an open position."""
        exec_state = self._exec_states.get(strategy_name)
        return exec_state.has_position if exec_state else False


    def has_position(self, strategy_name: str) -> bool:
        """Return True if the strategy currently holds an open position."""
        exec_state = self._exec_states.get(strategy_name)
        return exec_state.has_position if exec_state else False

    def _resolve_order_contract(
        self,
        *,
        exchange: str,
        tradingsymbol: str,
        preferred_order_type: Optional[str],
        preferred_price: Optional[Any] = None,
        fallback_price: Optional[Any] = None,
    ) -> Tuple[str, float]:
        """
        Resolve order_type + price for OMS alert legs.
        If order_type is missing/invalid, derive default from ScriptMaster rule.
        """
        resolved_order_type = str(preferred_order_type or "").strip().upper()
        if resolved_order_type not in {"LIMIT", "MARKET"}:
            resolved_order_type = ""

        must_limit = False
        try:
            must_limit = requires_limit_order(
                exchange=str(exchange or "NFO").upper(),
                tradingsymbol=str(tradingsymbol or ""),
            )
        except Exception as e:
            logger.warning(f"Order contract lookup failed for {tradingsymbol}: {e}")

        if resolved_order_type == "MARKET" and must_limit:
            logger.warning(f"Overriding MARKET to LIMIT for {tradingsymbol} (instrument requires LIMIT)")
            resolved_order_type = "LIMIT"

        if not resolved_order_type:
            resolved_order_type = "LIMIT" if must_limit else "MARKET"

        def _as_price(value: Any) -> Optional[float]:
            try:
                px = float(value)
                return px if px > 0 else None
            except Exception:
                return None

        if resolved_order_type == "LIMIT":
            resolved_price = _as_price(preferred_price) or _as_price(fallback_price)
            return "LIMIT", float(resolved_price or 0.0)

        return "MARKET", 0.0

    def _open_monitored_leg(
        self,
        *,
        strategy_name: str,
        exchange: str,
        symbol: str,
        side: str,
        qty: int,
        entry_price: float,
        source: str,
    ) -> None:
        symbol = str(symbol or "").strip()
        if not symbol:
            return
        side_u = str(side or "").upper()
        if side_u not in {"BUY", "SELL"}:
            return
        now_iso = datetime.now().isoformat()
        with self._leg_monitor_lock:
            rows = self._leg_monitor.setdefault(strategy_name, [])
            for row in reversed(rows):
                if row.get("symbol") == symbol and row.get("status") == "ACTIVE":
                    return
            self._leg_monitor_seq += 1
            rows.append({
                "leg_id": f"{strategy_name}:{self._leg_monitor_seq}",
                "strategy_name": strategy_name,
                "exchange": str(exchange or ""),
                "symbol": symbol,
                "side": side_u,
                "qty": int(max(0, qty or 0)),
                "entry_price": float(entry_price or 0.0),
                "exit_price": None,
                "status": "ACTIVE",
                "source": str(source or "ENTRY"),
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "total_pnl": 0.0,
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "opened_at": now_iso,
                "closed_at": None,
                "updated_at": now_iso,
            })

    def _update_monitored_leg_metrics(
        self,
        *,
        strategy_name: str,
        symbol: str,
        unrealized_pnl: float,
        delta: float,
        gamma: float,
        theta: float,
        vega: float,
        ltp: Optional[float] = None,
    ) -> None:
        symbol = str(symbol or "").strip()
        if not symbol:
            return
        now_iso = datetime.now().isoformat()
        with self._leg_monitor_lock:
            rows = self._leg_monitor.get(strategy_name, [])
            for row in reversed(rows):
                if row.get("symbol") == symbol and row.get("status") == "ACTIVE":
                    row["unrealized_pnl"] = float(unrealized_pnl or 0.0)
                    row["delta"] = float(delta or 0.0)
                    row["gamma"] = float(gamma or 0.0)
                    row["theta"] = float(theta or 0.0)
                    row["vega"] = float(vega or 0.0)
                    row["total_pnl"] = float(row.get("realized_pnl", 0.0) or 0.0) + float(row.get("unrealized_pnl", 0.0) or 0.0)
                    if ltp is not None:
                        row["ltp"] = float(ltp or 0.0)
                    row["updated_at"] = now_iso
                    return

    def _close_monitored_leg(
        self,
        *,
        strategy_name: str,
        symbol: str,
        realized_pnl: float,
        exit_price: Optional[float] = None,
    ) -> None:
        symbol = str(symbol or "").strip()
        if not symbol:
            return
        now_iso = datetime.now().isoformat()
        with self._leg_monitor_lock:
            rows = self._leg_monitor.get(strategy_name, [])
            for row in reversed(rows):
                if row.get("symbol") == symbol and row.get("status") == "ACTIVE":
                    row["status"] = "CLOSED"
                    row["realized_pnl"] = float(realized_pnl or 0.0)
                    row["unrealized_pnl"] = 0.0
                    row["total_pnl"] = float(row["realized_pnl"])
                    if exit_price is not None:
                        row["exit_price"] = float(exit_price or 0.0)
                    row["closed_at"] = now_iso
                    row["updated_at"] = now_iso
                    return

    def get_strategy_leg_monitor_snapshot(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        with self._leg_monitor_lock:
            for strategy_name, rows in self._leg_monitor.items():
                copied = [dict(r) for r in rows]
                out[strategy_name] = {
                    "legs": copied,
                    "active_legs": len([r for r in copied if r.get("status") == "ACTIVE"]),
                    "closed_legs": len([r for r in copied if r.get("status") == "CLOSED"]),
                    "realized_pnl": sum(float(r.get("realized_pnl", 0.0) or 0.0) for r in copied),
                    "unrealized_pnl": sum(float(r.get("unrealized_pnl", 0.0) or 0.0) for r in copied if r.get("status") == "ACTIVE"),
                }
        return out
    
    def _reconcile_all_strategies_at_startup(self):
        """
        CRITICAL ENHANCEMENT: Verify all persisted states match broker reality.
        
        Runs once at service startup to catch any state corruption from crashes.
        """
        logger.info("ðŸ” STARTUP: Reconciling all strategies with broker...")
        
        all_strategy_names = self.state_mgr.list_all()
        
        if not all_strategy_names:
            logger.info("â„¹ï¸ No persisted strategies found")
            return
        
        for strategy_name in all_strategy_names:
            try:
                # Load persisted state
                exec_state = self.state_mgr.load(strategy_name)
                if not exec_state:
                    continue
                
                # Get config to know exchange/underlying
                config_path = Path(__file__).parent / "saved_configs" / f"{strategy_name}.json"
                if not config_path.exists():
                    logger.warning(f"âš ï¸ No config found for persisted strategy: {strategy_name}")
                    continue
                
                with open(config_path) as f:
                    config = json.load(f)
                if self._is_paper_mode(config):
                    logger.info(f"PAPER MODE STARTUP: skip broker reconcile for {strategy_name}")
                    exec_state.last_reconcile_timestamp = time.time()
                    self.state_mgr.save(exec_state)
                    continue
                
                basic = config.get("basic", {})
                exchange = basic.get("exchange", "NFO")
                underlying = basic.get("underlying", "NIFTY")
                
                # Reconcile with broker
                is_ok, reason = self.reconciler.reconcile(exec_state, exchange, underlying)
                
                if not is_ok:
                    logger.warning(f"âš ï¸ STARTUP RECONCILE: {strategy_name} | {reason}")
                else:
                    logger.info(f"âœ… STARTUP RECONCILE: {strategy_name} | {reason}")
                
                # Save synced state
                if reason in ("forced_state_clear", "reconstructed_from_broker", "qty_sync_forced"):
                    self.state_mgr.save(exec_state)
                    logger.info(f"ðŸ’¾ Synced state saved: {strategy_name}")
            
            except Exception as e:
                logger.error(f"âŒ Startup reconcile failed for {strategy_name}: {e}")
        
        logger.info("âœ… STARTUP RECONCILIATION COMPLETE")
    
    def register_strategy(self, name: str, config_path: str):
        """
        Register strategy with comprehensive validation.
        
        CRITICAL ENHANCEMENT: Validates config before accepting strategy.
        """
        logger.info(f"ðŸ“ Registering strategy: {name}")
        
        # 1ï¸âƒ£ Load JSON and normalize schema for runner
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = json.load(f)

        config, was_converted = _normalize_config_for_runner(raw_config, name)
        if was_converted:
            logger.warning(
                "âš ï¸ Schema adapter applied for strategy '%s': dashboard v2 -> runner v3",
                name,
            )

        # Inject P&L exit conditions from builder structured blocks (target_profit, stop_loss)
        config = _inject_pnl_exit_conditions(config)
        logger.debug(f"Exit conditions after P&L injection: {config.get('exit', {}).get('conditions', {})}")

        # 2ï¸âƒ£ Validate normalized config
        is_valid, errors = validate_config(config)
        if not is_valid:
            error_msg = f"âŒ VALIDATION FAILED: {name}\n"
            for err in errors:
                if err.severity == "error":
                    error_msg += f"  â€¢ {err.path}: {err.message}\n"
            
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Show warnings (non-blocking)
        warnings = [e for e in errors if e.severity == "warning"]
        if warnings:
            logger.warning(f"âš ï¸ Config warnings for {name}:")
            for w in warnings:
                logger.warning(f"  â€¢ {w.path}: {w.message}")
        
        # 3ï¸âƒ£ Coerce numerics
        config = coerce_config_numerics(config)
        
        # 4ï¸âƒ£ Validate market data source exists
        basic = config.get("basic", {})
        identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
        market_data_cfg = config.get("market_data", {}) if isinstance(config.get("market_data"), dict) else {}
        market_cfg = config.get("market_config", {}) if isinstance(config.get("market_config"), dict) else {}
        exchange = basic.get("exchange", "NFO")
        underlying = basic.get("underlying", "NIFTY")
        db_path = (
            market_data_cfg.get("db_path")
            or identity_cfg.get("db_path")
            or market_cfg.get("db_path")
        )
        
        reader = MarketReader(exchange, underlying, db_path=db_path)
        if not reader.db_path:
            raise RuntimeError(
                f"âŒ No market data DB found for {exchange}:{underlying}\n"
                f"Run OptionChainSupervisor first to generate data"
            )
        
        if not reader.connect():
            raise RuntimeError(
                f"âŒ Cannot connect to market data: {reader.db_path}\n"
                f"Check if OptionChainSupervisor is running"
            )
        
        reader.close()
        
        # 5ï¸âƒ£ Check timing window (warning only)
        timing = config.get("timing", {})
        entry_time = timing.get("entry_time", "09:15")
        exit_time = timing.get("exit_time", "15:20")
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        def to_min(t): 
            parts = t.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        
        if not (to_min(entry_time) <= to_min(current_time) <= to_min(exit_time)):
            logger.warning(
                f"âš ï¸ OUTSIDE TRADING WINDOW: {name}\n"
                f"   Current: {current_time}\n"
                f"   Window: {entry_time} - {exit_time}\n"
                f"   Strategy will wait until entry time"
            )
        
        # 6ï¸âƒ£ Create run_id for this session
        run_id = f"{name}_{int(time.time())}"
        
        # 7ï¸âƒ£ Load or create execution state
        exec_state = self.state_mgr.load(name)
        paper_mode = self._is_paper_mode(config)
        if not exec_state:
            exec_state = ExecutionState(
                strategy_name=name,
                run_id=run_id,
            )
            logger.info(f"ðŸ“ Created new execution state: {name}")
        else:
            logger.info(f"ðŸ“– Loaded existing execution state: {name}")
            
            # Reconcile loaded state with broker (live only).
            if not paper_mode:
                is_ok, reason = self.reconciler.reconcile(exec_state, exchange, underlying)
                if not is_ok or reason != "in_sync":
                    logger.warning(f"âš ï¸ State reconciled: {name} | {reason}")
                    self.state_mgr.save(exec_state)
            else:
                exec_state.last_reconcile_timestamp = time.time()
                self.state_mgr.save(exec_state)
                logger.info(f"PAPER MODE REGISTER: skip broker reconcile for {name}")
        
        # 8ï¸âƒ£ Register in executor
        self._strategies[name] = config
        self._exec_states[name] = exec_state
        engine_state = StrategyState()
        # Build tag -> option_type mapping from entry legs for condition resolution
        engine_state.tag_map = {
            leg.get("tag", ""): str(leg.get("option_type", "")).upper()
            for leg in (config.get("entry", {}).get("action", {}).get("legs") or [])
            if isinstance(leg, dict) and leg.get("tag") and leg.get("option_type")
        }
        if engine_state.tag_map:
            logger.info(f"✅ Tag map built for {name}: {engine_state.tag_map}")
        self._engine_states[name] = engine_state
        self._readers[name] = MarketReader(exchange, underlying, db_path=db_path)
        
        logger.info(f"âœ… Strategy registered: {name} | run_id={run_id}")
    
    def unregister_strategy(self, name: str):
        """Unregister and cleanup strategy."""
        if name in self._strategies:
            del self._strategies[name]
        if name in self._readers:
            self._readers[name].close()
            del self._readers[name]
        if name in self._exec_states:
            del self._exec_states[name]
        if name in self._engine_states:
            del self._engine_states[name]
        
        logger.info(f"ðŸ—‘ï¸ Strategy unregistered: {name}")
    
    def start(self):
        """Start execution loop in background thread."""
        if self._running:
            logger.warning("âš ï¸ Already running")
            return
        
        self._running = True
        self._stop_event.clear()
        
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="StrategyExecutor"
        )
        self._thread.start()
        
        logger.info("ðŸš€ Strategy executor started")
    
    def stop(self):
        """Stop execution loop."""
        if not self._running:
            return
        
        logger.info("ðŸ›‘ Stopping strategy executor...")
        
        self._running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=10)
        
        # Close all market readers
        for reader in self._readers.values():
            reader.close()
        
        logger.info("âœ… Strategy executor stopped")
    
    def _run_loop(self):
        """Main execution loop."""
        while self._running and not self._stop_event.is_set():
            try:
                for name in list(self._strategies.keys()):
                    try:
                        self._process_strategy(name)
                    except Exception as e:
                        logger.error(f"âŒ Strategy processing error: {name} | {e}", exc_info=True)
                
                # Poll interval (configurable per strategy later)
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"âŒ Execution loop error: {e}", exc_info=True)
                time.sleep(5)
    
    def _process_strategy(self, name: str):
        """Process single strategy tick with proper type safety."""
        # Get all components
        config = self._strategies.get(name)
        exec_state = self._exec_states.get(name)
        engine_state = self._engine_states.get(name)
        reader = self._readers.get(name)
        
        # CRITICAL: Type guard - verify all components exist
        if not all([config, exec_state, engine_state, reader]):
            logger.error(f"âŒ Missing components for {name}")
            return
        
        # FIXED: After the all() check, we KNOW these are not None
        # But Python type checker doesn't know, so we assert it
        assert config is not None, f"Config is None for {name}"
        assert exec_state is not None, f"ExecState is None for {name}"
        assert engine_state is not None, f"EngineState is None for {name}"
        assert reader is not None, f"Reader is None for {name}"
        
        # Now all type checkers know these are NOT None
        
        # 1ï¸âƒ£ Check timing window
        timing = config.get("timing", {})
        entry_time = timing.get("entry_time", "09:15")
        exit_time = timing.get("exit_time", "15:20")
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        def to_min(t: str) -> int:
            parts = t.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        
        current_min = to_min(current_time)
        entry_min = to_min(entry_time)
        exit_min = to_min(exit_time)
        
        if current_min < entry_min:
            return  # Before entry window
        
        if current_min >= exit_min:
            # Force exit at end of day
            if exec_state.has_position:
                logger.info(f"â° END OF DAY EXIT: {name}")
                self._execute_exit(name, exec_state, config, "end_of_day")
            return
        
        # 2ï¸âƒ£ Update market data (with staleness check)
        if not self._update_market_data(name, exec_state, engine_state, reader):
            return  # Stale data, skip this tick
        
        # 3ï¸âƒ£ Reconcile with broker (periodic)
        seconds_since_reconcile = time.time() - exec_state.last_reconcile_timestamp
        # When flat, reconcile more frequently so orphan positions are recovered quickly.
        reconcile_interval_sec = 5 if not exec_state.has_position else 60
        if seconds_since_reconcile > reconcile_interval_sec:
            if self._is_paper_mode(config):
                exec_state.last_reconcile_timestamp = time.time()
            else:
                basic = config.get("basic", {}) if isinstance(config.get("basic"), dict) else {}
                identity = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
                exchange = basic.get("exchange") or identity.get("exchange") or "NFO"
                underlying = basic.get("underlying") or identity.get("underlying") or "NIFTY"
                
                is_ok, reason = self.reconciler.reconcile(exec_state, exchange, underlying)
                if reason in ("forced_state_clear", "reconstructed_from_broker", "qty_sync_forced"):
                    self.state_mgr.save(exec_state)
        
        # 4ï¸âƒ£ Check risk management (always first priority)
        risk_result = evaluate_risk_management(config, engine_state)
        if risk_result and risk_result.triggered:
            logger.warning(f"RISK LIMIT: {name} | {risk_result.rule_name}")
            
            if "max_loss" in risk_result.rule_name:
                if exec_state.has_position:
                    self._execute_exit(name, exec_state, config, risk_result.rule_name)
                return

            # Max trades should block NEW entries only.
            # If a position is already open, allow adjustment/exit flow to continue.
            if "max_trades" in risk_result.rule_name:
                if not exec_state.has_position:
                    return
            else:
                return  # Block further action for other risk triggers
        
        # 5ï¸âƒ£ Entry / Adjustment / Exit logic
        if not exec_state.has_position:
            self._check_entry(name, exec_state, engine_state, config, reader)
        else:
            self._check_adjustment(name, exec_state, engine_state, config, reader)
            self._check_exit(name, exec_state, engine_state, config)
            
    def _update_market_data(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        reader: MarketReader,
    ) -> bool:
        """
        Update market data with staleness detection.
        
        CRITICAL ENHANCEMENT: Detects and handles stale data.
        Returns False if data too old (skips tick).
        """
        try:
            # CRITICAL: Check snapshot age FIRST
            age_sec = reader.get_snapshot_age_seconds()
            MAX_AGE = 300  # 5 minutes
            
            if age_sec > MAX_AGE:
                logger.error(
                    f"ðŸš¨ STALE DATA: {name} | age={age_sec:.0f}s (max={MAX_AGE}s)\n"
                    f"   DB: {reader.db_path}\n"
                    f"   Skipping this tick - waiting for fresh data"
                )
                
                # Alert on first stale detection (per strategy)
                if name not in self._stale_alerted:
                    self._stale_alerted.add(name)
                    
                    if self.bot.telegram_enabled:
                        self.bot.send_telegram(
                            f"âš ï¸ STALE MARKET DATA\n"
                            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                            f"Strategy: {name}\n"
                            f"Data age: {age_sec:.0f}s (max {MAX_AGE}s)\n"
                            f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                            f"â¸ï¸ Strategy paused\n"
                            f"Waiting for fresh data..."
                        )
                
                return False  # Skip this tick
            
            # Clear stale flag if data is fresh again
            if name in self._stale_alerted:
                self._stale_alerted.remove(name)
                logger.info(f"âœ… Fresh data resumed: {name}")
                
                if self.bot.telegram_enabled:
                    self.bot.send_telegram(
                        f"âœ… MARKET DATA FRESH\n"
                        f"Strategy: {name}\n"
                        f"â–¶ï¸ Strategy resumed"
                    )
            
            # Update spot / market data
            engine_state.spot_price = reader.get_spot_price()
            engine_state.atm_strike = reader.get_atm_strike()
            engine_state.fut_ltp = reader.get_fut_ltp()
            # Update ticker-ribbon index snapshot for dynamic condition params.
            try:
                engine_state.set_index_ticks(
                    index_tokens_subscriber.get_index_prices(include_missing=False)
                )
            except Exception as idx_err:
                logger.debug("Index metric update skipped for %s: %s", name, idx_err)
            
            # Update position data if we have positions
            if exec_state.has_position:
                engine_state.entry_time = datetime.fromtimestamp(exec_state.entry_timestamp)
                engine_state.last_adjustment_time = exec_state.last_adjustment_timestamp
                engine_state.adjustments_today = exec_state.adjustments_today
                engine_state.total_trades_today = exec_state.total_trades_today
                engine_state.cumulative_daily_pnl = exec_state.cumulative_daily_pnl
                
                # CE leg
                if exec_state.ce_symbol:
                    ce_data = reader.get_option_at_strike(exec_state.ce_strike, "CE")
                    if ce_data:
                        engine_state.ce_ltp = float(ce_data.get("ltp", 0) or 0)
                        engine_state.ce_delta = float(ce_data.get("delta", 0) or 0)
                        engine_state.ce_gamma = float(ce_data.get("gamma", 0) or 0)
                        engine_state.ce_theta = float(ce_data.get("theta", 0) or 0)
                        engine_state.ce_vega = float(ce_data.get("vega", 0) or 0)
                        engine_state.ce_iv = float(ce_data.get("iv", 0) or 0)
                        engine_state.ce_entry_price = exec_state.ce_entry_price
                        engine_state.ce_qty = exec_state.ce_qty
                        engine_state.ce_direction = exec_state.ce_side
                        
                        # Calculate P&L
                        if exec_state.ce_side == "SELL":
                            engine_state.ce_pnl = (exec_state.ce_entry_price - engine_state.ce_ltp) * exec_state.ce_qty
                        else:
                            engine_state.ce_pnl = (engine_state.ce_ltp - exec_state.ce_entry_price) * exec_state.ce_qty
                        
                        if exec_state.ce_entry_price > 0:
                            engine_state.ce_pnl_pct = (engine_state.ce_pnl / (exec_state.ce_entry_price * exec_state.ce_qty)) * 100.0
                        self._update_monitored_leg_metrics(
                            strategy_name=name,
                            symbol=exec_state.ce_symbol,
                            unrealized_pnl=float(engine_state.ce_pnl or 0.0),
                            delta=float(engine_state.ce_delta or 0.0),
                            gamma=float(engine_state.ce_gamma or 0.0),
                            theta=float(engine_state.ce_theta or 0.0),
                            vega=float(engine_state.ce_vega or 0.0),
                            ltp=float(engine_state.ce_ltp or 0.0),
                        )
                    elif exec_state.ce_symbol:
                        # Recovered/restarted state fallback: ensure active leg appears in monitor.
                        self._open_monitored_leg(
                            strategy_name=name,
                            exchange=str(config.get("basic", {}).get("exchange", "NFO")),
                            symbol=exec_state.ce_symbol,
                            side=str(exec_state.ce_side or ""),
                            qty=int(exec_state.ce_qty or 0),
                            entry_price=float(exec_state.ce_entry_price or 0.0),
                            source="RECOVERED",
                        )
                
                # PE leg
                if exec_state.pe_symbol:
                    pe_data = reader.get_option_at_strike(exec_state.pe_strike, "PE")
                    if pe_data:
                        engine_state.pe_ltp = float(pe_data.get("ltp", 0) or 0)
                        engine_state.pe_delta = float(pe_data.get("delta", 0) or 0)
                        engine_state.pe_gamma = float(pe_data.get("gamma", 0) or 0)
                        engine_state.pe_theta = float(pe_data.get("theta", 0) or 0)
                        engine_state.pe_vega = float(pe_data.get("vega", 0) or 0)
                        engine_state.pe_iv = float(pe_data.get("iv", 0) or 0)
                        engine_state.pe_entry_price = exec_state.pe_entry_price
                        engine_state.pe_qty = exec_state.pe_qty
                        engine_state.pe_direction = exec_state.pe_side
                        
                        # Calculate P&L
                        if exec_state.pe_side == "SELL":
                            engine_state.pe_pnl = (exec_state.pe_entry_price - engine_state.pe_ltp) * exec_state.pe_qty
                        else:
                            engine_state.pe_pnl = (engine_state.pe_ltp - exec_state.pe_entry_price) * exec_state.pe_qty
                        
                        if exec_state.pe_entry_price > 0:
                            engine_state.pe_pnl_pct = (engine_state.pe_pnl / (exec_state.pe_entry_price * exec_state.pe_qty)) * 100.0
                        self._update_monitored_leg_metrics(
                            strategy_name=name,
                            symbol=exec_state.pe_symbol,
                            unrealized_pnl=float(engine_state.pe_pnl or 0.0),
                            delta=float(engine_state.pe_delta or 0.0),
                            gamma=float(engine_state.pe_gamma or 0.0),
                            theta=float(engine_state.pe_theta or 0.0),
                            vega=float(engine_state.pe_vega or 0.0),
                            ltp=float(engine_state.pe_ltp or 0.0),
                        )
                    elif exec_state.pe_symbol:
                        # Recovered/restarted state fallback: ensure active leg appears in monitor.
                        self._open_monitored_leg(
                            strategy_name=name,
                            exchange=str(config.get("basic", {}).get("exchange", "NFO")),
                            symbol=exec_state.pe_symbol,
                            side=str(exec_state.pe_side or ""),
                            qty=int(exec_state.pe_qty or 0),
                            entry_price=float(exec_state.pe_entry_price or 0.0),
                            source="RECOVERED",
                        )
                
                engine_state.has_position = True
                engine_state.ce_strike = exec_state.ce_strike
                engine_state.pe_strike = exec_state.pe_strike
            
            return True
            
        except Exception as e:
            logger.error(f"âŒ Market data update error: {name} | {e}")
            return False
    
    def _check_entry(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
        reader: MarketReader,
    ):
        """Check entry conditions and execute if triggered."""
        
        # CRITICAL: Verify mode hasn't changed unexpectedly
        current_mode = self.get_strategy_mode(name)
        config_mode = "MOCK" if self._is_paper_mode(config) else "LIVE"
        
        if current_mode != config_mode:
            logger.warning(
                f"⚠️ MODE MISMATCH DETECTED: {name}
"
                f"   Memory mode: {current_mode}
"
                f"   Config mode: {config_mode}
"
                f"   Reloading config..."
            )
            self.reload_strategy_config(name)
        result = evaluate_entry_rules(config, engine_state)
        
        if not result or not isinstance(result, RuleResult) or not result.triggered:
            return
        
        logger.info(f"ðŸŽ¯ ENTRY TRIGGERED: {name} | {result.rule_name}")
        
        entry_cfg = config.get("entry", {})
        action = entry_cfg.get("action", {})
        action_type = action.get("type", "short_both")
        action_legs = action.get("legs", []) if isinstance(action.get("legs"), list) else []

        # Guard: prevent rapid re-fire if prior entry attempt is still settling.
        execution_cfg = entry_cfg.get("execution", {}) if isinstance(entry_cfg.get("execution"), dict) else {}
        retry_cooldown_sec = int(execution_cfg.get("retry_cooldown_seconds", 45) or 45)
        now_ts = time.time()
        if exec_state.last_entry_attempt_timestamp > 0:
            elapsed = now_ts - exec_state.last_entry_attempt_timestamp
            if elapsed < retry_cooldown_sec:
                logger.info(
                    f"â³ ENTRY COOLING DOWN: {name} | elapsed={elapsed:.1f}s < {retry_cooldown_sec}s"
                )
                return
        exec_state.last_entry_attempt_timestamp = now_ts
        self.state_mgr.save(exec_state)
        
        basic = config.get("basic", {})
        identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
        exchange = str(basic.get("exchange") or identity_cfg.get("exchange") or "NFO").upper()
        lots = basic.get("lots", 1)
        underlying = basic.get("underlying", "NIFTY")
        lot_size = LOT_SIZES.get(underlying, 1)
        qty = lots * lot_size
        ce_qty = qty
        pe_qty = qty
        default_order_type = str(identity_cfg.get("order_type") or "").upper()
        product_type = str(identity_cfg.get("product_type") or "NRML").upper()
        
        # Extract delta targets from conditions
        conditions = entry_cfg.get("conditions", {})
        rules = conditions.get("rules", [])
        
        ce_delta_target = 0.30
        pe_delta_target = 0.30
        
        for rule in rules:
            if rule.get("parameter") == "ce_delta":
                ce_delta_target = float(rule.get("value", 0.30))
            elif rule.get("parameter") == "pe_delta":
                pe_delta_target = float(rule.get("value", 0.30))

        # Infer directional intent and included legs.
        include_ce = False
        include_pe = False
        ce_direction = "SELL"
        pe_direction = "SELL"
        normalized_action = str(action_type or "").lower()

        if normalized_action in ("short_both", "short_straddle", "short_strangle"):
            include_ce, include_pe = True, True
            ce_direction, pe_direction = "SELL", "SELL"
        elif normalized_action == "short_ce":
            include_ce, include_pe = True, False
            ce_direction = "SELL"
        elif normalized_action == "short_pe":
            include_ce, include_pe = False, True
            pe_direction = "SELL"
        elif normalized_action in ("long_both", "long_straddle", "long_strangle"):
            include_ce, include_pe = True, True
            ce_direction, pe_direction = "BUY", "BUY"
        elif normalized_action == "long_ce":
            include_ce, include_pe = True, False
            ce_direction = "BUY"
        elif normalized_action == "long_pe":
            include_ce, include_pe = False, True
            pe_direction = "BUY"
        elif action_legs:
            # Custom payload from strategy builder: derive CE/PE presence and direction.
            for leg in action_legs:
                if not isinstance(leg, dict):
                    continue
                option_type = str(leg.get("option_type", "")).upper()
                side = str(leg.get("side", "SELL")).upper()
                leg_lots = int(leg.get("lots") or lots)
                if option_type == "CE":
                    include_ce = True
                    ce_direction = "BUY" if side == "BUY" else "SELL"
                    ce_qty = max(1, leg_lots) * lot_size
                elif option_type == "PE":
                    include_pe = True
                    pe_direction = "BUY" if side == "BUY" else "SELL"
                    pe_qty = max(1, leg_lots) * lot_size
        else:
            # Backward-compatible default.
            include_ce, include_pe = True, True
            ce_direction, pe_direction = "SELL", "SELL"

        def _safe_float(v, default=0.0):
            try:
                return float(v)
            except Exception:
                return float(default)

        def _infer_strike_step() -> float:
            try:
                chain = reader.get_full_chain() or []
                strikes = sorted({
                    _safe_float(r.get("strike", 0))
                    for r in chain
                    if _safe_float(r.get("strike", 0)) > 0
                })
                if len(strikes) < 2:
                    return 50.0
                diffs = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
                diffs = [d for d in diffs if d > 0]
                return min(diffs) if diffs else 50.0
            except Exception:
                return 50.0

        strike_step = _infer_strike_step()

        def _find_nearest_by_strike(option_type: str, target_strike: float):
            chain = reader.get_full_chain() or []
            filtered = [r for r in chain if str(r.get("option_type", "")).upper() == option_type.upper()]
            if not filtered:
                return None
            return min(filtered, key=lambda r: abs(_safe_float(r.get("strike", 0)) - target_strike))

        def _get_leg_cfg(option_type: str):
            for leg in action_legs:
                if not isinstance(leg, dict):
                    continue
                if str(leg.get("option_type", "")).upper() == option_type.upper():
                    return leg
            return {}

        def _select_option(option_type: str, default_delta: float):
            leg_cfg = _get_leg_cfg(option_type)
            sel = str(leg_cfg.get("strike_selection", "delta") or "delta").lower()
            val = leg_cfg.get("strike_value")
            num_val = _safe_float(val, default_delta)

            # Explicit strike selection.
            if sel == "strike" and val is not None:
                exact = reader.get_option_at_strike(num_val, option_type)
                return exact or _find_nearest_by_strike(option_type, num_val)

            # Premium-based leg selection.
            if sel == "premium" and val is not None:
                return reader.find_option_by_premium(option_type, num_val, tolerance=max(5.0, num_val * 0.3))

            # ATM offset steps.
            if sel.startswith("atm"):
                atm = reader.get_atm_strike()
                if atm <= 0:
                    atm = reader.get_spot_price()
                sign = 1.0
                steps = 0.0
                if "+" in sel:
                    steps = _safe_float(sel.split("+", 1)[1], 0.0)
                    sign = 1.0
                elif "-" in sel:
                    steps = _safe_float(sel.split("-", 1)[1], 0.0)
                    sign = -1.0
                target = atm + (sign * steps * strike_step)
                exact = reader.get_option_at_strike(target, option_type)
                return exact or _find_nearest_by_strike(option_type, target)

            # OTM by percentage from spot.
            if sel == "otm_pct" and val is not None:
                spot = reader.get_spot_price()
                if spot > 0:
                    if option_type.upper() == "CE":
                        target = spot * (1.0 + (num_val / 100.0))
                    else:
                        target = spot * (1.0 - (num_val / 100.0))
                    exact = reader.get_option_at_strike(target, option_type)
                    return exact or _find_nearest_by_strike(option_type, target)

            # Default: delta-based (including explicit sel == "delta").
            target_delta = num_val if sel == "delta" and val is not None else default_delta
            return reader.find_option_by_delta(option_type, target_delta, tolerance=0.1)

        # Per-leg condition gating: evaluate conditions_block for each leg.
        # Skip any leg whose IF conditions are not met.
        def _leg_conditions_met(leg_cfg: dict) -> bool:
            cond_block = leg_cfg.get("conditions_block")
            if not cond_block or not isinstance(cond_block, dict):
                return True  # No conditions = always execute
            rules = cond_block.get("rules", [])
            if not rules:
                return True  # Empty rules = always execute
            from shoonya_platform.strategy_runner.condition_engine import evaluate_condition as _eval_cond
            result = _eval_cond(cond_block, engine_state)
            if not result:
                mode = leg_cfg.get("condition_mode", "if_then")
                if mode == "if_then_else":
                    else_block = leg_cfg.get("else_conditions_block")
                    if else_block and isinstance(else_block, dict) and else_block.get("rules"):
                        return _eval_cond(else_block, engine_state)
            return result

        # Apply per-leg condition gate when builder legs are present
        if action_legs:
            for _leg_item in action_legs:
                if not isinstance(_leg_item, dict):
                    continue
                _otype = str(_leg_item.get("option_type", "")).upper()
                if not _leg_conditions_met(_leg_item):
                    logger.info(f"  Leg {_otype} skipped: per-leg conditions not met")
                    if _otype == "CE":
                        include_ce = False
                    elif _otype == "PE":
                        include_pe = False

        # Find options from builder leg intent.
        ce_option = _select_option("CE", ce_delta_target) if include_ce else None
        pe_option = _select_option("PE", pe_delta_target) if include_pe else None
        if include_ce and not ce_option:
            logger.error(f"âŒ No CE option found for configured CE leg selection")
            return
        if include_pe and not pe_option:
            logger.error(f"âŒ No PE option found for configured PE leg selection")
            return
        
        # Build legs
        legs = []
        test_mode = self._resolve_intent_test_mode(config)
        paper_mode = self._is_paper_mode(config)

        if include_ce and ce_option:
            ce_leg_cfg = _get_leg_cfg("CE")
            ce_order_type, ce_price = self._resolve_order_contract(
                exchange=exchange,
                tradingsymbol=str(ce_option.get("trading_symbol", "")),
                preferred_order_type=ce_leg_cfg.get("order_type", default_order_type),
                preferred_price=ce_leg_cfg.get("price") or ce_leg_cfg.get("limit_price"),
                fallback_price=ce_option.get("ltp", 0),
            )
            if ce_order_type == "LIMIT" and ce_price <= 0:
                logger.error("CE leg requires LIMIT price but no valid price is available")
                return
            legs.append({
                "tradingsymbol": ce_option.get("trading_symbol", ""),
                "direction": ce_direction,
                "qty": ce_qty,
                "order_type": ce_order_type,
                "price": ce_price,
                "product_type": str(ce_leg_cfg.get("product_type") or product_type).upper(),
            })

        if include_pe and pe_option:
            pe_leg_cfg = _get_leg_cfg("PE")
            pe_order_type, pe_price = self._resolve_order_contract(
                exchange=exchange,
                tradingsymbol=str(pe_option.get("trading_symbol", "")),
                preferred_order_type=pe_leg_cfg.get("order_type", default_order_type),
                preferred_price=pe_leg_cfg.get("price") or pe_leg_cfg.get("limit_price"),
                fallback_price=pe_option.get("ltp", 0),
            )
            if pe_order_type == "LIMIT" and pe_price <= 0:
                logger.error("PE leg requires LIMIT price but no valid price is available")
                return
            legs.append({
                "tradingsymbol": pe_option.get("trading_symbol", ""),
                "direction": pe_direction,
                "qty": pe_qty,
                "order_type": pe_order_type,
                "price": pe_price,
                "product_type": str(pe_leg_cfg.get("product_type") or product_type).upper(),
            })

        if not legs:
            logger.error(f"âŒ ENTRY ABORTED: {name} | no executable legs for action={action_type}")
            return
        
        # SAFETY CHECK: Log execution mode prominently
        paper_mode = self._is_paper_mode(config)
        execution_mode = "MOCK (PAPER)" if paper_mode else "LIVE (REAL MONEY)"
        logger.critical(
            f"{'🧪' if paper_mode else '⚡'} ENTRY EXECUTION MODE: {execution_mode}
"
            f"   Strategy: {name}
"
            f"   Paper Mode: {paper_mode}
"
            f"   Test Mode: {test_mode}
"
            f"   Legs: {len(legs)}"
        )
        
        if not paper_mode and self.bot.telegram_enabled:
            self.bot.send_telegram(
                f"⚡ LIVE TRADE ALERT
"
                f"━━━━━━━━━━━━━━━━━
"
                f"Strategy: {name}
"
                f"Mode: LIVE (REAL MONEY)
"
                f"Legs: {len(legs)}
"
                f"━━━━━━━━━━━━━━━━━"
            )
        
        # Send entry alert to OMS
        alert_result = self._send_entry_alert(name, config, legs, test_mode=test_mode)
        alert_status = str((alert_result or {}).get("status", "")).upper()
        if alert_status == "FAILED":
            logger.error(f"ENTRY ALERT FAILED: {name} | result={alert_result}")
            return
        
        # CRITICAL: Verify execution
        ce_symbol = ce_option.get("trading_symbol", "") if ce_option else ""
        pe_symbol = pe_option.get("trading_symbol", "") if pe_option else ""
        
        if not paper_mode:
            is_verified, reason = self.verifier.verify_entry(name, ce_symbol, pe_symbol, timeout_sec=30)

            if not is_verified:
                logger.error(f"❌ ENTRY VERIFICATION FAILED: {name} | {reason}")

                # Fast recovery: if broker already has positions, reconstruct state now
                # instead of waiting for the periodic reconciler.
                basic_cfg = config.get("basic", {}) if isinstance(config.get("basic"), dict) else {}
                identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
                exchange = basic_cfg.get("exchange") or identity_cfg.get("exchange") or "NFO"
                underlying = basic_cfg.get("underlying") or identity_cfg.get("underlying") or "NIFTY"

                _, reconcile_reason = self.reconciler.reconcile(exec_state, exchange, underlying)
                if reconcile_reason in ("forced_state_clear", "reconstructed_from_broker", "qty_sync_forced"):
                    self.state_mgr.save(exec_state)
                if exec_state.has_position:
                    logger.warning(
                        f"⚠️ ENTRY RECOVERED VIA RECONCILE: {name} | reason={reconcile_reason}"
                    )
                    return

                if self.bot.telegram_enabled:
                    self.bot.send_telegram(
                        f"❌ ENTRY FAILED\n"
                        f"Strategy: {name}\n"
                        f"Reason: {reason}\n"
                        f"Check OMS logs"
                    )

                return
        else:
            logger.info(f"🧪 PAPER MODE ENTRY: {name} | verification skipped")
        # Update execution state
        exec_state.has_position = True
        if ce_option:
            exec_state.ce_symbol = ce_symbol
            exec_state.ce_strike = float(ce_option.get("strike", 0))
            exec_state.ce_qty = ce_qty
            exec_state.ce_side = ce_direction
            exec_state.ce_entry_price = float(ce_option.get("ltp", 0))
        else:
            exec_state.ce_symbol = ""
            exec_state.ce_strike = 0.0
            exec_state.ce_qty = 0
            exec_state.ce_side = ""
            exec_state.ce_entry_price = 0.0
        
        if pe_option:
            exec_state.pe_symbol = pe_symbol
            exec_state.pe_strike = float(pe_option.get("strike", 0))
            exec_state.pe_qty = pe_qty
            exec_state.pe_side = pe_direction
            exec_state.pe_entry_price = float(pe_option.get("ltp", 0))
        else:
            exec_state.pe_symbol = ""
            exec_state.pe_strike = 0.0
            exec_state.pe_qty = 0
            exec_state.pe_side = ""
            exec_state.pe_entry_price = 0.0
        
        exec_state.entry_timestamp = time.time()
        exec_state.total_trades_today += len(legs)

        if ce_option and ce_symbol:
            self._open_monitored_leg(
                strategy_name=name,
                exchange=exchange,
                symbol=ce_symbol,
                side=ce_direction,
                qty=ce_qty,
                entry_price=float(ce_option.get("ltp", 0) or 0.0),
                source="ENTRY",
            )
        if pe_option and pe_symbol:
            self._open_monitored_leg(
                strategy_name=name,
                exchange=exchange,
                symbol=pe_symbol,
                side=pe_direction,
                qty=pe_qty,
                entry_price=float(pe_option.get("ltp", 0) or 0.0),
                source="ENTRY",
            )
        
        self.state_mgr.save(exec_state)
        
        logger.info(
            f"{'PAPER ENTRY COMPLETE' if paper_mode else 'ENTRY COMPLETE'}: {name}"
        )
    
    def _check_adjustment(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
        reader: MarketReader,
    ):
        """Check adjustment conditions."""
        adj_cfg = config.get("adjustment", {})
        if not adj_cfg.get("enabled", False):
            return
        
        # Check cooldown
        cooldown = adj_cfg.get("cooldown_seconds", 60)
        if exec_state.last_adjustment_timestamp > 0:
            seconds_since = time.time() - exec_state.last_adjustment_timestamp
            if seconds_since < cooldown:
                return
        
        # Evaluate adjustment rules (returns list)
        results = evaluate_adjustment_rules(config, engine_state)
        if not results or not isinstance(results, list):
            return
        
        for result in results:
            if result.triggered:
                logger.info(f"ADJUSTMENT TRIGGERED: {name} | {result.rule_name}")
                logger.info(f"   Action: {result.action.get('type', '?')}")
                
                # EXECUTE THE ADJUSTMENT
                success = self._execute_adjustment(
                    name, exec_state, engine_state, config, result.action, reader
                )
                
                if success:
                    # Update tracking
                    exec_state.last_adjustment_timestamp = time.time()
                    exec_state.adjustments_today += 1
                    self.state_mgr.save(exec_state)
                    
                    logger.info(f"ADJUSTMENT EXECUTED: {name}")
                else:
                    logger.error(f"ADJUSTMENT FAILED: {name}")
                
                # Only process first triggered rule
                break
    
    def _execute_adjustment(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
        action: Dict,
        reader: MarketReader,
    ) -> bool:
        """
        Execute adjustment action.
        
        Returns True if successful, False otherwise.
        """
        action_type = action.get("type", "")
        
        if action_type == "do_nothing":
            logger.info(f"   Action: do_nothing - no execution needed")
            return True

        # strategy_builder v3: simple_close_open_new
        # action.details.leg_swaps: [{close_tag, new_leg: {side, option_type, ...}}]
        # close_tag maps to CE/PE via engine_state.tag_map (built at registration).
        if action_type == "simple_close_open_new":
            return self._execute_simple_close_open_new(
                name=name,
                exec_state=exec_state,
                engine_state=engine_state,
                config=config,
                action=action,
                reader=reader,
            )
        
        try:
            # Get basic config for exchange and lots
            basic = config.get("basic", {})
            exchange = basic.get("exchange", "NFO")
            lots = basic.get("lots", 1)
            lot_size = reader.get_lot_size()
            qty = lots * lot_size
            
            # Execute based on action type
            if action_type == "close_ce":
                return self._adjustment_close_leg(name, exec_state, engine_state, "CE", exchange, qty, config)
            
            elif action_type == "close_pe":
                return self._adjustment_close_leg(name, exec_state, engine_state, "PE", exchange, qty, config)
            
            elif action_type == "close_higher_delta":
                leg = "CE" if abs(engine_state.ce_delta) >= abs(engine_state.pe_delta) else "PE"
                logger.info(f"   Closing higher delta leg: {leg}")
                return self._adjustment_close_leg(name, exec_state, engine_state, leg, exchange, qty, config)
            
            elif action_type == "close_lower_delta":
                leg = "PE" if abs(engine_state.ce_delta) >= abs(engine_state.pe_delta) else "CE"
                logger.info(f"   Closing lower delta leg: {leg}")
                return self._adjustment_close_leg(name, exec_state, engine_state, leg, exchange, qty, config)
            
            elif action_type == "close_most_profitable" or action_type == "close_higher_pnl_leg":
                leg = "CE" if engine_state.ce_pnl >= engine_state.pe_pnl else "PE"
                logger.info(f"   Closing most profitable leg: {leg} (P&L: â‚¹{max(engine_state.ce_pnl, engine_state.pe_pnl):.2f})")
                return self._adjustment_close_leg(name, exec_state, engine_state, leg, exchange, qty, config)
            
            elif action_type == "roll_ce":
                return self._adjustment_roll_leg(name, exec_state, engine_state, "CE", config, reader, qty)
            
            elif action_type == "roll_pe":
                return self._adjustment_roll_leg(name, exec_state, engine_state, "PE", config, reader, qty)
            
            elif action_type == "roll_both":
                success_ce = self._adjustment_roll_leg(name, exec_state, engine_state, "CE", config, reader, qty)
                success_pe = self._adjustment_roll_leg(name, exec_state, engine_state, "PE", config, reader, qty)
                return success_ce and success_pe
            
            elif action_type == "lock_profit":
                return self._adjustment_lock_profit(name, exec_state, engine_state, exchange, qty, config)
            
            elif action_type == "trailing_stop":
                return self._adjustment_trailing_stop(name, exec_state, engine_state, action)
            
            elif action_type == "add_hedge":
                return self._adjustment_add_hedge(name, exec_state, engine_state, config, reader, action, qty)
            
            elif action_type == "shift_strikes":
                return self._adjustment_shift_strikes(name, exec_state, engine_state, config, reader, qty)
            
            elif action_type in ("increase_lots", "decrease_lots"):
                logger.warning(f"   Action '{action_type}' not yet implemented")
                return False
            
            elif action_type == "remove_hedge":
                logger.warning(f"   Action 'remove_hedge' not yet implemented")
                return False
            
            elif action_type == "custom":
                logger.warning(f"   Custom actions require manual implementation")
                return False
            
            else:
                logger.error(f"   Unknown action type: {action_type}")
                return False
        
        except Exception as e:
            logger.error(f"âŒ Adjustment execution error: {e}", exc_info=True)
            
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"âš ï¸ ADJUSTMENT ERROR\n"
                    f"Strategy: {name}\n"
                    f"Action: {action_type}\n"
                    f"Error: {str(e)}"
                )
            
            return False
    
    def _execute_simple_close_open_new(
        self,
        *,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
        action: Dict,
        reader: MarketReader,
    ) -> bool:
        """
        Execute strategy_builder v3 'simple_close_open_new' adjustment.

        action.details.leg_swaps is a list of:
            {close_tag: 'LEG@1', new_leg: {side, option_type, strike_selection, strike_value, lots, order_type}}

        close_tag is resolved to CE/PE via engine_state.tag_map, which is built
        at registration from entry.action.legs[].tag + option_type.
        """
        details = action.get("details") or {}
        leg_swaps = details.get("leg_swaps") or []
        if not leg_swaps:
            logger.error(f"simple_close_open_new: no leg_swaps in action.details for {name}")
            return False

        basic = config.get("basic", {}) or {}
        identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
        exchange = str(basic.get("exchange") or identity_cfg.get("exchange") or "NFO").upper()
        lots_base = int(basic.get("lots") or 1)
        lot_size = reader.get_lot_size() or 1
        default_order_type = identity_cfg.get("order_type")
        default_product_type = str(identity_cfg.get("product_type") or "NRML").upper()
        test_mode = self._resolve_intent_test_mode(config)

        overall_success = True

        for swap in leg_swaps:
            if not isinstance(swap, dict):
                continue

            close_tag = str(swap.get("close_tag") or "").strip()
            new_leg_cfg = swap.get("new_leg") or {}

            # Resolve close_tag -> option_type -> CE/PE
            option_type = engine_state.tag_map.get(close_tag, "").upper()
            if not option_type:
                # Fallback: check if tag directly encodes option type
                if "CE" in close_tag.upper():
                    option_type = "CE"
                elif "PE" in close_tag.upper():
                    option_type = "PE"
                else:
                    logger.error(f"simple_close_open_new: cannot resolve tag '{close_tag}' to CE/PE for {name}")
                    overall_success = False
                    continue

            logger.info(f"  Swap: close {close_tag} ({option_type}), open new {new_leg_cfg.get('option_type','?')}")

            # --- Step 1: Close the current leg ---
            qty_for_close = (exec_state.ce_qty if option_type == "CE" else exec_state.pe_qty) or (lots_base * lot_size)
            close_ok = self._adjustment_close_leg(
                name=name,
                exec_state=exec_state,
                engine_state=engine_state,
                leg=option_type,
                exchange=exchange,
                qty=qty_for_close,
                config=config,
            )
            if not close_ok:
                logger.error(f"simple_close_open_new: close of {option_type} failed for {name}")
                overall_success = False
                continue

            # --- Step 2: Open the new leg ---
            new_opt_type = str(new_leg_cfg.get("option_type") or option_type).upper()
            new_side = str(new_leg_cfg.get("side") or "SELL").upper()
            new_lots = int(new_leg_cfg.get("lots") or lots_base)
            new_qty = new_lots * lot_size
            sel = str(new_leg_cfg.get("strike_selection") or "atm").lower()
            sel_val = new_leg_cfg.get("strike_value")

            def _safe_float_local(v, d=0.0):
                try: return float(v)
                except: return float(d)

            # Select the new option
            new_option = None
            if sel == "delta" and sel_val is not None:
                new_option = reader.find_option_by_delta(new_opt_type, _safe_float_local(sel_val, 0.30), tolerance=0.1)
            elif sel == "premium" and sel_val is not None:
                prem = _safe_float_local(sel_val)
                new_option = reader.find_option_by_premium(new_opt_type, prem, tolerance=max(5.0, prem * 0.3))
            elif sel == "strike" and sel_val is not None:
                new_option = reader.get_option_at_strike(_safe_float_local(sel_val), new_opt_type)
            elif sel.startswith("atm"):
                atm = reader.get_atm_strike() or reader.get_spot_price()
                try:
                    chain = reader.get_full_chain() or []
                    strikes = sorted({_safe_float_local(r.get('strike', 0)) for r in chain if _safe_float_local(r.get('strike', 0)) > 0})
                    step = min(strikes[i+1] - strikes[i] for i in range(len(strikes)-1)) if len(strikes) >= 2 else 50.0
                except Exception:
                    step = 50.0
                sign = 1.0
                steps = 0.0
                if "+" in sel:
                    steps = _safe_float_local(sel.split("+", 1)[1], 0.0)
                elif "-" in sel:
                    steps = _safe_float_local(sel.split("-", 1)[1], 0.0)
                    sign = -1.0
                target = atm + (sign * steps * step)
                new_option = reader.get_option_at_strike(target, new_opt_type)
            else:
                # Default: by delta 0.30
                new_option = reader.find_option_by_delta(new_opt_type, 0.30, tolerance=0.1)

            if not new_option:
                logger.error(f"simple_close_open_new: could not find new {new_opt_type} option for {name}")
                overall_success = False
                continue

            new_symbol = str(new_option.get("trading_symbol") or "")
            new_ltp = float(new_option.get("ltp") or 0.0)
            new_strike = float(new_option.get("strike") or 0.0)
            preferred_otype = str(new_leg_cfg.get("order_type") or default_order_type or "")

            open_order_type, open_price = self._resolve_order_contract(
                exchange=exchange,
                tradingsymbol=new_symbol,
                preferred_order_type=preferred_otype,
                fallback_price=new_ltp,
            )
            if open_order_type == "LIMIT" and open_price <= 0:
                logger.error(f"simple_close_open_new: new leg {new_symbol} requires LIMIT price but none available")
                overall_success = False
                continue

            open_alert = {
                "secret_key": self._resolve_webhook_secret(),
                "execution_type": "ADJUSTMENT",
                "strategy_name": name,
                "exchange": exchange,
                "legs": [{
                    "tradingsymbol": new_symbol,
                    "direction": new_side,
                    "qty": new_qty,
                    "order_type": open_order_type,
                    "price": open_price,
                    "product_type": str(new_leg_cfg.get("product_type") or default_product_type).upper(),
                }],
            }
            if test_mode:
                open_alert["test_mode"] = test_mode

            logger.info(f"  Opening new {new_opt_type} leg: {new_symbol} {new_side} x{new_qty}")
            open_result = self.bot.process_alert(open_alert)
            logger.info(f"  Open result: {open_result}")

            # Track the newly opened leg in exec_state
            self._open_monitored_leg(
                strategy_name=name,
                exchange=exchange,
                symbol=new_symbol,
                side=new_side,
                qty=new_qty,
                entry_price=new_ltp,
                source="ADJUSTMENT_SWAP",
            )
            if new_opt_type == "CE":
                exec_state.ce_symbol = new_symbol
                exec_state.ce_strike = new_strike
                exec_state.ce_qty = new_qty
                exec_state.ce_side = new_side
                exec_state.ce_entry_price = new_ltp
            elif new_opt_type == "PE":
                exec_state.pe_symbol = new_symbol
                exec_state.pe_strike = new_strike
                exec_state.pe_qty = new_qty
                exec_state.pe_side = new_side
                exec_state.pe_entry_price = new_ltp
            exec_state.has_position = True
            self.state_mgr.save(exec_state)

        return overall_success

    def _adjustment_close_leg(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        leg: str,
        exchange: str,
        qty: int,
        config: Dict,
    ) -> bool:
        """Close a specific leg (CE or PE)."""
        try:
            if leg == "CE":
                if not exec_state.ce_symbol:
                    logger.warning(f"   CE leg not found in position")
                    return False
                
                symbol = exec_state.ce_symbol
                side = exec_state.ce_side
                ltp = exec_state.ce_entry_price  # Approximate price
                leg_qty = exec_state.ce_qty if exec_state.ce_qty > 0 else qty
            else:
                if not exec_state.pe_symbol:
                    logger.warning(f"   PE leg not found in position")
                    return False
                
                symbol = exec_state.pe_symbol
                side = exec_state.pe_side
                ltp = exec_state.pe_entry_price
                leg_qty = exec_state.pe_qty if exec_state.pe_qty > 0 else qty
            
            # Exit direction is opposite of entry
            exit_direction = "BUY" if side == "SELL" else "SELL"
            identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
            order_type, price = self._resolve_order_contract(
                exchange=exchange,
                tradingsymbol=symbol,
                preferred_order_type=identity_cfg.get("order_type"),
                fallback_price=ltp,
            )
            if order_type == "LIMIT" and price <= 0:
                logger.error(f"   Close leg requires LIMIT price but none is available: {symbol}")
                return False
            
            # Build exit leg
            legs = [{
                "tradingsymbol": symbol,
                "direction": exit_direction,
                "qty": leg_qty,
                "order_type": order_type,
                "price": price,
                "product_type": str(identity_cfg.get("product_type") or "NRML").upper(),
            }]
            
            # Send adjustment alert
            alert = {
                "secret_key": self._resolve_webhook_secret(),
                "execution_type": "ADJUSTMENT",
                "strategy_name": name,
                "exchange": exchange,
                "legs": legs,
            }
            test_mode = self._resolve_intent_test_mode(config)
            if test_mode:
                alert["test_mode"] = test_mode
            
            logger.info(f"   â†’ Closing {leg} leg: {symbol}")
            result = self.bot.process_alert(alert)
            logger.info(f"   â† Close result: {result}")

            realized = float(engine_state.ce_pnl if leg == "CE" else engine_state.pe_pnl)
            exit_px = float(engine_state.ce_ltp if leg == "CE" else engine_state.pe_ltp)
            self._close_monitored_leg(
                strategy_name=name,
                symbol=symbol,
                realized_pnl=realized,
                exit_price=exit_px,
            )
            
            # Update state - remove the closed leg
            if leg == "CE":
                exec_state.ce_symbol = ""
                exec_state.ce_strike = 0.0
                exec_state.ce_qty = 0
                exec_state.ce_side = ""
                exec_state.ce_entry_price = 0.0
            else:
                exec_state.pe_symbol = ""
                exec_state.pe_strike = 0.0
                exec_state.pe_qty = 0
                exec_state.pe_side = ""
                exec_state.pe_entry_price = 0.0
            
            # If both legs closed, mark position as closed
            if not exec_state.ce_symbol and not exec_state.pe_symbol:
                exec_state.has_position = False
            
            self.state_mgr.save(exec_state)
            return True
            
        except Exception as e:
            logger.error(f"   Close leg failed: {e}", exc_info=True)
            return False
    
    def _adjustment_roll_leg(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        leg: str,
        config: Dict,
        reader: MarketReader,
        qty: int,
    ) -> bool:
        """Roll a leg to a new strike (close old, open new)."""
        try:
            basic = config.get("basic", {})
            exchange = basic.get("exchange", "NFO")
            identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
            default_order_type = identity_cfg.get("order_type")
            default_product_type = str(identity_cfg.get("product_type") or "NRML").upper()
            test_mode = self._resolve_intent_test_mode(config)
            
            # Get current leg details
            if leg == "CE":
                old_symbol = exec_state.ce_symbol
                old_side = exec_state.ce_side
                option_type = "CE"
                old_ltp = exec_state.ce_entry_price
                leg_qty = exec_state.ce_qty if exec_state.ce_qty > 0 else qty
            else:
                old_symbol = exec_state.pe_symbol
                old_side = exec_state.pe_side
                option_type = "PE"
                old_ltp = exec_state.pe_entry_price
                leg_qty = exec_state.pe_qty if exec_state.pe_qty > 0 else qty
            
            if not old_symbol:
                logger.warning(f"   {leg} leg not found in position")
                return False
            
            # Find new option at similar delta (30% default)
            target_delta = 0.30
            new_option = reader.find_option_by_delta(option_type, target_delta, tolerance=0.1)
            
            if not new_option:
                logger.error(f"   No new {option_type} option found with delta â‰ˆ {target_delta}")
                return False
            
            new_symbol = new_option.get("trading_symbol", "")
            new_strike = float(new_option.get("strike", 0))
            new_ltp = float(new_option.get("ltp", 0))

            # No-op guard: avoid generating close+open intents when strike resolver returns same contract.
            if str(new_symbol).strip() == str(old_symbol).strip():
                logger.info(f"   Roll skipped ({leg}): target resolved to same symbol {old_symbol}")
                return True
            
            # Exit old position
            exit_direction = "BUY" if old_side == "SELL" else "SELL"
            close_order_type, close_price = self._resolve_order_contract(
                exchange=exchange,
                tradingsymbol=old_symbol,
                preferred_order_type=default_order_type,
                fallback_price=old_ltp,
            )
            if close_order_type == "LIMIT" and close_price <= 0:
                logger.error(f"   Roll close leg requires LIMIT price but none is available: {old_symbol}")
                return False

            open_order_type, open_price = self._resolve_order_contract(
                exchange=exchange,
                tradingsymbol=new_symbol,
                preferred_order_type=default_order_type,
                fallback_price=new_ltp,
            )
            if open_order_type == "LIMIT" and open_price <= 0:
                logger.error(f"   Roll open leg requires LIMIT price but none is available: {new_symbol}")
                return False
            
            # Entry new position (same direction as original)
            legs = [
                # Close old
                {
                    "tradingsymbol": old_symbol,
                    "direction": exit_direction,
                    "qty": leg_qty,
                    "order_type": close_order_type,
                    "price": close_price,
                    "product_type": default_product_type,
                },
                # Open new
                {
                    "tradingsymbol": new_symbol,
                    "direction": old_side,
                    "qty": leg_qty,
                    "order_type": open_order_type,
                    "price": open_price,
                    "product_type": default_product_type,
                },
            ]
            
            # Send roll alert
            alert = {
                "secret_key": self._resolve_webhook_secret(),
                "execution_type": "ADJUSTMENT",
                "strategy_name": name,
                "exchange": exchange,
                "legs": legs,
            }
            if test_mode:
                alert["test_mode"] = test_mode
            
            logger.info(f"   â†’ Rolling {leg}: {old_symbol} â†’ {new_symbol}")
            result = self.bot.process_alert(alert)
            logger.info(f"   â† Roll result: {result}")

            realized = float(engine_state.ce_pnl if leg == "CE" else engine_state.pe_pnl)
            exit_px = float(engine_state.ce_ltp if leg == "CE" else engine_state.pe_ltp)
            self._close_monitored_leg(
                strategy_name=name,
                symbol=old_symbol,
                realized_pnl=realized,
                exit_price=exit_px,
            )
            self._open_monitored_leg(
                strategy_name=name,
                exchange=exchange,
                symbol=new_symbol,
                side=old_side,
                qty=int(leg_qty),
                entry_price=float(new_ltp or 0.0),
                source="ADJUSTMENT_ROLL",
            )
            
            # Update state with new position
            if leg == "CE":
                exec_state.ce_symbol = new_symbol
                exec_state.ce_strike = new_strike
                exec_state.ce_entry_price = new_ltp
            else:
                exec_state.pe_symbol = new_symbol
                exec_state.pe_strike = new_strike
                exec_state.pe_entry_price = new_ltp
            
            self.state_mgr.save(exec_state)
            return True
            
        except Exception as e:
            logger.error(f"   Roll leg failed: {e}", exc_info=True)
            return False
    
    def _adjustment_lock_profit(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        exchange: str,
        qty: int,
        config: Dict,
    ) -> bool:
        """Lock in profit by closing the most profitable leg."""
        try:
            # Determine most profitable leg
            if engine_state.ce_pnl >= engine_state.pe_pnl:
                leg = "CE"
                pnl = engine_state.ce_pnl
            else:
                leg = "PE"
                pnl = engine_state.pe_pnl
            
            logger.info(f"   Locking profit by closing {leg} (P&L: â‚¹{pnl:.2f})")
            return self._adjustment_close_leg(name, exec_state, engine_state, leg, exchange, qty, config)
            
        except Exception as e:
            logger.error(f"   Lock profit failed: {e}", exc_info=True)
            return False
    
    def _adjustment_trailing_stop(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        action: Dict,
    ) -> bool:
        """Activate trailing stop loss."""
        try:
            # Get trailing parameters
            trail_pct = action.get("trail_pct", 50)  # Trail 50% of profit by default
            
            # Calculate trailing stop level
            current_pnl = engine_state.combined_pnl
            
            if not engine_state.trailing_stop_active:
                # Activate trailing stop
                engine_state.trailing_stop_active = True
                engine_state.peak_pnl = current_pnl
                engine_state.trailing_stop_level = current_pnl * (1 - trail_pct / 100.0)
                
                logger.info(f"   Trailing stop ACTIVATED:")
                logger.info(f"   â€¢ Current P&L: â‚¹{current_pnl:.2f}")
                logger.info(f"   â€¢ Trail %: {trail_pct}%")
                logger.info(f"   â€¢ Stop Level: â‚¹{engine_state.trailing_stop_level:.2f}")
                
                if self.bot.telegram_enabled:
                    self.bot.send_telegram(
                        f"ðŸ“Š TRAILING STOP ACTIVATED\n"
                        f"Strategy: {name}\n"
                        f"Current P&L: â‚¹{current_pnl:.2f}\n"
                        f"Trail: {trail_pct}%\n"
                        f"Stop Level: â‚¹{engine_state.trailing_stop_level:.2f}"
                    )
                
                return True
            else:
                logger.info(f"   Trailing stop already active")
                return True
            
        except Exception as e:
            logger.error(f"   Trailing stop failed: {e}", exc_info=True)
            return False
    
    def _adjustment_add_hedge(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
        reader: MarketReader,
        action: Dict,
        qty: int,
    ) -> bool:
        """Add hedge by buying OTM options."""
        try:
            basic = config.get("basic", {})
            exchange = basic.get("exchange", "NFO")
            identity_cfg = config.get("identity", {}) if isinstance(config.get("identity"), dict) else {}
            default_order_type = identity_cfg.get("order_type")
            default_product_type = str(identity_cfg.get("product_type") or "NRML").upper()
            test_mode = self._resolve_intent_test_mode(config)
            
            # Get hedge parameters
            hedge_type = action.get("hedge_type", "both")  # "ce", "pe", or "both"
            hedge_delta = action.get("hedge_delta", 0.15)  # OTM options around 15 delta
            
            legs = []
            
            # Add CE hedge
            if hedge_type in ("ce", "both"):
                ce_hedge = reader.find_option_by_delta("CE", hedge_delta, tolerance=0.05)
                if ce_hedge:
                    ce_order_type, ce_price = self._resolve_order_contract(
                        exchange=exchange,
                        tradingsymbol=str(ce_hedge.get("trading_symbol", "")),
                        preferred_order_type=default_order_type,
                        fallback_price=ce_hedge.get("ltp", 0),
                    )
                    if ce_order_type == "LIMIT" and ce_price <= 0:
                        logger.error("   CE hedge requires LIMIT price but none is available")
                        return False
                    legs.append({
                        "tradingsymbol": ce_hedge.get("trading_symbol", ""),
                        "direction": "BUY",
                        "qty": qty,
                        "order_type": ce_order_type,
                        "price": ce_price,
                        "product_type": default_product_type,
                    })
                    logger.info(f"   Adding CE hedge: {ce_hedge.get('trading_symbol', '')}")
            
            # Add PE hedge
            if hedge_type in ("pe", "both"):
                pe_hedge = reader.find_option_by_delta("PE", hedge_delta, tolerance=0.05)
                if pe_hedge:
                    pe_order_type, pe_price = self._resolve_order_contract(
                        exchange=exchange,
                        tradingsymbol=str(pe_hedge.get("trading_symbol", "")),
                        preferred_order_type=default_order_type,
                        fallback_price=pe_hedge.get("ltp", 0),
                    )
                    if pe_order_type == "LIMIT" and pe_price <= 0:
                        logger.error("   PE hedge requires LIMIT price but none is available")
                        return False
                    legs.append({
                        "tradingsymbol": pe_hedge.get("trading_symbol", ""),
                        "direction": "BUY",
                        "qty": qty,
                        "order_type": pe_order_type,
                        "price": pe_price,
                        "product_type": default_product_type,
                    })
                    logger.info(f"   Adding PE hedge: {pe_hedge.get('trading_symbol', '')}")
            
            if not legs:
                logger.error(f"   No hedge options found")
                return False
            
            # Send hedge alert
            alert = {
                "secret_key": self._resolve_webhook_secret(),
                "execution_type": "ADJUSTMENT",
                "strategy_name": name,
                "exchange": exchange,
                "legs": legs,
            }
            if test_mode:
                alert["test_mode"] = test_mode
            
            logger.info(f"   â†’ Adding {len(legs)} hedge leg(s)")
            result = self.bot.process_alert(alert)
            logger.info(f"   â† Hedge result: {result}")
            
            return True
            
        except Exception as e:
            logger.error(f"   Add hedge failed: {e}", exc_info=True)
            return False
    
    def _adjustment_shift_strikes(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
        reader: MarketReader,
        qty: int,
    ) -> bool:
        """Shift strikes by rolling both legs."""
        try:
            logger.info(f"   Shifting strikes (rolling both legs)")
            
            success_ce = self._adjustment_roll_leg(
                name, exec_state, engine_state, "CE", config, reader, qty
            )
            
            success_pe = self._adjustment_roll_leg(
                name, exec_state, engine_state, "PE", config, reader, qty
            )
            
            return success_ce and success_pe
            
        except Exception as e:
            logger.error(f"   Shift strikes failed: {e}", exc_info=True)
            return False
    
    def _check_exit(
        self,
        name: str,
        exec_state: ExecutionState,
        engine_state: StrategyState,
        config: Dict,
    ):
        """
        Check exit conditions.
        
        CRITICAL FIX: Handles single RuleResult (not list).
        """
        result = evaluate_exit_rules(config, engine_state)
        
        # FIXED: Handle single RuleResult (not list)
        if not result or not isinstance(result, RuleResult):
            return
        
        if result.triggered:
            logger.info(f"ðŸšª EXIT TRIGGERED: {name} | {result.rule_name}")
            self._execute_exit(name, exec_state, config, result.rule_name)
    
    def _send_entry_alert(self, name: str, config: Dict, legs: List[Dict], test_mode: Optional[str] = None):
        """Send ENTRY alert via bot.process_alert() and return OMS response."""
        basic = config.get("basic", {})
        
        alert = {
            "secret_key": self._resolve_webhook_secret(),
            "execution_type": "ENTRY",
            "strategy_name": name,
            "exchange": basic.get("exchange", "NFO"),
            "legs": legs,
        }
        if test_mode:
            alert["test_mode"] = test_mode
        
        logger.info(f"ENTRY ALERT: {name} | {len(legs)} legs")
        
        try:
            result = self.bot.process_alert(alert)
            logger.info(f"ENTRY RESULT: {result}")
            return result if isinstance(result, dict) else {"status": "UNKNOWN", "raw_result": result}
        except Exception as e:
            logger.error(f"Entry alert failed: {e}", exc_info=True)
            return {"status": "FAILED", "reason": str(e)}
    
    def _execute_exit(
        self,
        name: str,
        exec_state: ExecutionState,
        config: Dict,
        reason: str,
    ):
        """Execute exit via broker (live) or virtual close (paper mode)."""
        logger.info(f"EXECUTING EXIT: {name} | reason={reason}")
        
        try:
            paper_mode = self._is_paper_mode(config)
            if not paper_mode:
                self.bot.request_exit(
                    scope="strategy",
                    strategy_name=name,
                    product_type="ALL",
                    reason=reason,
                    source="STRATEGY_EXECUTOR",
                )
                
                # CRITICAL: Verify exit completed
                symbols = [exec_state.ce_symbol, exec_state.pe_symbol]
                is_verified, verify_reason = self.verifier.verify_exit(
                    name,
                    symbols=symbols,
                    timeout_sec=30,
                )
                
                if not is_verified:
                    logger.error(f"EXIT VERIFICATION FAILED: {name} | {verify_reason}")
                    
                    if self.bot.telegram_enabled:
                        self.bot.send_telegram(
                            f"âš ï¸ EXIT INCOMPLETE\n"
                            f"Strategy: {name}\n"
                            f"Reason: {verify_reason}\n"
                            f"Manual check required"
                        )
                    
                    return
            else:
                logger.info(f"PAPER MODE EXIT: {name} | broker exit skipped")
            
            # FIXED: Get engine_state from registry to access combined_pnl
            engine_state = self._engine_states.get(name)
            if engine_state:
                # Add current position P&L to cumulative daily P&L
                exec_state.cumulative_daily_pnl += engine_state.combined_pnl
                logger.info(
                    f"P&L Update: {name} | "
                    f"Position P&L: INR {engine_state.combined_pnl:.2f} | "
                    f"Cumulative Daily: INR {exec_state.cumulative_daily_pnl:.2f}"
                )
                if exec_state.ce_symbol:
                    self._close_monitored_leg(
                        strategy_name=name,
                        symbol=exec_state.ce_symbol,
                        realized_pnl=float(engine_state.ce_pnl or 0.0),
                        exit_price=float(engine_state.ce_ltp or 0.0),
                    )
                if exec_state.pe_symbol:
                    self._close_monitored_leg(
                        strategy_name=name,
                        symbol=exec_state.pe_symbol,
                        realized_pnl=float(engine_state.pe_pnl or 0.0),
                        exit_price=float(engine_state.pe_ltp or 0.0),
                    )
            else:
                if exec_state.ce_symbol:
                    self._close_monitored_leg(
                        strategy_name=name,
                        symbol=exec_state.ce_symbol,
                        realized_pnl=0.0,
                        exit_price=None,
                    )
                if exec_state.pe_symbol:
                    self._close_monitored_leg(
                        strategy_name=name,
                        symbol=exec_state.pe_symbol,
                        realized_pnl=0.0,
                        exit_price=None,
                    )
            
            # Clear position state
            exec_state.has_position = False
            exec_state.ce_symbol = ""
            exec_state.ce_strike = 0.0
            exec_state.ce_qty = 0
            exec_state.ce_side = ""
            exec_state.ce_entry_price = 0.0
            exec_state.pe_symbol = ""
            exec_state.pe_strike = 0.0
            exec_state.pe_qty = 0
            exec_state.pe_side = ""
            exec_state.pe_entry_price = 0.0
            
            self.state_mgr.save(exec_state)
            
            logger.info(f"EXIT COMPLETE: {name}")

            # Optional one-shot mode: auto-stop strategy after first full exit.
            basic_cfg = config.get("basic", {}) if isinstance(config.get("basic"), dict) else {}
            run_once = bool(
                config.get("run_once")
                or config.get("single_cycle")
                or basic_cfg.get("run_once")
                or basic_cfg.get("single_cycle")
            )
            if run_once:
                logger.info(f"RUN_ONCE enabled - stopping strategy after exit: {name}")
                try:
                    self.unregister_strategy(name)
                    with self.bot._live_strategies_lock:
                        self.bot._live_strategies.pop(name, None)
                    self.state_mgr.delete(name)
                except Exception as stop_err:
                    logger.warning(f"Could not auto-stop run_once strategy {name}: {stop_err}")
            
        except Exception as e:
            logger.error(f"Exit execution failed: {e}", exc_info=True)
            
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"ðŸš¨ EXIT ERROR\n"
                    f"Strategy: {name}\n"
                    f"Error: {str(e)}\n"
                    f"URGENT: Manual check required"
                )
