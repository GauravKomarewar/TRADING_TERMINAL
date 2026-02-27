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
        "schema_version": "4.0",
        "identity": {
            "exchange": "NFO",
            "underlying": "NIFTY",
            "product_type": "NRML",
            "order_type": "MARKET",
        },
        "timing": {"entry_window_start": "09:20", "entry_window_end": "15:20", "eod_exit_time": "15:20"},
        "schedule": {"expiry_mode": "weekly_current", "active_days": ["mon", "tue", "wed", "thu", "fri"]},
        "entry": {
            "global_conditions": [],
            "legs": [
                {
                    "tag": "ce",
                    "instrument": "OPT",
                    "side": "SELL",
                    "option_type": "CE",
                    "lots": 1,
                    "strike_mode": "standard",
                    "strike_selection": "atm",
                }
            ],
        },
        "adjustment": {"rules": []},
        "exit": {},
    }


def test_validate_config_success():
    is_valid, issues = validate_config(_valid_config())
    assert is_valid
    assert all(i.severity != "error" for i in issues)


def test_validate_config_missing_required_sections():
    is_valid, issues = validate_config({"name": "BROKEN"})
    assert not is_valid
    assert any(i.path == "identity" for i in issues)
    assert any(i.path == "timing" for i in issues)
    assert any(i.path == "schedule" for i in issues)
    assert any(i.path == "entry" for i in issues)
    assert any(i.path == "exit" for i in issues)


def test_coerce_config_numerics_preserves_int_fields():
    cfg = {"risk_management": {"max_trades_per_day": 2.0, "cooldown_seconds": 30.9}}
    out = coerce_config_numerics(cfg)
    assert isinstance(out["risk_management"]["max_trades_per_day"], int)
    assert isinstance(out["risk_management"]["cooldown_seconds"], int)
