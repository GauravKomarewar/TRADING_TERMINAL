"""
Universal Strategy Settings
===========================

Centralized location for all universal strategy infrastructure and configuration:
- universal_config/ - Universal configuration interface
- universal_strategy_reporter/ - Strategy performance reporting
- universal_registry/ - Strategy registry and metadata
- writer/ - Universal output and result writers
"""

from .universal_config.universal_strategy_config import UniversalStrategyConfig

__all__ = ["UniversalStrategyConfig"]
