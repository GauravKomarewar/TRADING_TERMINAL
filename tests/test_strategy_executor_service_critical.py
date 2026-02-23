import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from shoonya_platform.strategy_runner.market_reader import MockMarketReader
from shoonya_platform.strategy_runner.models import InstrumentType, OptionType, Side
from shoonya_platform.strategy_runner.state import LegState, StrategyState
from shoonya_platform.strategy_runner.strategy_executor_service import (
    PerStrategyExecutor,
    StrategyExecutorService,
)


class _DummyBot:
    def __init__(self):
        self.alerts = []
        self.config = type("Cfg", (), {"webhook_secret": "x"})()

    def process_alert(self, alert):
        self.alerts.append(alert)
        return {"status": "SUCCESS"}

    def request_exit(self, **kwargs):
        self.alerts.append({"execution_type": "REQUEST_EXIT", **kwargs})
        return {"status": "SUCCESS"}


class _TestMarketReader(MockMarketReader):
    def __init__(self, exchange: str, symbol: str, max_stale_seconds: int = 30):
        super().__init__(exchange=exchange, symbol=symbol)


def _base_config():
    return {
        "name": "svc_critical",
        "identity": {
            "exchange": "NFO",
            "underlying": "NIFTY",
            "product_type": "NRML",
            "order_type": "MARKET",
        },
        "timing": {"entry_window_start": "09:15", "entry_window_end": "15:00"},
        "schedule": {"expiry_mode": "weekly_current", "active_days": ["mon", "tue", "wed", "thu", "fri"]},
        "entry": {"global_conditions": [], "legs": []},
        "adjustment": {"rules": []},
        "exit": {},
    }


def _mk_leg(tag: str, side: Side, qty: int = 1, strike: float = 25000.0):
    return LegState(
        tag=tag,
        symbol="NIFTY",
        instrument=InstrumentType.OPT,
        option_type=OptionType.CE,
        strike=strike,
        expiry="weekly_current",
        side=side,
        qty=qty,
        entry_price=100.0,
        ltp=100.0,
        delta=0.3,
        trading_symbol=f"{tag}_TSYM",
    )


def test_should_enter_respects_active_days():
    cfg = _base_config()
    now = datetime.now()
    today = now.strftime("%a").lower()[:3]
    cfg["schedule"]["active_days"] = [d for d in ["mon", "tue", "wed", "thu", "fri"] if d != today]

    bot = _DummyBot()
    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        _TestMarketReader,
    ):
        ex = PerStrategyExecutor("svc_days", cfg, bot, str(Path(td) / "state.sqlite"))
        ex.state.entered_today = False
        assert ex._should_enter(now) is False


def test_adjustment_dispatch_sends_broker_orders():
    cfg = _base_config()
    bot = _DummyBot()
    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        _TestMarketReader,
    ):
        ex = PerStrategyExecutor("svc_adj", cfg, bot, str(Path(td) / "state.sqlite"))
        ex.state.entered_today = True
        ex.state.legs["L1"] = _mk_leg("L1", Side.SELL, qty=1)

        def _fake_adjust(_now):
            ex.state.legs["L1"].is_active = False
            ex.state.legs["L2"] = _mk_leg("L2", Side.SELL, qty=1, strike=25100.0)
            return ["Rule X: IF triggered"]

        ex.adjustment_engine.check_and_apply = _fake_adjust
        ex.process_tick()

        adj_alerts = [a for a in bot.alerts if a.get("execution_type") == "ADJUSTMENT"]
        assert len(adj_alerts) == 1
        legs = adj_alerts[0]["legs"]
        assert len(legs) == 2
        directions = {l["direction"] for l in legs}
        assert directions == {"BUY", "SELL"}


def test_leg_rule_close_leg_executes_and_updates_state():
    cfg = _base_config()
    cfg["exit"] = {
        "leg_rules": [
            {
                "exit_leg_ref": "all",
                "action": "close_leg",
                "conditions": [{"parameter": "net_delta", "comparator": ">=", "value": -999}],
            }
        ]
    }
    bot = _DummyBot()
    with tempfile.TemporaryDirectory() as td, patch(
        "shoonya_platform.strategy_runner.strategy_executor_service.MarketReader",
        _TestMarketReader,
    ):
        ex = PerStrategyExecutor("svc_leg_exit", cfg, bot, str(Path(td) / "state.sqlite"))
        ex.state.entered_today = True
        ex.state.legs["L1"] = _mk_leg("L1", Side.SELL, qty=2)

        ex.process_tick()

        exit_alerts = [a for a in bot.alerts if a.get("execution_type") == "EXIT"]
        assert len(exit_alerts) == 1
        assert exit_alerts[0]["legs"][0]["direction"] == "BUY"
        assert ex.state.legs["L1"].is_active is False
        assert ex.state.legs["L1"].qty == 0


def test_strategy_leg_monitor_snapshot_exposes_live_leg_metrics():
    bot = _DummyBot()
    with tempfile.TemporaryDirectory() as td:
        svc = StrategyExecutorService(bot=bot, state_db_path=str(Path(td) / "state.sqlite"))
        cfg = _base_config()
        cfg["paper_mode"] = True
        cfg["identity"]["paper_mode"] = True
        cfg["test_mode"] = "SUCCESS"
        cfg["identity"]["test_mode"] = "SUCCESS"

        active_leg = _mk_leg("L_ACTIVE", Side.SELL, qty=2, strike=25100.0)
        active_leg.ltp = 95.0
        active_leg.delta = -0.31
        active_leg.gamma = 0.02
        active_leg.theta = -0.04
        active_leg.vega = 0.06

        closed_leg = _mk_leg("L_CLOSED", Side.SELL, qty=0, strike=25200.0)
        closed_leg.is_active = False

        state = StrategyState(
            legs={"L_ACTIVE": active_leg, "L_CLOSED": closed_leg},
            cumulative_daily_pnl=123.45,
            entered_today=True,
            entry_time=datetime.now(),
        )

        svc._strategies["demo"] = cfg
        svc._exec_states["demo"] = state
        svc._executors["demo"] = type("Exec", (), {"state": state})()

        snap = svc.get_strategy_leg_monitor_snapshot()
        assert "demo" in snap
        demo = snap["demo"]
        assert demo["mode"] == "MOCK"
        assert demo["active_legs"] == 1
        assert demo["closed_legs"] == 1
        assert float(demo["realized_pnl"]) == 123.45
        assert float(demo["unrealized_pnl"]) == float(active_leg.pnl)

        rows = demo["legs"]
        assert len(rows) == 2
        active_rows = [r for r in rows if r["status"] == "ACTIVE"]
        assert len(active_rows) == 1
        assert active_rows[0]["symbol"] == "L_ACTIVE_TSYM"
        assert float(active_rows[0]["ltp"]) == 95.0
        assert float(active_rows[0]["delta"]) == -0.31
