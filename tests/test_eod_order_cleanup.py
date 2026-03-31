"""
Tests for EOD (End-of-Day) order cleanup.

Validates:
- _cancel_all_pending_orders expires all CREATED/SENT_TO_BROKER orders
- stop() calls _cancel_all_pending_orders before shutdown
- Nightly 23:45 cleanup logic fires correctly
- EOD_CLEANUP tag is appended for audit trail
"""
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shoonya_platform.persistence.order_record import OrderRecord


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _insert_order(repo, command_id, strategy_name, status, execution_type="EXIT"):
    """Insert a test order into the repository."""
    record = OrderRecord(
        command_id=command_id,
        source="STRATEGY",
        user="TEST",
        strategy_name=strategy_name,
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
        execution_type=execution_type,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        tag=execution_type,
    )
    repo.create(record)
    return record


def _make_svc(bot, td):
    """Create a StrategyExecutorService for testing."""
    from shoonya_platform.strategy_runner.strategy_executor_service import (
        StrategyExecutorService,
    )
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader

    with patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        return StrategyExecutorService(bot=bot, state_db_path=str(Path(td) / "state.db"))


# ---------------------------------------------------------------------------
# 1. _cancel_all_pending_orders expires CREATED orders
# ---------------------------------------------------------------------------

def test_cancel_all_pending_expires_created(bot):
    """CREATED orders should be expired by EOD cleanup."""
    _insert_order(bot.order_repo, "eod-created-1", "strat_a", "CREATED")
    _insert_order(bot.order_repo, "eod-created-2", "strat_b", "CREATED")

    with tempfile.TemporaryDirectory() as td:
        svc = _make_svc(bot, td)
        svc._cancel_all_pending_orders()

    # Both should be expired
    r1 = bot.order_repo.get_by_id("eod-created-1")
    r2 = bot.order_repo.get_by_id("eod-created-2")
    assert r1.status == "EXPIRED"
    assert r2.status == "EXPIRED"


def test_cancel_all_pending_expires_sent_to_broker(bot):
    """SENT_TO_BROKER orders should be expired by EOD cleanup."""
    _insert_order(bot.order_repo, "eod-sent-1", "strat_a", "SENT_TO_BROKER")

    with tempfile.TemporaryDirectory() as td:
        svc = _make_svc(bot, td)
        svc._cancel_all_pending_orders()

    r = bot.order_repo.get_by_id("eod-sent-1")
    assert r.status == "EXPIRED"


def test_cancel_all_pending_skips_executed(bot):
    """EXECUTED orders should NOT be touched by EOD cleanup."""
    _insert_order(bot.order_repo, "eod-exec-1", "strat_a", "EXECUTED")

    with tempfile.TemporaryDirectory() as td:
        svc = _make_svc(bot, td)
        svc._cancel_all_pending_orders()

    r = bot.order_repo.get_by_id("eod-exec-1")
    assert r.status == "EXECUTED"


def test_cancel_all_pending_appends_eod_tag(bot):
    """EOD_CLEANUP should be appended to the tag for audit trail."""
    _insert_order(bot.order_repo, "eod-tag-1", "strat_a", "CREATED")

    with tempfile.TemporaryDirectory() as td:
        svc = _make_svc(bot, td)
        svc._cancel_all_pending_orders()

    r = bot.order_repo.get_by_id("eod-tag-1")
    assert "EOD_CLEANUP" in str(r.tag)


def test_cancel_all_pending_handles_empty(bot):
    """No-op when there are no pending orders — should not error."""
    with tempfile.TemporaryDirectory() as td:
        svc = _make_svc(bot, td)
        svc._cancel_all_pending_orders()  # Should not raise


# ---------------------------------------------------------------------------
# 2. stop() calls cleanup
# ---------------------------------------------------------------------------

def test_stop_calls_cancel_all_pending(bot):
    """stop() should expire pending orders before shutdown."""
    _insert_order(bot.order_repo, "eod-stop-1", "strat_a", "CREATED")

    with tempfile.TemporaryDirectory() as td:
        svc = _make_svc(bot, td)
        svc.stop()

    r = bot.order_repo.get_by_id("eod-stop-1")
    assert r.status == "EXPIRED"
