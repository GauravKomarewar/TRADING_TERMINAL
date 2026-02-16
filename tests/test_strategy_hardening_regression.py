import os
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock

os.environ.setdefault("DASHBOARD_PASSWORD", "test-pass")
os.environ.setdefault("DASHBOARD_USERNAME", "test-user")

from shoonya_platform.api.dashboard.api.router import get_live_positions_overview
from shoonya_platform.execution.trading_bot import ShoonyaBot
from shoonya_platform.strategy_runner.strategy_executor_service import (
    ExecutionState,
    StrategyExecutorService,
)


def test_shutdown_handles_none_strategy_runner_without_error():
    bot = ShoonyaBot.__new__(ShoonyaBot)
    bot._shutdown_event = threading.Event()
    bot.order_watcher = Mock()
    bot.option_supervisor = Mock()
    bot.strategy_runner = None  # Legacy path disabled
    bot.strategy_executor_service = Mock()
    bot.telegram_enabled = False
    bot.api = Mock()
    bot.trade_records = []

    bot.shutdown()

    bot.order_watcher.stop.assert_called_once()
    bot.strategy_executor_service.stop.assert_called_once()
    bot.api.logout.assert_called_once()


def test_roll_leg_noop_same_symbol_skips_alert_submission():
    svc = StrategyExecutorService.__new__(StrategyExecutorService)
    svc.bot = Mock()
    svc.bot.process_alert = Mock()
    svc.state_mgr = Mock()

    exec_state = ExecutionState(
        strategy_name="s1",
        run_id="r1",
        has_position=True,
        ce_symbol="CRUDEOILM17FEB26C5850",
        ce_side="SELL",
        ce_qty=50,
        ce_entry_price=120.0,
        ce_strike=5850.0,
    )

    reader = Mock()
    reader.find_option_by_delta.return_value = {
        "trading_symbol": "CRUDEOILM17FEB26C5850",  # same symbol -> no-op
        "strike": 5850.0,
        "ltp": 118.0,
    }

    ok = StrategyExecutorService._adjustment_roll_leg(
        svc,
        name="s1",
        exec_state=exec_state,
        engine_state=Mock(),
        leg="CE",
        config={"basic": {"exchange": "MCX"}},
        reader=reader,
        qty=50,
    )

    assert ok is True
    assert exec_state.ce_symbol == "CRUDEOILM17FEB26C5850"
    svc.bot.process_alert.assert_not_called()


def test_monitor_payload_contains_runtime_and_leg_consistency_fields():
    now = datetime.now()
    bot = Mock()
    bot._live_strategies_lock = threading.RLock()
    bot._live_strategies = {"demo_strategy": {}}

    svc = Mock()
    svc._exec_states = {}
    svc._engine_states = {}
    svc._strategies = {}
    svc.get_strategy_leg_monitor_snapshot.return_value = {
        "demo_strategy": {
            "active_legs": 1,
            "closed_legs": 1,
            "realized_pnl": 12.5,
            "unrealized_pnl": -2.0,
            "legs": [
                {
                    "symbol": "NIFTY17FEB26C25750",
                    "status": "ACTIVE",
                    "side": "SELL",
                    "qty": 50,
                    "source": "ENTRY",
                    "realized_pnl": 0.0,
                    "unrealized_pnl": -2.0,
                    "delta": -0.42,
                    "gamma": 0.01,
                    "theta": -0.03,
                    "vega": 0.06,
                    "opened_at": (now - timedelta(minutes=3)).isoformat(),
                    "updated_at": now.isoformat(),
                },
                {
                    "symbol": "NIFTY17FEB26P25650",
                    "status": "CLOSED",
                    "side": "SELL",
                    "qty": 50,
                    "source": "ADJUSTMENT_ROLL",
                    "realized_pnl": 12.5,
                    "unrealized_pnl": 0.0,
                    "delta": 0.0,
                    "gamma": 0.0,
                    "theta": 0.0,
                    "vega": 0.0,
                    "opened_at": (now - timedelta(minutes=5)).isoformat(),
                    "closed_at": (now - timedelta(minutes=1)).isoformat(),
                    "updated_at": (now - timedelta(minutes=1)).isoformat(),
                },
            ],
        }
    }
    bot.strategy_executor_service = svc

    broker = Mock()
    broker.get_positions.return_value = []
    system = Mock()
    system.get_orders.return_value = []

    payload = get_live_positions_overview(
        ctx={"bot": bot},
        broker=broker,
        system=system,
    )

    assert "summary" in payload
    assert payload["summary"]["portfolio_realized_pnl"] == 12.5
    assert payload["summary"]["portfolio_unrealized_pnl"] == -2.0
    assert payload["summary"]["portfolio_total_pnl"] == 10.5

    groups = payload["strategy_groups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["strategy_name"] == "demo_strategy"
    assert g["active_legs"] == 1
    assert g["closed_legs"] == 1
    assert len(g["active_leg_rows"]) == 1
    assert len(g["closed_leg_rows"]) == 1
    assert g["runtime_seconds"] >= 0
    assert "analytics" in g
    assert g["analytics"]["win_legs"] == 1
