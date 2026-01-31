"""
TRAILING LOGIC ENGINE (PRODUCTION — FROZEN)
==========================================

All trailing stop-loss engines live here.

Rules:
- All engines MUST inherit TrailingEngine
- Engine selection is dynamic
- No broker logic here
"""
from typing import Optional
from abc import ABC, abstractmethod


# ======================================================
# BASE ENGINE
# ======================================================
class TrailingEngine(ABC):
    """
    Base interface for all trailing engines.
    """

    @abstractmethod
    def compute_new_sl(self, current_price: float, last_sl: float) -> float:
        """
        Return updated stop loss.
        Must NEVER reduce protection.
        """
        pass


# ======================================================
# POINTS TRAILING
# ======================================================
class PointsTrailing(TrailingEngine):
    """
    Trailing SL by fixed points.

    Example:
    price = 100
    points = 10
    SL = 90
    """
    def __init__(self, points: float, step: Optional[float] = None):

        self.points = points
        self.step = step  # reserved for future step-based trailing

    def compute_new_sl(self, current_price: float, last_sl: float) -> float:
        new_sl = current_price - self.points
        return max(new_sl, last_sl)


# ======================================================
# PERCENT TRAILING
# ======================================================
class PercentTrailing(TrailingEngine):
    """
    Trailing SL by percentage.
    """

    def __init__(self, percent: float):
        self.percent = percent

    def compute_new_sl(self, current_price: float, last_sl: float) -> float:
        new_sl = current_price * (1 - self.percent / 100)
        return max(new_sl, last_sl)


# ======================================================
# ABSOLUTE PRICE TRAILING
# ======================================================
class AbsoluteTrailing(TrailingEngine):
    """
    Fixed absolute SL (manual override).
    """

    def __init__(self, price: float):
        self.price = price

    def compute_new_sl(self, *_):
        return self.price
