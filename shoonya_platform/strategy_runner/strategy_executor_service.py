#!/usr/bin/env python3
"""
strategy_executor_service.py — Drop‑in replacement using Universal Engine
==========================================================================
Implements the same interface as the old service, but uses the new engine.
"""

import json
import logging
import threading
import time
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

class StrategyExecutorService:
    """
    Service that manages multiple strategies using the Universal Engine.
    Compatible with the old interface expected by ShoonyaBot.
    """

    def __init__(self, bot, state_db_path: str):
        self.bot = bot
        self.state_db_path = state_db_path
        self._strategies: Dict[str, Dict] = {}          # name -> config
        self._executors: Dict[str, 'PerStrategyExecutor'] = {}
        self._engine_states: Dict[str, StrategyState] = {}  # name -> live state
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._mode_change_dict_lock = threading.Lock()
        self._mode_change_lock: Dict[str, threading.Lock] = {}

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
            self._engine_states[name] = executor.state
            logger.info(f"Registered strategy: {name}")

    def unregister_strategy(self, name: str):
        """Remove a strategy from the service."""
        with self._lock:
            self._executors.pop(name, None)
            self._strategies.pop(name, None)
            self._engine_states.pop(name, None)
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
            for name in names:
                executor = self._executors.get(name)
                if executor:
                    try:
                        executor.process_tick()
                    except Exception as e:
                        logger.exception(f"Error processing strategy {name}: {e}")
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
        state = self._engine_states.get(strategy_name)
        if not state:
            return False
        return state.any_leg_active


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
        if exit_action:
            self._execute_exit(exit_action, source=exit_action)
            return

        # Check entry (if not already entered today)
        if not self.state.entered_today and self._should_enter(now):
            self._execute_entry()

        # Check adjustments
        actions = self.adjustment_engine.check_and_apply(now)
        for action in actions:
            logger.info(f"Adjustment: {action}")

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
        except:
            return False
        return start_t <= now.time() <= end_t

    def _execute_entry(self):
        """Run entry engine and send orders via bot."""
        symbol = self.config["identity"]["underlying"]
        default_expiry = self.config["schedule"]["expiry_mode"]
        new_legs = self.entry_engine.process_entry(
            self.config["entry"], symbol, default_expiry
        )
        if not new_legs:
            return

        # Get default order type from identity
        identity = self.config.get("identity", {})
        default_order_type = identity.get("order_type", "MARKET")
        product_type = identity.get("product_type", "NRML")

        # Convert each LegState to an alert leg
        alert_legs = []
        for leg in new_legs:
            # Determine order type and price
            if default_order_type == "LIMIT":
                price = leg.ltp  # use current LTP as limit price
                order_type = "LIMIT"
            else:
                price = 0.0
                order_type = "MARKET"

            alert_legs.append({
                "tradingsymbol": leg.symbol,
                "direction": leg.side.value,
                "qty": leg.qty,
                "order_type": order_type,
                "price": price,
                "product_type": product_type,
            })

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
        logger.info(f"Entry executed for {self.name}")

    def _execute_exit(self, action: str, source: str = "unknown"):
        """Execute exit via bot."""
        if action.startswith("exit_all"):
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
            logger.info(f"Exit executed for {self.name}")
        elif action == "partial_50":
            # Close 50% of each leg (simplified)
            for leg in self.state.legs.values():
                if leg.is_active:
                    leg.qty = leg.qty // 2
            logger.info(f"Partial 50% exit for {self.name}")

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