from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from .state import StrategyState
from .condition_engine import ConditionEngine
from .models import Condition, Comparator, JoinOperator

logger = logging.getLogger(__name__)

class ExitEngine:
    def __init__(self, state: StrategyState):
        self.state = state
        self.condition_engine = ConditionEngine(state)
        self.exit_config = {}

    def load_config(self, exit_config: Dict[str, Any]):
        self.exit_config = exit_config

    def check_exits(self, current_time: datetime) -> Optional[str]:
        # 1. Profit target
        action = self._check_profit_target()
        if action:
            return action

        # 2. Stop loss
        action = self._check_stop_loss()
        if action:
            return action

        # 3. Trailing stop
        action = self._check_trailing_stop()
        if action:
            return action

        # 4. Profit steps
        action = self._check_profit_steps()
        if action:
            return action

        # 5. Time-based exit
        action = self._check_time_exit(current_time)
        if action:
            return action

        # 6. Combined conditions (custom)
        combined = self.exit_config.get("combined_conditions", {})
        if combined.get("operator") == "OR":
            rules = combined.get("rules", [])
            if rules:
                cond_objs = [self._dict_to_condition(c) for c in rules]
                if self.condition_engine.evaluate(cond_objs):
                    return "combined_conditions"
        elif combined.get("operator") == "AND":
            # ✅ BUG-011 FIX: AND operator was silently ignored — all conditions must hold
            rules = combined.get("rules", [])
            if rules:
                cond_objs = [self._dict_to_condition(c) for c in rules]
                if all(self.condition_engine.evaluate([c]) for c in cond_objs):
                    return "combined_conditions"

        # 7. Per-leg exit rules
        leg_rules = self.exit_config.get("leg_rules", [])
        for rule in leg_rules:
            if self._check_leg_rule(rule):
                return f"leg_rule_{rule.get('action')}"

        return None

    def _check_profit_target(self) -> Optional[str]:
        cfg = self.exit_config.get("profit_target", {})
        amount = cfg.get("amount")
        pct = cfg.get("pct")
        if amount and self.state.combined_pnl >= amount:
            return cfg.get("action", "exit_all")
        if pct and self.state.total_premium != 0 and (self.state.combined_pnl / self.state.total_premium * 100) >= pct:
            return cfg.get("action", "exit_all")
        return None

    def _check_stop_loss(self) -> Optional[str]:
        cfg = self.exit_config.get("stop_loss", {})
        amount = cfg.get("amount")
        pct = cfg.get("pct")
        # ✅ BUG-010 FIX: `if amount` is False when amount=0. Use `is not None` so
        # a zero stop-loss (lock breakeven) correctly triggers.
        if amount is not None and self.state.combined_pnl <= -amount:
            return cfg.get("action", "exit_all")
        if pct and self.state.total_premium != 0 and (self.state.combined_pnl / self.state.total_premium * 100) <= -pct:
            return cfg.get("action", "exit_all")
        return None

    def _check_trailing_stop(self) -> Optional[str]:
        cfg = self.exit_config.get("trailing", {})
        trail_amt = cfg.get("trail_amount")
        lock_in = cfg.get("lock_in_at")
        step = cfg.get("trail_step")
        step_trigger = cfg.get("step_trigger")

        if not trail_amt:
            return None

        current_pnl = self.state.combined_pnl
        if current_pnl > self.state.peak_pnl:
            self.state.peak_pnl = current_pnl

        if not self.state.trailing_stop_active and lock_in and current_pnl >= lock_in:
            self.state.trailing_stop_active = True
            self.state.trailing_stop_level = current_pnl - trail_amt

        if self.state.trailing_stop_active:
            if step_trigger and (self.state.peak_pnl - self.state.trailing_stop_level) >= step_trigger:
                self.state.trailing_stop_level = self.state.peak_pnl - trail_amt

            if current_pnl <= self.state.trailing_stop_level:
                return "exit_all"

        return None

    def _check_profit_steps(self) -> Optional[str]:
        cfg = self.exit_config.get("profit_steps", {})
        step_size = cfg.get("step_size")
        max_steps = cfg.get("max_steps")
        action = cfg.get("action", "adj")
        if not step_size or not max_steps:
            return None
        # ✅ BUG-017 FIX: step_size=0 causes ZeroDivisionError — guard explicitly
        if not step_size:
            return None

        current_pnl = self.state.combined_pnl
        step = int(current_pnl // step_size)
        if step > max_steps:
            step = max_steps
        if step > self.state.current_profit_step:
            self.state.current_profit_step = step
            return f"profit_step_{action}"
        return None

    def _check_time_exit(self, current_time: datetime) -> Optional[str]:
        exit_time_str = self.exit_config.get("time", {}).get("strategy_exit_time")
        if exit_time_str:
            try:
                exit_t = datetime.strptime(exit_time_str, "%H:%M").time()
                if current_time.time() >= exit_t:
                    return "exit_all"
            except ValueError:
                pass
        return None

    def _check_leg_rule(self, rule: Dict[str, Any]) -> bool:
        ref = rule.get("exit_leg_ref")
        group = rule.get("group")
        applicable_legs = []
        if ref == "all":
            applicable_legs = [leg for leg in self.state.legs.values() if leg.is_active]
        elif ref == "group" and group:
            applicable_legs = [leg for leg in self.state.legs.values() if leg.is_active and leg.group == group]
        elif ref in self.state.legs:
            leg = self.state.legs[ref]
            if leg.is_active:
                applicable_legs = [leg]

        conds = rule.get("conditions", [])
        if not conds:
            return False
        cond_objs = [self._dict_to_condition(c) for c in conds]
        # If any applicable leg, evaluate conditions (they may refer to specific leg via tag)
        for leg in applicable_legs:
            # Condition engine already resolves tag references using state
            if self.condition_engine.evaluate(cond_objs):
                return True
        return False

    def _dict_to_condition(self, d: Dict[str, Any]) -> Condition:
        return Condition(
            parameter=d["parameter"],
            comparator=Comparator(d["comparator"]),
            value=d["value"],
            value2=d.get("value2"),
            join=JoinOperator(d["join"]) if d.get("join") else None
        )