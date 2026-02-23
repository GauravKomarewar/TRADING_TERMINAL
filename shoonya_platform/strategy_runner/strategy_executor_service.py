#!/usr/bin/env python3
"""
strategy_executor_service.py — Drop‑in replacement using Universal Engine
==========================================================================
Implements the same interface as the old service, but uses the new engine.
"""

import json
import logging
import sqlite3
import threading
import time
import copy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .models import (
    InstrumentType, OptionType, Side, OrderType, StrikeMode, StrikeConfig
)
from .state import StrategyState, LegState
from .condition_engine import ConditionEngine
from .market_reader import MarketReader
from .entry_engine import EntryEngine
from .adjustment_engine import AdjustmentEngine
from .exit_engine import ExitEngine
from .reconciliation import BrokerReconciliation
from .persistence import StatePersistence

logger = logging.getLogger("STRATEGY_EXECUTOR_SERVICE")


@dataclass
class ExecutionState:
    """
    Backward-compatible execution snapshot used by dashboard/runtime recovery paths.
    """
    strategy_name: str
    run_id: str
    has_position: bool = False
    entry_timestamp: float = 0.0

    ce_symbol: Optional[str] = None
    ce_side: Optional[str] = None
    ce_qty: int = 0
    ce_entry_price: float = 0.0
    ce_strike: float = 0.0
    ce_delta: float = 0.0

    pe_symbol: Optional[str] = None
    pe_side: Optional[str] = None
    pe_qty: int = 0
    pe_entry_price: float = 0.0
    pe_strike: float = 0.0
    pe_delta: float = 0.0

    updated_at: float = 0.0


class StateManager:
    """
    Minimal SQLite-backed state store for legacy strategy lifecycle compatibility.
    """

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_states (
                    strategy_name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, state: ExecutionState):
        state.updated_at = time.time()
        payload = json.dumps(asdict(state), default=str)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO execution_states(strategy_name, payload, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(strategy_name) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (state.strategy_name, payload, state.updated_at),
            )
            conn.commit()
        finally:
            conn.close()

    def load(self, strategy_name: str) -> Optional[ExecutionState]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM execution_states WHERE strategy_name = ?",
                (strategy_name,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["payload"])
            return ExecutionState(**data)
        finally:
            conn.close()

    def delete(self, strategy_name: str):
        conn = self._connect()
        try:
            conn.execute("DELETE FROM execution_states WHERE strategy_name = ?", (strategy_name,))
            conn.commit()
        finally:
            conn.close()

    def list_all(self) -> List[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT strategy_name FROM execution_states ORDER BY strategy_name"
            ).fetchall()
            return [r["strategy_name"] for r in rows]
        finally:
            conn.close()

