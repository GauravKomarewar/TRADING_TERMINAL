"""
Tests for daily boundary isolation and cross-midnight safety.

Validates fixes for:
- Guard positions persist across midnight → block next day's ENTRY
- cycle_completed persists across midnight → strategy never re-enters
- Stale CREATED EXIT orders dispatched on next day
- _has_pending_exit_orders counts yesterday's orders as pending
"""
import json
import tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shoonya_platform.persistence.order_record import OrderRecord


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_bot_with_guard(bot):
    """Attach a real ExecutionGuard to the FakeBot fixture."""
    from shoonya_platform.execution.execution_guard import ExecutionGuard
    bot.execution_guard = ExecutionGuard()
    return bot


def _make_executor(bot, name="test_strategy", config=None):
    """Create a PerStrategyExecutor for testing."""
    from shoonya_platform.strategy_runner.strategy_executor_service import (
        PerStrategyExecutor,
    )
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader

    if config is None:
        config = {
            "identity": {"exchange": "NFO", "underlying": "NIFTY", "product_type": "MIS",
                         "lots": 1, "paper_mode": True, "test_mode": "SUCCESS"},
            "entry": {"legs": []},
            "exit": {},
            "adjustment": {"rules": []},
            "timing": {"entry_window_start": "09:25", "entry_window_end": "14:00",
                        "eod_exit_time": "15:10"},
            "schedule": {},
        }
    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        executor = PerStrategyExecutor(
            name=name, config=config, bot=bot, state_db_path=str(Path(td) / "state.db"),
        )
        yield executor


# ---------------------------------------------------------------------------
# 1. Daily reset clears execution guard
# ---------------------------------------------------------------------------

def test_daily_reset_clears_guard(bot):
    """Guard positions from previous day must be cleared on daily reset."""
    bot = _make_bot_with_guard(bot)
    guard = bot.execution_guard

    from shoonya_platform.execution.execution_guard import LegIntent, Position

    strategy_name = "test_daily_guard"

    # Simulate yesterday's entry in the guard
    guard._strategy_positions[strategy_name] = {
        "NIFTY07APR26P22300": Position("NIFTY07APR26P22300", "SELL", 65),
    }
    guard._global_positions["NIFTY07APR26P22300"] = {"SELL": 65}

    assert guard.has_strategy(strategy_name)

    for executor in _make_executor(bot, name=strategy_name):
        # Set _last_date to yesterday so daily reset fires
        executor._last_date = date.today() - timedelta(days=1)
        executor._process_tick_inner()

    # Guard should be cleared
    assert not guard.has_strategy(strategy_name)


# ---------------------------------------------------------------------------
# 2. Daily reset resets cycle_completed
# ---------------------------------------------------------------------------

def test_daily_reset_resets_cycle_completed(bot):
    """cycle_completed from yesterday must be False after daily reset."""
    bot = _make_bot_with_guard(bot)

    for executor in _make_executor(bot, name="test_cycle_reset"):
        executor.cycle_completed = True  # yesterday's exit set this
        executor._last_date = date.today() - timedelta(days=1)
        executor._process_tick_inner()
        assert executor.cycle_completed is False


# ---------------------------------------------------------------------------
# 3. Daily reset expires stale CREATED orders
# ---------------------------------------------------------------------------

def test_daily_reset_expires_stale_orders(bot):
    """CREATED EXIT orders from yesterday must be expired during daily reset."""
    bot = _make_bot_with_guard(bot)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT15:28:00")

    record = OrderRecord(
        command_id="stale-exit-001",
        source="STRATEGY",
        user="TEST",
        strategy_name="test_expire_stale",
        exchange="NFO",
        symbol="NIFTY07APR26C22800",
        side="BUY",
        quantity=65,
        product="M",
        order_type="MARKET",
        price=0.0,
        stop_loss=None,
        target=None,
        trailing_type=None,
        trailing_value=None,
        broker_order_id=None,
        execution_type="EXIT",
        status="CREATED",
        created_at=yesterday,
        updated_at=yesterday,
        tag="EXIT|TEST_MODE_SUCCESS",
    )
    bot.order_repo.create(record)

    # Verify it's initially open
    open_before = bot.order_repo.get_open_orders_by_strategy("test_expire_stale")
    assert len(open_before) >= 1

    for executor in _make_executor(bot, name="test_expire_stale"):
        executor._last_date = date.today() - timedelta(days=1)
        executor._process_tick_inner()

    # After daily reset, the stale order should be expired
    open_after = bot.order_repo.get_open_orders_by_strategy("test_expire_stale")
    stale_remaining = [
        o for o in open_after
        if o.command_id == "stale-exit-001"
    ]
    assert len(stale_remaining) == 0, (
        f"Stale order from yesterday should be expired, but found {len(stale_remaining)}"
    )


