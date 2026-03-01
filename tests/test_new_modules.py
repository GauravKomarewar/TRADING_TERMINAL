#!/usr/bin/env python3
"""
Smoke tests for migrated strategy_runner modules.
"""

from shoonya_platform.strategy_runner.config_schema import validate_config


def test_strategy_runner_config_schema_smoke():
    config = {
        "name": "TEST_STRATEGY",
        "schema_version": "4.0",
        "identity": {
            "exchange": "NFO",
            "underlying": "NIFTY",
            "product_type": "NRML",
            "order_type": "MARKET",
        },
        "timing": {"entry_window_start": "09:20", "entry_window_end": "15:20", "eod_exit_time": "15:15"},
        "schedule": {"expiry_mode": "weekly_current", "active_days": ["mon", "tue", "wed", "thu", "fri"]},
        "entry": {"global_conditions": [], "legs": [{"tag": "L1", "side": "SELL", "option_type": "CE", "lots": 1, "strike_mode": "standard", "strike_selection": "ATM"}]},
        "adjustment": {"rules": []},
        "exit": {},
    }
    is_valid, issues = validate_config(config)
    assert is_valid
    assert all(i.severity != "error" for i in issues)
