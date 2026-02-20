from typing import List, Dict, Any, Optional
import logging
from .models import (
    Condition, Side, InstrumentType, OptionType, OrderType,
    StrikeMode, StrikeConfig, Comparator, JoinOperator
)
from .state import StrategyState, LegState
from .condition_engine import ConditionEngine
from .market_reader import MarketReader

logger = logging.getLogger(__name__)

class EntryEngine:
    def __init__(self, state: StrategyState, market: MarketReader):
        self.state = state
        self.market = market
        self.condition_engine = ConditionEngine(state)

    def process_entry(self, entry_config: Dict[str, Any], symbol: str, default_expiry: str) -> List[LegState]:
        """
        Process entry legs according to JSON config.
        Returns list of newly created LegState objects.
        """
        # 1. Evaluate global conditions
        global_conds = entry_config.get("global_conditions", [])
        cond_objs = [self._dict_to_condition(c) for c in global_conds]
        if not self.condition_engine.evaluate(cond_objs):
            return []  # global gate blocks entry

        # 2. Process each leg
        new_legs = []
        legs_config = entry_config.get("legs", [])
        sequence = entry_config.get("entry_sequence", "parallel")

        for leg_cfg in legs_config:
            leg_state = self._process_single_leg(leg_cfg, symbol, default_expiry)
            if leg_state:
                new_legs.append(leg_state)
                if sequence == "sequential":
                    # In a real system we would wait for fill confirmation.
                    # For now, we just continue.
                    logger.warning("Sequential entry mode is not fully implemented; legs are being placed together.")

        return new_legs

    def _process_single_leg(self, leg_cfg: Dict[str, Any], symbol: str, default_expiry: str) -> Optional[LegState]:
        """Process one entry leg: evaluate IF/ELSE, resolve strike, create LegState."""
        # --- Tag validation ---
        tag = leg_cfg.get("tag")
        if not tag or not isinstance(tag, str):
            raise ValueError("Each leg must have a non-empty string 'tag' field")

        # Evaluate IF conditions
        if_conds = leg_cfg.get("conditions", [])
        cond_objs = [self._dict_to_condition(c) for c in if_conds]
        if_condition_true = self.condition_engine.evaluate(cond_objs)

        # Decide which branch to use (IF or ELSE)
        use_else = leg_cfg.get("else_enabled", False) and not if_condition_true
        if use_else:
            else_conds = leg_cfg.get("else_conditions", [])
            else_cond_objs = [self._dict_to_condition(c) for c in else_conds]
            if not self.condition_engine.evaluate(else_cond_objs):
                return None
            exec_config = leg_cfg.get("else_action", {})
        else:
            if not if_condition_true:
                return None
            exec_config = leg_cfg

        # Determine instrument type
        instrument = InstrumentType(exec_config.get("instrument", "OPT"))
        side = Side(exec_config.get("side", "SELL"))
        lots = int(exec_config.get("lots", 1))
        order_type_str = exec_config.get("order_type")
        order_type = OrderType(order_type_str) if order_type_str else None

        # --- Expiry resolution ---
        expiry_mode = exec_config.get("expiry", "strategy_default")
        if expiry_mode == "strategy_default":
            expiry_mode = default_expiry

        # Resolve the mode to an actual date string using market reader
        try:
            expiry = self.market.resolve_expiry_mode(expiry_mode)
        except Exception as e:
            logger.error(f"Failed to resolve expiry mode '{expiry_mode}': {e}")
            return None

        if instrument == InstrumentType.FUT:
            # Futures leg
            ltp = self.market.get_fut_ltp(expiry) if hasattr(self.market, 'get_fut_ltp') else self.market.get_spot_price()
            leg = LegState(
                tag=tag,
                symbol=symbol,
                instrument=InstrumentType.FUT,
                option_type=None,
                strike=None,
                expiry=expiry,
                side=side,
                qty=lots,
                entry_price=ltp,
                ltp=ltp
            )
            return leg

        else:
            # Option leg
            opt_type = OptionType(exec_config.get("option_type", "CE"))
            strike_mode = StrikeMode(exec_config.get("strike_mode", "standard"))

            strike_cfg = StrikeConfig(
                mode=strike_mode,
                side=side,
                option_type=opt_type,
                lots=lots,
                order_type=order_type,
                strike_selection=exec_config.get("strike_selection"),
                strike_value=exec_config.get("strike_value"),
                exact_strike=exec_config.get("exact_strike"),
                atm_offset_points=exec_config.get("atm_offset_points"),
                atm_offset_pct=exec_config.get("atm_offset_pct"),
                match_leg=exec_config.get("match_leg"),
                match_param=exec_config.get("match_param"),
                match_offset=exec_config.get("match_offset", 0.0),
                match_multiplier=exec_config.get("match_multiplier", 1.0),
                rounding=exec_config.get("rounding")
            )

            reference_leg = None
            if strike_mode == StrikeMode.MATCH_LEG and strike_cfg.match_leg:
                reference_leg = self.state.legs.get(strike_cfg.match_leg)

            strike, opt_data = self.market.resolve_strike(
                strike_cfg, symbol, expiry, reference_leg
            )

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
                iv=opt_data.get("iv", 0.0)
            )
            return leg

    def _dict_to_condition(self, d: Dict[str, Any]) -> Condition:
        return Condition(
            parameter=d["parameter"],
            comparator=Comparator(d["comparator"]),
            value=d["value"],
            value2=d.get("value2"),
            join=JoinOperator(d["join"]) if d.get("join") else None
        )