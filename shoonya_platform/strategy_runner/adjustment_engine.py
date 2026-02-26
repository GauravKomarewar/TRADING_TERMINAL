from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
from .state import StrategyState, LegState
from .condition_engine import ConditionEngine
from .market_reader import MarketReader
from .models import (
    Condition, Comparator, JoinOperator, StrikeConfig,
    InstrumentType, OptionType, Side, OrderType, StrikeMode
)

logger = logging.getLogger(__name__)

class AdjustmentEngine:
    def __init__(self, state: StrategyState, market: MarketReader):
        self.state = state
        self.market = market
        self.condition_engine = ConditionEngine(state)
        self.rules_config = []

    def load_rules(self, rules_config: List[Dict[str, Any]]):
        self.rules_config = sorted(rules_config, key=lambda r: r.get("priority", 999))

    def check_and_apply(self, current_time: datetime) -> List[str]:
        actions_taken = []
        for rule in self.rules_config:
            if not self._check_guards(rule, current_time):
                continue

            if_conds = rule.get("conditions", [])
            cond_objs = [self._dict_to_condition(c) for c in if_conds]
            if self.condition_engine.evaluate(cond_objs):
                action = rule["action"]
                self._execute_action(action, "if", rule)
                actions_taken.append(f"Rule {rule.get('name')}: IF triggered")
                self.state.last_adjustment_time = current_time
                self.state.adjustments_today += 1
                self.state.lifetime_adjustments += 1

            elif rule.get("else_enabled"):
                else_conds = rule.get("else_conditions", [])
                else_cond_objs = [self._dict_to_condition(c) for c in else_conds]
                if self.condition_engine.evaluate(else_cond_objs):
                    else_action = rule["else_action"]
                    self._execute_action(else_action, "else", rule)
                    actions_taken.append(f"Rule {rule.get('name')}: ELSE triggered")
                    self.state.last_adjustment_time = current_time
                    self.state.adjustments_today += 1
                    self.state.lifetime_adjustments += 1

        return actions_taken

    def _check_guards(self, rule: Dict[str, Any], current_time: Optional[datetime] = None) -> bool:
        cooldown = rule.get("cooldown_sec", 0)
        now = current_time or datetime.now()
        if cooldown > 0 and self.state.last_adjustment_time:
            if (now - self.state.last_adjustment_time).total_seconds() < cooldown:
                return False

        max_day = rule.get("max_per_day")
        if max_day and self.state.adjustments_today >= max_day:
            return False

        max_total = rule.get("max_total")
        if max_total and self.state.lifetime_adjustments >= max_total:
            return False

        leg_guard = rule.get("leg_guard")
        if leg_guard:
            leg = self.state.legs.get(leg_guard)
            if not leg or not leg.is_active:
                return False

        return True

    def _execute_action(self, action_cfg: Dict[str, Any], branch: str, rule: Dict[str, Any]):
        action_type = action_cfg["type"]

        if action_type == "close_leg":
            close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
            if close_tag and close_tag in self.state.legs:
                self.state.legs[close_tag].is_active = False

        elif action_type == "partial_close_lots":
            close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
            lots_to_close = action_cfg.get("lots", 1)
            if close_tag and close_tag in self.state.legs:
                leg = self.state.legs[close_tag]
                leg.qty -= lots_to_close
                if leg.qty <= 0:
                    leg.is_active = False

        elif action_type == "reduce_by_pct":
            close_tag = self._resolve_close_tag(action_cfg.get("close_tag"))
            pct = action_cfg.get("reduce_pct", 50) / 100.0
            if close_tag and close_tag in self.state.legs:
                leg = self.state.legs[close_tag]
                new_qty = int(leg.qty * (1 - pct))
                leg.qty = new_qty
                if leg.qty <= 0:
                    leg.is_active = False

        elif action_type == "open_hedge":
            new_leg_cfg = action_cfg.get("new_leg", {})
            self._open_new_leg(new_leg_cfg)

        elif action_type == "roll_to_next_expiry":
            leg_tag = self._resolve_close_tag(action_cfg.get("leg"))
            target_expiry = action_cfg.get("target_expiry", "weekly_next")
            same_strike = action_cfg.get("same_strike", "yes")
            if leg_tag not in self.state.legs:
                logger.error(f"Roll target leg {leg_tag} not found")
                return
            old_leg = self.state.legs[leg_tag]

            # Ensure the leg is an option (rolling futures not supported)
            if old_leg.instrument != InstrumentType.OPT:
                raise ValueError(f"Roll action can only be applied to option legs, not {old_leg.instrument}")

            # At this point, old_leg.option_type is guaranteed to be not None
            assert old_leg.option_type is not None, "Option leg must have option_type"

            old_leg.is_active = False
            new_expiry = self._resolve_next_expiry(target_expiry, old_leg.expiry)

            # Determine new strike and option data
            opt_data: Optional[Dict[str, Any]] = None
            strike: float = 0.0

            if same_strike == "yes":
                if old_leg.strike is None:
                    raise ValueError(f"Leg {leg_tag} has no strike, cannot roll with same_strike=yes")
                strike = old_leg.strike
                opt_data = self.market.get_option_at_strike(
                    strike, old_leg.option_type, expiry=new_expiry
                )
            elif same_strike == "atm":
                new_atm = self.market.get_atm_strike(new_expiry)
                strike = new_atm
                opt_data = self.market.get_option_at_strike(
                    new_atm, old_leg.option_type, expiry=new_expiry
                )
            elif same_strike == "delta":
                # old_leg.option_type is already asserted not None
                opt_data = self.market.find_option_by_delta(
                    old_leg.option_type, abs(old_leg.delta), expiry=new_expiry
                )
                if opt_data is not None:
                    strike = opt_data["strike"]
            else:
                raise ValueError(f"Unknown same_strike option: {same_strike}")

            if opt_data is None:
                raise ValueError(f"Could not resolve option for roll: {leg_tag} -> {new_expiry}")

            # ✅ BUG-015 FIX: Tag collision on multiple rolls — e.g. "LEG_ROLLED_ROLLED".
            # Use a numeric counter suffix to guarantee uniqueness.
            base_tag = leg_tag.split("_ROLLED")[0]  # strip any existing _ROLLED suffix
            roll_num = 1
            candidate = f"{base_tag}_ROLLED_{roll_num}"
            while candidate in self.state.legs:
                roll_num += 1
                candidate = f"{base_tag}_ROLLED_{roll_num}"
            new_tag = candidate
            new_leg = LegState(
                tag=new_tag,
                symbol=old_leg.symbol,
                instrument=old_leg.instrument,
                option_type=old_leg.option_type,
                strike=strike,
                expiry=new_expiry,
                side=old_leg.side,
                qty=old_leg.qty,
                entry_price=opt_data["ltp"],
                ltp=opt_data["ltp"],
                delta=opt_data.get("delta", 0.0),
                gamma=opt_data.get("gamma", 0.0),
                theta=opt_data.get("theta", 0.0),
                vega=opt_data.get("vega", 0.0),
                iv=opt_data.get("iv", 0.0),
                trading_symbol=(
                    opt_data.get("trading_symbol")
                    or opt_data.get("tsym")
                    or opt_data.get("symbol")
                    or old_leg.trading_symbol
                ),
            )
            # 🔒 Mark as pending – will become active only after fill
            new_leg.is_active = False
            new_leg.order_status = "PENDING"
            new_leg.order_placed_at = datetime.now()
            self.state.legs[new_tag] = new_leg

        elif action_type == "convert_to_spread":
            wing_cfg = action_cfg.get("wing_leg", {})
            self._open_new_leg(wing_cfg)

        elif action_type == "simple_close_open_new":
            swaps = action_cfg.get("leg_swaps", [])
            for swap in swaps:
                close_tag = self._resolve_close_tag(swap.get("close_tag"))
                new_leg_cfg = swap.get("new_leg", {})
                closing_leg = self.state.legs.get(close_tag) if close_tag else None
                if close_tag and close_tag in self.state.legs:
                    self.state.legs[close_tag].is_active = False
                self._open_new_leg(new_leg_cfg, closing_leg=closing_leg)

    def _open_new_leg(self, leg_cfg: Dict[str, Any], closing_leg: Optional[LegState] = None):
        """Open a new leg based on strike config (from action)."""
        # Extract basic fields
        side = Side(leg_cfg.get("side", "BUY"))
        opt_type = self._resolve_option_type(leg_cfg.get("option_type", "CE"), closing_leg)
        lots = int(leg_cfg.get("lots", 1))
        order_type_str = leg_cfg.get("order_type")
        order_type = OrderType(order_type_str) if order_type_str else None

        # Determine strike mode
        mode_str = leg_cfg.get("strike_mode", "standard")
        try:
            mode = StrikeMode(mode_str)
        except ValueError:
            mode = StrikeMode.STANDARD

        # Build StrikeConfig
        strike_cfg = StrikeConfig(
            mode=mode,
            side=side,
            option_type=opt_type,
            lots=lots,
            order_type=order_type,
            strike_selection=leg_cfg.get("strike_selection"),
            strike_value=leg_cfg.get("strike_value"),
            exact_strike=leg_cfg.get("exact_strike"),
            atm_offset_points=leg_cfg.get("atm_offset_points"),
            atm_offset_pct=leg_cfg.get("atm_offset_pct"),
            match_leg=leg_cfg.get("match_leg"),
            match_param=leg_cfg.get("match_param"),
            match_offset=leg_cfg.get("match_offset", 0.0),
            match_multiplier=leg_cfg.get("match_multiplier", 1.0),
            rounding=leg_cfg.get("rounding")
        )

        # Determine symbol and expiry from existing legs
        symbol: Optional[str] = None
        expiry: Optional[str] = None
        for leg in self.state.legs.values():
            if leg.is_active:
                symbol = leg.symbol
                expiry = leg.expiry
                break
        if symbol is None:
            # No active legs — pick symbol from any existing leg for reference
            for leg in self.state.legs.values():
                symbol = leg.symbol
                break
        # If still no symbol, we cannot proceed
        if symbol is None:
            raise ValueError("Cannot determine symbol for adjustment leg: no active or existing leg found.")
        if expiry is None:
            expiry = "current"   # market reader should resolve this

        # For match_leg, we may need a reference leg
        reference_leg = None
        if mode == StrikeMode.MATCH_LEG and strike_cfg.match_leg:
            ref_tag = self._resolve_close_tag(strike_cfg.match_leg)
            if ref_tag:
                reference_leg = self.state.legs.get(ref_tag)

        strike, opt_data = self.market.resolve_strike(
            strike_cfg, symbol, expiry=expiry, reference_leg_state=reference_leg
        )

        # Generate unique tag
        base_tag = leg_cfg.get("tag", "NEW_LEG")
        existing_tags = set(self.state.legs.keys())
        tag = base_tag
        counter = 1
        while tag in existing_tags:
            tag = f"{base_tag}_{counter}"
            counter += 1

        # Create the new leg
        leg = LegState(
            tag=tag,
            symbol=symbol,
            instrument=InstrumentType.OPT,
            option_type=opt_type,
            strike=strike,
            expiry=expiry,
            side=side,
            qty=lots,
            entry_price=opt_data["ltp"],
            ltp=opt_data["ltp"],
            delta=opt_data.get("delta", 0.0),
            gamma=opt_data.get("gamma", 0.0),
            theta=opt_data.get("theta", 0.0),
            vega=opt_data.get("vega", 0.0),
            iv=opt_data.get("iv", 0.0),
            trading_symbol=(
                opt_data.get("trading_symbol")
                or opt_data.get("tsym")
                or opt_data.get("symbol")
                or ""
            ),
        )

        # 🔒 Mark as pending, not active – will become active only after fill
        leg.is_active = False
        leg.order_status = "PENDING"
        leg.order_placed_at = datetime.now()

        self.state.legs[tag] = leg

    def _resolve_close_tag(self, close_tag: Optional[str]) -> Optional[str]:
        if not close_tag:
            return None
        if close_tag in self.state.legs and self.state.legs[close_tag].is_active:
            return close_tag
        dynamic_map = {
            "HIGHER_DELTA_LEG": self.state.higher_delta_leg,
            "LOWER_DELTA_LEG": self.state.lower_delta_leg,
            "MOST_PROFITABLE_LEG": self.state.most_profitable_leg,
            "LEAST_PROFITABLE_LEG": self.state.least_profitable_leg,
            "HIGHER_THETA_LEG": self.state.higher_theta_leg,
            "LOWER_THETA_LEG": self.state.lower_theta_leg,
            "HIGHER_IV_LEG": self.state.higher_iv_leg,
            "LOWER_IV_LEG": self.state.lower_iv_leg,
            "DEEPEST_ITM_LEG": self.state.deepest_itm_leg,
            "MOST_OTM_LEG": self.state.most_otm_leg,
        }
        return dynamic_map.get(close_tag)

    def _resolve_option_type(self, raw_option_type: str, closing_leg: Optional[LegState]) -> OptionType:
        if raw_option_type == "MATCH_CLOSING":
            if closing_leg and closing_leg.option_type:
                return closing_leg.option_type
            tag = self.state.higher_delta_leg
            if tag and tag in self.state.legs and self.state.legs[tag].option_type:
                return self.state.legs[tag].option_type  # type: ignore[return-value]
            return OptionType.CE
        if raw_option_type == "MATCH_OPPOSITE":
            if closing_leg and closing_leg.option_type == OptionType.CE:
                return OptionType.PE
            if closing_leg and closing_leg.option_type == OptionType.PE:
                return OptionType.CE
            tag = self.state.higher_delta_leg
            if tag and tag in self.state.legs:
                ref_opt = self.state.legs[tag].option_type
                if ref_opt == OptionType.CE:
                    return OptionType.PE
                if ref_opt == OptionType.PE:
                    return OptionType.CE
            return OptionType.PE
        return OptionType(raw_option_type)

    def _resolve_next_expiry(self, target_expiry: str, current_expiry: str) -> str:
        """
        Resolve expiry string for roll using market reader.
        """
        return self.market.get_next_expiry(current_expiry, target_expiry)

    def _dict_to_condition(self, d: Dict[str, Any]) -> Condition:
        return Condition(
            parameter=d["parameter"],
            comparator=Comparator(d["comparator"]),
            value=d["value"],
            value2=d.get("value2"),
            join=JoinOperator(d["join"]) if d.get("join") else None
        )
