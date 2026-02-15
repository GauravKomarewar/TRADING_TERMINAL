#!/usr/bin/env python3
"""
Integration smoke tests for strategy_runner stack.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

from shoonya_platform.strategy_runner.config_schema import validate_config
from shoonya_platform.strategy_runner.universal_settings.universal_registry import (
    list_strategy_templates,
)
from shoonya_platform.strategy_runner.universal_settings.universal_strategy_reporter import (
    build_strategy_report,
)
from shoonya_platform.strategy_runner.universal_settings.writer import StrategyRunWriter


class _MockLeg:
    def __init__(self, symbol="LEG", delta=0.3):
        self.symbol = symbol
        self.delta = delta
        self.entry_price = 100.0
        self.current_price = 101.0

    def unrealized_pnl(self):
        return 1.0


class _MockState:
    active = True
    ce_leg = _MockLeg("CE_LEG", 0.3)
    pe_leg = _MockLeg("PE_LEG", -0.3)
    realized_pnl = 0.0
    adjustment_phase = None
    adjustment_target_delta = None
    adjustment_leg_type = None
    next_profit_target = None

    @staticmethod
    def total_unrealized_pnl():
        return 2.0

    @staticmethod
    def total_delta():
        return 0.0


class _MockStrategy:
    def __init__(self):
        self.state = _MockState()
        self.config = Mock()
        self.config.cooldown_seconds = 30


def test_registry_and_validation_integration():
    templates = list_strategy_templates()
    assert isinstance(templates, list)
    assert all(t["module"].startswith("shoonya_platform.strategy_runner.") for t in templates)

    config = {
        "name": "NIFTY_DNSS",
        "schema_version": "3.0",
        "basic": {"exchange": "NFO", "underlying": "NIFTY"},
        "timing": {"entry_time": "09:20", "exit_time": "15:20"},
        "entry": {"enabled": True, "action": "entry_both_legs", "conditions": []},
        "exit": {
            "enabled": True,
            "conditions": [{"parameter": "spot_ltp", "comparator": ">", "value": 0}],
        },
    }
    is_valid, issues = validate_config(config)
    assert is_valid
    assert all(i.severity != "error" for i in issues)


def test_reporter_writer_integration():
    strategy = _MockStrategy()
    report = build_strategy_report(strategy)
    assert isinstance(report, str)
    assert report

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        writer = StrategyRunWriter(db_path)
        writer.start_run(
            run_id="run_integration_1",
            resolved_config={"strategy_name": "NIFTY_DNSS"},
            market_type="database_market",
        )
        writer.log_event(run_id="run_integration_1", event_type="entry", payload={"source": "test"})
        writer.update_metrics(
            run_id="run_integration_1",
            max_mtm=10.0,
            max_drawdown=1.0,
            adjustments=0,
        )

        run = writer.get_run("run_integration_1")
        events = writer.get_run_events("run_integration_1")
        metrics = writer.get_run_metrics("run_integration_1")

        assert run is not None
        assert len(events) == 1
        assert metrics is not None
    finally:
        Path(db_path).unlink(missing_ok=True)
