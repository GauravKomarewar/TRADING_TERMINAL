#!/usr/bin/env python3
"""
config_schema.py — JSON Strategy Config Validator
===================================================

Validates every possible field and combination in the v3.0 strategy JSON schema.
Ensures configs built by strategy_builder_advanced.html or edited by hand are correct
before the runner processes them.

All validation errors are collected (not fail-fast) so the user sees every problem at once.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fresh_strategy.validator")

# ─── Valid values ────────────────────────────────────────────────────────────

VALID_EXCHANGES = {"NFO", "MCX", "BFO", "NSE", "BSE", "CDS", "NCDEX"}
VALID_UNDERLYINGS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "SENSEX", "BANKEX",
    "CRUDEOIL", "CRUDEOILM", "GOLD", "GOLDM", "SILVER", "SILVERM",
    "NATURALGAS", "COPPER", "ZINC", "LEAD", "ALUMINIUM", "NICKEL",
}
VALID_EXPIRY_MODES = {"weekly_current", "weekly_next", "monthly_current", "monthly_next", "custom"}
VALID_MARKET_SOURCES = {"database", "sqlite"}
VALID_COMPARATORS = {">", ">=", "<", "<=", "==", "!=", "~=", "between", "not_between"}
VALID_OPERATORS = {"AND", "OR"}
VALID_RULE_TYPES = {"if_then", "if_then_else", "if_any", "always"}

LOT_SIZES = {
    "NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60,
    "MIDCPNIFTY": 120, "SENSEX": 10, "BANKEX": 15,
    "CRUDEOIL": 100, "CRUDEOILM": 10, "GOLD": 100,
    "GOLDM": 10, "SILVER": 30, "SILVERM": 5,
    "NATURALGAS": 1250, "COPPER": 2500,
}

# Parameters that can appear in conditions
VALID_PARAMETERS = {
    # Per-leg greeks
    "ce_delta", "pe_delta", "ce_gamma", "pe_gamma",
    "ce_theta", "pe_theta", "ce_vega", "pe_vega", "ce_iv", "pe_iv",
    # Per-leg prices
    "ce_ltp", "pe_ltp", "ce_entry_price", "pe_entry_price",
    # Per-leg PnL
    "ce_pnl", "pe_pnl", "ce_pnl_pct", "pe_pnl_pct",
    # Combined / calculated
    "net_delta", "combined_pnl", "combined_pnl_pct", "delta_diff",
    "any_leg_delta", "both_legs_delta", "both_legs_delta_below",
    "higher_delta_leg", "lower_delta_leg",
    "most_profitable_leg", "least_profitable_leg",
    # Spot / market
    "spot_price", "spot_change", "spot_change_pct",
    "atm_strike", "fut_ltp",
    # Time
    "time_current", "time_in_position_sec", "time_since_last_adjustment_sec",
    # Position
    "adjustments_today", "total_trades_today",
    # Premium
    "ce_premium_decay_pct", "pe_premium_decay_pct",
    "total_premium", "total_premium_decay_pct",
}

VALID_ENTRY_ACTIONS = {
    "short_both", "long_both",
    "short_ce", "short_pe", "long_ce", "long_pe",
    "short_straddle", "short_strangle", "long_straddle", "long_strangle",
    "iron_condor", "iron_butterfly",
    "custom",
}

VALID_ADJUSTMENT_ACTIONS = {
    "close_higher_delta", "close_lower_delta",
    "close_higher_pnl_leg", "close_most_profitable",
    "close_ce", "close_pe",
    "roll_ce", "roll_pe", "roll_both",
    "add_hedge", "remove_hedge",
    "lock_profit", "trailing_stop",
    "increase_lots", "decrease_lots",
    "shift_strikes",
    "do_nothing",
    "custom",
}

VALID_EXIT_ACTIONS = {
    "close_all_positions", "close_ce", "close_pe",
    "partial_exit", "custom",
}


class ValidationError:
    """Single validation error with path context."""
    def __init__(self, path: str, message: str, severity: str = "error"):
        self.path = path
        self.message = message
        self.severity = severity  # "error" or "warning"

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.path}: {self.message}"


def validate_config(config: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
    """
    Validate a complete strategy JSON config.

    Returns:
        (is_valid, errors_list)
        is_valid is True only if there are zero errors (warnings OK).
    """
    errors: List[ValidationError] = []

    if not isinstance(config, dict):
        errors.append(ValidationError("root", "Config must be a JSON object"))
        return False, errors

    # ── Top level ──
    _validate_top_level(config, errors)

    # ── basic ──
    if "basic" in config:
        _validate_basic(config["basic"], errors)
    else:
        errors.append(ValidationError("basic", "Missing required section 'basic'"))

    # ── timing ──
    if "timing" in config:
        _validate_timing(config["timing"], errors)
    else:
        errors.append(ValidationError("timing", "Missing required section 'timing'"))

    # ── market_data ──
    if "market_data" in config:
        _validate_market_data(config["market_data"], errors)

    # ── calculated_params (optional) ──
    if "calculated_params" in config:
        _validate_calculated_params(config["calculated_params"], errors)

    # ── entry ──
    if "entry" in config:
        _validate_entry(config["entry"], errors)
    else:
        errors.append(ValidationError("entry", "Missing required section 'entry'"))

    # ── adjustment (optional) ──
    if "adjustment" in config:
        _validate_adjustment(config["adjustment"], errors)

    # ── exit ──
    if "exit" in config:
        _validate_exit(config["exit"], errors)
    else:
        errors.append(ValidationError("exit", "Missing required section 'exit'"))

    # ── risk_management (optional) ──
    if "risk_management" in config:
        _validate_risk(config["risk_management"], errors)

    is_valid = not any(e.severity == "error" for e in errors)
    return is_valid, errors


def validate_config_file(path: str) -> Tuple[bool, List[ValidationError], Optional[Dict]]:
    """
    Load and validate a JSON config file.

    Returns:
        (is_valid, errors, parsed_config_or_None)
    """
    try:
        with open(path, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return False, [ValidationError("file", f"Invalid JSON: {e}")], None
    except FileNotFoundError:
        return False, [ValidationError("file", f"File not found: {path}")], None
    except Exception as e:
        return False, [ValidationError("file", f"Cannot read file: {e}")], None

    is_valid, errors = validate_config(config)
    return is_valid, errors, config


def coerce_config_numerics(config: Any) -> Any:
    """
    Recursively walk the JSON config and coerce all numeric values to float.

    Exceptions (kept as int):
    - "lots", "qty", "max_lots", "max_adjustments_per_day", "max_trades_per_day"
    - Any key containing "priority"

    Time strings like "09:20" are left as-is.
    Lists (e.g. [low, high] for 'between') are recursed into.
    """
    _INT_KEYS = {
        "lots", "qty", "max_lots", "max_adjustments_per_day",
        "max_trades_per_day", "priority",
    }

    def _walk(obj: Any, key: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: _walk(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(item, key) for item in obj]
        if isinstance(obj, bool):
            return obj  # bool before int — bool is subclass of int
        if isinstance(obj, int):
            if key in _INT_KEYS:
                return obj
            return float(obj)
        return obj

    return _walk(config)


# ─── Section validators ─────────────────────────────────────────────────────

def _validate_top_level(config: Dict, errors: List[ValidationError]):
    """Validate top-level fields."""
    if "name" not in config:
        errors.append(ValidationError("name", "Missing strategy name"))
    elif not isinstance(config["name"], str) or not config["name"].strip():
        errors.append(ValidationError("name", "Strategy name must be a non-empty string"))

    sv = config.get("schema_version")
    if sv and sv != "3.0":
        errors.append(ValidationError("schema_version", f"Expected '3.0', got '{sv}'", "warning"))


def _validate_basic(basic: Dict, errors: List[ValidationError]):
    """Validate basic section."""
    path = "basic"

    exchange = basic.get("exchange")
    if not exchange:
        errors.append(ValidationError(f"{path}.exchange", "Missing exchange"))
    elif exchange.upper() not in VALID_EXCHANGES:
        errors.append(ValidationError(f"{path}.exchange",
            f"Invalid exchange '{exchange}'. Valid: {sorted(VALID_EXCHANGES)}"))

    underlying = basic.get("underlying")
    if not underlying:
        errors.append(ValidationError(f"{path}.underlying", "Missing underlying"))
    elif underlying.upper() not in VALID_UNDERLYINGS:
        errors.append(ValidationError(f"{path}.underlying",
            f"Unknown underlying '{underlying}'. Valid: {sorted(VALID_UNDERLYINGS)}", "warning"))

    expiry = basic.get("expiry_mode")
    if expiry and expiry not in VALID_EXPIRY_MODES:
        errors.append(ValidationError(f"{path}.expiry_mode",
            f"Invalid expiry_mode '{expiry}'. Valid: {sorted(VALID_EXPIRY_MODES)}"))

    lots = basic.get("lots")
    if lots is not None:
        if not isinstance(lots, (int, float)) or lots < 1:
            errors.append(ValidationError(f"{path}.lots", "lots must be >= 1"))


def _validate_timing(timing: Dict, errors: List[ValidationError]):
    """Validate timing section."""
    path = "timing"

    for key in ("entry_time", "exit_time"):
        val = timing.get(key)
        if not val:
            errors.append(ValidationError(f"{path}.{key}", f"Missing {key}"))
        elif isinstance(val, str):
            try:
                parts = val.split(":")
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except (ValueError, IndexError):
                errors.append(ValidationError(f"{path}.{key}",
                    f"Invalid time format '{val}'. Expected HH:MM"))

    # Entry must be before exit
    et = timing.get("entry_time", "")
    xt = timing.get("exit_time", "")
    if et and xt:
        try:
            e_parts = et.split(":")
            x_parts = xt.split(":")
            if int(e_parts[0]) * 60 + int(e_parts[1]) >= int(x_parts[0]) * 60 + int(x_parts[1]):
                errors.append(ValidationError(f"{path}",
                    f"entry_time ({et}) must be before exit_time ({xt})"))
        except (ValueError, IndexError):
            pass  # Already caught above


def _validate_market_data(md: Dict, errors: List[ValidationError]):
    """Validate market_data section."""
    path = "market_data"
    source = md.get("source", "database")
    if source not in VALID_MARKET_SOURCES:
        errors.append(ValidationError(f"{path}.source",
            f"Invalid source '{source}'. Valid: {sorted(VALID_MARKET_SOURCES)}"))

    db_path = md.get("db_path")
    if db_path and not Path(db_path).suffix == ".sqlite":
        errors.append(ValidationError(f"{path}.db_path",
            "db_path should end in .sqlite", "warning"))


def _validate_calculated_params(cp: Dict, errors: List[ValidationError]):
    """Validate calculated_params section (informational, not strictly required)."""
    path = "calculated_params"
    if not isinstance(cp, dict):
        errors.append(ValidationError(path, "calculated_params must be a dict"))
        return

    for key, val in cp.items():
        if isinstance(val, dict):
            if "formula" not in val:
                errors.append(ValidationError(f"{path}.{key}",
                    "Each calculated param should have a 'formula' field", "warning"))


def _validate_condition(cond: Dict, path: str, errors: List[ValidationError]):
    """Validate a single condition dict."""
    param = cond.get("parameter")
    if not param:
        errors.append(ValidationError(f"{path}.parameter", "Missing parameter"))
    elif param not in VALID_PARAMETERS:
        errors.append(ValidationError(f"{path}.parameter",
            f"Unknown parameter '{param}'. Valid: {sorted(VALID_PARAMETERS)}", "warning"))

    comp = cond.get("comparator")
    if not comp:
        errors.append(ValidationError(f"{path}.comparator", "Missing comparator"))
    elif comp not in VALID_COMPARATORS:
        errors.append(ValidationError(f"{path}.comparator",
            f"Invalid comparator '{comp}'. Valid: {sorted(VALID_COMPARATORS)}"))

    if "value" not in cond:
        errors.append(ValidationError(f"{path}.value", "Missing value"))

    # ~= requires tolerance
    if comp == "~=" and "tolerance" not in cond:
        errors.append(ValidationError(f"{path}.tolerance",
            "Comparator '~=' requires 'tolerance' field", "warning"))

    # between requires value to be list of 2
    if comp in ("between", "not_between"):
        val = cond.get("value")
        if not isinstance(val, (list, tuple)) or len(val) != 2:
            errors.append(ValidationError(f"{path}.value",
                f"Comparator '{comp}' requires value to be [min, max]"))


def _validate_conditions_block(block: Dict, path: str, errors: List[ValidationError]):
    """Validate a conditions block (may be nested with AND/OR + rules)."""
    if "rules" in block:
        operator = block.get("operator", "AND")
        if operator not in VALID_OPERATORS:
            errors.append(ValidationError(f"{path}.operator",
                f"Invalid operator '{operator}'. Valid: {sorted(VALID_OPERATORS)}"))

        rules = block["rules"]
        if not isinstance(rules, list):
            errors.append(ValidationError(f"{path}.rules", "rules must be an array"))
            return

        if len(rules) == 0:
            errors.append(ValidationError(f"{path}.rules", "rules array is empty"))

        for i, rule in enumerate(rules):
            if isinstance(rule, dict):
                # Could be nested conditions block or a leaf condition
                if "rules" in rule:
                    _validate_conditions_block(rule, f"{path}.rules[{i}]", errors)
                else:
                    _validate_condition(rule, f"{path}.rules[{i}]", errors)
            else:
                errors.append(ValidationError(f"{path}.rules[{i}]",
                    "Each rule must be a dict"))
    else:
        # Single condition (no nesting)
        _validate_condition(block, path, errors)


def _validate_entry(entry: Dict, errors: List[ValidationError]):
    """Validate entry section."""
    path = "entry"

    rule_type = entry.get("rule_type")
    if rule_type and rule_type not in VALID_RULE_TYPES:
        errors.append(ValidationError(f"{path}.rule_type",
            f"Invalid rule_type '{rule_type}'. Valid: {sorted(VALID_RULE_TYPES)}"))

    conditions = entry.get("conditions")
    if conditions:
        _validate_conditions_block(conditions, f"{path}.conditions", errors)

    action = entry.get("action")
    if not action:
        errors.append(ValidationError(f"{path}.action", "Missing entry action"))
    elif isinstance(action, dict):
        atype = action.get("type")
        if not atype:
            errors.append(ValidationError(f"{path}.action.type", "Missing action type"))
        elif atype not in VALID_ENTRY_ACTIONS:
            errors.append(ValidationError(f"{path}.action.type",
                f"Unknown entry action '{atype}'. Valid: {sorted(VALID_ENTRY_ACTIONS)}", "warning"))


def _validate_adjustment(adj: Dict, errors: List[ValidationError]):
    """Validate adjustment section."""
    path = "adjustment"

    if "enabled" in adj and not isinstance(adj["enabled"], bool):
        errors.append(ValidationError(f"{path}.enabled", "enabled must be boolean"))

    for num_field in ("check_interval_min", "max_adjustments_per_day", "cooldown_seconds"):
        val = adj.get(num_field)
        if val is not None and (not isinstance(val, (int, float)) or val < 0):
            errors.append(ValidationError(f"{path}.{num_field}", f"{num_field} must be >= 0"))

    rules = adj.get("rules", [])
    if not isinstance(rules, list):
        errors.append(ValidationError(f"{path}.rules", "rules must be an array"))
        return

    priorities_seen = set()
    for i, rule in enumerate(rules):
        rpath = f"{path}.rules[{i}]"

        if not isinstance(rule, dict):
            errors.append(ValidationError(rpath, "Each adjustment rule must be a dict"))
            continue

        # Priority
        pri = rule.get("priority")
        if pri is not None:
            if pri in priorities_seen:
                errors.append(ValidationError(f"{rpath}.priority",
                    f"Duplicate priority {pri}", "warning"))
            priorities_seen.add(pri)

        # Name
        if not rule.get("name"):
            errors.append(ValidationError(f"{rpath}.name", "Adjustment rule missing 'name'", "warning"))

        # Conditions
        conditions = rule.get("conditions")
        if conditions:
            _validate_conditions_block(conditions, f"{rpath}.conditions", errors)

        # Action
        action = rule.get("action")
        if action:
            atype = action.get("type")
            if atype and atype not in VALID_ADJUSTMENT_ACTIONS:
                errors.append(ValidationError(f"{rpath}.action.type",
                    f"Unknown adjustment action '{atype}'", "warning"))
        else:
            errors.append(ValidationError(f"{rpath}.action", "Adjustment rule missing 'action'"))


def _validate_exit(exit_cfg: Dict, errors: List[ValidationError]):
    """Validate exit section."""
    path = "exit"

    conditions = exit_cfg.get("conditions")
    if not conditions:
        errors.append(ValidationError(f"{path}.conditions", "Missing exit conditions"))
    elif isinstance(conditions, list):
        for i, cond in enumerate(conditions):
            if isinstance(cond, dict):
                _validate_condition(cond, f"{path}.conditions[{i}]", errors)
            else:
                errors.append(ValidationError(f"{path}.conditions[{i}]",
                    "Each exit condition must be a dict"))
    elif isinstance(conditions, dict):
        _validate_conditions_block(conditions, f"{path}.conditions", errors)

    action = exit_cfg.get("action")
    if action and isinstance(action, dict):
        atype = action.get("type")
        if atype and atype not in VALID_EXIT_ACTIONS:
            errors.append(ValidationError(f"{path}.action.type",
                f"Unknown exit action '{atype}'", "warning"))


def _validate_risk(risk: Dict, errors: List[ValidationError]):
    """Validate risk_management section."""
    path = "risk_management"

    for field in ("max_loss_per_day", "max_trades_per_day"):
        val = risk.get(field)
        if val is not None and (not isinstance(val, (int, float)) or val < 0):
            errors.append(ValidationError(f"{path}.{field}", f"{field} must be >= 0"))

    ps = risk.get("position_sizing")
    if ps and isinstance(ps, dict):
        ml = ps.get("max_lots")
        if ml is not None and (not isinstance(ml, (int, float)) or ml < 1):
            errors.append(ValidationError(f"{path}.position_sizing.max_lots",
                "max_lots must be >= 1"))
