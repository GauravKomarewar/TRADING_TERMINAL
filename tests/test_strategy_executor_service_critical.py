import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from shoonya_platform.strategy_runner.market_reader import MockMarketReader
from shoonya_platform.strategy_runner.models import InstrumentType, OptionType, Side
from shoonya_platform.strategy_runner.state import LegState
from shoonya_platform.strategy_runner.strategy_executor_service import PerStrategyExecutor


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