class StrategyExecutorService:
    """
    Service that manages multiple strategies using the Universal Engine.
    Compatible with the old interface expected by ShoonyaBot.
    """

    def __init__(self, bot, state_db_path: str):
        self.bot = bot
        self.state_db_path = state_db_path
        self.state_mgr = StateManager(state_db_path)
        self._strategies: Dict[str, Dict] = {}          # name -> config
        self._executors: Dict[str, 'PerStrategyExecutor'] = {}
        self._exec_states: Dict[str, StrategyState] = {}  # name -> live state
        self._engine_states = self._exec_states  # legacy alias expected by dashboard/tests
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._mode_change_dict_lock = threading.Lock()
        self._mode_change_lock: Dict[str, threading.Lock] = {}
        self._monitor_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def register_strategy(self, name: str, config_path: str):
        """Register a strategy with the service."""
        with self._lock:
            if name in self._strategies:
                logger.warning(f"Strategy {name} already registered, overwriting")
            # Load config – assume it's valid (validation should be done by caller)
            with open(config_path, 'r') as f:
                config = json.load(f)
            self._strategies[name] = config
            # Create per‑strategy executor
            executor = PerStrategyExecutor(
                name=name,
                config=config,
                bot=self.bot,
                state_db_path=self.state_db_path
            )
            self._executors[name] = executor
            self._exec_states[name] = executor.state
            self._monitor_cache[name] = {}
            logger.info(f"Registered strategy: {name}")

    def unregister_strategy(self, name: str):
        """Remove a strategy from the service."""
        with self._lock:
            self._executors.pop(name, None)
            self._strategies.pop(name, None)
            self._exec_states.pop(name, None)
            self._monitor_cache.pop(name, None)
            logger.info(f"Strategy unregistered: {name}")

    def start(self):
        """Start the background processing thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("StrategyExecutorService started")

    def stop(self):
        """Stop the background thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("StrategyExecutorService stopped")

    def _run_loop(self):
        """Main loop: iterate over all strategies and process each."""
        while self._running and not self._stop_event.is_set():
            with self._lock:
                names = list(self._executors.keys())
            completed_names: List[str] = []
            for name in names:
                executor = self._executors.get(name)
                if executor:
                    try:
                        executor.process_tick()
                        if getattr(executor, "cycle_completed", False) and not executor.state.any_leg_active:
                            completed_names.append(name)
                    except Exception as e:
                        logger.exception(f"Error processing strategy {name}: {e}")
            for name in completed_names:
                try:
                    self.unregister_strategy(name)
                    logger.info(f"Strategy cycle completed and auto-stopped: {name}")
                except Exception as e:
                    logger.error(f"Failed to auto-stop completed strategy {name}: {e}")
            time.sleep(2)  # same as old service

    def acquire_mode_change_lock(self, strategy_name: str) -> threading.Lock:
        with self._mode_change_dict_lock:
            if strategy_name not in self._mode_change_lock:
                self._mode_change_lock[strategy_name] = threading.Lock()
            return self._mode_change_lock[strategy_name]

    def _validate_mode_change_allowed(self, strategy_name: str) -> Tuple[bool, str]:
        """Return (allowed, reason)."""
        if self.has_position(strategy_name):
            return False, "Strategy has active positions"
        return True, ""

    def has_position(self, strategy_name: str) -> bool:
        state = self._exec_states.get(strategy_name)
        if not state:
            return False
        return state.any_leg_active

    def _is_paper_mode(self, config: Dict[str, Any]) -> bool:
        identity = config.get("identity", {}) or {}
        return bool(
            config.get("paper_mode")
            or identity.get("paper_mode")
            or config.get("is_paper")
            or config.get("test_mode")
            or identity.get("test_mode")
        )

    # BUG-014 FIX: get_strategy_mode() was called by router but never existed in service.
    # The router used hasattr guard so it silently fell back to "LIVE" for all strategies —
    # paper-mode strategies appeared as LIVE in the dashboard.
    def get_strategy_mode(self, strategy_name: str) -> str:
        """Return 'MOCK' or 'LIVE' based on strategy config paper_mode / test_mode flags."""
        config = self._strategies.get(strategy_name, {})
        return "MOCK" if self._is_paper_mode(config) else "LIVE"

    def get_strategy_leg_monitor_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Build monitor-ready leg snapshot from current executor state.
        """
        snapshot: Dict[str, Dict[str, Any]] = {}
        now_iso = datetime.now().isoformat()
        with self._lock:
            names = list(self._exec_states.keys())
            for strategy_name in names:
                state = self._exec_states.get(strategy_name)
                if state is None:
                    continue

                config = self._strategies.get(strategy_name, {}) or {}
                identity = config.get("identity", {}) or {}
                mode = "MOCK" if self._is_paper_mode(config) else "LIVE"
                cache = self._monitor_cache.setdefault(strategy_name, {})
                seen_keys: set[str] = set()

                for leg in (getattr(state, "legs", {}) or {}).values():
                    side_val = getattr(getattr(leg, "side", None), "value", getattr(leg, "side", ""))
                    side = str(side_val or "").upper()
                    qty = int(getattr(leg, "qty", 0) or 0)
                    is_active = bool(getattr(leg, "is_active", False)) and qty > 0
                    status = "ACTIVE" if is_active else "CLOSED"
                    leg_pnl = float(getattr(leg, "pnl", 0) or 0)
                    unrealized = leg_pnl if is_active else 0.0
                    symbol = str(
                        getattr(leg, "trading_symbol", None)
                        or getattr(leg, "symbol", "")
                        or ""
                    ).strip()
                    if not symbol:
                        continue

                    tag = str(getattr(leg, "tag", "") or symbol)
                    leg_key = f"{tag}::{symbol}"
                    seen_keys.add(leg_key)

                    row = cache.get(leg_key)
                    if row is None:
                        row = {
                            "strategy_name": strategy_name,
                            "opened_at": now_iso,
                            "closed_at": None,
                            "source": "ENTRY" if tag.startswith("LEG@") else "ADJUSTMENT",
                            "realized_pnl": 0.0,
                        }
                        cache[leg_key] = row

                    was_active = str(row.get("status", "")).upper() == "ACTIVE"
                    if was_active and not is_active and row.get("closed_at") is None:
                        row["closed_at"] = now_iso
                        row["realized_pnl"] = float(row.get("realized_pnl", 0) or 0) + float(leg_pnl)

                    row.update({
                        "strategy_name": strategy_name,
                        "exchange": identity.get("exchange", ""),
                        "symbol": symbol,
                        "side": side,
                        "qty": max(0, qty),
                        "entry_price": float(getattr(leg, "entry_price", 0) or 0),
                        "exit_price": None,
                        "ltp": float(getattr(leg, "ltp", 0) or 0),
                        "status": status,
                        "unrealized_pnl": (unrealized if is_active else 0.0),
                        "delta": float(getattr(leg, "delta", 0) or 0),
                        "gamma": float(getattr(leg, "gamma", 0) or 0),
                        "theta": float(getattr(leg, "theta", 0) or 0),
                        "vega": float(getattr(leg, "vega", 0) or 0),
                        "opened_at": row.get("opened_at") or (getattr(state, "entry_time", None).isoformat() if getattr(state, "entry_time", None) else now_iso),
                        "closed_at": None if is_active else (row.get("closed_at") or now_iso),
                        "updated_at": now_iso,
                        "mode": mode,
                    })
                    row["total_pnl"] = float(row.get("realized_pnl", 0) or 0) + float(row.get("unrealized_pnl", 0) or 0)
                    if is_active:
                        row["closed_at"] = None

                # Keep cached closed legs for lifecycle visibility; drop stale never-seen rows.
                for k in list(cache.keys()):
                    if k in seen_keys:
                        continue
                    stale = cache.get(k) or {}
                    if str(stale.get("status", "")).upper() != "CLOSED":
                        cache.pop(k, None)

                legs_payload: List[Dict[str, Any]] = list(cache.values())
                active_legs = len([r for r in legs_payload if str(r.get("status", "")).upper() == "ACTIVE"])
                closed_legs = len([r for r in legs_payload if str(r.get("status", "")).upper() == "CLOSED"])
                unrealized_pnl = sum(float(r.get("unrealized_pnl", 0) or 0) for r in legs_payload if str(r.get("status", "")).upper() == "ACTIVE")
                realized_leg_pnl = sum(float(r.get("realized_pnl", 0) or 0) for r in legs_payload if str(r.get("status", "")).upper() == "CLOSED")
                realized_pnl = float(getattr(state, "cumulative_daily_pnl", 0) or 0.0)
                snapshot[strategy_name] = {
                    "mode": mode,
                    "active_legs": active_legs,
                    "closed_legs": closed_legs,
                    "realized_pnl": float(realized_pnl + realized_leg_pnl),
                    "unrealized_pnl": float(unrealized_pnl),
                    "adjustments_today": int(getattr(state, "adjustments_today", 0) or 0),
                    "lifetime_adjustments": int(getattr(state, "lifetime_adjustments", 0) or 0),
                    "last_adjustment_time": (
                        getattr(state, "last_adjustment_time", None).isoformat()
                        if getattr(state, "last_adjustment_time", None)
                        else None
                    ),
                    "legs": legs_payload,
                }
        return snapshot

    # BUG-026 FIX: STRATEGY_RECOVER_RESUME intent was submitted by the dashboard but
    # had NO consumer anywhere. The intent was stored in DB forever; recovery never happened.
    def handle_recover_resume(self, payload: dict) -> dict:
        """
        Handle a STRATEGY_RECOVER_RESUME intent submitted by the dashboard.

        Sets the strategy state to 'already entered' so the executor monitors
        exits/adjustments rather than waiting for a fresh entry signal.

        Args:
            payload: {
                "strategy_name": str,      # strategy to recover
                "symbol": str,             # broker symbol with open position
                "resume_monitoring": bool  # True = skip re-entry, monitor only
            }
        """
        strategy_name = payload.get("strategy_name", "").strip()
        symbol = payload.get("symbol", "").strip()
        resume_monitoring = payload.get("resume_monitoring", True)

        if not strategy_name:
            logger.error("RECOVER_RESUME: strategy_name is required")
            return {"status": "error", "reason": "strategy_name required"}

        with self._lock:
            executor = self._executors.get(strategy_name)
            if executor is None:
                logger.warning(f"RECOVER_RESUME: strategy '{strategy_name}' not registered; "
                               f"cannot apply until strategy is loaded via /runner/start")
                return {"status": "not_registered", "strategy_name": strategy_name}

            state = executor.state
            if resume_monitoring:
                # Mark as entered so executor skips fresh ENTRY and monitors exits/adjustments
                state.entered_today = True
                if state.entry_time is None:
                    state.entry_time = datetime.now()

                # If symbol provided and not already tracked, create a placeholder leg
                # so the exit engine can monitor it until full reconciliation happens
                if symbol and symbol not in [leg.symbol for leg in state.legs.values()]:
                    from .state import LegState
                    from .models import InstrumentType, Side
                    recovery_tag = f"RECOVERED_{symbol}"
                    recovery_leg = LegState(
                        tag=recovery_tag,
                        symbol=symbol,
                        trading_symbol=symbol,
                        instrument=InstrumentType.OPT,
                        option_type=None,
                        strike=None,
                        expiry="UNKNOWN",
                        side=Side.SELL,   # default; reconciliation will correct this
                        qty=0,            # qty=0 signals "needs reconciliation"
                        entry_price=0.0,
                        ltp=0.0,
                        is_active=True,
                    )
                    state.legs[recovery_tag] = recovery_leg
                    logger.info(f"RECOVER_RESUME: placeholder leg created for '{symbol}' "
                                f"in strategy '{strategy_name}'")

                # Persist the recovery state immediately
                try:
                    executor.persistence.save(state, str(executor.state_file))
                    logger.info(f"RECOVER_RESUME: state persisted for '{strategy_name}'")
                except Exception as e:
                    logger.error(f"RECOVER_RESUME: state persist failed: {e}")

            logger.warning(f"♻️ RECOVER_RESUME APPLIED | strategy={strategy_name} | "
                           f"symbol={symbol} | resume_monitoring={resume_monitoring}")
            return {
                "status": "resumed",
                "strategy_name": strategy_name,
                "symbol": symbol,
                "resume_monitoring": resume_monitoring,
            }

    @staticmethod
    def _adjustment_roll_leg(
        svc,
        name: str,
        exec_state: ExecutionState,
        engine_state: Any,
        leg: str,
        config: Dict[str, Any],
        reader: Any,
        qty: int,
    ) -> bool:
        """
        Legacy roll helper used by hardening tests and old adjustment flow.
        """
        leg_key = leg.strip().upper()
        if leg_key not in ("CE", "PE"):
            return False

        prefix = leg_key.lower()
        opposite = "pe" if prefix == "ce" else "ce"
        cur_symbol = getattr(exec_state, f"{prefix}_symbol", None)
        side = getattr(exec_state, f"{prefix}_side", None) or "SELL"
        raw_delta = getattr(engine_state, f"{opposite}_delta", 0.3)
        try:
            target_abs_delta = abs(float(raw_delta))
        except (TypeError, ValueError):
            target_abs_delta = 0.3

        candidate = reader.find_option_by_delta(
            option_type=leg_key,
            target_delta=target_abs_delta,
            tolerance=0.1,
        )
        if not candidate:
            logger.error("Roll failed for %s: no candidate by delta %.4f", name, target_abs_delta)
            return False

        new_symbol = candidate.get("trading_symbol") or candidate.get("symbol")
        if not new_symbol:
            return False
        if cur_symbol and new_symbol == cur_symbol:
            return True

        exchange = ((config or {}).get("basic", {}) or {}).get("exchange", "NFO")
        alert = {
            "execution_type": "ADJUSTMENT",
            "strategy_name": name,
            "exchange": exchange,
            "legs": [
                {
                    "tradingsymbol": cur_symbol,
                    "direction": "BUY" if str(side).upper() == "SELL" else "SELL",
                    "qty": int(qty),
                    "order_type": "MARKET",
                    "price": 0.0,
                    "product_type": "NRML",
                },
                {
                    "tradingsymbol": new_symbol,
                    "direction": str(side).upper(),
                    "qty": int(qty),
                    "order_type": "MARKET",
                    "price": 0.0,
                    "product_type": "NRML",
                },
            ],
        }
        result = svc.bot.process_alert(alert)
        if isinstance(result, dict) and result.get("status") in ("FAILED", "blocked"):
            return False

        setattr(exec_state, f"{prefix}_symbol", new_symbol)
        setattr(exec_state, f"{prefix}_strike", float(candidate.get("strike", 0.0) or 0.0))
        setattr(exec_state, f"{prefix}_qty", int(qty))
        if candidate.get("ltp") is not None:
            setattr(exec_state, f"{prefix}_entry_price", float(candidate.get("ltp") or 0.0))

        try:
            svc.state_mgr.save(exec_state)
        except Exception as e:
            logger.warning("Roll state persist failed for %s: %s", name, e)
        return True


class PerStrategyExecutor:
    """
    Encapsulates the engine components for a single strategy.
    """

    def __init__(self, name: str, config: Dict[str, Any], bot, state_db_path: str):
        self.name = name
        self.config = config
        self.bot = bot

        # State persistence (use name‑based file)
        state_file = Path(state_db_path).parent / f"{name}_state.pkl"
        self.persistence = StatePersistence()
        self.state = self.persistence.load(str(state_file)) or StrategyState()

        # Market reader – db_path not needed, auto-resolves
        identity = config.get("identity", {})
        exchange = identity.get("exchange", "NFO")
        symbol = identity.get("underlying", "NIFTY")
        self.market = MarketReader(exchange, symbol, max_stale_seconds=30)

        # Engines
        self.condition_engine = ConditionEngine(self.state)
        self.entry_engine = EntryEngine(self.state, self.market)
        self.adjustment_engine = AdjustmentEngine(self.state, self.market)
        self.exit_engine = ExitEngine(self.state)
        self.exit_engine.load_config(config.get("exit", {}))
        self.adjustment_engine.load_rules(config.get("adjustment", {}).get("rules", []))
        self.reconciliation = BrokerReconciliation(self.state)

        self.state_file = state_file

        # Daily reset tracking
        self._last_date = datetime.now().date()
        self.cycle_completed = False

    def process_tick(self):
        """Called by the service loop each tick."""
        now = datetime.now()

        # Daily reset
        if self._last_date != now.date():
            self.state.adjustments_today = 0
            self.state.total_trades_today = 0
            self.state.entered_today = False
            self._last_date = now.date()
            logger.info(f"Daily counters reset for {self.name}")

        # Update market data (including leg data)
        self._update_market_data()

        # Check exits first
        exit_action = self.exit_engine.check_exits(now)
        if exit_action and exit_action != "profit_step_adj":
            self._execute_exit(exit_action, source=exit_action)
            return

        # Check entry (if not already entered today)
        if not self.state.entered_today and self._should_enter(now):
            self._execute_entry()

        # Check adjustments
        pre_adjustment_legs = copy.deepcopy(self.state.legs)
        pre_adjustments_today = self.state.adjustments_today
        pre_lifetime_adjustments = self.state.lifetime_adjustments
        pre_last_adjustment_time = self.state.last_adjustment_time
        actions = self.adjustment_engine.check_and_apply(now)
        for action in actions:
            logger.info(f"Adjustment: {action}")
        if actions:
            if not self._dispatch_adjustment_orders(pre_adjustment_legs):
                # Roll back local state if broker rejected adjustment orders.
                self.state.legs = pre_adjustment_legs
                self.state.adjustments_today = pre_adjustments_today
                self.state.lifetime_adjustments = pre_lifetime_adjustments
                self.state.last_adjustment_time = pre_last_adjustment_time
                logger.error(f"Adjustment rollback applied for {self.name}")
            else:
                self.persistence.save(self.state, str(self.state_file))

        # BUG-012 FIX: Run broker reconciliation every 5 minutes to catch drift
        # between strategy state and live broker positions (e.g. manual broker exits,
        # partial fills, session restarts). Previously reconcile() compared state
        # against itself — it never actually contacted the broker.
        if now.second == 0 and now.minute % 5 == 0 and not self._resolve_test_mode():
            try:
                broker_view = getattr(self.bot, "broker_view", None)
                if broker_view is not None:
                    warnings = self.reconciliation.reconcile_from_broker(broker_view)
                    if warnings:
                        logger.warning(f"RECONCILE [{self.name}]: {len(warnings)} mismatch(es) corrected")
            except Exception as e:
                logger.error(f"Broker reconciliation failed for {self.name}: {e}")

        # Persist state periodically (every minute)
        if now.second == 0:
            self.persistence.save(self.state, str(self.state_file))

    def _update_market_data(self):
        """Refresh spot, ATM, and per‑leg data."""
        self.state.spot_price = self.market.get_spot_price()
        self.state.atm_strike = self.market.get_atm_strike()
        self.state.fut_ltp = self.market.get_fut_ltp()
        # Update each active leg
        for leg in self.state.legs.values():
            if not leg.is_active:
                continue
            if leg.instrument == InstrumentType.OPT:
                # For option legs, strike and option_type must be present
                if leg.strike is None or leg.option_type is None:
                    logger.warning(f"Leg {leg.tag} is active but missing strike or option_type")
                    continue
                opt_data = self.market.get_option_at_strike(leg.strike, leg.option_type, leg.expiry)
                if opt_data:
                    leg.ltp = opt_data.get("ltp", leg.ltp)
                    leg.delta = opt_data.get("delta", leg.delta)
                    leg.gamma = opt_data.get("gamma", leg.gamma)
                    leg.theta = opt_data.get("theta", leg.theta)
                    leg.vega = opt_data.get("vega", leg.vega)
                    leg.iv = opt_data.get("iv", leg.iv)
                    leg.oi = opt_data.get("oi", leg.oi)
                    leg.volume = opt_data.get("volume", leg.volume)
            # For futures legs, we could update via a different method, but not implemented here

    def _should_enter(self, now: datetime) -> bool:
        """Check if within entry window."""
        if self.state.entered_today:
            return False
        timing = self.config.get("timing", {})
        entry_start = timing.get("entry_window_start", "09:15")
        entry_end = timing.get("entry_window_end", "14:00")
        try:
            start_t = datetime.strptime(entry_start, "%H:%M").time()
            end_t = datetime.strptime(entry_end, "%H:%M").time()
        except ValueError:
            return False
        if not (start_t <= now.time() <= end_t):
            return False

        # Respect configured trading days from schedule.
        active_days = self.config.get("schedule", {}).get("active_days", [])
        if active_days:
            day_name = now.strftime("%a").lower()[:3]
            if day_name not in [str(d).lower()[:3] for d in active_days]:
                return False
        return True

    def _execute_entry(self):
        """Run entry engine and send orders via bot."""
        symbol = self.config["identity"]["underlying"]
        default_expiry = self.config["schedule"]["expiry_mode"]
        new_legs = self.entry_engine.process_entry(
            self.config["entry"], symbol, default_expiry
        )
        if not new_legs:
            return

        identity = self.config.get("identity", {})
        product_type = identity.get("product_type", "NRML")

        # Convert each LegState to an alert leg. Leg qty is tracked in lots internally;
        # alert payload qty must be broker contract quantity.
        alert_legs = []
        for leg in new_legs:
            payload = self._build_alert_leg(
                leg=leg,
                direction=leg.side.value,
                qty=int(leg.qty),
            )
            payload["product_type"] = product_type
            alert_legs.append(payload)

        alert = {
            "secret_key": self._resolve_webhook_secret(),
            "execution_type": "ENTRY",
            "strategy_name": self.name,
            "exchange": identity.get("exchange", "NFO"),
            "legs": alert_legs,
            "test_mode": self._resolve_test_mode(),
        }

        result = self.bot.process_alert(alert)
        if result.get("status") in ("FAILED", "blocked"):
            logger.error(f"Entry failed: {result}")
            return

        # Update state
        for leg in new_legs:
            self.state.legs[leg.tag] = leg
        self.state.entered_today = True
        self.state.entry_time = datetime.now()
        self.cycle_completed = False
        logger.info(f"Entry executed for {self.name}")

    def _execute_exit(self, action: str, source: str = "unknown"):
        """Execute exit via bot."""
        if action == "combined_conditions":
            action = "exit_all"

        if action.startswith("exit_all"):
            # In paper mode, route through process_alert(EXIT) so mock runs
            # exercise the same alert pipeline (including test_mode handling).
            if self._resolve_test_mode():
                active_legs = [leg for leg in self.state.legs.values() if leg.is_active and int(leg.qty) > 0]
                if active_legs:
                    alert_legs = [
                        self._build_alert_leg(
                            leg=leg,
                            direction="BUY" if leg.side.value == "SELL" else "SELL",
                            qty=int(leg.qty),
                        )
                        for leg in active_legs
                    ]
                    result = self._submit_alert(execution_type="EXIT", legs=alert_legs)
                    status = str((result or {}).get("status", "")).upper()
                    # When broker already has no open qty for a leg, executor should
                    # treat that as effectively closed to avoid infinite exit retries.
                    if status in ("FAILED", "BLOCKED") and not self._is_no_position_exit_result(result):
                        logger.error(f"Exit rejected for {self.name}: {result}")
                        return
            else:
                self.bot.request_exit(
                    scope="strategy",
                    strategy_name=self.name,
                    product_type="ALL",
                    reason=source,
                    source="STRATEGY_EXECUTOR"
                )
            # Mark all legs inactive
            for leg in self.state.legs.values():
                leg.is_active = False
            self.state.cumulative_daily_pnl += self.state.combined_pnl
            # Re‑entry only allowed if source is stop_loss and config says so
            if source == "stop_loss":
                sl_cfg = self.config.get("exit", {}).get("stop_loss", {})
                if sl_cfg.get("allow_reentry"):
                    self.state.entered_today = False
                else:
                    self.state.entered_today = True
            else:
                self.state.entered_today = True
                self.cycle_completed = True
            logger.info(f"Exit executed for {self.name}")
        elif action.startswith("leg_rule_"):
            self._execute_leg_rule_exit(action)
        elif action == "partial_50":
            # Close 50% of each leg (simplified)
            for leg in self.state.legs.values():
                if leg.is_active:
                    leg.qty = leg.qty // 2
            logger.info(f"Partial 50% exit for {self.name}")

    @staticmethod
    def _is_no_position_exit_result(result: Dict[str, Any]) -> bool:
        """Return True when all failed exits are benign 'no position' outcomes."""
        if not isinstance(result, dict):
            return False
        legs = result.get("legs")
        if not isinstance(legs, list) or not legs:
            return False
        saw_failed = False
        for leg in legs:
            if not isinstance(leg, dict):
                return False
            leg_status = str(leg.get("status", "")).upper()
            if leg_status not in ("FAILED", "BLOCKED"):
                continue
            saw_failed = True
            msg = str(leg.get("message", "") or "").upper()
            if "NO POSITION" not in msg and "POSITION NOT FOUND" not in msg:
                return False
        return saw_failed

    def _execute_leg_rule_exit(self, action: str):
        """Execute per-leg exit actions configured in exit.leg_rules."""
        rule = self.exit_engine.last_triggered_leg_rule or {}
        rule_action = str(rule.get("action") or action.replace("leg_rule_", "")).strip().lower()
        targets = self._resolve_leg_rule_targets(rule)
        if not targets:
            logger.warning(f"Leg-rule exit had no active targets: {self.name} action={rule_action}")
            return

        if rule_action == "close_all":
            self._execute_exit("exit_all", source="leg_rule_close_all")
            return

        close_qty_map: Dict[str, int] = {}
        if rule_action == "close_leg":
            close_qty_map = {leg.tag: int(leg.qty) for leg in targets}
        elif rule_action == "reduce_50pct":
            close_qty_map = {leg.tag: max(0, int(leg.qty // 2)) for leg in targets}
        elif rule_action == "partial_lots":
            lots = int(rule.get("lots") or rule.get("qty") or 1)
            close_qty_map = {leg.tag: max(0, min(int(leg.qty), lots)) for leg in targets}
        elif rule_action == "roll_next":
            # Roll selected legs to next expiry at same strike/side.
            alert_legs: List[Dict[str, Any]] = []
            updates: List[Tuple[LegState, str, float, float, str]] = []
            for leg in targets:
                if leg.qty <= 0:
                    continue
                close_payload = self._build_alert_leg(
                    leg=leg,
                    direction="BUY" if leg.side.value == "SELL" else "SELL",
                    qty=int(leg.qty),
                )
                alert_legs.append(close_payload)

                if leg.option_type is None or leg.strike is None:
                    continue
                try:
                    new_expiry = self.market.get_next_expiry(leg.expiry, "weekly_next")
                    opt_data = self.market.get_option_at_strike(leg.strike, leg.option_type, new_expiry) or {}
                except Exception as e:
                    logger.error(f"Roll-next lookup failed for {leg.tag}: {e}")
                    continue

                open_payload = self._build_alert_leg(
                    leg=leg,
                    direction=leg.side.value,
                    qty=int(leg.qty),
                    tradingsymbol_override=(
                        opt_data.get("trading_symbol")
                        or opt_data.get("tsym")
                        or opt_data.get("symbol")
                        or leg.trading_symbol
                        or leg.symbol
                    ),
                    price_override=float(opt_data.get("ltp", leg.ltp) or leg.ltp),
                )
                alert_legs.append(open_payload)

                updates.append((
                    leg,
                    new_expiry,
                    float(opt_data.get("ltp", leg.entry_price) or leg.entry_price),
                    float(opt_data.get("ltp", leg.ltp) or leg.ltp),
                    str(open_payload.get("tradingsymbol") or leg.trading_symbol),
                ))

            if alert_legs:
                result = self._submit_alert(execution_type="ADJUSTMENT", legs=alert_legs)
                if str((result or {}).get("status", "")).upper() not in ("FAILED", "BLOCKED"):
                    for leg, new_expiry, new_entry, new_ltp, tsym in updates:
                        leg.expiry = new_expiry
                        leg.entry_price = new_entry
                        leg.ltp = new_ltp
                        if tsym:
                            leg.trading_symbol = tsym
            return
        else:
            logger.warning(f"Unsupported leg rule action '{rule_action}' in strategy {self.name}")
            return

        alert_legs = []
        reductions: List[Tuple[LegState, int]] = []
        for leg in targets:
            qty = int(close_qty_map.get(leg.tag, 0))
            if qty <= 0:
                continue
            alert_legs.append(
                self._build_alert_leg(
                    leg=leg,
                    direction="BUY" if leg.side.value == "SELL" else "SELL",
                    qty=qty,
                )
            )
            reductions.append((leg, qty))

        if alert_legs:
            result = self._submit_alert(execution_type="EXIT", legs=alert_legs)
            if str((result or {}).get("status", "")).upper() not in ("FAILED", "BLOCKED"):
                for leg, qty in reductions:
                    leg.qty = max(0, int(leg.qty) - qty)
                    if leg.qty == 0:
                        leg.is_active = False

    def _resolve_leg_rule_targets(self, rule: Dict[str, Any]) -> List[LegState]:
        ref = rule.get("exit_leg_ref", "all")
        group = rule.get("group")
        if ref == "all":
            return [leg for leg in self.state.legs.values() if leg.is_active]
        if ref == "group" and group:
            return [leg for leg in self.state.legs.values() if leg.is_active and leg.group == group]
        leg = self.state.legs.get(ref)
        if leg and leg.is_active:
            return [leg]
        return []

    def _dispatch_adjustment_orders(self, before_legs: Dict[str, LegState]) -> bool:
        """
        Translate state transitions from adjustment engine into broker orders.
        Returns False when broker rejects the adjustment payload.
        """
        tags = sorted(set(before_legs.keys()) | set(self.state.legs.keys()))
        legs_payload: List[Dict[str, Any]] = []

        for tag in tags:
            before = before_legs.get(tag)
            after = self.state.legs.get(tag)
            before_qty = int(before.qty) if (before and before.is_active) else 0
            after_qty = int(after.qty) if (after and after.is_active) else 0
            delta = after_qty - before_qty

            if delta < 0:
                ref = before or after
                if ref is None:
                    continue
                legs_payload.append(
                    self._build_alert_leg(
                        leg=ref,
                        direction="BUY" if ref.side.value == "SELL" else "SELL",
                        qty=abs(delta),
                    )
                )
            elif delta > 0:
                if after is None:
                    continue
                legs_payload.append(
                    self._build_alert_leg(
                        leg=after,
                        direction=after.side.value,
                        qty=delta,
                    )
                )

        if not legs_payload:
            return True
        result = self._submit_alert(execution_type="ADJUSTMENT", legs=legs_payload)
        status = str((result or {}).get("status", "")).upper()
        return status not in ("FAILED", "BLOCKED")

    def _build_alert_leg(
        self,
        leg: LegState,
        direction: str,
        qty: int,
        tradingsymbol_override: Optional[str] = None,
        price_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        identity = self.config.get("identity", {})
        default_order_type = str(identity.get("order_type", "MARKET")).upper()
        order_type = "LIMIT" if default_order_type == "LIMIT" else "MARKET"
        if price_override is not None:
            price = float(price_override)
        else:
            price = float(leg.ltp) if order_type == "LIMIT" else 0.0

        tradingsymbol = tradingsymbol_override or leg.trading_symbol or leg.symbol
        if tradingsymbol == leg.symbol and leg.instrument == InstrumentType.OPT and leg.strike is not None and leg.option_type is not None:
            try:
                opt_data = self.market.get_option_at_strike(leg.strike, leg.option_type, leg.expiry) or {}
                resolved = opt_data.get("trading_symbol") or opt_data.get("tsym") or opt_data.get("symbol")
                if resolved:
                    tradingsymbol = str(resolved)
                    leg.trading_symbol = tradingsymbol
            except Exception:
                pass

        return {
            "tradingsymbol": tradingsymbol,
            "direction": str(direction).upper(),
            "qty": self._lots_to_order_qty(int(qty), leg),
            "order_type": order_type,
            "price": price,
            "product_type": identity.get("product_type", "NRML"),
        }

    def _lots_to_order_qty(self, lots: int, leg: Optional[LegState] = None) -> int:
        """
        Convert lots (internal state unit) to broker order quantity (contract units).
        """
        try:
            normalized_lots = max(0, int(lots))
        except (TypeError, ValueError):
            normalized_lots = 0
        if normalized_lots == 0:
            return 0

        lot_size = 1
        expiry = getattr(leg, "expiry", None) if leg is not None else None
        try:
            resolved = int(self.market.get_lot_size(expiry))
            if resolved > 0:
                lot_size = resolved
        except Exception:
            lot_size = 1
        return normalized_lots * lot_size

    def _submit_alert(self, execution_type: str, legs: List[Dict[str, Any]]) -> Dict[str, Any]:
        identity = self.config.get("identity", {})
        alert = {
            "secret_key": self._resolve_webhook_secret(),
            "execution_type": execution_type,
            "strategy_name": self.name,
            "exchange": identity.get("exchange", "NFO"),
            "legs": legs,
            "test_mode": self._resolve_test_mode(),
        }
        result = self.bot.process_alert(alert)
        if isinstance(result, dict) and str(result.get("status", "")).upper() in ("FAILED", "BLOCKED"):
            logger.error(f"{execution_type} order rejected for {self.name}: {result}")
        return result if isinstance(result, dict) else {}

    def _resolve_webhook_secret(self) -> str:
        """Get webhook secret from bot config or env."""
        bot_cfg = getattr(self.bot, "config", None)
        if bot_cfg and hasattr(bot_cfg, "webhook_secret"):
            return str(bot_cfg.webhook_secret)
        import os
        return os.getenv("WEBHOOK_SECRET_KEY", os.getenv("WEBHOOK_SECRET", ""))

    def _resolve_test_mode(self) -> Optional[str]:
        """Return test_mode if paper mode is enabled."""
        if self.config.get("paper_mode"):
            return "SUCCESS"
        identity = self.config.get("identity", {})
        if identity.get("paper_mode"):
            return "SUCCESS"
        return None