# ---------------------------------------------------------------------------
# 4. _has_pending_exit_orders ignores yesterday's orders
# ---------------------------------------------------------------------------

def test_has_pending_exit_orders_ignores_yesterday(bot):
    """Stale CREATED EXIT orders from yesterday should not count as pending."""
    from shoonya_platform.strategy_runner.strategy_executor_service import (
        StrategyExecutorService,
    )
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT15:28:00")
    record = OrderRecord(
        command_id="stale-pending-001",
        source="STRATEGY",
        user="TEST",
        strategy_name="test_pending_yesterday",
        exchange="NFO",
        symbol="NIFTY07APR26P22300",
        side="BUY",
        quantity=65,
        product="M",
        order_type="MARKET",
        price=0.0,
        stop_loss=None,
        target=None,
        trailing_type=None,
        trailing_value=None,
        broker_order_id=None,
        execution_type="EXIT",
        status="CREATED",
        created_at=yesterday,
        updated_at=yesterday,
        tag="EXIT",
    )
    bot.order_repo.create(record)

    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        svc = StrategyExecutorService(bot=bot, state_db_path=str(Path(td) / "state.db"))
        assert svc._has_pending_exit_orders("test_pending_yesterday") is False


def test_has_pending_exit_orders_counts_today(bot):
    """CREATED EXIT orders from today should still count as pending."""
    from shoonya_platform.strategy_runner.strategy_executor_service import (
        StrategyExecutorService,
    )
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader

    today = datetime.now().strftime("%Y-%m-%dT15:28:00")
    record = OrderRecord(
        command_id="today-pending-001",
        source="STRATEGY",
        user="TEST",
        strategy_name="test_pending_today",
        exchange="NFO",
        symbol="NIFTY07APR26P22300",
        side="BUY",
        quantity=65,
        product="M",
        order_type="MARKET",
        price=0.0,
        stop_loss=None,
        target=None,
        trailing_type=None,
        trailing_value=None,
        broker_order_id=None,
        execution_type="EXIT",
        status="CREATED",
        created_at=today,
        updated_at=today,
        tag="EXIT",
    )
    bot.order_repo.create(record)

    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        svc = StrategyExecutorService(bot=bot, state_db_path=str(Path(td) / "state.db"))
        assert svc._has_pending_exit_orders("test_pending_today") is True


# ---------------------------------------------------------------------------
# 5. Dual strategy coexistence (live + mock)
# ---------------------------------------------------------------------------

def test_dual_strategy_same_symbol_no_conflict(bot):
    """Two strategies (live + mock) trading same direction same symbol must coexist."""
    bot = _make_bot_with_guard(bot)
    guard = bot.execution_guard

    from shoonya_platform.execution.execution_guard import LegIntent

    intents_a = [LegIntent("strategy_live", "NIFTY07APR26C22800", "BUY", 65, "ENTRY")]
    intents_b = [LegIntent("strategy_mock", "NIFTY07APR26C22800", "BUY", 65, "ENTRY")]

    # Both should succeed — same direction is allowed
    result_a = guard.validate_and_prepare(intents_a, "ENTRY")
    assert len(result_a) == 1

    result_b = guard.validate_and_prepare(intents_b, "ENTRY")
    assert len(result_b) == 1


def test_dual_strategy_independent_exit(bot):
    """Exiting one strategy should not affect the other."""
    bot = _make_bot_with_guard(bot)
    guard = bot.execution_guard

    from shoonya_platform.execution.execution_guard import LegIntent

    # Both strategies enter
    guard.validate_and_prepare(
        [LegIntent("strat_A", "NIFTY07APR26C22800", "BUY", 65, "ENTRY")], "ENTRY"
    )
    guard.validate_and_prepare(
        [LegIntent("strat_B", "NIFTY07APR26C22800", "BUY", 65, "ENTRY")], "ENTRY"
    )

    # Exit only strat_A
    guard.force_close_strategy("strat_A")

    # strat_B should still be active
    assert guard.has_strategy("strat_B")
    assert not guard.has_strategy("strat_A")

    # strat_A should be able to re-enter
    result = guard.validate_and_prepare(
        [LegIntent("strat_A", "NIFTY07APR26C22800", "BUY", 65, "ENTRY")], "ENTRY"
    )
    assert len(result) == 1
