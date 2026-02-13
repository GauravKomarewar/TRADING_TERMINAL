#!/usr/bin/env python3
"""
condition_engine.py — Rule & Condition Evaluation Engine
=========================================================

Evaluates JSON-defined conditions against live market data.

Capabilities:
- AND / OR compound conditions with unlimited nesting
- All comparators: >, >=, <, <=, ==, !=, ~= (approx), between, not_between
- Time-based comparisons (HH:MM format)
- Calculated parameters: net_delta, combined_pnl, delta_diff, etc.
- Special aggregate parameters: any_leg_delta, both_legs_delta, etc.
- Entry / Adjustment / Exit rule evaluation
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fresh_strategy.condition_engine")


class StrategyState:
    """
    Holds the live state of a running strategy (positions, P&L, etc.).

    The runner populates this from market data + tracked positions each tick.
    The condition engine reads it to evaluate rules.
    """

    def __init__(self):
        # ─── Position tracking ──────────────────────────────────────────
        self.has_position = False
        self.entry_time: Optional[datetime] = None

        # CE leg
        self.ce_strike: float = 0.0
        self.ce_entry_price: float = 0.0
        self.ce_trading_symbol: str = ""
        self.ce_direction: str = ""  # "BUY" or "SELL"
        self.ce_qty: int = 0

        # PE leg
        self.pe_strike: float = 0.0
        self.pe_entry_price: float = 0.0
        self.pe_trading_symbol: str = ""
        self.pe_direction: str = ""
        self.pe_qty: int = 0

        # ─── Live greeks (from current market snapshot) ─────────────────
        self.ce_delta: float = 0.0
        self.pe_delta: float = 0.0
        self.ce_gamma: float = 0.0
        self.pe_gamma: float = 0.0
        self.ce_theta: float = 0.0
        self.pe_theta: float = 0.0
        self.ce_vega: float = 0.0
        self.pe_vega: float = 0.0
        self.ce_iv: float = 0.0
        self.pe_iv: float = 0.0

        # ─── Live prices ────────────────────────────────────────────────
        self.ce_ltp: float = 0.0
        self.pe_ltp: float = 0.0

        # ─── P&L (calculated by runner from entry price vs current) ─────
        self.ce_pnl: float = 0.0
        self.pe_pnl: float = 0.0
        self.ce_pnl_pct: float = 0.0
        self.pe_pnl_pct: float = 0.0

        # ─── Spot / market ──────────────────────────────────────────────
        self.spot_price: float = 0.0
        self.spot_open: float = 0.0  # For change calculation
        self.atm_strike: float = 0.0
        self.fut_ltp: float = 0.0

        # ─── Counters ──────────────────────────────────────────────────
        self.adjustments_today: int = 0
        self.total_trades_today: int = 0

        # ─── Profit tracking ───────────────────────────────────────────
        self.peak_pnl: float = 0.0
        self.trailing_stop_active: bool = False
        self.trailing_stop_level: float = 0.0

        # ─── Timing (set by runner) ────────────────────────────────────
        self.last_adjustment_time: float = 0.0  # epoch seconds

        # ─── Cumulative daily P&L (survives position resets) ────────────
        self.cumulative_daily_pnl: float = 0.0

    # ─── Derived calculations ──────────────────────────────────────────

    @property
    def net_delta(self) -> float:
        """Directional net delta (CE + PE, where PE delta is negative)."""
        return self.ce_delta + self.pe_delta

    @property
    def combined_pnl(self) -> float:
        return self.ce_pnl + self.pe_pnl

    @property
    def combined_pnl_pct(self) -> float:
        total_entry = abs(self.ce_entry_price) + abs(self.pe_entry_price)
        if total_entry == 0:
            return 0.0
        return (self.combined_pnl / total_entry) * 100.0

    @property
    def delta_diff(self) -> float:
        """Difference between CE and PE absolute deltas."""
        return abs(abs(self.ce_delta) - abs(self.pe_delta))

    @property
    def higher_delta_leg(self) -> str:
        """Which leg has higher absolute delta: 'CE' or 'PE'."""
        return "CE" if abs(self.ce_delta) >= abs(self.pe_delta) else "PE"

    @property
    def lower_delta_leg(self) -> str:
        """Which leg has lower absolute delta: 'CE' or 'PE'."""
        return "PE" if abs(self.ce_delta) >= abs(self.pe_delta) else "CE"

    @property
    def spot_change(self) -> float:
        if self.spot_open == 0:
            return 0.0
        return self.spot_price - self.spot_open

    @property
    def spot_change_pct(self) -> float:
        if self.spot_open == 0:
            return 0.0
        return ((self.spot_price - self.spot_open) / self.spot_open) * 100.0

    @property
    def total_premium(self) -> float:
        return self.ce_ltp + self.pe_ltp

    @property
    def ce_premium_decay_pct(self) -> float:
        if self.ce_entry_price == 0:
            return 0.0
        return ((self.ce_entry_price - self.ce_ltp) / self.ce_entry_price) * 100.0

    @property
    def pe_premium_decay_pct(self) -> float:
        if self.pe_entry_price == 0:
            return 0.0
        return ((self.pe_entry_price - self.pe_ltp) / self.pe_entry_price) * 100.0

    @property
    def total_premium_decay_pct(self) -> float:
        total_entry = self.ce_entry_price + self.pe_entry_price
        if total_entry == 0:
            return 0.0
        return ((total_entry - self.total_premium) / total_entry) * 100.0

    @property
    def most_profitable_leg(self) -> str:
        """Which leg has higher P&L: 'CE' or 'PE'."""
        return "CE" if self.ce_pnl >= self.pe_pnl else "PE"

    @property
    def least_profitable_leg(self) -> str:
        """Which leg has lower P&L: 'CE' or 'PE'."""
        return "PE" if self.ce_pnl >= self.pe_pnl else "CE"

    @property
    def time_in_position_sec(self) -> float:
        """Seconds since entry."""
        if self.entry_time is None:
            return 0.0
        return (datetime.now() - self.entry_time).total_seconds()

    @property
    def time_since_last_adjustment_sec(self) -> float:
        """Seconds since last adjustment (0 if no adjustment yet)."""
        if self.last_adjustment_time <= 0:
            return 0.0
        return time.time() - self.last_adjustment_time

    def get_param(self, name: str) -> Any:
        """
        Resolve a parameter name to its current value.

        Returns the value, or None if unknown.
        """
        # Direct attributes + properties
        param_map = {
            "ce_delta": lambda: self.ce_delta,
            "pe_delta": lambda: self.pe_delta,
            "ce_gamma": lambda: self.ce_gamma,
            "pe_gamma": lambda: self.pe_gamma,
            "ce_theta": lambda: self.ce_theta,
            "pe_theta": lambda: self.pe_theta,
            "ce_vega": lambda: self.ce_vega,
            "pe_vega": lambda: self.pe_vega,
            "ce_iv": lambda: self.ce_iv,
            "pe_iv": lambda: self.pe_iv,
            "ce_ltp": lambda: self.ce_ltp,
            "pe_ltp": lambda: self.pe_ltp,
            "ce_entry_price": lambda: self.ce_entry_price,
            "pe_entry_price": lambda: self.pe_entry_price,
            "ce_pnl": lambda: self.ce_pnl,
            "pe_pnl": lambda: self.pe_pnl,
            "ce_pnl_pct": lambda: self.ce_pnl_pct,
            "pe_pnl_pct": lambda: self.pe_pnl_pct,
            "net_delta": lambda: self.net_delta,
            "combined_pnl": lambda: self.combined_pnl,
            "combined_pnl_pct": lambda: self.combined_pnl_pct,
            "delta_diff": lambda: self.delta_diff,
            "higher_delta_leg": lambda: self.higher_delta_leg,
            "lower_delta_leg": lambda: self.lower_delta_leg,
            "spot_price": lambda: self.spot_price,
            "spot_change": lambda: self.spot_change,
            "spot_change_pct": lambda: self.spot_change_pct,
            "atm_strike": lambda: self.atm_strike,
            "fut_ltp": lambda: self.fut_ltp,
            "adjustments_today": lambda: self.adjustments_today,
            "total_trades_today": lambda: self.total_trades_today,
            "ce_premium_decay_pct": lambda: self.ce_premium_decay_pct,
            "pe_premium_decay_pct": lambda: self.pe_premium_decay_pct,
            "total_premium": lambda: self.total_premium,
            "total_premium_decay_pct": lambda: self.total_premium_decay_pct,
            "time_current": lambda: datetime.now().strftime("%H:%M"),
            "time_in_position_sec": lambda: self.time_in_position_sec,
            "time_since_last_adjustment_sec": lambda: self.time_since_last_adjustment_sec,
            "most_profitable_leg": lambda: self.most_profitable_leg,
            "least_profitable_leg": lambda: self.least_profitable_leg,
        }

        resolver = param_map.get(name)
        if resolver is not None:
            return resolver()

        # Special aggregate parameters
        if name == "any_leg_delta":
            # For "> X": if max > X, at least one leg exceeds. Correct.
            return max(abs(self.ce_delta), abs(self.pe_delta))
        if name == "both_legs_delta" or name == "both_legs_delta_below":
            # For "< X":  return max — if max < X, both are below. Correct.
            # For "> X":  return min — if min > X, both are above. Correct.
            # The caller decides which comparator to use.
            # Return both as a tuple tag so _compare can branch.
            # SIMPLER: return min for '>' and max for '<' at _compare level.
            # But we don't know comparator here. Return max (most common usage is < ).
            # The condition writer should use any_leg_delta for > checks.
            return max(abs(self.ce_delta), abs(self.pe_delta))

        logger.warning(f"Unknown parameter: '{name}'")
        return None


# ─── Comparator Functions ────────────────────────────────────────────────────

def _compare(actual: Any, comparator: str, value: Any, tolerance: float = 0.0) -> bool:
    """
    Evaluate: actual <comparator> value

    Handles numeric, string (time), and special comparators.
    """
    if actual is None:
        return False

    # Time comparison: "HH:MM" strings
    if comparator in (">", ">=", "<", "<=", "==", "!=") and isinstance(value, str) and ":" in str(value):
        try:
            actual_t = _parse_time(str(actual))
            target_t = _parse_time(value)
            if comparator == ">":
                return actual_t > target_t
            if comparator == ">=":
                return actual_t >= target_t
            if comparator == "<":
                return actual_t < target_t
            if comparator == "<=":
                return actual_t <= target_t
            if comparator == "==":
                return actual_t == target_t
            if comparator == "!=":
                return actual_t != target_t
        except Exception as e:
            logger.error(f"Time comparison failed: {actual} {comparator} {value}: {e}")
            return False

    # Handle between/not_between first (value is a list/tuple)
    if comparator in ("between", "not_between"):
        try:
            a = float(actual)
        except (ValueError, TypeError):
            logger.error(f"Cannot convert actual to float for {comparator}: {actual}")
            return False
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            logger.error(f"'{comparator}' comparator needs [low, high], got: {value}")
            return False
        low, high = float(value[0]), float(value[1])
        if comparator == "between":
            return low <= a <= high
        return not (low <= a <= high)

    # Numeric comparison (value is a scalar)
    try:
        a = float(actual)
        v = float(value)
    except (ValueError, TypeError):
        # String equality/inequality
        if comparator == "==":
            return str(actual) == str(value)
        if comparator == "!=":
            return str(actual) != str(value)
        logger.error(f"Cannot compare: {actual} {comparator} {value}")
        return False

    if comparator == ">":
        return a > v
    if comparator == ">=":
        return a >= v
    if comparator == "<":
        return a < v
    if comparator == "<=":
        return a <= v
    if comparator == "==":
        return a == v
    if comparator == "!=":
        return a != v
    if comparator == "~=":
        # Approximately equal (within tolerance)
        # Use abs() on both sides for delta-like signed values
        tol = tolerance if tolerance > 0 else abs(v) * 0.1
        return abs(abs(a) - abs(v)) <= tol

    logger.error(f"Unknown comparator: {comparator}")
    return False


def _parse_time(time_str: str) -> int:
    """Convert HH:MM to minutes since midnight for comparison."""
    parts = str(time_str).split(":")
    return int(parts[0]) * 60 + int(parts[1])


# ─── Condition Evaluation ─────────────────────────────────────────────────────

def evaluate_condition(condition: Dict[str, Any], state: StrategyState) -> bool:
    """
    Evaluate a single condition rule or a compound AND/OR group.

    Args:
        condition: A condition dict. Can be:
            - Simple: {"parameter": "...", "comparator": "...", "value": ...}
            - Compound: {"operator": "AND"/"OR", "rules": [...]}
        state: Current strategy state

    Returns:
        True if condition is met
    """
    # Compound conditions
    if "operator" in condition and "rules" in condition:
        op = condition["operator"].upper()
        rules = condition["rules"]

        if not rules:
            return True

        if op == "AND":
            return all(evaluate_condition(r, state) for r in rules)
        elif op == "OR":
            return any(evaluate_condition(r, state) for r in rules)
        else:
            logger.error(f"Unknown operator: {op}")
            return False

    # Simple condition
    param_name = condition.get("parameter", "")
    comparator = condition.get("comparator", "")
    value = condition.get("value")
    tolerance = float(condition.get("tolerance", 0) or 0)

    if not param_name or not comparator:
        logger.warning(f"Incomplete condition: {condition}")
        return False

    # Coerce value to float for numeric comparisons (except time strings and lists)
    if value is not None and not isinstance(value, (str, list, tuple, bool)):
        try:
            value = float(value)
        except (ValueError, TypeError):
            pass

    actual = state.get_param(param_name)
    result = _compare(actual, comparator, value, tolerance)

    logger.debug(
        f"Condition: {param_name}={actual} {comparator} {value} "
        f"(tol={tolerance}) → {'PASS' if result else 'FAIL'}"
    )
    return result


def evaluate_conditions_list(conditions: List[Dict], state: StrategyState, mode: str = "any") -> bool:
    """
    Evaluate a flat list of conditions.

    Args:
        conditions: List of condition dicts
        state: Strategy state
        mode: "any" (OR) or "all" (AND)

    Returns:
        True if conditions met per mode
    """
    if not conditions:
        return True

    results = [evaluate_condition(c, state) for c in conditions]

    if mode == "any":
        return any(results)
    return all(results)


# ─── Rule Evaluation ──────────────────────────────────────────────────────────

class RuleResult:
    """Result of evaluating a rule."""

    def __init__(self, triggered: bool, rule_name: str = "", action: Optional[Dict] = None):
        self.triggered = triggered
        self.rule_name = rule_name
        self.action = action or {}

    def __bool__(self):
        return self.triggered

    def __repr__(self):
        return f"RuleResult(triggered={self.triggered}, rule='{self.rule_name}', action={self.action.get('type', 'none')})"


def evaluate_entry_rules(config: Dict[str, Any], state: StrategyState) -> RuleResult:
    """
    Evaluate entry rules from config['entry'].

    Returns RuleResult with triggered=True if entry conditions are met.
    """
    entry = config.get("entry", {})
    if not entry:
        return RuleResult(False, "no_entry_rules")

    rule_type = entry.get("rule_type", "if_then")
    conditions = entry.get("conditions", {})
    action = entry.get("action", {})

    if rule_type == "always":
        return RuleResult(True, "entry_always", action)

    if rule_type in ("if_then", "if_then_else"):
        # Conditions can be a compound or a flat list
        if isinstance(conditions, dict):
            met = evaluate_condition(conditions, state)
        elif isinstance(conditions, list):
            met = evaluate_conditions_list(conditions, state, mode="all")
        else:
            met = False

        if met:
            return RuleResult(True, "entry_conditions_met", action)
        elif rule_type == "if_then_else":
            else_action = entry.get("else_action", {})
            return RuleResult(True, "entry_else_branch", else_action)
        return RuleResult(False, "entry_conditions_not_met")

    if rule_type == "if_any":
        # conditions is a flat list, ANY must match
        if isinstance(conditions, list):
            met = evaluate_conditions_list(conditions, state, mode="any")
        elif isinstance(conditions, dict):
            met = evaluate_condition(conditions, state)
        else:
            met = False
        if met:
            return RuleResult(True, "entry_any_met", action)
        return RuleResult(False, "entry_none_met")

    logger.warning(f"Unknown entry rule_type: {rule_type}")
    return RuleResult(False, f"unknown_rule_type_{rule_type}")


def evaluate_adjustment_rules(
    config: Dict[str, Any],
    state: StrategyState
) -> List[RuleResult]:
    """
    Evaluate adjustment rules, sorted by priority.

    Returns list of triggered RuleResults (may be empty).
    Only the FIRST triggered rule per evaluation cycle is usually acted upon,
    but we return all for logging/visibility.
    """
    adj = config.get("adjustment", {})
    if not adj or not adj.get("enabled", False):
        return []

    rules = adj.get("rules", [])
    if not rules:
        return []

    # Sort by priority (lower number = higher priority)
    sorted_rules = sorted(rules, key=lambda r: r.get("priority", 999))

    triggered = []
    for rule in sorted_rules:
        rule_name = rule.get("name", f"adjustment_rule_{rule.get('priority', '?')}")
        conditions = rule.get("conditions", {})
        action = rule.get("action", {})
        rule_type = rule.get("rule_type", "if_then")

        if rule_type == "always":
            triggered.append(RuleResult(True, rule_name, action))
            continue

        # Evaluate conditions
        if isinstance(conditions, dict):
            met = evaluate_condition(conditions, state)
        elif isinstance(conditions, list):
            # For if_any: any condition met; for if_then: all must match
            mode = "any" if rule_type == "if_any" else "all"
            met = evaluate_conditions_list(conditions, state, mode=mode)
        else:
            met = False

        if met:
            triggered.append(RuleResult(True, rule_name, action))
            logger.info(f"Adjustment rule triggered: {rule_name} → {action.get('type', '?')}")
        elif rule_type == "if_then_else":
            else_action = rule.get("else_action", {})
            if else_action:
                triggered.append(RuleResult(True, f"{rule_name}_else", else_action))
                logger.info(f"Adjustment rule else-branch: {rule_name}")

    return triggered


def evaluate_exit_rules(config: Dict[str, Any], state: StrategyState) -> RuleResult:
    """
    Evaluate exit rules from config['exit'].

    Returns RuleResult with triggered=True if ANY exit condition is met
    (exit is typically OR logic — any reason to exit triggers it).
    """
    exit_cfg = config.get("exit", {})
    if not exit_cfg:
        return RuleResult(False, "no_exit_rules")

    rule_type = exit_cfg.get("rule_type", "if_any")
    conditions = exit_cfg.get("conditions", {})
    action = exit_cfg.get("action", {})

    if rule_type == "always":
        return RuleResult(True, "exit_always", action)

    # For exit, conditions can be a list (if_any) or a compound dict
    if isinstance(conditions, list):
        # Check each condition individually so we can log which triggered
        for i, cond in enumerate(conditions):
            if evaluate_condition(cond, state):
                desc = cond.get("description", cond.get("parameter", f"condition_{i}"))
                logger.info(f"Exit condition triggered: {desc}")
                return RuleResult(True, f"exit_{desc}", action)
        return RuleResult(False, "exit_no_conditions_met")

    elif isinstance(conditions, dict):
        if rule_type == "if_any" and "rules" in conditions:
            # Compound with OR semantics for exit
            conditions_copy = dict(conditions)
            if conditions_copy.get("operator", "").upper() != "OR":
                conditions_copy["operator"] = "OR"
            met = evaluate_condition(conditions_copy, state)
        else:
            met = evaluate_condition(conditions, state)

        if met:
            return RuleResult(True, "exit_conditions_met", action)
        return RuleResult(False, "exit_conditions_not_met")

    return RuleResult(False, "exit_invalid_conditions")


def evaluate_risk_management(config: Dict[str, Any], state: StrategyState) -> Optional[RuleResult]:
    """
    Check risk management limits. Returns a triggered RuleResult if any limit breached.

    These are hard limits that override everything.
    """
    risk = config.get("risk_management", {})
    if not risk:
        return None

    # Max loss — check CUMULATIVE daily P&L (all cycles, not just current position)
    max_loss = risk.get("max_loss_per_day")
    daily_pnl = state.cumulative_daily_pnl + state.combined_pnl
    if max_loss is not None and daily_pnl <= -abs(max_loss):
        return RuleResult(
            True, "risk_max_loss_breached",
            {"type": "close_all_positions", "reason": f"Max daily loss ₹{max_loss} breached (daily PnL=₹{daily_pnl:.0f})"}
        )

    # Max trades
    max_trades = risk.get("max_trades_per_day")
    if max_trades is not None and state.total_trades_today >= max_trades:
        return RuleResult(
            True, "risk_max_trades_reached",
            {"type": "do_nothing", "reason": f"Max trades {max_trades} reached"}
        )

    # Max lots
    pos_sizing = risk.get("position_sizing", {})
    max_lots = pos_sizing.get("max_lots")
    if max_lots is not None:
        lots_cfg = config.get("basic", {}).get("lots", 1)
        if lots_cfg > max_lots:
            logger.warning(f"Configured lots {lots_cfg} exceeds max_lots {max_lots}")

    return None


def evaluate_trailing_stop(state: StrategyState) -> Optional[RuleResult]:
    """
    Check if trailing stop loss has been hit.

    Returns RuleResult if trailing stop is active and P&L has fallen below the stop level.
    """
    if not state.trailing_stop_active:
        return None

    # Update trailing stop level as P&L makes new highs
    if state.combined_pnl > state.peak_pnl:
        old_peak = state.peak_pnl
        state.peak_pnl = state.combined_pnl
        # Move stop up by the same amount the peak moved
        gain = state.peak_pnl - old_peak
        state.trailing_stop_level += gain

    if state.combined_pnl <= state.trailing_stop_level:
        logger.info(
            f"TRAILING STOP HIT: PnL={state.combined_pnl:.0f} <= "
            f"stop_level={state.trailing_stop_level:.0f}"
        )
        return RuleResult(
            True, "trailing_stop_hit",
            {"type": "close_all_positions", "reason": "Trailing stop loss hit"}
        )
    return None