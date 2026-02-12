"""
Shoonya Platform - Strategy Execution Engine
=============================================

Consolidated strategy infrastructure with unified execution:

1. **market** - Strategy data providers (MarketData → Greeks, spot prices)
2. **strategy_runner.py** - Universal strategy executor (polls, registers, manages lifecycle)
3. **universal_config** - Standardized config format for all strategies
4. **delta_neutral** - DNSS (Delta Neutral Short Strangle) implementation

UNIFIED ARCHITECTURE:
- Single StrategyRunner for all strategies
- UniversalStrategyConfig as standard config format
- Strategy-specific adapters (adapter.py) for config conversion
- DBBackedMarket provides Greeks + spot price snapshots
- Thread-safe parallel execution with error isolation

This structure ensures all strategy code stays in strategies/ folder,
keeping execution/ clean for OMS concerns only (orders, positions, risk).
"""

from .database_market.adapter import DatabaseMarketAdapter
from .live_feed_market.adapter import LiveFeedMarketAdapter
from .universal_settings.universal_config import UniversalStrategyConfig
from .market_adapter_factory import MarketAdapterFactory
from .strategy_runner import StrategyRunner

__all__ = [
    # Market adapters
    "DatabaseMarketAdapter",
    "LiveFeedMarketAdapter",
    # Factory
    "MarketAdapterFactory",
    # Config
    "UniversalStrategyConfig",
    # Runner
    "StrategyRunner",
]
