"""
RECOVERY CORE (NEW PLATFORM)
============================

• Minimal restart-safe state detection
• No broker assumptions
• Strategy-driven recovery
"""

from enum import Enum
from typing import List, Dict


class StrategyRuntimeState(Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    UNBALANCED_MANUAL_EXIT = "UNBALANCED_MANUAL_EXIT"
    FAILED = "FAILED"


class RecoveryInspector:
    """
    Inspect broker + persistence state and infer strategy runtime state.
    """

    def __init__(
        self,
        *,
        broker,
        strategy_name: str,
        exchange: str,
        underlying: str,
        repository,
        expected_legs: int,
    ):
        self.broker = broker
        self.strategy_name = strategy_name
        self.exchange = exchange
        self.underlying = underlying
        self.repository = repository
        self.expected_legs = expected_legs

    def inspect(self) -> Dict:
        """
        Minimal safe inspection.
        """

        try:
            open_positions = self.broker.get_open_positions()
        except Exception:
            open_positions = []

        if not open_positions:
            return {
                "state": StrategyRuntimeState.IDLE,
                "reason": "no_open_positions",
                "open_legs": [],
            }

        if len(open_positions) == self.expected_legs:
            return {
                "state": StrategyRuntimeState.ACTIVE,
                "reason": "positions_match_expected",
                "open_legs": open_positions,
            }

        if len(open_positions) == 1:
            return {
                "state": StrategyRuntimeState.UNBALANCED_MANUAL_EXIT,
                "reason": "single_leg_open",
                "open_legs": open_positions,
            }

        return {
            "state": StrategyRuntimeState.FAILED,
            "reason": "unexpected_position_count",
            "open_legs": open_positions,
        }


class ManualUnbalanceManager:
    def __init__(self, exit_time):
        self.exit_time = exit_time

    def validate(self, *, open_legs: List[Dict], entry_confirmed: bool) -> bool:
        return bool(open_legs and entry_confirmed)


class TrailingStopController:
    def __init__(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        entry_price: float,
        trail_points: float,
    ):
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.entry_price = entry_price
        self.trail_points = trail_points
        self._stop = None

    def rebuild(self, ltp: float):
        self._stop = ltp - self.trail_points

    def update(self, ltp: float):
        if self._stop is None:
            return
        self._stop = max(self._stop, ltp - self.trail_points)

    def should_exit(self, ltp: float) -> bool:
        return self._stop is not None and ltp <= self._stop
