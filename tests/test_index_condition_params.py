from shoonya_platform.strategy_runner.condition_engine import StrategyState, evaluate_condition
from shoonya_platform.strategy_runner.config_schema import validate_config


def _minimal_config_with_param(param: str):
    return {
        "schema_version": "4.0",
        "name": "IDX_PARAM_TEST",
        "identity": {
            "exchange": "NFO",
            "underlying": "NIFTY",
            "product_type": "NRML",
            "order_type": "MARKET",
        },
        "timing": {
            "entry_window_start": "09:20",
            "entry_window_end": "15:20",
            "eod_exit_time": "15:15",
        },
        "schedule": {"expiry_mode": "weekly_current", "active_days": ["mon", "tue", "wed", "thu", "fri"]},
        "entry": {
            "global_conditions": [
                    {"parameter": param, "comparator": ">=", "value": 1},
            ],
            "legs": [{"tag": "L1", "side": "SELL", "option_type": "CE", "lots": 1, "strike_mode": "standard", "strike_selection": "ATM"}],
        },
        "adjustment": {"rules": []},
        "exit": {},
    }


def test_config_validation_accepts_dynamic_index_param():
    config = _minimal_config_with_param("index_INDIAVIX_ltp")
    is_valid, issues = validate_config(config)
    unknown_param_warnings = [
        i for i in issues if "Unknown parameter" in i.message and "index_INDIAVIX_ltp" in i.message
    ]
    assert is_valid is True
    assert not unknown_param_warnings


def test_condition_engine_reads_index_params_and_alias():
    state = StrategyState()
    state.set_index_ticks({"INDIAVIX": {"ltp": 12.3, "pc": 1.5, "c": 12.0}})

    assert evaluate_condition(
        {"parameter": "index_INDIAVIX_ltp", "comparator": ">=", "value": 12.0}, state
    )
    assert evaluate_condition(
        {"parameter": "index_INDIAVIX_change_pct", "comparator": ">=", "value": 1.0}, state
    )
    assert evaluate_condition({"parameter": "india_vix", "comparator": ">=", "value": 12.0}, state)
