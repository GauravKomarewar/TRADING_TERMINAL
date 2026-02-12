"""
Universal Strategy Registry

Central registry for strategy discovery, metadata, and lifecycle management.
Works with both database_market and live_feed_market adapters.
"""

from .registry import list_strategy_templates

__all__ = ["list_strategy_templates"]
