import time
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from .state import StrategyState, LegState
from .models import Side, InstrumentType
from .market_reader import MarketReader
from .condition_engine import ConditionEngine
from .entry_engine import EntryEngine
from .adjustment_engine import AdjustmentEngine
from .exit_engine import ExitEngine
from .reconciliation import BrokerReconciliation
from .persistence import StatePersistence

logger = logging.getLogger(__name__)

class StrategyExecutor:
    def __init__(self, config_path: str, state_path: Optional[str] = None):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.state_path = state_path or "state.pkl"
        self.state = self._load_or_create_state()

        # Initialize market reader
        identity = self.config["identity"]
        self.market = MarketReader(
            exchange=identity["exchange"],
            symbol=identity["underlying"],
            max_stale_seconds=30
        )

        # Initialize engines
        self.condition_engine = ConditionEngine(self.state)
        self.entry_engine = EntryEngine(self.state, self.market)
        self.adjustment_engine = AdjustmentEngine(self.state, self.market)
        self.exit_engine = ExitEngine(self.state)
        self.reconciliation = BrokerReconciliation(self.state)

        # Load rules
        self.adjustment_engine.load_rules(self.config.get("adjustment", {}).get("rules", []))
        self.exit_engine.load_config(self.config.get("exit", {}))

    def _load_or_create_state(self) -> StrategyState:
        state = StatePersistence.load(self.state_path)
        if state is None:
            state = StrategyState()
        return state

    def run(self, interval_sec: int = 1):
        logger.info("Starting strategy executor...")
        while True:
            try:
                self._tick()
                time.sleep(interval_sec)
            except KeyboardInterrupt:
                logger.info("Stopping...")
                self._save_state()
                break

    def _tick(self):
        now = datetime.now()
        self.state.current_time = now

        # Daily reset
        if self.state.last_date is None or self.state.last_date != now.date():
            self.state.adjustments_today = 0
            self.state.total_trades_today = 0
            self.state.entered_today = False
            self.state.last_date = now.date()
            logger.info("Daily counters reset")

        # Update market data (including per‑leg data)
        self._update_market_data()

        # Compute minutes to exit
        exit_time_str = self.config.get("exit", {}).get("time", {}).get("strategy_exit_time")
        if exit_time_str:
            try:
                exit_t = datetime.strptime(exit_time_str, "%H:%M").time()
                exit_dt = datetime.combine(now.date(), exit_t)
                if now > exit_dt:
                    self.state.minutes_to_exit = 0
                else:
                    delta = exit_dt - now
                    self.state.minutes_to_exit = int(delta.total_seconds() / 60)
            except:
                self.state.minutes_to_exit = 0
        else:
            self.state.minutes_to_exit = 0

        # Reconciliation with broker (simulate)
        broker_positions = self._fetch_broker_positions()
        warnings = self.reconciliation.reconcile(broker_positions)
        for w in warnings:
            logger.warning(f"Reconciliation warning: {w}")

        # Check exits first
        exit_action = self.exit_engine.check_exits(now)
        if exit_action:
            logger.info(f"Exit triggered: {exit_action}")
            self._execute_exit(exit_action)
            return

        # Check if we should enter today
        if self._should_enter(now):
            self._execute_entry()

        # Check adjustments
        actions = self.adjustment_engine.check_and_apply(now)
        for a in actions:
            logger.info(f"Adjustment: {a}")

        # Save state periodically (every minute)
        if now.second == 0:
            self._save_state()

    def _update_market_data(self):
        """Update spot, ATM, futures and per‑leg LTP & greeks."""
        self.state.spot_price = self.market.get_spot_price()
        self.state.atm_strike = self.market.get_atm_strike()
        self.state.fut_ltp = self.market.get_fut_ltp()

        # Update each active leg
        for leg in self.state.legs.values():
            if not leg.is_active:
                continue
            if leg.instrument == InstrumentType.OPT and leg.strike is not None:
                # Option leg – option_type cannot be None here
                assert leg.option_type is not None, f"Option leg {leg.tag} missing option_type"
                try:
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
                except Exception as e:
                    logger.debug(f"Could not update leg {leg.tag}: {e}")
            # For futures legs, we might need a separate update – currently not implemented

        # Optionally update index_data (e.g., from external feed)
        # This is left to subclasses or a separate method

    def _fetch_broker_positions(self) -> list:
        # Placeholder - would call broker API
        # For simulation, we return current legs as positions
        positions = []
        for leg in self.state.legs.values():
            if leg.is_active:
                positions.append({
                    "tag": leg.tag,
                    "symbol": leg.symbol,
                    "instrument": leg.instrument.value,
                    "option_type": leg.option_type.value if leg.option_type else None,
                    "strike": leg.strike,
                    "expiry": leg.expiry,
                    "side": leg.side.value,
                    "qty": leg.qty,
                    "ltp": leg.ltp,
                    "delta": leg.delta
                })
        return positions

    def _should_enter(self, now: datetime) -> bool:
        if self.state.entered_today:
            return False
        # Check schedule
        entry_start = self.config["timing"]["entry_window_start"]
        entry_end = self.config["timing"]["entry_window_end"]
        try:
            start_t = datetime.strptime(entry_start, "%H:%M").time()
            end_t = datetime.strptime(entry_end, "%H:%M").time()
        except:
            return False
        if start_t <= now.time() <= end_t:
            # Also check active days
            day_name = now.strftime("%a").lower()[:3]
            active_days = self.config["schedule"]["active_days"]
            if day_name in active_days:
                return True
        return False

    def _execute_entry(self):
        logger.info("Executing entry...")
        symbol = self.config["identity"]["underlying"]
        default_expiry = self.config["schedule"]["expiry_mode"]
        new_legs = self.entry_engine.process_entry(
            self.config["entry"], symbol, default_expiry
        )
        for leg in new_legs:
            self.state.legs[leg.tag] = leg
        self.state.entered_today = True
        self.state.entry_time = datetime.now()
        logger.info(f"Entered {len(new_legs)} legs")

    def _execute_exit(self, action: str):
        if action.startswith("exit_all"):
            for leg in self.state.legs.values():
                leg.is_active = False
            self.state.cumulative_daily_pnl += self.state.combined_pnl
            # Check if re-entry allowed (from stop loss config)
            sl_cfg = self.exit_engine.exit_config.get("stop_loss", {})
            if sl_cfg.get("allow_reentry"):
                self.state.entered_today = False
            else:
                self.state.entered_today = True  # prevent re-entry
        elif action.startswith("partial_"):
            # Handle partial exits (simplified) - could update state if needed
            logger.info(f"Partial exit triggered: {action}")
            # Actual execution with broker should be overridden in subclass
        # other actions can be added

    def _save_state(self):
        StatePersistence.save(self.state, self.state_path)
        logger.info(f"State saved to {self.state_path}")