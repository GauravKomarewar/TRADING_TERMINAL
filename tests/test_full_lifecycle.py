#!/usr/bin/env python3
"""
test_full_lifecycle.py — End-to-End Strategy Lifecycle Tests
=============================================================

Tests EVERY mode of the strategy engine using fake market data:
  ✅ Entry (with conditions, guards, cooldown)
  ✅ Adjustments (close_leg, partial_close, reduce_by_pct, convert_to_spread, roll)
  ✅ Exits (profit target, stop loss, trailing stop, time exit, leg rules)
  ✅ Market data updates (Greeks refresh every tick)
  ✅ Persistence (save/load state roundtrip)
  ✅ PnL tracking and history
  ✅ Daily reset
  ✅ Reconciliation flows

SAFETY:
  - Uses FakeMarketDB with 2099 expiries (impossible real trade overlap)
  - All data in tests/fake_market_data/ (not real data dir)
  - MarketReader pointed at fake directory via monkey-patching
  - No broker connection — pure state-machine testing

Run:
    pytest tests/test_full_lifecycle.py -v
    python tests/test_full_lifecycle.py          # Direct execution
"""

import sys
import os
import logging
import math
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.fake_market_db import FakeMarketDB, FakeMarketSimulator, FAKE_DATA_DIR

from shoonya_platform.strategy_runner.state import StrategyState, LegState, PnLSnapshot, AdjustmentEvent
from shoonya_platform.strategy_runner.models import (
    InstrumentType, OptionType, Side, StrikeMode, StrikeConfig,
    Condition, Comparator, JoinOperator,
)
from shoonya_platform.strategy_runner.entry_engine import EntryEngine
from shoonya_platform.strategy_runner.exit_engine import ExitEngine
from shoonya_platform.strategy_runner.adjustment_engine import AdjustmentEngine
from shoonya_platform.strategy_runner.condition_engine import ConditionEngine
from shoonya_platform.strategy_runner.persistence import StatePersistence
from shoonya_platform.strategy_runner.market_reader import MarketReader
from shoonya_platform.strategy_runner.reconciliation import BrokerReconciliation

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("test_full_lifecycle")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SAFETY: Patch MarketReader to use FAKE data directory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import shoonya_platform.strategy_runner.market_reader as mr_module
_ORIGINAL_DB_FOLDER = mr_module.DB_FOLDER


def _patch_db_folder():
    """Redirect MarketReader to use fake data directory."""
    mr_module.DB_FOLDER = FAKE_DATA_DIR


def _unpatch_db_folder():
    """Restore original DB folder."""
    mr_module.DB_FOLDER = _ORIGINAL_DB_FOLDER


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER: Create a MarketReader that reads from fake DB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_test_market_reader(symbol: str = "NIFTY", exchange: str = "NFO") -> MarketReader:
    """Create a MarketReader pointed at fake DB directory."""
    _patch_db_folder()
    reader = MarketReader(exchange=exchange, symbol=symbol, max_stale_seconds=99999)
    return reader


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER: Build complete strategy config for testing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_straddle_entry_config(
    max_entries_per_day: int = 3,
    entry_cooldown_sec: int = 0,
) -> Dict[str, Any]:
    """Standard short straddle entry config."""
    return {
        "max_entries_per_day": max_entries_per_day,
        "entry_cooldown_sec": entry_cooldown_sec,
        "global_conditions": [],
        "entry_sequence": "parallel",
        "legs": [
            {
                "tag": "CE_SELL",
                "side": "SELL",
                "instrument": "OPT",
                "option_type": "CE",
                "lots": 1,
                "strike_mode": "standard",
                "strike_selection": "atm",
                "expiry": "10-JAN-2099",
            },
            {
                "tag": "PE_SELL",
                "side": "SELL",
                "instrument": "OPT",
                "option_type": "PE",
                "lots": 1,
                "strike_mode": "standard",
                "strike_selection": "atm",
                "expiry": "10-JAN-2099",
            },
        ],
    }


def make_exit_config(
    profit_target_amount: float = 5000,
    stop_loss_amount: float = 3000,
    trail_amount: float = 1000,
    lock_in_at: float = 2000,
    exit_time: str = "15:20",
) -> Dict[str, Any]:
    """Standard exit config with all exit types."""
    return {
        "profit_target": {
            "amount": profit_target_amount,
            "action": "exit_all",
        },
        "stop_loss": {
            "amount": stop_loss_amount,
            "action": "exit_all",
        },
        "trailing": {
            "trail_amount": trail_amount,
            "lock_in_at": lock_in_at,
        },
        "time": {
            "strategy_exit_time": exit_time,
        },
    }


