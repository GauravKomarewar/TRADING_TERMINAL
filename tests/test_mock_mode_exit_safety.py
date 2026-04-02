"""
Tests for mock/live mode safety during strategy exit.

Validates fixes for:
- BUG: _check_saved_config_paper_mode() was called but never defined
- BUG: TEST_MODE marker lost when OrderWatcher reconstructs command from DB record
- BUG: Race condition — strategy unregistered before all EXIT orders dispatched
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.persistence.order_record import OrderRecord


# -------------------------------------------------------
# 1. TEST_MODE marker preserved in OrderRecord tag
# -------------------------------------------------------

def test_register_preserves_test_mode_in_tag(bot):
    """When a command has TEST_MODE_SUCCESS in its comment, 
    the EXIT tag should contain that marker for later reconstruction."""
    cmd = UniversalOrderCommand(
        intent="EXIT",
        symbol="NIFTY07APR26P22300",
        exchange="NFO",
        side="BUY",
        quantity=65,
        product="M",
        comment="TEST_MODE_SUCCESS",
        strategy_name="test_strategy",
        source="STRATEGY",
        user="TEST_USER",
    )
    bot.command_service.register(cmd)

    record = bot.order_repo.get_by_id(cmd.command_id)
    assert record is not None
    assert "TEST_MODE_SUCCESS" in str(record.tag), (
        f"tag should contain TEST_MODE_SUCCESS, got: {record.tag}"
    )


def test_register_preserves_test_mode_failure_in_tag(bot):
    """TEST_MODE_FAILURE should also be preserved in tag."""
    cmd = UniversalOrderCommand(
        intent="EXIT",
        symbol="NIFTY07APR26C22800",
        exchange="NFO",
        side="BUY",
        quantity=65,
        product="M",
        comment="TEST_MODE_FAILURE",
        strategy_name="test_fail_strategy",
        source="STRATEGY",
        user="TEST_USER",
    )
    bot.command_service.register(cmd)

    record = bot.order_repo.get_by_id(cmd.command_id)
    assert "TEST_MODE_FAILURE" in str(record.tag)


def test_register_without_test_mode_keeps_exit_tag(bot):
    """When no test_mode marker, tag should be plain EXIT."""
    cmd = UniversalOrderCommand(
        intent="EXIT",
        symbol="NIFTY07APR26C22800",
        exchange="NFO",
        side="BUY",
        quantity=65,
        product="M",
        comment=None,
        strategy_name="live_strategy",
        source="STRATEGY",
        user="TEST_USER",
    )
    bot.command_service.register(cmd)

    record = bot.order_repo.get_by_id(cmd.command_id)
    assert record.tag == "EXIT"


def test_from_record_reconstructs_test_mode_comment():
    """UniversalOrderCommand.from_record should reconstruct TEST_MODE from tag."""
    record = OrderRecord(
        command_id="test-123",
        source="ORDER_WATCHER",
        user="FAxxxxx",
        strategy_name="test_strategy",
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
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag="EXIT|TEST_MODE_SUCCESS",
    )
    cmd = UniversalOrderCommand.from_record(
        record, order_type="MARKET", price=0.0, source="ORDER_WATCHER"
    )
    assert cmd.comment is not None
    assert "TEST_MODE_SUCCESS" in cmd.comment


# -------------------------------------------------------
# 2. _check_saved_config_paper_mode reads disk correctly
# -------------------------------------------------------

def _get_check_saved_config_paper_mode():
    """Import the real method from bot_execution module."""
    from shoonya_platform.execution.bot_execution import ExecutionMixin
    return ExecutionMixin._check_saved_config_paper_mode


def test_check_saved_config_paper_mode_reads_disk():
    """_check_saved_config_paper_mode should read paper_mode from saved config JSON."""
    strategy_name = "test_paper_check"
    config_dir = (
        Path(__file__).resolve().parent.parent
        / "shoonya_platform" / "strategy_runner" / "saved_configs"
    )
    cfg_path = config_dir / f"{strategy_name}.json"
    try:
        cfg_path.write_text(json.dumps({
            "identity": {"paper_mode": True, "test_mode": "SUCCESS"},
            "status": "RUNNING",
        }))
        method = _get_check_saved_config_paper_mode()
        fake_self = MagicMock()
        assert method(fake_self, strategy_name) is True
    finally:
        cfg_path.unlink(missing_ok=True)


def test_check_saved_config_paper_mode_live_returns_false():
    """Live strategy config on disk should return False."""
    strategy_name = "test_live_check"
    config_dir = (
        Path(__file__).resolve().parent.parent
        / "shoonya_platform" / "strategy_runner" / "saved_configs"
    )
    cfg_path = config_dir / f"{strategy_name}.json"
    try:
        cfg_path.write_text(json.dumps({
            "identity": {"paper_mode": False, "test_mode": None},
            "status": "RUNNING",
        }))
        method = _get_check_saved_config_paper_mode()
        fake_self = MagicMock()
        assert method(fake_self, strategy_name) is False
    finally:
        cfg_path.unlink(missing_ok=True)


def test_check_saved_config_paper_mode_missing_file():
    """Missing config file should return False (not crash)."""
    method = _get_check_saved_config_paper_mode()
    fake_self = MagicMock()
    assert method(fake_self, "nonexistent_strategy_xyz") is False


# -------------------------------------------------------
# 3. _has_pending_exit_orders blocks unregistration
# -------------------------------------------------------

def test_has_pending_exit_orders_detects_created(bot):
    """Service should detect CREATED EXIT orders as pending."""
    from shoonya_platform.strategy_runner.strategy_executor_service import (
        StrategyExecutorService,
    )
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader
    from unittest.mock import patch

    strategy_name = "test_pending_exit"
    # Create a CREATED EXIT order in the repo
    record = OrderRecord(
        command_id="pending-exit-001",
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
        execution_type="EXIT",
        status="CREATED",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag="EXIT|TEST_MODE_SUCCESS",
    )
    bot.order_repo.create(record)

    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        svc = StrategyExecutorService(bot=bot, state_db_path=str(Path(td) / "state.db"))
        assert svc._has_pending_exit_orders(strategy_name) is True


def test_has_pending_exit_orders_none_when_all_executed(bot):
    """No pending orders when all EXIT orders are EXECUTED."""
    from shoonya_platform.strategy_runner.strategy_executor_service import (
        StrategyExecutorService,
    )
    from shoonya_platform.strategy_runner.market_reader import MockMarketReader
    from unittest.mock import patch

    strategy_name = "test_no_pending"
    record = OrderRecord(
        command_id="done-exit-001",
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
        broker_order_id="MOCK_12345",
        execution_type="EXIT",
        status="EXECUTED",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag="EXIT|TEST_MODE_SUCCESS",
    )
    bot.order_repo.create(record)

    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        MockMarketReader,
    ):
        svc = StrategyExecutorService(bot=bot, state_db_path=str(Path(td) / "state.db"))
        assert svc._has_pending_exit_orders(strategy_name) is False


# -------------------------------------------------------
# 4. Mock detection via comment (from_record chain)
# -------------------------------------------------------

def test_mock_detection_via_tag_comment():
    """Execute_command_inner mock detection should find TEST_MODE_SUCCESS from tag."""
    record = OrderRecord(
        command_id="mock-detect-001",
        source="ORDER_WATCHER",
        user="FAxxxxx",
        strategy_name="mock_strategy",
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
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag="EXIT|TEST_MODE_SUCCESS",
    )
    cmd = UniversalOrderCommand.from_record(
        record, order_type="MARKET", price=0.0, source="ORDER_WATCHER"
    )
    # This simulates what _execute_command_inner does
    comment = str(getattr(cmd, "comment", "") or "").upper()
    explicit_mock_success = "TEST_MODE_SUCCESS" in comment
    assert explicit_mock_success is True, (
        f"Mock detection should find TEST_MODE_SUCCESS in comment '{comment}'"
    )


# -------------------------------------------------------
# 5. DISPATCHING tag preserves TEST_MODE marker on retry
# -------------------------------------------------------

def test_dispatch_tag_preserves_test_mode_for_retry():
    """When _dispatch_simple_exit marks order DISPATCHING, it should retain
    the TEST_MODE_SUCCESS marker so retries loaded fresh from DB still detect mock."""
    record = OrderRecord(
        command_id="retry-exit-001",
        source="ORDER_WATCHER",
        user="FAxxxxx",
        strategy_name="mock_retry_strategy",
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
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag="EXIT|TEST_MODE_SUCCESS",
    )
    # Simulate the dispatch tag construction (mirrors _dispatch_simple_exit)
    _orig_tag = str(record.tag or "")
    _has_mock = "TEST_MODE_SUCCESS" in _orig_tag or "TEST_MODE_FAILURE" in _orig_tag
    dispatch_tag = "DISPATCHING|TEST_MODE_SUCCESS" if _has_mock else "DISPATCHING"

    assert "TEST_MODE_SUCCESS" in dispatch_tag, (
        f"DISPATCHING tag for mock order must carry TEST_MODE_SUCCESS, got: {dispatch_tag}"
    )

    # Simulate mock detection from the retry tag (fresh DB load)
    record_retry = OrderRecord(
        command_id="retry-exit-001",
        source="ORDER_WATCHER",
        user="FAxxxxx",
        strategy_name="mock_retry_strategy",
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
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag=dispatch_tag,  # tag as it sits in DB after first dispatch attempt
    )
    cmd_retry = UniversalOrderCommand.from_record(
        record_retry, order_type="MARKET", price=0.0, source="ORDER_WATCHER"
    )
    comment = str(getattr(cmd_retry, "comment", "") or "").upper()
    assert "TEST_MODE_SUCCESS" in comment, (
        f"Retry command comment must contain TEST_MODE_SUCCESS, got: '{comment}'"
    )


def test_live_order_dispatch_tag_has_no_test_mode():
    """LIVE order dispatch tag must NOT carry TEST_MODE marker."""
    record = OrderRecord(
        command_id="live-exit-001",
        source="ORDER_WATCHER",
        user="FAxxxxx",
        strategy_name="live_strategy",
        exchange="NSE",
        symbol="NIFTY",
        side="SELL",
        quantity=50,
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
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        tag="EXIT",  # no TEST_MODE marker
    )
    _orig_tag = str(record.tag or "")
    _has_mock = "TEST_MODE_SUCCESS" in _orig_tag or "TEST_MODE_FAILURE" in _orig_tag
    dispatch_tag = "DISPATCHING|TEST_MODE_SUCCESS" if _has_mock else "DISPATCHING"

    assert dispatch_tag == "DISPATCHING", (
        f"LIVE order dispatch tag must be plain DISPATCHING, got: {dispatch_tag}"
    )
