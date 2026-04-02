"""
Tests for strategy run isolation: every completed run (SL or PT or time exit)
must cleanly unregister so orphan legs never leak into the next run.

Validates fixes for:
- SL exit with allow_reentry=False must set cycle_completed=True → strategy unregisters
- SL exit with allow_reentry=True must keep cycle_completed=False → strategy re-enters
- After unregistration, monitor rows must be cleared
- ltp=0 on state restore must not trigger false profit target
"""
import json
import tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from shoonya_platform.strategy_runner.state import StrategyState, LegState, Side, InstrumentType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executor(bot, name="test_strategy", config=None):
    from shoonya_platform.strategy_runner.strategy_executor_service import PerStrategyExecutor
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader

    if config is None:
        config = {
            "identity": {
                "exchange": "NFO", "underlying": "NIFTY", "product_type": "MIS",
                "lots": 1, "paper_mode": True, "test_mode": "SUCCESS",
            },
            "entry": {"legs": []},
            "exit": {
                "stop_loss": {"amount": 3000, "allow_reentry": False, "action": "exit_all"},
                "profit_target": {"amount": 20000, "action": "exit_all"},
                "time": {"strategy_exit_time": "15:28"},
            },
            "adjustment": {"rules": []},
            "timing": {
                "entry_window_start": "09:25",
                "entry_window_end": "14:00",
                "eod_exit_time": "15:10",
            },
            "schedule": {},
        }
    # Ensure bot has process_alert (needed by _execute_exit in paper mode)
    if not hasattr(bot, "process_alert"):
        bot.process_alert = MagicMock(return_value={"status": "MOCK_EXECUTED"})

    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        executor = PerStrategyExecutor(
            name=name, config=config, bot=bot, state_db_path=str(Path(td) / "state.db"),
        )
        yield executor


def _make_leg(tag, symbol, side=Side.SELL, qty=1, entry_price=100.0, ltp=90.0, is_active=True):
    """Helper to create a LegState with all required fields."""
    from shoonya_platform.strategy_runner.state import OptionType
    opt_type = OptionType.CE if symbol.endswith(("C23000", "CE")) else OptionType.PE
    return LegState(
        tag=tag,
        symbol=symbol,
        instrument=InstrumentType.OPT,
        option_type=opt_type,
        strike=23000.0 if opt_type == OptionType.CE else 21000.0,
        expiry="2026-04-28",
        side=side,
        qty=qty,
        entry_price=entry_price,
        ltp=ltp,
        is_active=is_active,
    )


def _add_active_legs(executor, entry_price=100.0, ltp=90.0):
    """Add two active SELL legs to the executor state."""
    executor.state.legs["LEG@1_CE"] = _make_leg("LEG@1_CE", "NIFTY28APR26C23000", entry_price=entry_price, ltp=ltp)
    executor.state.legs["LEG@2_PE"] = _make_leg("LEG@2_PE", "NIFTY28APR26P21000", entry_price=entry_price, ltp=ltp)
    executor.state.entered_today = True


# ---------------------------------------------------------------------------
# Test 1: SL exit with allow_reentry=False sets cycle_completed=True
# ---------------------------------------------------------------------------

def test_sl_exit_no_reentry_sets_cycle_completed(bot):
    """
    CRITICAL BUG FIX: When SL fires and allow_reentry=False, cycle_completed
    must be set True so _run_loop unregisters the strategy cleanly.
    Without this fix, the strategy stays registered forever and its closed
    legs mix into the next day's run as orphan positions.
    """
    for executor in _make_executor(bot, name="test_sl_no_reentry"):
        _add_active_legs(executor)
        assert executor.cycle_completed is False

        # Simulate SL exit: mark exit_engine reason, then call _execute_exit
        executor.exit_engine.last_exit_reason = "stop_loss_amount:3000"
        executor._execute_exit("exit_all", source="exit_all")

        assert executor.cycle_completed is True, (
            "_execute_exit with SL and allow_reentry=False must set cycle_completed=True"
        )
        assert executor.state.entered_today is True, "entered_today must be True to block re-entry"
        assert not executor.state.any_leg_active, "All legs must be inactive after exit"


