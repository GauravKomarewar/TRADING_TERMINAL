#!/usr/bin/env python3
"""
runner.py — Fresh Strategy Runner
====================================

Self-contained strategy runner that:
1. Loads & validates a v3.0 JSON strategy config
2. Reads live option chain data from SQLite databases
3. Evaluates conditions (entry / adjustment / exit / risk)
4. Sends alerts to process_alert() on the global TradingBot — no direct execution

Usage:
    from shoonya_platform.fresh_strategy.runner import FreshStrategyRunner
    runner = FreshStrategyRunner("path/to/strategy.json")
    runner.start()   # Blocking loop
    runner.stop()    # From another thread / signal handler
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Internal imports — all inside fresh_strategy package
from shoonya_platform.fresh_strategy.config_schema import (
    LOT_SIZES,
    coerce_config_numerics,
    validate_config,
    validate_config_file,
)
from shoonya_platform.fresh_strategy.condition_engine import (
    RuleResult,
    StrategyState,
    evaluate_adjustment_rules,
    evaluate_entry_rules,
    evaluate_exit_rules,
    evaluate_risk_management,
    evaluate_trailing_stop,
)
from shoonya_platform.fresh_strategy.market_reader import MarketReader

logger = logging.getLogger("fresh_strategy.runner")


class FreshStrategyRunner:
    """
    Main strategy runner. Reads config, polls market data, evaluates rules,
    sends alerts to the OMS via process_alert().
    """

    def __init__(self, config_path: str, test_mode: bool = False):
        """
        Args:
            config_path: Path to v3.0 JSON strategy config file
            test_mode: If True, adds test_mode flag to alerts (no real orders)
        """
        self.config_path = config_path
        self.test_mode = test_mode

        # ─── Loaded config ──────────────────────────────────────────────
        self.config: Dict[str, Any] = {}
        self.strategy_name: str = ""
        self.exchange: str = ""
        self.symbol: str = ""
        self.lots: int = 1
        self.lot_size: int = 1

        # ─── Components ─────────────────────────────────────────────────
        self.reader: Optional[MarketReader] = None
        self.state: StrategyState = StrategyState()

        # ─── Control ────────────────────────────────────────────────────
        self._stop_event = threading.Event()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # ─── Timing ─────────────────────────────────────────────────────
        self._poll_interval: float = 5.0  # seconds between ticks
        self._last_adjustment_time: float = 0.0  # timestamp of last adjustment
        self._tick_count: int = 0  # total ticks processed
    # ─── Lifecycle ────────────────────────────────────────────────────────

    def load_config(self) -> bool:
        """Load and validate the JSON config."""
        try:
            valid, errors, loaded_cfg = validate_config_file(self.config_path)
            real_errors = [e for e in errors if e.severity == "error"]
            warnings = [e for e in errors if e.severity == "warning"]

            for w in warnings:
                logger.warning(f"Config warning [{w.path}]: {w.message}")

            if real_errors:
                for e in real_errors:
                    logger.error(f"Config error [{e.path}]: {e.message}")
                return False

            with open(self.config_path, "r") as f:
                self.config = json.load(f)

            # Coerce all numeric values to float (except qty/lots/priority)
            self.config = coerce_config_numerics(self.config)

            # Extract basics
            basic = self.config.get("basic", {})
            self.strategy_name = self.config.get("name", "unnamed_strategy")
            self.exchange = basic.get("exchange", "NFO").upper()
            self.symbol = basic.get("underlying", "NIFTY").upper()
            self.lots = basic.get("lots", 1)
            self.lot_size = LOT_SIZES.get(self.symbol, 1)

            # Poll interval from adjustment config (if specified)
            adj = self.config.get("adjustment", {})
            check_min = adj.get("check_interval_min", 0)
            if check_min and check_min > 0:
                self._poll_interval = check_min * 60
            else:
                self._poll_interval = 5.0  # Default 5s

            logger.info(
                f"Config loaded: {self.strategy_name} | "
                f"{self.exchange}:{self.symbol} | "
                f"{self.lots} lots × {self.lot_size} = {self.lots * self.lot_size} qty | "
                f"poll={self._poll_interval}s"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False

    def setup_reader(self) -> bool:
        """Initialize the market data reader."""
        # Use explicit db_path from config if provided
        db_path = self.config.get("market_data", {}).get("db_path")
        self.reader = MarketReader(self.exchange, self.symbol, db_path=db_path)

        if not self.reader.connect():
            logger.error("Failed to connect to market DB")
            return False

        # Quick sanity check
        meta = self.reader.get_meta()
        if not meta:
            logger.error("No meta data in DB — is option chain supervisor running?")
            return False

        spot = self.reader.get_spot_price()
        atm = self.reader.get_atm_strike()
        logger.info(f"Market data OK: spot={spot}, ATM={atm}, meta keys={list(meta.keys())}")
        return True

    def start(self):
        """Start the strategy runner (blocking)."""
        if not self.load_config():
            logger.error("Config load failed — aborting")
            return

        if not self.config.get("basic", {}).get("enabled", True):
            logger.info(f"Strategy '{self.strategy_name}' is disabled — skipping")
            return

        if not self.setup_reader():
            logger.error("Market reader setup failed — aborting")
            return

        self._running = True
        self._stop_event.clear()

        logger.info(f"▶ Strategy '{self.strategy_name}' started")

        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt — stopping")
        except Exception as e:
            logger.error(f"Runner crashed: {e}", exc_info=True)
        finally:
            self.stop()

    def start_async(self):
        """Start the runner in a background thread."""
        self._thread = threading.Thread(
            target=self.start,
            daemon=True,
            name=f"FreshStrategy-{self.strategy_name}",
        )
        self._thread.start()
        return self._thread

    def stop(self):
        """Stop the runner gracefully."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        if self.reader:
            self.reader.close()

        logger.info(f"■ Strategy '{self.strategy_name}' stopped")

    # ─── Main Loop ────────────────────────────────────────────────────────

    def _run_loop(self):
        """Main tick loop."""
        timing = self.config.get("timing", {})
        entry_time_str = timing.get("entry_time", "09:15")
        exit_time_str = timing.get("exit_time", "15:30")

        entry_minutes = self._parse_time_minutes(entry_time_str)
        exit_minutes = self._parse_time_minutes(exit_time_str)

        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                now_minutes = now.hour * 60 + now.minute

                # Before entry time — wait
                if now_minutes < entry_minutes:
                    wait_s = (entry_minutes - now_minutes) * 60 - now.second
                    if wait_s > 0:
                        logger.debug(f"Waiting for entry time ({entry_time_str})… {wait_s}s")
                        self._stop_event.wait(min(wait_s, 30))
                    continue

                # After exit time — force exit if position held, then stop
                if now_minutes >= exit_minutes:
                    if self.state.has_position:
                        logger.info("Exit time reached — closing all positions")
                        self._send_exit_alert("time_exit")
                    logger.info("Past exit time — stopping runner for today")
                    break

                # ─── Tick logic ──────────────────────────────────────────
                self._tick()

            except Exception as e:
                logger.error(f"Tick error: {e}", exc_info=True)

            # Wait for next poll
            self._stop_event.wait(self._poll_interval)

    def _tick(self):
        """Single evaluation tick."""
        assert self.reader is not None
        self._tick_count += 1

        # 1. Update market data into state
        if not self._update_state():
            logger.warning("Market data update failed — skipping tick")
            return

        # 2. Check data freshness (skip if snapshot_ts not in meta)
        age = self.reader.get_snapshot_age_seconds()
        if age < 90000 and age > 120:  # Stale data > 2 min (90000 = no timestamp)
            logger.warning(f"Market snapshot is {age:.0f}s old — may be stale")

        # Periodic state summary (every 60 ticks)
        if self._tick_count % 60 == 0:
            self._log_state_summary()

        # 3. Risk management check (overrides everything)
        risk_result = evaluate_risk_management(self.config, self.state)
        if risk_result and risk_result.triggered:
            logger.warning(f"RISK LIMIT: {risk_result.rule_name}")
            if risk_result.action.get("type") == "close_all_positions" and self.state.has_position:
                self._send_exit_alert(f"risk_{risk_result.rule_name}")
            return  # Don't evaluate further

        # 4. Route based on position state
        if not self.state.has_position:
            self._evaluate_entry()
        else:
            # 4a. Trailing stop check (before regular exit/adjustment)
            if self.state.trailing_stop_active:
                ts_result = evaluate_trailing_stop(self.state)
                if ts_result and ts_result.triggered:
                    logger.warning(
                        f"TRAILING STOP HIT: PnL=₹{self.state.combined_pnl:.0f} "
                        f"<= stop=₹{self.state.trailing_stop_level:.0f}"
                    )
                    self._send_exit_alert("trailing_stop")
                    return

            self._evaluate_exit()
            if self.state.has_position:  # Not exited
                self._evaluate_adjustments()

            # Update peak P&L for trailing stop
            if self.state.combined_pnl > self.state.peak_pnl:
                self.state.peak_pnl = self.state.combined_pnl

    # ─── State Update ─────────────────────────────────────────────────────

    def _update_state(self) -> bool:
        """Read live market data and update strategy state."""
        if not self.reader:
            return False

        meta = self.reader.get_meta()
        if not meta:
            return False

        # Spot / market info
        try:
            self.state.spot_price = float(meta.get("spot_ltp", 0))
            self.state.fut_ltp = float(meta.get("fut_ltp", 0))

            # ATM may be missing in some DB versions — derive from spot
            atm_raw = meta.get("atm", 0)
            if atm_raw:
                self.state.atm_strike = float(atm_raw)
            elif self.state.spot_price > 0:
                # Derive ATM from spot (round to nearest 50 for NIFTY, 100 for BANKNIFTY)
                step = 100.0 if self.symbol == "BANKNIFTY" else 50.0
                self.state.atm_strike = round(self.state.spot_price / step) * step
        except (ValueError, TypeError):
            pass

        # Capture opening spot once (for spot_change / spot_change_pct)
        if self.state.spot_open == 0.0 and self.state.spot_price > 0:
            self.state.spot_open = self.state.spot_price
            logger.info(f"Spot open captured: {self.state.spot_open}")

        # If we have positions, update live greeks/prices for our legs
        if self.state.has_position:
            self._update_leg_data()

        return True

    def _update_leg_data(self):
        """Update live data for held positions from the option chain."""
        if not self.reader:
            return

        # CE leg
        if self.state.ce_strike > 0:
            ce_data = self.reader.get_option_at_strike(self.state.ce_strike, "CE")
            if ce_data:
                self.state.ce_ltp = float(ce_data.get("ltp", 0))
                self.state.ce_delta = float(ce_data.get("delta", 0))
                self.state.ce_gamma = float(ce_data.get("gamma", 0))
                self.state.ce_theta = float(ce_data.get("theta", 0))
                self.state.ce_vega = float(ce_data.get("vega", 0))
                self.state.ce_iv = float(ce_data.get("iv", 0))

                # P&L calculation (for short: entry_price - current = profit)
                if self.state.ce_direction == "SELL":
                    self.state.ce_pnl = (self.state.ce_entry_price - self.state.ce_ltp) * self.state.ce_qty
                else:  # BUY
                    self.state.ce_pnl = (self.state.ce_ltp - self.state.ce_entry_price) * self.state.ce_qty

                if self.state.ce_entry_price > 0:
                    self.state.ce_pnl_pct = (self.state.ce_pnl / (self.state.ce_entry_price * self.state.ce_qty)) * 100

        # PE leg
        if self.state.pe_strike > 0:
            pe_data = self.reader.get_option_at_strike(self.state.pe_strike, "PE")
            if pe_data:
                self.state.pe_ltp = float(pe_data.get("ltp", 0))
                self.state.pe_delta = float(pe_data.get("delta", 0))
                self.state.pe_gamma = float(pe_data.get("gamma", 0))
                self.state.pe_theta = float(pe_data.get("theta", 0))
                self.state.pe_vega = float(pe_data.get("vega", 0))
                self.state.pe_iv = float(pe_data.get("iv", 0))

                if self.state.pe_direction == "SELL":
                    self.state.pe_pnl = (self.state.pe_entry_price - self.state.pe_ltp) * self.state.pe_qty
                else:
                    self.state.pe_pnl = (self.state.pe_ltp - self.state.pe_entry_price) * self.state.pe_qty

                if self.state.pe_entry_price > 0:
                    self.state.pe_pnl_pct = (self.state.pe_pnl / (self.state.pe_entry_price * self.state.pe_qty)) * 100

    # ─── Entry ────────────────────────────────────────────────────────────

    def _evaluate_entry(self):
        """Evaluate entry conditions and send entry alert if met."""
        # We need live option data to evaluate delta-based entry conditions
        # Update delta state from the chain even before position entry
        self._update_entry_scan_state()

        result = evaluate_entry_rules(self.config, self.state)
        if not result.triggered:
            return

        action = result.action
        action_type = action.get("type", "")
        logger.info(f"ENTRY TRIGGERED: {result.rule_name} → {action_type}")

        legs = self._build_entry_legs(action)
        if not legs:
            logger.error("No legs built for entry — skipping")
            return

        self._send_entry_alert(legs)

    def _update_entry_scan_state(self):
        """
        Before entry, scan the chain for options matching the entry conditions.

        Supports multiple entry modes:
        - Delta-based: find CE/PE at target delta
        - Premium-based: find CE/PE at target premium (ltp)
        - IV-based: find CE/PE at target IV
        - ATM straddle/strangle: use ATM strike directly
        """
        assert self.reader is not None
        entry = self.config.get("entry", {})
        conditions = entry.get("conditions", {})

        # ─── Delta-based entry ─────────────────────────────────────────
        ce_delta_target = self._extract_target_value(conditions, "ce_delta")
        pe_delta_target = self._extract_target_value(conditions, "pe_delta")

        if ce_delta_target is not None:
            tolerance = self._extract_tolerance(conditions, "ce_delta") or 0.1
            ce_option = self.reader.find_option_by_delta("CE", ce_delta_target, tolerance)
            if ce_option:
                self._populate_leg_state("CE", ce_option)

        if pe_delta_target is not None:
            tolerance = self._extract_tolerance(conditions, "pe_delta") or 0.1
            pe_option = self.reader.find_option_by_delta("PE", pe_delta_target, tolerance)
            if pe_option:
                self._populate_leg_state("PE", pe_option)

        # ─── Premium-based entry (ce_ltp / pe_ltp target) ─────────────
        ce_prem_target = self._extract_target_value(conditions, "ce_ltp")
        pe_prem_target = self._extract_target_value(conditions, "pe_ltp")

        if ce_prem_target is not None and ce_delta_target is None:
            tolerance = self._extract_tolerance(conditions, "ce_ltp") or 10.0
            ce_option = self.reader.find_option_by_premium(
                "CE", ce_prem_target, tolerance
            )
            if ce_option:
                self._populate_leg_state("CE", ce_option)

        if pe_prem_target is not None and pe_delta_target is None:
            tolerance = self._extract_tolerance(conditions, "pe_ltp") or 10.0
            pe_option = self.reader.find_option_by_premium(
                "PE", pe_prem_target, tolerance
            )
            if pe_option:
                self._populate_leg_state("PE", pe_option)

        # ─── IV-based entry (ce_iv / pe_iv target) ────────────────────
        ce_iv_target = self._extract_target_value(conditions, "ce_iv")
        pe_iv_target = self._extract_target_value(conditions, "pe_iv")

        if ce_iv_target is not None and ce_delta_target is None and ce_prem_target is None:
            tolerance = self._extract_tolerance(conditions, "ce_iv") or 5.0
            ce_option = self.reader.find_option_by_iv("CE", ce_iv_target, tolerance)
            if ce_option:
                self._populate_leg_state("CE", ce_option)

        if pe_iv_target is not None and pe_delta_target is None and pe_prem_target is None:
            tolerance = self._extract_tolerance(conditions, "pe_iv") or 5.0
            pe_option = self.reader.find_option_by_iv("PE", pe_iv_target, tolerance)
            if pe_option:
                self._populate_leg_state("PE", pe_option)

        # ─── ATM straddle / strangle fallback ─────────────────────────
        # If no specific option found yet, check if entry action is straddle
        action_type = entry.get("action", {}).get("type", "")
        if action_type in ("short_straddle", "long_straddle") and not self.state.ce_trading_symbol:
            ce_atm, pe_atm = self.reader.get_atm_options()
            if ce_atm:
                self._populate_leg_state("CE", ce_atm)
            if pe_atm:
                self._populate_leg_state("PE", pe_atm)

    def _populate_leg_state(self, leg_type: str, option_data: Dict):
        """Set state fields for a CE or PE leg from option chain row."""
        if leg_type == "CE":
            self.state.ce_delta = float(option_data.get("delta", 0))
            self.state.ce_ltp = float(option_data.get("ltp", 0))
            self.state.ce_iv = float(option_data.get("iv", 0))
            self.state.ce_strike = float(option_data.get("strike", 0))
            self.state.ce_trading_symbol = option_data.get("trading_symbol", "")
        else:
            self.state.pe_delta = float(option_data.get("delta", 0))
            self.state.pe_ltp = float(option_data.get("ltp", 0))
            self.state.pe_iv = float(option_data.get("iv", 0))
            self.state.pe_strike = float(option_data.get("strike", 0))
            self.state.pe_trading_symbol = option_data.get("trading_symbol", "")

    def _extract_target_value(self, conditions: Dict, param_name: str) -> Optional[float]:
        """Extract target value for a parameter from conditions (recursively)."""
        # Check direct rules in compound condition
        if "rules" in conditions:
            for rule in conditions["rules"]:
                if "rules" in rule:
                    # Nested compound
                    val = self._extract_target_value(rule, param_name)
                    if val is not None:
                        return val
                elif rule.get("parameter") == param_name:
                    raw = rule.get("value")
                    return float(raw) if raw is not None else None
        # Direct condition
        if conditions.get("parameter") == param_name:
            raw = conditions.get("value")
            return float(raw) if raw is not None else None
        return None

    def _extract_tolerance(self, conditions: Dict, param_name: str) -> Optional[float]:
        """Extract tolerance for a parameter from conditions (recursively)."""
        if "rules" in conditions:
            for rule in conditions["rules"]:
                if "rules" in rule:
                    val = self._extract_tolerance(rule, param_name)
                    if val is not None:
                        return val
                elif rule.get("parameter") == param_name:
                    raw = rule.get("tolerance")
                    return float(raw) if raw is not None else None
        if conditions.get("parameter") == param_name:
            raw = conditions.get("tolerance")
            return float(raw) if raw is not None else None
        return None

    def _build_entry_legs(self, action: Dict) -> List[Dict]:
        """Build leg dicts from an entry action."""
        action_type = action.get("type", "")
        qty = self.lots * self.lot_size
        legs = []

        # ─── Short strategies (sell both) ─────────────────────────────
        if action_type in ("short_both", "short_strangle", "short_straddle"):
            if self.state.ce_trading_symbol:
                legs.append(self._make_leg(
                    self.state.ce_trading_symbol, "SELL", qty
                ))
                # Record entry
                self.state.ce_entry_price = self.state.ce_ltp
                self.state.ce_direction = "SELL"
                self.state.ce_qty = qty

            if self.state.pe_trading_symbol:
                legs.append(self._make_leg(
                    self.state.pe_trading_symbol, "SELL", qty
                ))
                self.state.pe_entry_price = self.state.pe_ltp
                self.state.pe_direction = "SELL"
                self.state.pe_qty = qty

        # ─── Long strategies (buy both) ──────────────────────────────
        elif action_type in ("long_both", "long_strangle", "long_straddle"):
            if self.state.ce_trading_symbol:
                legs.append(self._make_leg(
                    self.state.ce_trading_symbol, "BUY", qty
                ))
                self.state.ce_entry_price = self.state.ce_ltp
                self.state.ce_direction = "BUY"
                self.state.ce_qty = qty

            if self.state.pe_trading_symbol:
                legs.append(self._make_leg(
                    self.state.pe_trading_symbol, "BUY", qty
                ))
                self.state.pe_entry_price = self.state.pe_ltp
                self.state.pe_direction = "BUY"
                self.state.pe_qty = qty

        # ─── Single leg ──────────────────────────────────────────────
        elif action_type in ("short_ce", "long_ce"):
            direction = "SELL" if "short" in action_type else "BUY"
            if self.state.ce_trading_symbol:
                legs.append(self._make_leg(
                    self.state.ce_trading_symbol, direction, qty
                ))
                self.state.ce_entry_price = self.state.ce_ltp
                self.state.ce_direction = direction
                self.state.ce_qty = qty

        elif action_type in ("short_pe", "long_pe"):
            direction = "SELL" if "short" in action_type else "BUY"
            if self.state.pe_trading_symbol:
                legs.append(self._make_leg(
                    self.state.pe_trading_symbol, direction, qty
                ))
                self.state.pe_entry_price = self.state.pe_ltp
                self.state.pe_direction = direction
                self.state.pe_qty = qty

        # ─── Iron Condor (4 legs: sell near + buy far, both sides) ──
        elif action_type == "iron_condor":
            details = action.get("details", {})
            hedge_offset = float(details.get("hedge_offset_strikes", 500))

            # Near legs (short)
            if self.state.ce_trading_symbol:
                legs.append(self._make_leg(self.state.ce_trading_symbol, "SELL", qty))
                self.state.ce_entry_price = self.state.ce_ltp
                self.state.ce_direction = "SELL"
                self.state.ce_qty = qty
            if self.state.pe_trading_symbol:
                legs.append(self._make_leg(self.state.pe_trading_symbol, "SELL", qty))
                self.state.pe_entry_price = self.state.pe_ltp
                self.state.pe_direction = "SELL"
                self.state.pe_qty = qty

            # Far legs (hedge — buy further OTM)
            if self.reader and self.state.ce_strike > 0:
                far_ce = self.reader.get_option_at_strike(
                    self.state.ce_strike + hedge_offset, "CE"
                )
                if far_ce:
                    legs.append(self._make_leg(
                        far_ce.get("trading_symbol", ""), "BUY", qty
                    ))
            if self.reader and self.state.pe_strike > 0:
                far_pe = self.reader.get_option_at_strike(
                    self.state.pe_strike - hedge_offset, "PE"
                )
                if far_pe:
                    legs.append(self._make_leg(
                        far_pe.get("trading_symbol", ""), "BUY", qty
                    ))

        # ─── Iron Butterfly (4 legs: sell ATM + buy OTM, both sides) ─
        elif action_type == "iron_butterfly":
            details = action.get("details", {})
            wing_offset = float(details.get("wing_offset_strikes", 500))

            # Sell ATM on both sides
            if self.reader:
                ce_atm, pe_atm = self.reader.get_atm_options()
                if ce_atm:
                    self._populate_leg_state("CE", ce_atm)
                    legs.append(self._make_leg(
                        ce_atm.get("trading_symbol", ""), "SELL", qty
                    ))
                    self.state.ce_entry_price = float(ce_atm.get("ltp", 0))
                    self.state.ce_direction = "SELL"
                    self.state.ce_qty = qty
                if pe_atm:
                    self._populate_leg_state("PE", pe_atm)
                    legs.append(self._make_leg(
                        pe_atm.get("trading_symbol", ""), "SELL", qty
                    ))
                    self.state.pe_entry_price = float(pe_atm.get("ltp", 0))
                    self.state.pe_direction = "SELL"
                    self.state.pe_qty = qty

                # Wing (hedge) legs — buy further OTM
                atm = self.reader.get_atm_strike()
                if atm > 0:
                    far_ce = self.reader.get_option_at_strike(atm + wing_offset, "CE")
                    if far_ce:
                        legs.append(self._make_leg(
                            far_ce.get("trading_symbol", ""), "BUY", qty
                        ))
                    far_pe = self.reader.get_option_at_strike(atm - wing_offset, "PE")
                    if far_pe:
                        legs.append(self._make_leg(
                            far_pe.get("trading_symbol", ""), "BUY", qty
                        ))

        # ─── Custom — legs must be in action.details ─────────────────
        elif action_type == "custom":
            custom_legs = action.get("details", {}).get("legs", [])
            for cl in custom_legs:
                legs.append({
                    "tradingsymbol": cl.get("tradingsymbol", ""),
                    "direction": cl.get("direction", "SELL"),
                    "qty": cl.get("qty", qty),
                    "order_type": cl.get("order_type", "MKT"),
                    "price": cl.get("price", 0.0),
                    "product_type": cl.get("product_type", "M"),
                })

        else:
            logger.warning(f"Unhandled entry action type: {action_type}")

        if legs:
            self.state.has_position = True
            self.state.entry_time = datetime.now()
            logger.info(
                f"Entry built: {len(legs)} legs | "
                f"CE={self.state.ce_trading_symbol}@{self.state.ce_strike} "
                f"PE={self.state.pe_trading_symbol}@{self.state.pe_strike}"
            )

        return legs

    # ─── Exit ─────────────────────────────────────────────────────────────

    def _evaluate_exit(self):
        """Evaluate exit conditions."""
        result = evaluate_exit_rules(self.config, self.state)
        if result.triggered:
            logger.info(f"EXIT TRIGGERED: {result.rule_name}")
            self._send_exit_alert(result.rule_name)

    # ─── Adjustments ──────────────────────────────────────────────────────

    def _evaluate_adjustments(self):
        """Evaluate adjustment rules (respects cooldown & limits)."""
        adj_cfg = self.config.get("adjustment", {})
        if not adj_cfg.get("enabled", False):
            return

        # Cooldown check
        cooldown = adj_cfg.get("cooldown_seconds", 60)
        elapsed = time.time() - self._last_adjustment_time
        if elapsed < cooldown:
            return

        # Max adjustments check
        max_adj = adj_cfg.get("max_adjustments_per_day", 999)
        if self.state.adjustments_today >= max_adj:
            logger.debug("Max adjustments reached for today")
            return

        results = evaluate_adjustment_rules(self.config, self.state)
        if not results:
            return

        # Act on the FIRST triggered rule only (highest priority)
        first = results[0]
        logger.info(f"ADJUSTMENT: {first.rule_name} → {first.action.get('type', '?')}")
        self._execute_adjustment(first)

    def _execute_adjustment(self, result: RuleResult):
        """Execute an adjustment action."""
        assert self.reader is not None
        action = result.action
        action_type = action.get("type", "")
        details = action.get("details", {})
        qty = self.lots * self.lot_size

        if action_type == "do_nothing":
            return

        # ─── Close higher/lower delta leg and re-enter ────────────────
        if action_type in ("close_higher_delta", "close_lower_delta"):
            target_leg = details.get("close_leg", "")
            if not target_leg:
                target_leg = self.state.higher_delta_leg if "higher" in action_type else self.state.lower_delta_leg

            # Build close leg
            close_legs = self._build_close_leg(target_leg)
            if close_legs:
                self._send_exit_alert_for_legs(close_legs, f"adj_{result.rule_name}")

            # Re-enter if specified
            if details.get("enter_new", False):
                # Find new option matching the other leg's delta
                other_leg = "PE" if target_leg == "CE" else "CE"
                other_delta = abs(self.state.ce_delta) if other_leg == "CE" else abs(self.state.pe_delta)

                new_option = self.reader.find_option_by_delta(
                    target_leg,  # Same type as closed leg
                    other_delta,  # Match other leg's delta
                    tolerance=0.1,
                )
                if new_option:
                    direction = self.state.ce_direction if target_leg == "CE" else self.state.pe_direction
                    new_legs = [self._make_leg(
                        new_option.get("trading_symbol", ""),
                        direction,
                        qty,
                    )]
                    self._send_entry_alert(new_legs)

                    # Update state
                    if target_leg == "CE":
                        self.state.ce_strike = float(new_option.get("strike", 0))
                        self.state.ce_trading_symbol = new_option.get("trading_symbol", "")
                        self.state.ce_entry_price = float(new_option.get("ltp", 0))
                    else:
                        self.state.pe_strike = float(new_option.get("strike", 0))
                        self.state.pe_trading_symbol = new_option.get("trading_symbol", "")
                        self.state.pe_entry_price = float(new_option.get("ltp", 0))

        # ─── Close specific leg ──────────────────────────────────────
        elif action_type in ("close_ce", "close_pe"):
            leg = "CE" if "ce" in action_type else "PE"
            close_legs = self._build_close_leg(leg)
            if close_legs:
                self._send_exit_alert_for_legs(close_legs, f"adj_{action_type}")

        # ─── Roll operations ─────────────────────────────────────────
        elif action_type in ("roll_ce", "roll_pe", "roll_both"):
            # Roll = close existing + enter at new strike
            # Details should specify target delta or strike offset
            legs_to_roll = []
            if "ce" in action_type or action_type == "roll_both":
                legs_to_roll.append("CE")
            if "pe" in action_type or action_type == "roll_both":
                legs_to_roll.append("PE")

            for leg in legs_to_roll:
                close_legs = self._build_close_leg(leg)
                if close_legs:
                    self._send_exit_alert_for_legs(close_legs, f"roll_close_{leg}")

                # Re-enter at new delta/strike
                target_delta = details.get("target_delta", 0.3)
                new_option = self.reader.find_option_by_delta(leg, target_delta, tolerance=0.1)
                if new_option:
                    direction = self.state.ce_direction if leg == "CE" else self.state.pe_direction
                    self._send_entry_alert([self._make_leg(
                        new_option.get("trading_symbol", ""), direction, qty
                    )])
                    # Update state
                    if leg == "CE":
                        self.state.ce_strike = float(new_option.get("strike", 0))
                        self.state.ce_trading_symbol = new_option.get("trading_symbol", "")
                        self.state.ce_entry_price = float(new_option.get("ltp", 0))
                    else:
                        self.state.pe_strike = float(new_option.get("strike", 0))
                        self.state.pe_trading_symbol = new_option.get("trading_symbol", "")
                        self.state.pe_entry_price = float(new_option.get("ltp", 0))

        # ─── Profit lock / trailing stop ─────────────────────────────
        elif action_type in ("lock_profit", "trailing_stop"):
            trail_by = details.get("trail_by", 200)
            self.state.trailing_stop_active = True
            self.state.trailing_stop_level = self.state.combined_pnl - trail_by
            logger.info(
                f"Trailing stop set: level=₹{self.state.trailing_stop_level:.0f} "
                f"(current PnL=₹{self.state.combined_pnl:.0f}, trail=₹{trail_by})"
            )

        else:
            logger.warning(f"Unhandled adjustment action: {action_type}")
            return

        # Update counters
        self.state.adjustments_today += 1
        self._last_adjustment_time = time.time()

    def _build_close_leg(self, leg_type: str) -> List[Dict]:
        """Build a close (exit) leg dict for a given leg type."""
        legs = []
        if leg_type == "CE" and self.state.ce_trading_symbol:
            # Reverse direction to close
            close_dir = "BUY" if self.state.ce_direction == "SELL" else "SELL"
            legs.append(self._make_leg(
                self.state.ce_trading_symbol, close_dir, self.state.ce_qty
            ))
        elif leg_type == "PE" and self.state.pe_trading_symbol:
            close_dir = "BUY" if self.state.pe_direction == "SELL" else "SELL"
            legs.append(self._make_leg(
                self.state.pe_trading_symbol, close_dir, self.state.pe_qty
            ))
        return legs

    # ─── Alert Construction & Sending ─────────────────────────────────────

    def _make_leg(self, tradingsymbol: str, direction: str, qty: int) -> Dict:
        """Build a single leg dict for process_alert."""
        return {
            "tradingsymbol": tradingsymbol,
            "direction": direction.upper(),
            "qty": int(qty),
            "order_type": "MKT",
            "price": 0.0,
            "product_type": "M",
        }

    def _get_webhook_secret(self) -> str:
        """Get webhook secret from environment."""
        return os.getenv("WEBHOOK_SECRET_KEY", "")

    def _send_entry_alert(self, legs: List[Dict]):
        """Send an ENTRY alert to process_alert."""
        alert = {
            "secret_key": self._get_webhook_secret(),
            "execution_type": "ENTRY",
            "strategy_name": self.strategy_name,
            "exchange": self.exchange,
            "underlying": self.symbol,
            "expiry": self._get_current_expiry(),
            "legs": legs,
        }
        if self.test_mode:
            alert["test_mode"] = "true"

        self._dispatch_alert(alert)

    def _send_exit_alert(self, reason: str = ""):
        """Send an EXIT alert for ALL positions."""
        legs = []
        if self.state.ce_trading_symbol and self.state.ce_qty > 0:
            close_dir = "BUY" if self.state.ce_direction == "SELL" else "SELL"
            legs.append(self._make_leg(
                self.state.ce_trading_symbol, close_dir, self.state.ce_qty
            ))
        if self.state.pe_trading_symbol and self.state.pe_qty > 0:
            close_dir = "BUY" if self.state.pe_direction == "SELL" else "SELL"
            legs.append(self._make_leg(
                self.state.pe_trading_symbol, close_dir, self.state.pe_qty
            ))

        if not legs:
            logger.warning("No legs to exit")
            return

        alert = {
            "secret_key": self._get_webhook_secret(),
            "execution_type": "EXIT",
            "strategy_name": self.strategy_name,
            "exchange": self.exchange,
            "underlying": self.symbol,
            "expiry": self._get_current_expiry(),
            "legs": legs,
        }
        if self.test_mode:
            alert["test_mode"] = "true"

        logger.info(f"EXIT alert ({reason}): {len(legs)} legs")
        self._dispatch_alert(alert)
        self._clear_position()

    def _send_exit_alert_for_legs(self, legs: List[Dict], reason: str = ""):
        """Send an EXIT alert for specific legs only."""
        if not legs:
            return

        alert = {
            "secret_key": self._get_webhook_secret(),
            "execution_type": "EXIT",
            "strategy_name": self.strategy_name,
            "exchange": self.exchange,
            "underlying": self.symbol,
            "expiry": self._get_current_expiry(),
            "legs": legs,
        }
        if self.test_mode:
            alert["test_mode"] = "true"

        logger.info(f"Partial EXIT ({reason}): {len(legs)} legs")
        self._dispatch_alert(alert)

    def _dispatch_alert(self, alert: Dict):
        """
        Send alert to process_alert() via the global trading bot.

        This is the ONLY point where fresh_strategy talks to the OMS.
        """
        logger.info(
            f"→ ALERT: {alert['execution_type']} | {self.strategy_name} | "
            f"{len(alert['legs'])} legs | "
            f"symbols={[l['tradingsymbol'] for l in alert['legs']]}"
        )

        try:
            from shoonya_platform.execution.trading_bot import get_global_bot
            bot = get_global_bot()

            result = bot.process_alert(alert)
            logger.info(f"← ALERT RESULT: {result}")
            self.state.total_trades_today += len(alert["legs"])

        except RuntimeError as e:
            logger.error(
                f"Global bot not initialized — alert NOT dispatched: {e}. "
                f"Is main.py running?"
            )
        except ImportError as e:
            logger.error(f"Cannot import trading_bot: {e}")
        except Exception as e:
            logger.error(f"Alert dispatch failed: {e}", exc_info=True)

    def _clear_position(self):
        """Reset position state after full exit."""
        self.state.has_position = False
        self.state.ce_strike = 0.0
        self.state.ce_entry_price = 0.0
        self.state.ce_trading_symbol = ""
        self.state.ce_direction = ""
        self.state.ce_qty = 0
        self.state.ce_ltp = 0.0
        self.state.ce_pnl = 0.0
        self.state.ce_pnl_pct = 0.0

        self.state.pe_strike = 0.0
        self.state.pe_entry_price = 0.0
        self.state.pe_trading_symbol = ""
        self.state.pe_direction = ""
        self.state.pe_qty = 0
        self.state.pe_ltp = 0.0
        self.state.pe_pnl = 0.0
        self.state.pe_pnl_pct = 0.0

        self.state.peak_pnl = 0.0
        self.state.trailing_stop_active = False
        self.state.trailing_stop_level = 0.0

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _get_current_expiry(self) -> str:
        """Get the current expiry date from market data meta or config."""
        if self.reader:
            meta = self.reader.get_meta()
            if meta and "expiry" in meta:
                return str(meta["expiry"])
        return self.config.get("basic", {}).get("expiry", "")

    def _log_state_summary(self):
        """Log a periodic snapshot of strategy state for monitoring."""
        s = self.state
        if s.has_position:
            logger.info(
                f"[TICK #{self._tick_count}] {self.strategy_name} | "
                f"spot={s.spot_price:.1f} Δspot={s.spot_change:.1f} | "
                f"CE: Δ={s.ce_delta:.3f} ltp={s.ce_ltp:.1f} pnl={s.ce_pnl:.0f} | "
                f"PE: Δ={s.pe_delta:.3f} ltp={s.pe_ltp:.1f} pnl={s.pe_pnl:.0f} | "
                f"combined_pnl=₹{s.combined_pnl:.0f} peak=₹{s.peak_pnl:.0f} | "
                f"adj={s.adjustments_today} trades={s.total_trades_today}"
            )
        else:
            logger.info(
                f"[TICK #{self._tick_count}] {self.strategy_name} | "
                f"spot={s.spot_price:.1f} | NO POSITION | "
                f"trades_today={s.total_trades_today}"
            )

    @staticmethod
    def _parse_time_minutes(time_str: str) -> int:
        """Convert 'HH:MM' to minutes since midnight."""
        parts = str(time_str).split(":")
        return int(parts[0]) * 60 + int(parts[1])
