import time
import json
import logging
import re
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

_DB_FILE_EXPIRY_RE = re.compile(
    r"^[A-Za-z0-9]+_[A-Za-z0-9]+_(\d{2}-[A-Za-z]{3}-\d{4})\.sqlite$"
)

class StrategyExecutor:
    def __init__(self, config_path: str, state_path: Optional[str] = None):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.state_path = state_path or "state.json"  # ✅ BUG-006: JSON instead of pkl
        self.state = self._load_or_create_state()

        # Initialize market reader
        identity = self.config["identity"]
        self.market = MarketReader(
            exchange=identity["exchange"],
            symbol=identity["underlying"],
            max_stale_seconds=30
        )
        self._fixed_expiry_date = self._extract_expiry_from_db_file()
        self._cycle_expiry_date = self._resolve_cycle_expiry()

        # Initialize engines
        self.condition_engine = ConditionEngine(self.state)
        self.entry_engine = EntryEngine(self.state, self.market)
        self.adjustment_engine = AdjustmentEngine(self.state, self.market)
        self.exit_engine = ExitEngine(self.state)
        self.reconciliation = BrokerReconciliation(
            self.state,
            lot_size_resolver=self.market.get_lot_size,
        )

        # Load rules
        self.adjustment_engine.load_rules(self.config.get("adjustment", {}).get("rules", []))
        self.exit_engine.load_config(self.config.get("exit", {}))

    def _extract_expiry_from_db_file(self) -> Optional[str]:
        identity = self.config.get("identity", {}) or {}
        market_data = self.config.get("market_data", {}) or {}
        db_file = str(identity.get("db_file") or market_data.get("db_file") or "").strip()
        if not db_file:
            return None
        match = _DB_FILE_EXPIRY_RE.match(db_file)
        if not match:
            logger.warning(
                "Could not parse expiry from db_file '%s'; falling back to schedule.expiry_mode",
                db_file,
            )
            return None
        return match.group(1)

    def _resolve_cycle_expiry(self) -> str:
        schedule_mode = str(
            (self.config.get("schedule", {}) or {}).get("expiry_mode", "weekly_current")
        ).strip() or "weekly_current"
        if schedule_mode == "custom":
            if self._fixed_expiry_date:
                logger.info(
                    "Using custom db_file expiry: %s",
                    self._fixed_expiry_date,
                )
                return self._fixed_expiry_date
            logger.warning(
                "schedule.expiry_mode=custom but db_file expiry is missing/invalid; falling back to weekly_current"
            )
            schedule_mode = "weekly_current"

        try:
            resolved = self.market.resolve_expiry_mode(schedule_mode)
            logger.info(
                "Resolved cycle expiry: %s (mode=%s)",
                resolved,
                schedule_mode,
            )
            if self._fixed_expiry_date and schedule_mode != "custom":
                logger.info(
                    "Ignoring db_file expiry because mode=%s is dynamic (db_file=%s)",
                    schedule_mode,
                    self._fixed_expiry_date,
                )
            return resolved
        except Exception as e:
            logger.error(
                "Failed to resolve cycle expiry with mode=%s: %s; using weekly_current",
                schedule_mode,
                e,
            )
            return self.market.resolve_expiry_mode("weekly_current")

    def _load_or_create_state(self) -> StrategyState:
        state = StatePersistence.load(self.state_path)
        if state is None:
            state = StrategyState()
        return state

    def run(self, interval_sec: int = 1):
        logger.info("Starting strategy executor...")
        _backoff = 1  # seconds; reset on successful tick
        while True:
            try:
                self._tick()
                time.sleep(interval_sec)
                _backoff = 1  # reset after clean tick
            except KeyboardInterrupt:
                logger.info("Stopping...")
                self._save_state()
                break
            except Exception as e:
                # ✅ BUG-007 FIX: Fatal exceptions must NOT crash the run loop.
                # Log, save state, then back off before retrying.
                logger.exception(f"Tick error (backing off {_backoff}s): {e}")
                try:
                    self._save_state()
                except Exception:
                    pass
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, 60)  # cap at 60s backoff

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
            except Exception:
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
        if exit_action and exit_action != "profit_step_adj":
            logger.info(f"Exit triggered: {exit_action}")
            self._execute_exit(exit_action)
            self._save_state()  # Save immediately on significant event
            return

        # Check if we should enter today
        if self._should_enter(now):
            self._execute_entry()
            self._save_state()  # ✅ BUG-022 FIX: Save immediately after entry

        # Check adjustments
        actions = self.adjustment_engine.check_and_apply(now)
        for a in actions:
            logger.info(f"Adjustment: {a}")
        if actions:
            self._save_state()  # ✅ BUG-022 FIX: Save immediately after any adjustment

        # Periodic save (every minute) as a safety net
        if now.second == 0:
            self._save_state()

    def _update_market_data(self):
        """Update spot, ATM, futures and per‑leg LTP & greeks."""
        self.state.current_time = datetime.now()
        self.state.spot_price = self.market.get_spot_price(self._cycle_expiry_date)
        if not self.state.spot_open and self.state.spot_price:
            self.state.spot_open = self.state.spot_price
        self.state.atm_strike = self.market.get_atm_strike(self._cycle_expiry_date)
        self.state.fut_ltp = self.market.get_fut_ltp(self._cycle_expiry_date)
        chain_metrics = self.market.get_chain_metrics(self._cycle_expiry_date)
        self.state.pcr = float(chain_metrics.get("pcr", 0.0) or 0.0)
        self.state.pcr_volume = float(chain_metrics.get("pcr_volume", 0.0) or 0.0)
        self.state.max_pain_strike = float(chain_metrics.get("max_pain_strike", 0.0) or 0.0)
        self.state.total_oi_ce = float(chain_metrics.get("total_oi_ce", 0.0) or 0.0)
        self.state.total_oi_pe = float(chain_metrics.get("total_oi_pe", 0.0) or 0.0)
        self.state.oi_buildup_ce = float(chain_metrics.get("oi_buildup_ce", 0.0) or 0.0)
        self.state.oi_buildup_pe = float(chain_metrics.get("oi_buildup_pe", 0.0) or 0.0)

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
        # ✅ BUG-008 FIX: Use .get() with safe defaults — hard key access raises KeyError if config section absent
        timing = self.config.get("timing", {})
        entry_start = timing.get("entry_window_start", "09:15")
        entry_end = timing.get("entry_window_end", "15:00")
        try:
            start_t = datetime.strptime(entry_start, "%H:%M").time()
            end_t = datetime.strptime(entry_end, "%H:%M").time()
        except Exception:
            return False
        if start_t <= now.time() <= end_t:
            # Also check active days
            day_name = now.strftime("%a").lower()[:3]
            active_days = self.config.get("schedule", {}).get("active_days", [])
            if day_name in active_days:
                return True
        return False

    def _execute_entry(self):
        logger.info("Executing entry...")
        symbol = self.config["identity"]["underlying"]
        default_expiry = self._cycle_expiry_date
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

