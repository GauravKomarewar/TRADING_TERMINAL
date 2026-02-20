#!/usr/bin/env python3
"""
condition_engine.py — Rule & Condition Evaluation Engine (Final)
=================================================================
"""
import re
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from .models import Condition, Comparator, JoinOperator
from .state import StrategyState

logger = logging.getLogger(__name__)

class ConditionEngine:
    def __init__(self, state: StrategyState):
        self.state = state

    def evaluate(self, conditions: List[Condition]) -> bool:
        if not conditions:
            return True

        result = None
        for i, cond in enumerate(conditions):
            val = self._evaluate_single(cond)
            if i == 0:
                result = val
            else:
                join_op = cond.join or JoinOperator.AND
                if join_op == JoinOperator.AND:
                    result = result and val
                else:
                    result = result or val
        return bool(result)

    def _evaluate_single(self, cond: Condition) -> bool:
        param_value = self._resolve_parameter(cond.parameter)
        comp = cond.comparator
        val1 = cond.value
        val2 = cond.value2

        # --- Helper conversion functions ---
        def to_numeric(x: Any) -> Optional[float]:
            if isinstance(x, (int, float)):
                return float(x)
            if isinstance(x, str):
                try:
                    return float(x)
                except ValueError:
                    return None
            return None

        def to_bool(x: Any) -> Optional[bool]:
            if isinstance(x, bool):
                return x
            if isinstance(x, str):
                if x.lower() == 'true':
                    return True
                if x.lower() == 'false':
                    return False
            return None

        def to_minutes(x: Any) -> Optional[float]:
            if isinstance(x, str) and ':' in x:
                try:
                    t = datetime.strptime(x, "%H:%M").time()
                    return t.hour * 60 + t.minute
                except ValueError:
                    return None
            return None

        # Determine intended comparison type
        param_is_bool = isinstance(param_value, bool)
        val1_is_bool = isinstance(val1, bool)
        param_is_time = isinstance(param_value, str) and ':' in param_value
        val1_is_time = isinstance(val1, str) and ':' in str(val1)

        # -------- BOOLEAN BRANCH --------
        if param_is_bool or val1_is_bool:
            pv = to_bool(param_value)
            v1 = to_bool(val1)
            if pv is None or v1 is None:
                logger.warning(f"Cannot compare boolean with non-boolean: {param_value} vs {val1}")
                return False
            # Both are now bool
            if comp == Comparator.GT:
                return pv > v1
            elif comp == Comparator.GTE:
                return pv >= v1
            elif comp == Comparator.LT:
                return pv < v1
            elif comp == Comparator.LTE:
                return pv <= v1
            elif comp == Comparator.EQ:
                return pv == v1
            elif comp == Comparator.NEQ:
                return pv != v1
            elif comp == Comparator.APPROX:
                # Approximation for bools – treat as equality
                return pv == v1
            elif comp == Comparator.BETWEEN:
                if val2 is None:
                    return False
                v2 = to_bool(val2)
                if v2 is None:
                    return False
                # between with two bools: pv must be between v1 and v2 inclusive
                low, high = (v1, v2) if v1 <= v2 else (v2, v1)
                return low <= pv <= high
            elif comp == Comparator.NOT_BETWEEN:
                if val2 is None:
                    return False
                v2 = to_bool(val2)
                if v2 is None:
                    return False
                low, high = (v1, v2) if v1 <= v2 else (v2, v1)
                return not (low <= pv <= high)
            elif comp == Comparator.IS_TRUE:
                return pv is True
            elif comp == Comparator.IS_FALSE:
                return pv is False
            elif comp in (Comparator.CROSSES_ABOVE, Comparator.CROSSES_BELOW):
                prev = self.state.prev_values.get(cond.parameter)
                self.state.prev_values[cond.parameter] = pv
                if prev is None:
                    return False
                prev_bool = to_bool(prev)
                if prev_bool is None:
                    return False
                if comp == Comparator.CROSSES_ABOVE:
                    return prev_bool <= v1 and pv > v1
                else:
                    return prev_bool >= v1 and pv < v1
            else:
                raise ValueError(f"Unsupported comparator for boolean: {comp}")

        # -------- TIME BRANCH --------
        if param_is_time or val1_is_time:
            pv = to_minutes(param_value)
            v1 = to_minutes(val1)
            if pv is None or v1 is None:
                logger.warning(f"Cannot compare time with non-time: {param_value} vs {val1}")
                return False
            # Both are now float (minutes)
            if comp == Comparator.GT:
                return pv > v1
            elif comp == Comparator.GTE:
                return pv >= v1
            elif comp == Comparator.LT:
                return pv < v1
            elif comp == Comparator.LTE:
                return pv <= v1
            elif comp == Comparator.EQ:
                return pv == v1
            elif comp == Comparator.NEQ:
                return pv != v1
            elif comp == Comparator.APPROX:
                if v1 == 0:
                    return abs(pv) < 0.02 * (abs(pv) + 1e-9)
                return abs((pv - v1) / v1) <= 0.02
            elif comp == Comparator.BETWEEN:
                if val2 is None:
                    return False
                v2 = to_minutes(val2)
                if v2 is None:
                    return False
                return v1 <= pv <= v2
            elif comp == Comparator.NOT_BETWEEN:
                if val2 is None:
                    return False
                v2 = to_minutes(val2)
                if v2 is None:
                    return False
                return not (v1 <= pv <= v2)
            elif comp == Comparator.IS_TRUE:
                return bool(pv) is True
            elif comp == Comparator.IS_FALSE:
                return bool(pv) is False
            elif comp in (Comparator.CROSSES_ABOVE, Comparator.CROSSES_BELOW):
                prev = self.state.prev_values.get(cond.parameter)
                self.state.prev_values[cond.parameter] = pv
                if prev is None:
                    return False
                prev_time = to_minutes(prev)
                if prev_time is None:
                    return False
                if comp == Comparator.CROSSES_ABOVE:
                    return prev_time <= v1 and pv > v1
                else:
                    return prev_time >= v1 and pv < v1
            else:
                raise ValueError(f"Unsupported comparator for time: {comp}")

        # -------- NUMERIC BRANCH (default) --------
        pv = to_numeric(param_value)
        v1 = to_numeric(val1)
        if pv is None or v1 is None:
            logger.warning(f"Cannot compare numeric with non-numeric: {param_value} vs {val1}")
            return False
        # Both are now float

        if comp == Comparator.GT:
            return pv > v1
        elif comp == Comparator.GTE:
            return pv >= v1
        elif comp == Comparator.LT:
            return pv < v1
        elif comp == Comparator.LTE:
            return pv <= v1
        elif comp == Comparator.EQ:
            return pv == v1
        elif comp == Comparator.NEQ:
            return pv != v1
        elif comp == Comparator.APPROX:
            if v1 == 0:
                return abs(pv) < 0.02 * (abs(pv) + 1e-9)
            return abs((pv - v1) / v1) <= 0.02
        elif comp == Comparator.BETWEEN:
            if val2 is None:
                return False
            v2 = to_numeric(val2)
            if v2 is None:
                return False
            return v1 <= pv <= v2
        elif comp == Comparator.NOT_BETWEEN:
            if val2 is None:
                return False
            v2 = to_numeric(val2)
            if v2 is None:
                return False
            return not (v1 <= pv <= v2)
        elif comp == Comparator.IS_TRUE:
            return bool(pv) is True
        elif comp == Comparator.IS_FALSE:
            return bool(pv) is False
        elif comp in (Comparator.CROSSES_ABOVE, Comparator.CROSSES_BELOW):
            prev = self.state.prev_values.get(cond.parameter)
            self.state.prev_values[cond.parameter] = pv
            if prev is None:
                return False
            prev_num = to_numeric(prev)
            if prev_num is None:
                return False
            if comp == Comparator.CROSSES_ABOVE:
                return prev_num <= v1 and pv > v1
            else:
                return prev_num >= v1 and pv < v1
        else:
            raise ValueError(f"Unknown comparator: {comp}")

    def _resolve_parameter(self, param: str) -> Any:
        # Handle abs(...)
        abs_match = re.match(r'^abs\((.+)\)$', param)
        if abs_match:
            inner = abs_match.group(1)
            return abs(self._resolve_parameter(inner))

        # Handle moneyness (needs spot price)
        if param in ("ce_moneyness", "pe_moneyness"):
            opt_type = "CE" if param.startswith("ce") else "PE"
            leg = self._find_leg_by_option_type(opt_type)
            if leg and leg.strike and self.state.spot_price:
                return (leg.strike - self.state.spot_price) / self.state.spot_price
            return 0.0

        # New parameters
        if param == "days_to_expiry":
            return self.state.days_to_expiry
        if param == "is_expiry_day":
            return self.state.is_expiry_day
        if param == "session_type":
            return self.state.session_type
        if param == "minutes_to_exit":
            return self.state.minutes_to_exit
        if param == "india_vix":
            idx = self.state.index_data.get("INDIAVIX", {})
            return idx.get("ltp", 0.0)
        if param == "pcr":
            # Placeholder – implement via market reader if needed
            return 0.0
        if param == "pcr_volume":
            return 0.0

        # Legacy CE/PE parameter handling
        if param.startswith("ce_") or param.startswith("pe_"):
            opt_type = "CE" if param.startswith("ce_") else "PE"
            attr = param[3:]  # remove ce_ or pe_
            leg = self._find_leg_by_option_type(opt_type)
            if leg and hasattr(leg, attr):
                return getattr(leg, attr)
            return 0.0
        
        # Direct attributes + properties
        if param == "spot_price":
            return self.state.spot_price
        elif param == "spot_open":
            return self.state.spot_open
        elif param == "atm_strike":
            return self.state.atm_strike
        elif param == "fut_ltp":
            return self.state.fut_ltp
        elif param == "time_current":
            t = self.state.current_time or datetime.now()
            return t.strftime("%H:%M")
        elif param == "net_delta":
            return self.state.net_delta
        elif param == "combined_pnl":
            return self.state.combined_pnl
        elif param == "total_premium":
            return self.state.total_premium
        elif param == "max_leg_delta":
            return self.state.max_leg_delta
        elif param == "min_leg_delta":
            return self.state.min_leg_delta
        elif param == "most_profitable_leg":
            return self.state.most_profitable_leg
        elif param == "least_profitable_leg":
            return self.state.least_profitable_leg
        elif param == "adj_count_today":
            return self.state.adjustments_today
        elif param.startswith("index_"):
            parts = param.split('_', 2)
            if len(parts) >= 3:
                idx = parts[1]
                attr = parts[2]
                key = f"{idx}_{attr}"
                return self.state.index_data.get(key, 0.0)
            return 0.0
        elif param.startswith("tag."):
            match = re.match(r"tag\.([^.]+)\.(.+)", param)
            if match:
                tag, metric = match.groups()
                leg = self.state.legs.get(tag)
                if leg:
                    if metric == "pnl":
                        return leg.pnl
                    elif metric == "pnl_pct":
                        return leg.pnl_pct
                    elif metric == "abs_delta":
                        return leg.abs_delta
                    elif hasattr(leg, metric):
                        return getattr(leg, metric)
            return 0.0
        else:
            return getattr(self.state, param, 0.0)

    def _find_leg_by_option_type(self, opt_type: str):
        """Helper to find first leg with given option type (for CE/PE‑centric legacy params)."""
        for leg in self.state.legs.values():
            if leg.option_type and leg.option_type.value == opt_type:
                return leg
        return None