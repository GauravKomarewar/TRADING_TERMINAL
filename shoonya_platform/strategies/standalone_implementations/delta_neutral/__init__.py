"""
Delta Neutral Short Strangle Strategy Module
=============================================
Production-grade delta neutral short strangle strategy with automatic adjustments.

Integrates with:
- UniversalStrategyConfig (standard format)
- StrategyRunner (unified executor)
- Dashboard API
"""

from .dnss import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
    StrategyState,
    Leg,
)

from .adapter import (
    create_dnss_from_universal_config,
    dnss_config_to_universal,
)

__all__ = [
    # Strategy classes
    "DeltaNeutralShortStrangleStrategy",
    "StrategyConfig",
    "StrategyState", 
    "Leg",
    
    # Adapters for UniversalStrategyConfig integration
    "create_dnss_from_universal_config",
    "dnss_config_to_universal",
]
