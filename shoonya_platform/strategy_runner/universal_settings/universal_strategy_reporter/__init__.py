"""
Universal Strategy Reporter

Handles reporting and metrics collection for all strategy types.
Works with both database_market and live_feed_market adapters.
"""

from .reporter import build_strategy_report

__all__ = ["build_strategy_report"]
