from typing import List, Dict, Any, Optional
from .state import StrategyState, LegState
from .models import InstrumentType, OptionType, Side
import logging

logger = logging.getLogger(__name__)


class BrokerReconciliation:
    def __init__(self, state: StrategyState):
        self.state = state

    def reconcile(self, broker_positions: List[Dict[str, Any]]) -> List[str]:
        """
        Reconcile state legs against a list of positions that have 'tag' fields.
        This is the legacy method used for internal position snapshots.
        For live broker reconciliation, use reconcile_from_broker() instead.
        """
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

    def reconcile_from_broker(self, broker_view) -> List[str]:
        """
        BUG-012 FIX: Reconcile strategy state against LIVE broker positions.

        The original reconcile() compared state against itself (positions with 'tag' fields
        that came from the state). This method fetches REAL broker positions via BrokerView
        and maps them to state legs by trading_symbol / symbol match.

        Args:
            broker_view: BrokerView instance (bot.broker_view)

        Returns:
            List of warning strings describing mismatches found.
        """
        warnings: List[str] = []

        try:
            broker_positions = broker_view.get_positions(force_refresh=True) or []
        except Exception as e:
            warnings.append(f"RECONCILE: Failed to fetch broker positions: {e}")
            logger.error(f"BrokerReconciliation.reconcile_from_broker: fetch failed: {e}")
            return warnings

        # Build a map of broker symbol → net qty for fast lookup
        # Shoonya position fields: tsym=trading_symbol, netqty=net quantity
        broker_netqty: Dict[str, int] = {}
        for pos in broker_positions:
            tsym = pos.get("tsym", "")
            net = int(pos.get("netqty", 0))
            if tsym:
                broker_netqty[tsym] = broker_netqty.get(tsym, 0) + net

        # Check each active state leg against broker truth
        for tag, leg in list(self.state.legs.items()):
            if not leg.is_active:
                continue

            # Try trading_symbol first (the broker contract symbol), then symbol
            sym = getattr(leg, "trading_symbol", None) or leg.symbol
            if not sym:
                warnings.append(f"Leg {tag}: no symbol — cannot reconcile")
                continue

            net = broker_netqty.get(sym, 0)

            if net == 0:
                # State says active, broker says flat — position is gone
                warnings.append(
                    f"Leg {tag} ({sym}): state=ACTIVE but broker netqty=0 → marking inactive"
                )
                logger.warning(f"RECONCILE | {tag} ({sym}) | state says active but broker is flat")
                leg.is_active = False
            else:
                # Position exists — sync qty from broker truth
                broker_qty = abs(net)
                if leg.qty != broker_qty:
                    warnings.append(
                        f"Leg {tag} ({sym}): state qty={leg.qty} but broker qty={broker_qty} → syncing"
                    )
                    logger.info(f"RECONCILE | {tag} ({sym}) | qty state={leg.qty} → broker={broker_qty}")
                    leg.qty = broker_qty

        # Detect broker positions that have no corresponding active state leg
        # (orphan positions this strategy should know about)
        tracked_symbols = {
            (getattr(leg, "trading_symbol", None) or leg.symbol)
            for leg in self.state.legs.values()
            if leg.is_active
        }
        for sym, net in broker_netqty.items():
            if net != 0 and sym not in tracked_symbols:
                # Only warn — do NOT auto-create legs; that requires knowing expiry/strike/side
                warnings.append(
                    f"Broker has untracked position: {sym} netqty={net} "
                    f"(use /strategy/recover-resume to adopt it)"
                )
                logger.warning(f"RECONCILE | UNTRACKED BROKER POSITION | {sym} netqty={net}")

        if warnings:
            logger.warning(f"RECONCILE WARNINGS ({len(warnings)}): " + "; ".join(warnings))
        else:
            logger.debug("RECONCILE: state and broker are in sync")

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