# ---------------------------------------------------------------------------
# Test 2: SL exit with allow_reentry=True keeps cycle_completed=False
# ---------------------------------------------------------------------------

def test_sl_exit_with_reentry_keeps_cycle_not_completed(bot):
    """
    When SL fires with allow_reentry=True, the strategy should stay registered
    and be able to re-enter at the next opportunity.
    """
    config = {
        "identity": {
            "exchange": "NFO", "underlying": "NIFTY", "product_type": "MIS",
            "lots": 1, "paper_mode": True, "test_mode": "SUCCESS",
        },
        "entry": {"legs": []},
        "exit": {
            "stop_loss": {"amount": 3000, "allow_reentry": True, "action": "exit_all"},
            "time": {"strategy_exit_time": "15:28"},
        },
        "adjustment": {"rules": []},
        "timing": {"entry_window_start": "09:25", "entry_window_end": "14:00", "eod_exit_time": "15:10"},
        "schedule": {},
    }
    for executor in _make_executor(bot, name="test_sl_reentry", config=config):
        _add_active_legs(executor)
        assert executor.cycle_completed is False

        executor.exit_engine.last_exit_reason = "stop_loss_amount:3000"
        executor._execute_exit("exit_all", source="exit_all")

        assert executor.cycle_completed is False, (
            "With allow_reentry=True, cycle_completed must stay False so strategy can re-enter"
        )
        assert executor.state.entered_today is False, "entered_today must be False to allow re-entry"


# ---------------------------------------------------------------------------
# Test 3: Profit target exit always sets cycle_completed=True
# ---------------------------------------------------------------------------

def test_profit_target_exit_sets_cycle_completed(bot):
    """Non-SL exits (profit target, time exit) always set cycle_completed=True."""
    for executor in _make_executor(bot, name="test_pt_exit"):
        _add_active_legs(executor)
        executor.exit_engine.last_exit_reason = "profit_target_amount:20000"
        executor._execute_exit("exit_all", source="exit_all")

        assert executor.cycle_completed is True
        assert executor.state.entered_today is True


# ---------------------------------------------------------------------------
# Test 4: ltp=0 must not yield a false large PnL for SELL legs
# ---------------------------------------------------------------------------

def test_sell_leg_pnl_zero_when_ltp_is_zero():
    """
    When ltp is 0 (not yet received), pnl must return 0 so profit-target
    is not falsely triggered.  This was the root cause of the false 'profit
    target at 20000' after auto-resume when ltp defaulted to 0.0.
    """
    from shoonya_platform.strategy_runner.state import OptionType
    leg = LegState(
        tag="LEG@1_CE",
        symbol="NIFTY28APR26C23000",
        instrument=InstrumentType.OPT,
        option_type=OptionType.CE,
        strike=23000.0,
        expiry="2026-04-28",
        side=Side.SELL,
        qty=65,
        entry_price=100.0,
        ltp=0.0,
    )
    assert leg.pnl == 0.0, (
        f"ltp=0 should return pnl=0 for SELL leg, got {leg.pnl}"
    )


def test_sell_leg_pnl_zero_when_ltp_is_none():
    """ltp=None should also return pnl=0."""
    from shoonya_platform.strategy_runner.state import OptionType
    leg = LegState(
        tag="LEG@1_PE",
        symbol="NIFTY28APR26P21000",
        instrument=InstrumentType.OPT,
        option_type=OptionType.PE,
        strike=21000.0,
        expiry="2026-04-28",
        side=Side.SELL,
        qty=65,
        entry_price=150.0,
        ltp=None,  # type: ignore[arg-type]
    )
    # LegState should treat None the same as 0 (no tick received yet)
    assert leg.pnl == 0.0, (
        f"ltp=None should return pnl=0 for SELL leg, got {leg.pnl}"
    )


def test_buy_leg_pnl_zero_when_ltp_is_zero():
    """BUY leg with ltp=0 should also return pnl=0 (not negative)."""
    from shoonya_platform.strategy_runner.state import OptionType
    leg = LegState(
        tag="LEG@1_BUY",
        symbol="NIFTY28APR26C23000",
        instrument=InstrumentType.OPT,
        option_type=OptionType.CE,
        strike=23000.0,
        expiry="2026-04-28",
        side=Side.BUY,
        qty=65,
        entry_price=100.0,
        ltp=0.0,
    )
    assert leg.pnl == 0.0, (
        f"ltp=0 should return pnl=0 for BUY leg, got {leg.pnl}"
    )


