#!/usr/bin/env python3
"""
Compatibility migration tests for strategy_runner config schema.
"""

from shoonya_platform.strategy_runner.config_schema import (
    coerce_config_numerics,
    validate_config,
)


def _valid_config():
    return {
        "name": "NIFTY_DNSS",
        "schema_version": "3.0",
        "basic": {
            "exchange": "NFO",
            "underlying": "NIFTY",
            "expiry_mode": "weekly_current",
        },
        "timing": {"entry_time": "09:20", "exit_time": "15:20"},
        "entry": {"enabled": True, "action": "entry_both_legs", "conditions": []},
        "exit": {
            "enabled": True,
            "conditions": [{"parameter": "spot_ltp", "comparator": ">", "value": 0}],
        },
    }


def test_validate_config_success():
    is_valid, issues = validate_config(_valid_config())
    assert is_valid
    assert all(i.severity != "error" for i in issues)


def test_validate_config_missing_required_sections():
    is_valid, issues = validate_config({"name": "BROKEN"})
    assert not is_valid
    assert any(i.path == "basic" for i in issues)
    assert any(i.path == "timing" for i in issues)
    assert any(i.path == "entry" for i in issues)
    assert any(i.path == "exit" for i in issues)


def test_coerce_config_numerics_preserves_int_fields():
    cfg = {"risk_management": {"max_trades_per_day": 2.0, "cooldown_seconds": 30.9}}
    out = coerce_config_numerics(cfg)
    assert isinstance(out["risk_management"]["max_trades_per_day"], int)
    assert isinstance(out["risk_management"]["cooldown_seconds"], int)
