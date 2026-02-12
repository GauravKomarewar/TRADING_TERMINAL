"""
STRATEGY FACTORY
================
Dynamically instantiates strategy classes based on strategy_type field in config.

Enables:
- Runtime strategy selection from config
- Support for multiple strategy implementations
- Clean separation: config → type → class → instance
"""

import logging
from typing import Any, Dict
from pathlib import Path

logger = logging.getLogger("STRATEGY_FACTORY")


# Registry mapping strategy_type to implementation class
STRATEGY_REGISTRY = {
    # DNSS variants (all case-insensitive)
    "dnss": None,  # Lazy load
    "DNSS": None,
    "delta_neutral_short_strangle": None,
    "DELTA_NEUTRAL_SHORT_STRANGLE": None,
}


def _lazy_load_dnss():
    """Lazy load DNSS to avoid circular imports"""
    global STRATEGY_REGISTRY
    if STRATEGY_REGISTRY["dnss"] is None:
        try:
            from shoonya_platform.strategies.standalone_implementations.delta_neutral import DNSS
            STRATEGY_REGISTRY["dnss"] = DNSS
            STRATEGY_REGISTRY["DNSS"] = DNSS
            STRATEGY_REGISTRY["delta_neutral_short_strangle"] = DNSS
            STRATEGY_REGISTRY["DELTA_NEUTRAL_SHORT_STRANGLE"] = DNSS
            logger.info("✅ DNSS strategy loaded into registry")
        except ImportError as e:
            logger.error(f"❌ Failed to load DNSS: {e}")
            raise


def create_strategy(config: Dict[str, Any]) -> Any:
    """
    Create a strategy instance from config.
    
    Args:
        config: Strategy configuration dict with 'strategy_type' field
        
    Returns:
        Strategy instance
        
    Raises:
        ValueError: If strategy_type not found in config or registry
        Exception: If strategy instantiation fails
        
    Example:
        config = load_json("strategies/saved_configs/dnss_nifty.json")
        strategy = create_strategy(config)
    """
    _lazy_load_dnss()
    
    # Extract strategy_type (case-insensitive)
    strategy_type = config.get("strategy_type", "").strip()
    if not strategy_type:
        raise ValueError("Config missing 'strategy_type' field")
    
    # Look up in registry (case-insensitive)
    strategy_class = None
    for key, cls in STRATEGY_REGISTRY.items():
        if key.lower() == strategy_type.lower():
            strategy_class = cls
            break
    
    if strategy_class is None:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"Unknown strategy_type '{strategy_type}'. "
            f"Available: {available}"
        )
    
    # Instantiate
    try:
        strategy = strategy_class(config)
        strategy_name = config.get("strategy_name", strategy_type)
        logger.info(f"✅ Created strategy: {strategy_name} ({strategy_type})")
        return strategy
    except Exception as e:
        logger.error(f"❌ Failed to instantiate {strategy_type}: {e}")
        raise


def register_strategy(strategy_type: str, strategy_class: type):
    """
    Register a new strategy implementation.
    
    Args:
        strategy_type: String identifier (e.g., 'dnss', 'DELTA_NEUTRAL_SHORT_STRANGLE')
        strategy_class: Strategy class (must support __init__(config))
    """
    _lazy_load_dnss()
    STRATEGY_REGISTRY[strategy_type] = strategy_class
    logger.info(f"🔧 Registered strategy: {strategy_type}")


def get_available_strategies() -> Dict[str, type]:
    """Get all registered strategy implementations"""
    _lazy_load_dnss()
    return {k: v for k, v in STRATEGY_REGISTRY.items() if v is not None}