def test_combined_pnl_zero_when_all_ltp_zero():
    """StrategyState.combined_pnl must be 0 when all legs have ltp=0."""
    from shoonya_platform.strategy_runner.state import OptionType
    state = StrategyState()
    state.legs["LEG@1_CE"] = LegState(
        tag="LEG@1_CE", symbol="S1",
        instrument=InstrumentType.OPT, option_type=OptionType.CE,
        strike=23000.0, expiry="2026-04-28",
        side=Side.SELL, qty=1, entry_price=100.0, ltp=0.0,
    )
    state.legs["LEG@2_PE"] = LegState(
        tag="LEG@2_PE", symbol="S2",
        instrument=InstrumentType.OPT, option_type=OptionType.PE,
        strike=21000.0, expiry="2026-04-28",
        side=Side.SELL, qty=1, entry_price=150.0, ltp=0.0,
    )
    assert state.combined_pnl == 0.0, (
        f"combined_pnl with ltp=0 legs must be 0, got {state.combined_pnl}"
    )


# ---------------------------------------------------------------------------
# Test 5: False profit target at restart does not fire when ltp=0
# ---------------------------------------------------------------------------

def test_no_false_profit_target_on_ltp_zero_resume(bot):
    """
    Regression: after restart when ltp=0, the profit target (₹20,000) must
    NOT fire because combined_pnl is 0, not a large positive value.
    """
    for executor in _make_executor(bot, name="test_no_false_pt"):
        # Simulate post-restart state: active legs but ltp not yet received (0.0)
        _add_active_legs(executor, entry_price=100.0, ltp=0.0)
        executor.state.entered_today = True

        # Check profit target via exit engine
        from shoonya_platform.strategy_runner.exit_engine import ExitEngine
        executor.exit_engine.load_config(
            executor.config.get("exit", {})
        )
        action = executor.exit_engine._check_profit_target()
        assert action is None, (
            f"Profit target must NOT fire when ltp=0 (pnl=0), but got action={action}"
        )


# ---------------------------------------------------------------------------
# Test 6: Strategy isolation — two strategies don't share state
# ---------------------------------------------------------------------------

def test_two_strategies_isolated_state(bot):
    """Each strategy must have its own StrategyState — no shared references."""
    with tempfile.TemporaryDirectory() as td:
        from shoonya_platform.strategy_runner.strategy_executor_service import PerStrategyExecutor
        from shoonya_platform.strategy_runner.market_reader import MockMarketReader

        cfg = {
            "identity": {
                "exchange": "NFO", "underlying": "NIFTY", "product_type": "MIS",
                "lots": 1, "paper_mode": True, "test_mode": "SUCCESS",
            },
            "entry": {"legs": []},
            "exit": {"stop_loss": {"amount": 3000, "allow_reentry": False, "action": "exit_all"}},
            "adjustment": {"rules": []},
            "timing": {"entry_window_start": "09:25", "entry_window_end": "14:00", "eod_exit_time": "15:10"},
            "schedule": {},
        }
        with patch(
            "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
            MockMarketReader,
        ):
            exec_a = PerStrategyExecutor(
                name="strategy_a", config=cfg, bot=bot,
                state_db_path=str(Path(td) / "state_a.db"),
            )
            exec_b = PerStrategyExecutor(
                name="strategy_b", config=cfg, bot=bot,
                state_db_path=str(Path(td) / "state_b.db"),
            )

    # Mutate A's state — B must be unaffected
    exec_a.state.cumulative_daily_pnl = 999.0
    exec_a.cycle_completed = True

    assert exec_b.state.cumulative_daily_pnl == 0.0, "B's PnL must not be affected by A"
    assert exec_b.cycle_completed is False, "B's cycle_completed must not be affected by A"
    assert exec_a.state is not exec_b.state, "Both executors must have separate state objects"
