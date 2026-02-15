"""
Universal Strategy Writer

Handles output, logging, and persistence for strategy results and state.
Works with both database_market and live_feed_market adapters.
"""

from .writer import StrategyRunWriter

__all__ = ["StrategyRunWriter"]
