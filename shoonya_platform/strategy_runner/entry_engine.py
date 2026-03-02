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
            logger.info(
                "ENTRY_SKIPPED_GLOBAL_CONDITIONS | strategy_symbol=%s | conditions=%s",
                symbol,
                self._condition_summary(global_conds),
            )
            return []  # global gate blocks entry

        # 2. Detect if this is a straddle entry (CE + PE with delta matching)
        legs_config = entry_config.get("legs", [])
        is_straddle = self._detect_straddle_entry(legs_config)
        if is_straddle:
            logger.info(f"Detected straddle entry pattern - using balanced delta matching")

        # 3. Process each leg
        new_legs = []
        sequence = entry_config.get("entry_sequence", "parallel")

        for leg_cfg in legs_config:
            leg_state = self._process_single_leg(leg_cfg, symbol, default_expiry, is_straddle)
            if leg_state:
                new_legs.append(leg_state)
                if sequence == "sequential":
                    # In a real system we would wait for fill confirmation.
                    # For now, we just continue.
                    logger.warning("Sequential entry mode is not fully implemented; legs are being placed together.")

        if not new_legs:
            logger.info(
                "ENTRY_SKIPPED_ALL_LEGS_FILTERED | strategy_symbol=%s | leg_count=%s",
                symbol,
                len(legs_config),
            )
        return new_legs

    def _detect_straddle_entry(self, legs_config: List[Dict[str, Any]]) -> bool:
        """
        Detect if entry configuration is for a straddle (CE + PE with delta matching).
        Returns True if:
        - Exactly 2 legs
        - One is CE, one is PE
        - Both use "delta" strike_selection
        - Both have similar strike_values
        """
        if len(legs_config) != 2:
            return False
        
        leg_config_1, leg_config_2 = legs_config[0], legs_config[1]
        
        # Check if one is CE and one is PE
        opt_types = {leg_config_1.get("option_type"), leg_config_2.get("option_type")}
        if opt_types != {"CE", "PE"}:
            return False
        
        # Check if both use delta selection
        sel_1 = leg_config_1.get("strike_selection")
        sel_2 = leg_config_2.get("strike_selection")
        if sel_1 != "delta" or sel_2 != "delta":
            return False
        
        # Check if delta values are similar (for straddle, both should target ~0.5)
        val_1 = float(leg_config_1.get("strike_value", 0.3))
        val_2 = float(leg_config_2.get("strike_value", 0.3))
        if abs(val_1 - val_2) > 0.05:  # Allow 0.05 margin
            return False
        
        logger.debug(f"Straddle detected: CE delta={val_1}, PE delta={val_2}")
        return True

    def _process_single_leg(self, leg_cfg: Dict[str, Any], symbol: str, default_expiry: str, is_straddle: bool = False) -> Optional[LegState]:
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
                logger.info(
                    "ENTRY_LEG_SKIPPED | tag=%s | reason=ELSE_CONDITIONS_FALSE | if_conditions=%s | else_conditions=%s",
                    tag,
                    self._condition_summary(if_conds),
                    self._condition_summary(else_conds),
                )
                return None
            exec_config = leg_cfg.get("else_action", {})
        else:
            if not if_condition_true:
                logger.info(
                    "ENTRY_LEG_SKIPPED | tag=%s | reason=IF_CONDITIONS_FALSE | conditions=%s",
                    tag,
                    self._condition_summary(if_conds),
                )
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
                strike_cfg, symbol, expiry, reference_leg, is_straddle_context=is_straddle
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
                iv=opt_data.get("iv", 0.0),
                trading_symbol=(
                    opt_data.get("trading_symbol")
                    or opt_data.get("tsym")
                    or opt_data.get("symbol")
                    or ""
                ),
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

    @staticmethod
    def _condition_summary(conditions: List[Dict[str, Any]]) -> str:
        if not conditions:
            return "[]"
        parts: List[str] = []
        for c in conditions:
            if not isinstance(c, dict):
                continue
            param = c.get("parameter", "?")
            comp = c.get("comparator", "?")
            value = c.get("value")
            value2 = c.get("value2")
            join = c.get("join")
            expr = f"{param} {comp} {value}"
            if value2 is not None:
                expr += f", {value2}"
            if join:
                expr += f" [{join}]"
            parts.append(expr)
        return "; ".join(parts) if parts else "[]"