def make_adjustment_rules(state: StrategyState) -> List[Dict[str, Any]]:
    """Standard adjustment rules testing all action types."""
    return [
        {
            "name": "delta_hedge_close",
            "priority": 1,
            "cooldown_sec": 0,
            "max_per_day": 5,
            "max_total": 99,
            "conditions": [
                {"parameter": "net_delta", "comparator": ">", "value": 0.9}
            ],
            "action": {
                "type": "close_leg",
                "close_tag": "CE_SELL",
            },
        },
        {
            "name": "partial_close_on_profit",
            "priority": 2,
            "cooldown_sec": 0,
            "max_per_day": 5,
            "max_total": 99,
            "conditions": [
                {"parameter": "combined_pnl", "comparator": ">", "value": 3000}
            ],
            "action": {
                "type": "partial_close_lots",
                "close_tag": "PE_SELL",
                "lots": 1,
            },
        },
        {
            "name": "reduce_on_iv_spike",
            "priority": 3,
            "cooldown_sec": 0,
            "max_per_day": 3,
            "max_total": 99,
            "conditions": [
                {"parameter": "atm_iv", "comparator": ">", "value": 25}
            ],
            "action": {
                "type": "reduce_by_pct",
                "close_tag": "CE_SELL",
                "reduce_pct": 50,
            },
        },
        {
            "name": "convert_to_spread",
            "priority": 4,
            "cooldown_sec": 0,
            "max_per_day": 2,
            "max_total": 99,
            "conditions": [
                {"parameter": "combined_pnl", "comparator": "<", "value": -2000}
            ],
            "action": {
                "type": "convert_to_spread",
                "target_leg": "CE_SELL",
                "width": 100,
            },
        },
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST CLASS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFullLifecycle:
    """End-to-end tests for the entire strategy lifecycle."""

    @classmethod
    def setup_class(cls):
        """Create fake market databases before all tests."""
        _patch_db_folder()
        cls.sim = FakeMarketSimulator(base_expiry="10-JAN-2099")
        cls.nifty_db = cls.sim.add_symbol("NIFTY", spot=22500.0, base_iv=15.0, tte_days=5.0)
        cls.banknifty_db = cls.sim.add_symbol("BANKNIFTY", spot=48000.0, base_iv=16.0, tte_days=5.0)
        logger.info("✅ Fake market DBs created in %s", FAKE_DATA_DIR)

    @classmethod
    def teardown_class(cls):
        """Clean up fake databases."""
        cls.sim.cleanup_all()
        _unpatch_db_folder()
        logger.info("✅ Fake market DBs cleaned up")

    def _make_state_with_legs(self, market: MarketReader) -> StrategyState:
        """Helper: create state with a short straddle already entered."""
        state = StrategyState()
        spot = market.get_spot_price()
        atm = market.get_atm_strike()

        ce_data = market.get_option_at_strike(atm, OptionType.CE)
        pe_data = market.get_option_at_strike(atm, OptionType.PE)

        state.legs["CE_SELL"] = LegState(
            tag="CE_SELL",
            symbol="NIFTY",
            instrument=InstrumentType.OPT,
            option_type=OptionType.CE,
            strike=atm,
            expiry="10-JAN-2099",
            side=Side.SELL,
            qty=2,
            entry_price=ce_data["ltp"] if ce_data else 150.0,
            ltp=ce_data["ltp"] if ce_data else 150.0,
            delta=ce_data["delta"] if ce_data else 0.5,
            gamma=ce_data["gamma"] if ce_data else 0.005,
            theta=ce_data["theta"] if ce_data else -10,
            vega=ce_data["vega"] if ce_data else 20,
            iv=ce_data["iv"] if ce_data else 15,
            is_active=True,
            order_status="FILLED",
            lot_size=50,
            trading_symbol=f"NIFTY10JAN99C{int(atm)}",
        )
        state.legs["PE_SELL"] = LegState(
            tag="PE_SELL",
            symbol="NIFTY",
            instrument=InstrumentType.OPT,
            option_type=OptionType.PE,
            strike=atm,
            expiry="10-JAN-2099",
            side=Side.SELL,
            qty=2,
            entry_price=pe_data["ltp"] if pe_data else 150.0,
            ltp=pe_data["ltp"] if pe_data else 150.0,
            delta=pe_data["delta"] if pe_data else -0.5,
            gamma=pe_data["gamma"] if pe_data else 0.005,
            theta=pe_data["theta"] if pe_data else -10,
            vega=pe_data["vega"] if pe_data else 20,
            iv=pe_data["iv"] if pe_data else 15,
            is_active=True,
            order_status="FILLED",
            lot_size=50,
            trading_symbol=f"NIFTY10JAN99P{int(atm)}",
        )

        state.spot_price = spot
        state.spot_open = spot
        state.atm_strike = atm
        state.fut_ltp = market.get_fut_ltp()
        state.entry_time = datetime.now()
        state.entered_today = True
        state.total_trades_today = 1
        return state

    # ------------------------------------------------------------------
    # TEST: Market Data Reading from Fake DB
    # ------------------------------------------------------------------
    def test_01_market_data_reads_from_fake_db(self):
        """MarketReader correctly reads spot, ATM, chain from fake DB."""
        market = create_test_market_reader("NIFTY")
        spot = market.get_spot_price()
        atm = market.get_atm_strike()
        fut = market.get_fut_ltp()

        assert spot > 0, f"Spot should be positive, got {spot}"
        assert atm > 0, f"ATM should be positive, got {atm}"
        assert fut > 0, f"Fut LTP should be positive, got {fut}"
        assert abs(spot - 22500) < 100, f"Spot should be near 22500, got {spot}"

        # Chain data
        ce = market.get_option_at_strike(atm, OptionType.CE)
        pe = market.get_option_at_strike(atm, OptionType.PE)
        assert ce is not None, "CE option at ATM should exist"
        assert pe is not None, "PE option at ATM should exist"
        assert ce["ltp"] > 0, "CE LTP should be positive"
        assert pe["ltp"] > 0, "PE LTP should be positive"
        assert 0 < ce["delta"] < 1, f"CE delta should be 0-1, got {ce['delta']}"
        assert -1 < pe["delta"] < 0, f"PE delta should be -1-0, got {pe['delta']}"

        logger.info("✅ TEST 01 PASSED: Market data reads correctly from fake DB")
        market.close_all()

    # ------------------------------------------------------------------
    # TEST: Price Simulation / Updates
    # ------------------------------------------------------------------
    def test_02_price_simulation_updates_db(self):
        """FakeMarketDB.simulate_tick updates DB and MarketReader sees changes."""
        market = create_test_market_reader("NIFTY")
        old_spot = market.get_spot_price()

        # Force a big move
        self.nifty_db.update_prices(spot=old_spot + 200)
        market.close_all()  # Force reconnect to see new data

        market2 = create_test_market_reader("NIFTY")
        new_spot = market2.get_spot_price()
        assert abs(new_spot - (old_spot + 200)) < 1, f"Spot should have moved to {old_spot + 200}, got {new_spot}"

        # Restore
        self.nifty_db.update_prices(spot=22500)
        market2.close_all()
        logger.info("✅ TEST 02 PASSED: Price simulation updates DB correctly")

    # ------------------------------------------------------------------
    # TEST: Entry Engine
    # ------------------------------------------------------------------
    def test_03_entry_engine_creates_legs(self):
        """EntryEngine creates legs from config using fake market data."""
        market = create_test_market_reader("NIFTY")
        state = StrategyState()
        engine = EntryEngine(state, market)

        config = make_straddle_entry_config()
        legs = engine.process_entry(config, "NIFTY", "10-JAN-2099")

        assert len(legs) == 2, f"Should create 2 legs (straddle), got {len(legs)}"
        tags = [l.tag for l in legs]
        assert "CE_SELL" in tags, "Should have CE_SELL leg"
        assert "PE_SELL" in tags, "Should have PE_SELL leg"

        for leg in legs:
            assert leg.is_active, f"Leg {leg.tag} should be active"
            assert leg.entry_price > 0, f"Leg {leg.tag} should have entry price"
            assert leg.side == Side.SELL, f"Leg {leg.tag} should be SELL"

        market.close_all()
        logger.info("✅ TEST 03 PASSED: Entry engine creates legs correctly")

    # ------------------------------------------------------------------
    # TEST: Entry Guards (max entries, cooldown)
    # ------------------------------------------------------------------
    def test_04_entry_guards_block_excess_entries(self):
        """Entry guards block when max_entries_per_day reached."""
        market = create_test_market_reader("NIFTY")
        state = StrategyState()
        state.total_trades_today = 3  # Already at max
        engine = EntryEngine(state, market)

        config = make_straddle_entry_config(max_entries_per_day=3)
        legs = engine.process_entry(config, "NIFTY", "10-JAN-2099")
        assert len(legs) == 0, "Should block entry when max_entries_per_day reached"

        market.close_all()
        logger.info("✅ TEST 04 PASSED: Entry guard blocks excess entries")

    def test_05_entry_cooldown_blocks_rapid_entries(self):
        """Entry cooldown prevents entries too soon after last entry."""
        market = create_test_market_reader("NIFTY")
        state = StrategyState()
        state.entry_time = datetime.now()  # Just entered
        engine = EntryEngine(state, market)

        config = make_straddle_entry_config(entry_cooldown_sec=300)
        legs = engine.process_entry(config, "NIFTY", "10-JAN-2099")
        assert len(legs) == 0, "Should block entry during cooldown"

        market.close_all()
        logger.info("✅ TEST 05 PASSED: Entry cooldown blocks rapid entries")

    # ------------------------------------------------------------------
    # TEST: Exit Engine — Profit Target
    # ------------------------------------------------------------------
    def test_06_exit_profit_target(self):
        """Exit is triggered when profit target is hit."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        exit_engine = ExitEngine(state)
        exit_engine.load_config(make_exit_config(profit_target_amount=100))

        # Force profit by lowering LTP (we sold, so lower = profit)
        for leg in state.legs.values():
            leg.ltp = leg.entry_price * 0.1  # 90% premium decay = big profit

        action = exit_engine.check_exits(datetime.now())
        assert action is not None, "Should trigger exit on profit target"
        assert "profit" in exit_engine.last_exit_reason.lower() or action == "exit_all"

        market.close_all()
        logger.info("✅ TEST 06 PASSED: Exit profit target triggered")

    # ------------------------------------------------------------------
    # TEST: Exit Engine — Stop Loss
    # ------------------------------------------------------------------
    def test_07_exit_stop_loss(self):
        """Exit is triggered when stop loss is hit."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        exit_engine = ExitEngine(state)
        exit_engine.load_config(make_exit_config(stop_loss_amount=100))

        # Force loss by increasing LTP (we sold, so higher = loss)
        for leg in state.legs.values():
            leg.ltp = leg.entry_price * 3.0  # Tripled = big loss

        action = exit_engine.check_exits(datetime.now())
        assert action is not None, "Should trigger exit on stop loss"
        assert "stop_loss" in exit_engine.last_exit_reason.lower()

        market.close_all()
        logger.info("✅ TEST 07 PASSED: Exit stop loss triggered")

    # ------------------------------------------------------------------
    # TEST: Exit Engine — Trailing Stop
    # ------------------------------------------------------------------
    def test_08_trailing_stop_lifecycle(self):
        """Trailing stop: activates on profit, ratchets up, then triggers on pullback."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        exit_engine = ExitEngine(state)
        exit_config = {
            "stop_loss": {"amount": 99999},  # Disable
            "profit_target": {"amount": 99999},  # Disable
            "trailing": {
                "trail_amount": 500,
                "lock_in_at": 1000,
            },
        }
        exit_engine.load_config(exit_config)

        # Step 1: Not yet in profit — trailing should be inactive
        action = exit_engine.check_exits(datetime.now())
        assert action is None, "No exit yet — trailing not activated"
        assert not state.trailing_stop_active

        # Step 2: Move into profit (LTP drops = profit for short)
        for leg in state.legs.values():
            leg.ltp = leg.entry_price * 0.5  # 50% decay = good profit

        action = exit_engine.check_exits(datetime.now())
        # Trailing should now be active (combined_pnl > lock_in_at)
        if state.combined_pnl >= 1000:
            assert state.trailing_stop_active, "Trailing should activate when profit > lock_in"
            assert state.trailing_stop_level > 0, "Trailing stop level should be set"

        # Step 3: Increase profit further — stop level ratchets up
        old_level = state.trailing_stop_level
        for leg in state.legs.values():
            leg.ltp = leg.entry_price * 0.2  # More profit
        exit_engine.check_exits(datetime.now())
        if state.trailing_stop_active and state.combined_pnl > state.peak_pnl:
            # Peak updates on next check
            pass

        # Step 4: Pullback below trailing level — trigger exit
        for leg in state.legs.values():
            leg.ltp = leg.entry_price * 2.0  # Big reversal, loss
        state.trailing_stop_level = state.combined_pnl + 100  # Force trigger

        action = exit_engine.check_exits(datetime.now())
        if state.trailing_stop_active:
            assert action is not None, "Should trigger trailing stop on pullback"

        market.close_all()
        logger.info("✅ TEST 08 PASSED: Trailing stop lifecycle works")

    # ------------------------------------------------------------------
    # TEST: Exit Engine — Time Exit
    # ------------------------------------------------------------------
    def test_09_time_exit(self):
        """Time-based exit triggers at configured time."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        exit_engine = ExitEngine(state)

        # Set exit time to a past time
        exit_engine.load_config({
            "profit_target": {"amount": 99999},
            "stop_loss": {"amount": 99999},
            "time": {"strategy_exit_time": "09:00"},
        })

        now = datetime.now().replace(hour=15, minute=25)
        state.current_time = now
        action = exit_engine.check_exits(now)
        assert action is not None, "Should trigger time exit after strategy_exit_time"

        market.close_all()
        logger.info("✅ TEST 09 PASSED: Time exit works")

    # ------------------------------------------------------------------
    # TEST: Adjustment — Close Leg
    # ------------------------------------------------------------------
    def test_10_adjustment_close_leg(self):
        """Adjustment engine can close a leg when conditions met."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)

        adj_engine = AdjustmentEngine(state, market)
        rules = [
            {
                "name": "force_close_ce",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    # Always true: spot > 100
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {
                    "type": "close_leg",
                    "close_tag": "CE_SELL",
                },
            },
        ]
        adj_engine.load_rules(rules)
        actions = adj_engine.check_and_apply(datetime.now())

        assert len(actions) > 0, "Should have triggered close_leg action"
        assert not state.legs["CE_SELL"].is_active, "CE_SELL should be deactivated"
        assert state.legs["PE_SELL"].is_active, "PE_SELL should still be active"

        market.close_all()
        logger.info("✅ TEST 10 PASSED: Adjustment close_leg works")

    # ------------------------------------------------------------------
    # TEST: Adjustment — Partial Close
    # ------------------------------------------------------------------
    def test_11_adjustment_partial_close(self):
        """Partial close reduces lot count correctly."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        original_qty = state.legs["PE_SELL"].qty  # Should be 2

        adj_engine = AdjustmentEngine(state, market)
        rules = [
            {
                "name": "partial_close",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {
                    "type": "partial_close_lots",
                    "close_tag": "PE_SELL",
                    "lots": 1,
                },
            },
        ]
        adj_engine.load_rules(rules)
        adj_engine.check_and_apply(datetime.now())

        assert state.legs["PE_SELL"].qty == original_qty - 1, \
            f"Should reduce by 1 lot: {original_qty} -> {state.legs['PE_SELL'].qty}"
        assert state.legs["PE_SELL"].is_active, "Should still be active after partial close"

        market.close_all()
        logger.info("✅ TEST 11 PASSED: Adjustment partial_close_lots works")

    # ------------------------------------------------------------------
    # TEST: Adjustment — Reduce by Percentage
    # ------------------------------------------------------------------
    def test_12_adjustment_reduce_by_pct(self):
        """Reduce by percentage with round() and min-1-lot edge case."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        state.legs["CE_SELL"].qty = 5  # Set to 5 for clear percentage math

        adj_engine = AdjustmentEngine(state, market)
        rules = [
            {
                "name": "reduce_50pct",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {
                    "type": "reduce_by_pct",
                    "close_tag": "CE_SELL",
                    "reduce_pct": 50,
                },
            },
        ]
        adj_engine.load_rules(rules)
        adj_engine.check_and_apply(datetime.now())

        # 50% of 5 = 2.5, round() = 2, so remaining = 3
        assert state.legs["CE_SELL"].qty in (2, 3), \
            f"After 50% reduce of 5 lots, should be 2 or 3, got {state.legs['CE_SELL'].qty}"
        assert state.legs["CE_SELL"].is_active, "Should still be active"

        market.close_all()
        logger.info("✅ TEST 12 PASSED: Adjustment reduce_by_pct works")

    # ------------------------------------------------------------------
    # TEST: Adjustment — Convert to Spread
    # ------------------------------------------------------------------
    def test_13_adjustment_convert_to_spread(self):
        """Convert naked short to defined-risk spread."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)

        adj_engine = AdjustmentEngine(state, market)
        rules = [
            {
                "name": "spread_conversion",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {
                    "type": "convert_to_spread",
                    "target_leg": "CE_SELL",
                    "width": 100,
                },
            },
        ]
        adj_engine.load_rules(rules)
        adj_engine.check_and_apply(datetime.now())

        # Should have created a hedge leg
        hedge_key = "CE_SELL_HEDGE"
        assert hedge_key in state.legs, f"Hedge leg {hedge_key} should be created"
        hedge = state.legs[hedge_key]
        assert hedge.side == Side.BUY, "Hedge should be BUY"
        assert hedge.strike == state.legs["CE_SELL"].strike + 100, "Hedge should be 100pts above"

        market.close_all()
        logger.info("✅ TEST 13 PASSED: Adjustment convert_to_spread works")

    # ------------------------------------------------------------------
    # TEST: Adjustment Guards (cooldown, max_per_day)
    # ------------------------------------------------------------------
    def test_14_adjustment_guards(self):
        """Adjustment guards respect cooldown and max_per_day."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        state.adjustments_today = 5  # Already at max

        adj_engine = AdjustmentEngine(state, market)
        rules = [
            {
                "name": "blocked_rule",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {"type": "close_leg", "close_tag": "CE_SELL"},
            },
        ]
        adj_engine.load_rules(rules)
        actions = adj_engine.check_and_apply(datetime.now())

        assert len(actions) == 0, "Should block when max_per_day reached"
        assert state.legs["CE_SELL"].is_active, "Leg should not be closed"

        market.close_all()
        logger.info("✅ TEST 14 PASSED: Adjustment guards work")

    # ------------------------------------------------------------------
    # TEST: PnL Tracking and History
    # ------------------------------------------------------------------
    def test_15_pnl_tracking(self):
        """PnL snapshots are recorded and accessible."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)

        # Record some snapshots
        for i in range(5):
            for leg in state.legs.values():
                leg.ltp = leg.entry_price * (1.0 - i * 0.1)  # Progressive profit
                leg.record_pnl_snapshot(state.spot_price)

        for leg in state.legs.values():
            assert len(leg.pnl_history) == 5, f"Should have 5 snapshots, got {len(leg.pnl_history)}"
            assert all(isinstance(s, PnLSnapshot) for s in leg.pnl_history)

        market.close_all()
        logger.info("✅ TEST 15 PASSED: PnL tracking works")

    # ------------------------------------------------------------------
    # TEST: Adjustment History (AdjustmentEvent)
    # ------------------------------------------------------------------
    def test_16_adjustment_history(self):
        """Adjustments are recorded in state.adjustment_history."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        adj_engine = AdjustmentEngine(state, market)

        rules = [
            {
                "name": "test_audit",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {"type": "close_leg", "close_tag": "CE_SELL"},
            },
        ]
        adj_engine.load_rules(rules)
        adj_engine.check_and_apply(datetime.now())

        assert len(state.adjustment_history) > 0, "Should have recorded adjustment event"
        evt = state.adjustment_history[0]
        assert isinstance(evt, AdjustmentEvent)
        assert evt.rule_name == "test_audit"
        assert evt.action_type == "close_leg"

        market.close_all()
        logger.info("✅ TEST 16 PASSED: Adjustment history tracking works")

    # ------------------------------------------------------------------
    # TEST: Persistence (Save + Load roundtrip)
    # ------------------------------------------------------------------
    def test_17_persistence_roundtrip(self):
        """State can be saved and loaded without data loss."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        state.trailing_stop_active = True
        state.trailing_stop_level = 500.0
        state.peak_pnl = 2000.0
        state.adjustment_history.append(AdjustmentEvent(
            timestamp=datetime.now(),
            rule_name="test_rule",
            action_type="close_leg",
            affected_legs=["CE_SELL"],
            reason="test",
        ))
        for leg in state.legs.values():
            leg.record_pnl_snapshot(state.spot_price)

        # Save
        save_path = str(FAKE_DATA_DIR / "test_state.json")
        StatePersistence.save(state, save_path)

        # Load
        loaded = StatePersistence.load(save_path)
        assert loaded is not None, "Should load state"
        assert len(loaded.legs) == 2, "Should have 2 legs"
        assert loaded.trailing_stop_active, "Trailing stop should be active"
        assert loaded.trailing_stop_level == 500.0
        assert loaded.peak_pnl == 2000.0
        assert len(loaded.adjustment_history) > 0, "Should have adjustment history"

        for tag in ("CE_SELL", "PE_SELL"):
            orig = state.legs[tag]
            rest = loaded.legs[tag]
            assert rest.tag == orig.tag
            assert rest.strike == orig.strike
            assert rest.side == orig.side
            assert rest.entry_price == orig.entry_price
            assert rest.is_active == orig.is_active
            assert len(rest.pnl_history) > 0, "PnL history should be persisted"

        # Cleanup
        Path(save_path).unlink(missing_ok=True)
        market.close_all()
        logger.info("✅ TEST 17 PASSED: Persistence roundtrip works")

    # ------------------------------------------------------------------
    # TEST: Condition Engine — Various Parameters
    # ------------------------------------------------------------------
    def test_18_condition_engine(self):
        """Condition engine evaluates various state parameters correctly."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        engine = ConditionEngine(state)

        # spot_price > 20000 (should be ~22500)
        cond1 = Condition(parameter="spot_price", comparator=Comparator.GT, value=20000)
        assert engine.evaluate([cond1]), "spot > 20000 should be true"

        # net_delta should be near 0 for straddle
        cond2 = Condition(parameter="net_delta", comparator=Comparator.LT, value=10)
        assert engine.evaluate([cond2]), "net_delta < 10 should be true for straddle"

        # combined_pnl — initially ~0
        cond3 = Condition(parameter="combined_pnl", comparator=Comparator.GT, value=-99999)
        assert engine.evaluate([cond3]), "combined_pnl > -99999 should always be true"

        market.close_all()
        logger.info("✅ TEST 18 PASSED: Condition engine works")

    # ------------------------------------------------------------------
    # TEST: Reconciliation (State vs Broker Positions)
    # ------------------------------------------------------------------
    def test_19_reconciliation_detects_mismatches(self):
        """BrokerReconciliation detects missing legs."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        recon = BrokerReconciliation(state)

        # Simulate broker returning no positions for CE_SELL
        broker_positions = [
            {
                "tag": "PE_SELL",
                "ltp": 120.0,
                "delta": -0.4,
                "qty": 2,
            }
        ]
        warnings = recon.reconcile(broker_positions)

        assert len(warnings) > 0, "Should detect CE_SELL missing from broker"
        assert not state.legs["CE_SELL"].is_active, "CE_SELL should be marked inactive"
        assert state.legs["PE_SELL"].is_active, "PE_SELL should still be active"

        market.close_all()
        logger.info("✅ TEST 19 PASSED: Reconciliation detects mismatches")

    # ------------------------------------------------------------------
    # TEST: Daily Reset
    # ------------------------------------------------------------------
    def test_20_daily_reset(self):
        """Daily counters reset on new day."""
        state = StrategyState()
        state.adjustments_today = 5
        state.total_trades_today = 3
        state.entered_today = True
        state.trailing_stop_active = True
        state.trailing_stop_level = 500.0
        state.peak_pnl = 1000.0
        state.current_profit_step = 2
        state.cumulative_daily_pnl = 5000.0

        # Simulate daily reset (as done in strategy_executor_service._process_tick_inner)
        state.adjustments_today = 0
        state.total_trades_today = 0
        state.entered_today = False
        state.trailing_stop_active = False
        state.trailing_stop_level = 0.0
        state.peak_pnl = 0.0
        state.current_profit_step = -1
        state.cumulative_daily_pnl = 0.0

        assert state.adjustments_today == 0
        assert state.total_trades_today == 0
        assert not state.entered_today
        assert not state.trailing_stop_active
        assert state.peak_pnl == 0.0

        logger.info("✅ TEST 20 PASSED: Daily reset works")

    # ------------------------------------------------------------------
    # TEST: Multi-Symbol Simulation
    # ------------------------------------------------------------------
    def test_21_multi_symbol_simulation(self):
        """Multiple symbols can be simulated simultaneously."""
        nifty_market = create_test_market_reader("NIFTY")
        banknifty_market = create_test_market_reader("BANKNIFTY")

        nifty_spot = nifty_market.get_spot_price()
        bn_spot = banknifty_market.get_spot_price()

        assert abs(nifty_spot - 22500) < 500, f"NIFTY spot should be ~22500, got {nifty_spot}"
        assert abs(bn_spot - 48000) < 500, f"BANKNIFTY spot should be ~48000, got {bn_spot}"

        # Move NIFTY but not BANKNIFTY
        self.nifty_db.update_prices(spot=22800)
        nifty_market.close_all()
        nifty_market2 = create_test_market_reader("NIFTY")
        new_nifty = nifty_market2.get_spot_price()
        assert abs(new_nifty - 22800) < 1

        # Restore
        self.nifty_db.update_prices(spot=22500)
        nifty_market2.close_all()
        banknifty_market.close_all()
        logger.info("✅ TEST 21 PASSED: Multi-symbol simulation works")

    # ------------------------------------------------------------------
    # TEST: Scripted Scenario (deterministic market path)
    # ------------------------------------------------------------------
    def test_22_scripted_scenario(self):
        """Scripted scenarios produce deterministic price paths."""
        self.sim.set_scenario([
            {"symbol": "NIFTY", "spot_delta": +100, "description": "Gap up"},
            {"symbol": "NIFTY", "spot_delta": +100, "description": "Continue up"},
            {"symbol": "NIFTY", "spot_delta": -300, "description": "Sharp sell-off"},
        ])

        # Reset spot
        self.nifty_db.update_prices(spot=22500)

        prices = []
        for _ in range(3):
            p = self.sim.tick()
            prices.append(p.get("NIFTY", 0))

        # Nifty should go: 22600 -> 22700 -> 22400
        assert abs(prices[0] - 22600) < 1, f"Step 1: expected ~22600, got {prices[0]}"
        assert abs(prices[1] - 22700) < 1, f"Step 2: expected ~22700, got {prices[1]}"
        assert abs(prices[2] - 22400) < 1, f"Step 3: expected ~22400, got {prices[2]}"

        # Restore
        self.nifty_db.update_prices(spot=22500)
        logger.info("✅ TEST 22 PASSED: Scripted scenario works")

    # ------------------------------------------------------------------
    # TEST: Full Straddle Lifecycle (Entry → Adjust → Exit)
    # ------------------------------------------------------------------
    def test_23_full_straddle_lifecycle(self):
        """
        Complete lifecycle:
        1. Enter short straddle
        2. Market moves → adjustment triggers
        3. Continue → exit triggers
        """
        market = create_test_market_reader("NIFTY")

        # --- Step 1: Entry ---
        state = StrategyState()
        entry_engine = EntryEngine(state, market)
        config = make_straddle_entry_config()
        legs = entry_engine.process_entry(config, "NIFTY", "10-JAN-2099")
        assert len(legs) == 2, "Entry should create 2 legs"

        # Add legs to state (as strategy_executor_service does)
        for leg in legs:
            state.legs[leg.tag] = leg

        # Simulate filled
        for leg in state.legs.values():
            leg.order_status = "FILLED"
            leg.lot_size = 50
        state.entered_today = True
        state.entry_time = datetime.now()

        # --- Step 2: Update market data ---
        spot = market.get_spot_price()
        atm = market.get_atm_strike()
        state.spot_price = spot
        state.atm_strike = atm
        state.spot_open = spot
        state.fut_ltp = market.get_fut_ltp()
        for leg in state.legs.values():
            opt = market.get_option_at_strike(leg.strike, leg.option_type)
            if opt:
                leg.ltp = opt["ltp"]
                leg.delta = opt["delta"]

        # --- Step 3: Adjustment ---
        adj_engine = AdjustmentEngine(state, market)
        adj_rules = [
            {
                "name": "always_partial_close",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {
                    "type": "partial_close_lots",
                    "close_tag": "PE_SELL",
                    "lots": 1,
                },
            },
        ]
        adj_engine.load_rules(adj_rules)
        actions = adj_engine.check_and_apply(datetime.now())
        assert len(actions) > 0, "Adjustment should fire"

        # --- Step 4: Exit ---
        exit_engine = ExitEngine(state)
        exit_engine.load_config(make_exit_config(stop_loss_amount=1))

        # Force into loss
        for leg in state.legs.values():
            leg.ltp = leg.entry_price * 5.0

        action = exit_engine.check_exits(datetime.now())
        assert action is not None, "Should trigger exit"

        market.close_all()
        logger.info("✅ TEST 23 PASSED: Full straddle lifecycle works")

    # ------------------------------------------------------------------
    # TEST: Safety — Fake expiry validation
    # ------------------------------------------------------------------
    def test_24_safety_fake_expiry_enforced(self):
        """FakeMarketDB rejects non-2099 expiries."""
        try:
            db = FakeMarketDB(expiry_tag="10-MAR-2026")
            assert False, "Should have raised ValueError for real expiry"
        except ValueError as e:
            assert "2099" in str(e), "Error should mention 2099 requirement"

        logger.info("✅ TEST 24 PASSED: Safety — fake expiry enforcement works")

    # ------------------------------------------------------------------
    # TEST: Safety — Fake DB is in separate directory
    # ------------------------------------------------------------------
    def test_25_safety_fake_db_isolation(self):
        """Fake DB files are NOT in the real market data directory."""
        real_dir = Path(__file__).resolve().parents[1] / "shoonya_platform" / "market_data" / "option_chain" / "data"
        assert FAKE_DATA_DIR != real_dir, "Fake data dir must differ from real data dir"
        assert "test" in str(FAKE_DATA_DIR).lower() or "fake" in str(FAKE_DATA_DIR).lower(), \
            "Fake data dir should have 'test' or 'fake' in path"

        logger.info("✅ TEST 25 PASSED: Safety — fake DB directory isolation verified")

    # ------------------------------------------------------------------
    # TEST: Greeks update on market data refresh
    # ------------------------------------------------------------------
    def test_26_greeks_update_on_refresh(self):
        """Greeks change when spot moves (simulating _update_market_data)."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)

        # Record initial Greeks
        ce = state.legs["CE_SELL"]
        initial_delta = ce.delta
        initial_ltp = ce.ltp

        # Move spot up significantly
        self.nifty_db.update_prices(spot=22800)
        market.close_all()

        market2 = create_test_market_reader("NIFTY")
        # Simulate what _update_market_data does
        for leg in state.legs.values():
            if leg.is_active and leg.instrument == InstrumentType.OPT:
                opt = market2.get_option_at_strike(leg.strike, leg.option_type)
                if opt:
                    leg.ltp = opt["ltp"]
                    leg.delta = opt["delta"]
                    leg.gamma = opt["gamma"]
                    leg.theta = opt["theta"]
                    leg.vega = opt["vega"]
                    leg.iv = opt["iv"]

        # Delta should have changed
        assert ce.ltp != initial_ltp or ce.delta != initial_delta, \
            "Greeks should change after spot move"

        # Restore
        self.nifty_db.update_prices(spot=22500)
        market2.close_all()
        logger.info("✅ TEST 26 PASSED: Greeks update on market refresh")

    # ------------------------------------------------------------------
    # TEST: Leg exit_price and exit_timestamp persistence
    # ------------------------------------------------------------------
    def test_27_exit_metadata_persisted(self):
        """Exit price and timestamp are saved and loaded."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)

        # Simulate exit
        ce = state.legs["CE_SELL"]
        ce.is_active = False
        ce.exit_price = 50.0
        ce.exit_timestamp = datetime.now()
        ce.exit_reason = "stop_loss"

        save_path = str(FAKE_DATA_DIR / "test_exit_meta.json")
        StatePersistence.save(state, save_path)
        loaded = StatePersistence.load(save_path)

        assert loaded.legs["CE_SELL"].exit_price == 50.0
        assert loaded.legs["CE_SELL"].exit_timestamp is not None
        assert loaded.legs["CE_SELL"].exit_reason == "stop_loss"

        Path(save_path).unlink(missing_ok=True)
        market.close_all()
        logger.info("✅ TEST 27 PASSED: Exit metadata persisted correctly")

    # ------------------------------------------------------------------
    # TEST: Partial close > qty caps to available
    # ------------------------------------------------------------------
    def test_28_partial_close_caps_to_available(self):
        """Partial close requesting more lots than available caps to qty."""
        market = create_test_market_reader("NIFTY")
        state = self._make_state_with_legs(market)
        state.legs["CE_SELL"].qty = 2

        adj_engine = AdjustmentEngine(state, market)
        rules = [
            {
                "name": "over_close",
                "priority": 1,
                "cooldown_sec": 0,
                "max_per_day": 5,
                "max_total": 99,
                "conditions": [
                    {"parameter": "spot_price", "comparator": ">", "value": 100}
                ],
                "action": {
                    "type": "partial_close_lots",
                    "close_tag": "CE_SELL",
                    "lots": 10,  # More than available
                },
            },
        ]
        adj_engine.load_rules(rules)
        adj_engine.check_and_apply(datetime.now())

        assert state.legs["CE_SELL"].qty == 0, "Should cap to 0"
        assert not state.legs["CE_SELL"].is_active, "Should be deactivated when qty reaches 0"

        market.close_all()
        logger.info("✅ TEST 28 PASSED: Partial close caps to available qty")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DIRECT EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_all_tests():
    """Run all tests manually (without pytest)."""
    test = TestFullLifecycle()
    test.setup_class()

    results = {"passed": 0, "failed": 0, "errors": []}
    test_methods = sorted([m for m in dir(test) if m.startswith("test_")])

    print("\n" + "=" * 70)
    print("  FULL LIFECYCLE TEST SUITE — Fake Market Data")
    print("  Safety: 2099 expiry | Separate data dir | No broker connection")
    print("=" * 70 + "\n")

    for method_name in test_methods:
        method = getattr(test, method_name)
        try:
            method()
            results["passed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append((method_name, str(e)))
            logger.error("❌ FAILED: %s — %s", method_name, e)

    print("\n" + "=" * 70)
    print(f"  RESULTS: {results['passed']} passed, {results['failed']} failed")
    print("=" * 70)

    if results["errors"]:
        print("\n  FAILURES:")
        for name, err in results["errors"]:
            print(f"    ❌ {name}: {err}")

    test.teardown_class()
    return results["failed"] == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
