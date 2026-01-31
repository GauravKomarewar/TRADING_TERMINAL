# 🔒 EXECUTION GUARD — FROZEN (DO NOT MODIFY WITHOUT AUDIT)
# 🔒 CRITICAL RISK COMPONENT
# Version : v1.3.0
# Status  : PRODUCTION FROZEN — AUDITED 2026-01-30
# Changes from v1.2:
# • Added force_clear_symbol() — OrderWatcher failure recovery
# • Partial reconciliation support — broker qty reductions now tracked
# • Explicit direction-aware broker contract — {symbol: {direction: qty}}
# • Complete global position cleanup on reconciliation
#
# Any change requires:
# 1. Execution flow audit
# 2. Cross-strategy conflict review
# 3. Broker reconciliation validation


from dataclasses import dataclass
from typing import Dict, List
from threading import Lock
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------
@dataclass(frozen=True)
class LegIntent:
    strategy_id: str
    symbol: str
    direction: str  # BUY / SELL
    qty: int
    tag: str        # ENTRY / EXIT / ADJUST


@dataclass
class Position:
    symbol: str
    direction: str
    qty: int


# ---------------------------------------------------------
# EXECUTION GUARD
# ---------------------------------------------------------
class ExecutionGuard:
    """
    Defensive execution layer enforcing:

    - Strategy isolation
    - Duplicate ENTRY protection
    - Delta execution (ENTRY / ADJUST)
    - Cross-strategy conflict prevention
    - EXIT always allowed
    - Broker-truth based state mutation
    """

    def __init__(self):
        self._lock = Lock()

        # strategy_id -> symbol -> Position
        self._strategy_positions: Dict[str, Dict[str, Position]] = {}

        # global symbol -> direction -> total qty
        self._global_positions: Dict[str, Dict[str, int]] = {}

    # -----------------------------------------------------
    # PUBLIC ENTRY
    # -----------------------------------------------------
    def validate_and_prepare(
        self,
        intents: List[LegIntent],
        execution_type: str,  # ENTRY / ADJUST / EXIT
    ) -> List[LegIntent]:
        """
        Returns intents that MUST be sent to broker.
        Raises RuntimeError if blocked.
        """

        with self._lock:
            execution_type = execution_type.upper()

            if execution_type == "EXIT":
                return self._handle_exit(intents)

            self._validate_structure(intents)

            strategy = intents[0].strategy_id

            # 🔒 HARD BLOCK — DUPLICATE ENTRY
            if execution_type == "ENTRY":
                if strategy in self._strategy_positions and self._strategy_positions[strategy]:
                    raise RuntimeError(
                        f"Duplicate ENTRY blocked for strategy {strategy}"
                    )


            self._check_cross_strategy_conflicts(intents)

            return self._handle_entry_or_adjust(intents)

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------
    def _validate_structure(self, intents: List[LegIntent]):
        if not intents:
            raise RuntimeError("Empty intent list")

        strategy = intents[0].strategy_id

        for i in intents:
            if i.strategy_id != strategy:
                raise RuntimeError("Mixed strategies in single execution batch")

            if i.qty <= 0:
                raise RuntimeError(f"Invalid qty {i.qty} for {i.symbol}")

    # -----------------------------------------------------
    # RULE B — CROSS STRATEGY CONFLICT
    # -----------------------------------------------------
    def _check_cross_strategy_conflicts(self, intents: List[LegIntent]):
        for i in intents:
            if i.symbol in self._global_positions:
                for dir_, qty in self._global_positions[i.symbol].items():
                    if qty > 0 and dir_ != i.direction:
                        raise RuntimeError(
                            f"Cross-strategy conflict: {i.symbol} "
                            f"{dir_} exists, attempted {i.direction}"
                        )

    # -----------------------------------------------------
    # RULE A — DUPLICATE & DELTA EXECUTION
    # -----------------------------------------------------
    def _handle_entry_or_adjust(
        self,
        intents: List[LegIntent],
    ) -> List[LegIntent]:

        strategy = intents[0].strategy_id
        existing = self._strategy_positions.get(strategy, {})

        # 1️⃣ STRUCTURE CHECK — direction consistency
        for i in intents:
            if i.symbol in existing:
                pos = existing[i.symbol]
                if pos.direction != i.direction:
                    raise RuntimeError(
                        f"Direction mismatch for {i.symbol} in strategy {strategy}"
                    )

        # 2️⃣ DELTA CALCULATION
        final_intents: List[LegIntent] = []

        for i in intents:
            current_qty = existing.get(
                i.symbol,
                Position(i.symbol, i.direction, 0)
            ).qty

            delta = i.qty - current_qty

            if delta < 0:
                raise RuntimeError(
                    f"Strategy {strategy} attempting qty reduction without EXIT"
                )

            if delta > 0:
                final_intents.append(
                    LegIntent(
                        strategy_id=i.strategy_id,
                        symbol=i.symbol,
                        direction=i.direction,
                        qty=delta,
                        tag=i.tag,
                    )
                )

        # 3️⃣ ATOMICITY GUARANTEE
        if final_intents and len(final_intents) != len(intents):
            raise RuntimeError(
                f"Partial strategy execution blocked for {strategy}"
            )

        return final_intents

    # -----------------------------------------------------
    # RULE C — EXIT ALWAYS ALLOWED
    # -----------------------------------------------------
    def _handle_exit(self, intents: List[LegIntent]) -> List[LegIntent]:
        """
        EXIT intents are SYMBOLIC.
        Direction + qty MUST come from broker truth in trading_bot.
        """
        strategy = intents[0].strategy_id

        existing = self._strategy_positions.get(strategy, {})
        if not existing:
            return []

        exit_intents: List[LegIntent] = []

        for symbol, pos in existing.items():
            exit_intents.append(
                LegIntent(
                    strategy_id=strategy,
                    symbol=symbol,
                    direction="EXIT",   # 🔒 SYMBOLIC
                    qty=pos.qty,
                    tag="EXIT",
                )
            )

        return exit_intents

    def reconcile_with_broker(
        self,
        strategy_id: str,
        broker_positions: Dict[str, Dict[str, int]],
    ):
        """
        Reconcile ExecutionGuard state with broker truth.

        BROKER POSITIONS CONTRACT (v1.3+):
            broker_positions: Dict[symbol, Dict[direction, qty]]
            Example:
                {
                  "NIFTY25JAN18000CE": {"BUY": 50, "SELL": 0},
                  "NIFTY25JAN18200PE": {"BUY": 0, "SELL": 50}
                }

        This is direction-aware and REQUIRED for correct reconciliation.
        Callers: trading_bot.py (line ~844) builds this format from broker netqty.

        Reconcile guard state with broker truth. Removes or updates
        positions when broker shows reduced/cleared quantities.
        """
        with self._lock:
            existing = self._strategy_positions.get(strategy_id, {})

            if not existing:
                logger.debug(f"ExecutionGuard: no positions for strategy {strategy_id}")
                return

            to_remove = []
            to_update = []

            for symbol, pos in list(existing.items()):
                broker_qty = broker_positions.get(symbol, {}).get(pos.direction, 0)

                if broker_qty == 0:
                    to_remove.append(symbol)
                elif broker_qty < pos.qty:
                    to_update.append((symbol, broker_qty))

            # Apply removals
            for symbol in to_remove:
                pos = existing.pop(symbol)

                if symbol in self._global_positions:
                    if pos.direction in self._global_positions[symbol]:
                        self._global_positions[symbol][pos.direction] -= pos.qty

                        if self._global_positions[symbol][pos.direction] <= 0:
                            del self._global_positions[symbol][pos.direction]

                        if not self._global_positions[symbol]:
                            del self._global_positions[symbol]

                logger.warning(
                    f"ExecutionGuard: cleared stale position | "
                    f"strategy={strategy_id} symbol={symbol} qty={pos.qty}"
                )

            # Apply updates
            for symbol, new_qty in to_update:
                old_pos = existing[symbol]
                qty_delta = old_pos.qty - new_qty

                existing[symbol] = Position(
                    symbol=symbol,
                    direction=old_pos.direction,
                    qty=new_qty
                )

                if symbol in self._global_positions:
                    if old_pos.direction in self._global_positions[symbol]:
                        self._global_positions[symbol][old_pos.direction] -= qty_delta

                logger.warning(
                    f"ExecutionGuard: updated position | "
                    f"strategy={strategy_id} symbol={symbol} "
                    f"{old_pos.qty} → {new_qty}"
                )

            if not existing:
                self._strategy_positions.pop(strategy_id, None)
                logger.info(
                    f"ExecutionGuard: strategy {strategy_id} fully cleared "
                    f"after reconciliation"
                )

            if to_remove or to_update:
                logger.warning(
                    f"ExecutionGuard reconciled | strategy={strategy_id} | "
                    f"cleared={len(to_remove)} updated={len(to_update)}"
                )


    # -----------------------------------------------------
    # STATE MANAGEMENT
    # -----------------------------------------------------
    def force_close_strategy(self, strategy_id: str) -> None:
        """
        Force-clear all positions for a strategy.
        Used after EXIT completion or hard failure.
        """
        with self._lock:
            positions = self._strategy_positions.pop(strategy_id, {})

            for pos in positions.values():
                if pos.symbol in self._global_positions:
                    self._global_positions[pos.symbol][pos.direction] -= pos.qty
                    if self._global_positions[pos.symbol][pos.direction] <= 0:
                        del self._global_positions[pos.symbol][pos.direction]

            logger.info(
                f"ExecutionGuard: force-cleared {len(positions)} positions "
                f"for strategy {strategy_id}"
            )

    def force_clear_symbol(self, strategy_id: str, symbol: str) -> None:
        """
        Clear single symbol for a strategy (used on order failure).
        Called by OrderWatcher when individual order fails.
        """
        with self._lock:
            if strategy_id not in self._strategy_positions:
                logger.debug(
                    f"ExecutionGuard: strategy {strategy_id} not found for symbol clear"
                )
                return

            positions = self._strategy_positions[strategy_id]

            if symbol not in positions:
                logger.debug(
                    f"ExecutionGuard: symbol {symbol} not found in strategy {strategy_id}"
                )
                return

            pos = positions.pop(symbol)

            # Update global positions
            if symbol in self._global_positions:
                if pos.direction in self._global_positions[symbol]:
                    self._global_positions[symbol][pos.direction] -= pos.qty

                    if self._global_positions[symbol][pos.direction] <= 0:
                        del self._global_positions[symbol][pos.direction]

                    if not self._global_positions[symbol]:
                        del self._global_positions[symbol]

            # Clean up empty strategy
            if not positions:
                del self._strategy_positions[strategy_id]
                logger.info(
                    f"ExecutionGuard: strategy {strategy_id} fully cleared "
                    f"after removing {symbol}"
                )
            else:
                logger.info(
                    f"ExecutionGuard: cleared symbol {symbol} from strategy {strategy_id} "
                    f"({len(positions)} symbols remaining)"
                )

    def confirm_execution(
        self,
        strategy_id: str,
        symbol: str,
        direction: str,
        qty: int,
    ):
        if qty <= 0:
            return

        if direction == "EXIT":
            # EXIT confirmation must be resolved by trading_bot
            return

        with self._lock:
            self._strategy_positions.setdefault(strategy_id, {})

            existing = self._strategy_positions[strategy_id].get(symbol)
            new_qty = existing.qty + qty if existing else qty

            self._strategy_positions[strategy_id][symbol] = Position(
                symbol=symbol,
                direction=direction,
                qty=new_qty,
            )

            self._global_positions.setdefault(symbol, {})
            self._global_positions[symbol].setdefault(direction, 0)
            self._global_positions[symbol][direction] += qty

