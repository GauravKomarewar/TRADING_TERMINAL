#!/usr/bin/env python3
"""
Smoke tests for migrated strategy_runner modules.
"""

from shoonya_platform.strategy_runner.config_schema import validate_config


def test_strategy_runner_config_schema_smoke():
    config = {
        "name": "TEST_STRATEGY",
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
