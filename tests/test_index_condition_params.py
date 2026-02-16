from shoonya_platform.strategy_runner.condition_engine import StrategyState, evaluate_condition
from shoonya_platform.strategy_runner.config_schema import validate_config


def _minimal_config_with_param(param: str):
    return {
        "schema_version": "3.0",
        "name": "IDX_PARAM_TEST",
        "basic": {
            "exchange": "NFO",
            "underlying": "NIFTY",
            "expiry_mode": "weekly_current",
            "lots": 1,
        },
        "timing": {
            "entry_time": "09:20",
            "exit_time": "15:20",
        },
        "entry": {
            "rule_type": "if_then",
            "conditions": {
                "operator": "AND",
                "rules": [
                    {"parameter": param, "comparator": ">=", "value": 1},
                ],
            },
            "action": {
                "type": "short_both",
            },
        },
        "exit": {
            "rule_type": "if_any",
            "conditions": [
                {"parameter": "time_current", "comparator": ">=", "value": "15:20"},
            ],
            "action": {"type": "close_all_positions"},
        },
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
