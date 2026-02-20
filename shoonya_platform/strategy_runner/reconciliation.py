from typing import List, Dict, Any
from .state import StrategyState, LegState
from .models import InstrumentType, OptionType, Side

class BrokerReconciliation:
    def __init__(self, state: StrategyState):
        self.state = state

    def reconcile(self, broker_positions: List[Dict[str, Any]]) -> List[str]:
        warnings = []
        broker_tags = {p.get("tag") for p in broker_positions if p.get("tag")}

        for tag, leg in self.state.legs.items():
            if leg.is_active and tag not in broker_tags:
                warnings.append(f"Leg {tag} is active in state but missing in broker")
                leg.is_active = False

        for pos in broker_positions:
            tag = pos.get("tag")
            if tag and tag not in self.state.legs:
                warnings.append(f"Broker has extra position {tag} not in state")
                self._reconstruct_leg(pos)

        for pos in broker_positions:
            tag = pos.get("tag")
            if tag and tag in self.state.legs:
                leg = self.state.legs[tag]
                leg.ltp = pos.get("ltp", leg.ltp)
                if "delta" in pos:
                    leg.delta = pos["delta"]
                if "qty" in pos:
                    leg.qty = pos["qty"]
                    if leg.qty == 0:
                        leg.is_active = False

        return warnings

    def _reconstruct_leg(self, pos: Dict[str, Any]):
        leg = LegState(
            tag=pos.get("tag", "UNKNOWN"),
            symbol=pos.get("symbol", "UNKNOWN"),
            instrument=InstrumentType(pos.get("instrument", "OPT")),
            option_type=OptionType(pos.get("option_type")) if pos.get("option_type") else None,
            strike=pos.get("strike"),
            expiry=pos.get("expiry", "UNKNOWN"),
            side=Side(pos.get("side", "BUY")),
            qty=pos.get("qty", 0),
            entry_price=pos.get("entry_price", 0.0),
            ltp=pos.get("ltp", 0.0),
            group=pos.get("group", ""),
            label=pos.get("label", ""),
            oi=pos.get("oi", 0),
            oi_change=pos.get("oi_change", 0),
            volume=pos.get("volume", 0)
        )
        self.state.legs[leg.tag] = leg