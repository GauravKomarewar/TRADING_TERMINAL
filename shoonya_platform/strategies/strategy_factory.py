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
    # Simple test strategy
    "simple_test": None,
    "SIMPLE_TEST": None,
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


def _lazy_load_simple_test():
    """Lazy load SimpleTestStrategy"""
    global STRATEGY_REGISTRY
    if STRATEGY_REGISTRY.get("simple_test") is None:
        try:
            from shoonya_platform.strategies.standalone_implementations.simple_test import SimpleTestStrategy
            STRATEGY_REGISTRY["simple_test"] = SimpleTestStrategy
            STRATEGY_REGISTRY["SIMPLE_TEST"] = SimpleTestStrategy
            logger.info("✅ SimpleTestStrategy loaded into registry")
        except ImportError as e:
            logger.error(f"❌ Failed to load SimpleTestStrategy: {e}")
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
    _lazy_load_simple_test()
    
    # Extract strategy_type (case-insensitive)
    # Support both root-level and nested (identity.strategy_type) locations
    strategy_type = config.get("strategy_type", "").strip()
    if not strategy_type:
        # Try looking in nested 'identity' object
        identity = config.get("identity", {})
        if isinstance(identity, dict):
            strategy_type = identity.get("strategy_type", "").strip()
    
    if not strategy_type:
        raise ValueError("Config missing 'strategy_type' field (expected at root or in 'identity' object)")
    
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
        # Special handling for DNSS: use adapter instead of direct instantiation
        if strategy_type.lower() in ["dnss", "delta_neutral_short_strangle"]:
            from datetime import time as dt_time
            from shoonya_platform.strategies.universal_settings.universal_config.universal_strategy_config import UniversalStrategyConfig
            from shoonya_platform.strategies.standalone_implementations.delta_neutral.adapter import create_dnss_from_universal_config
            from shoonya_platform.strategies.market import DBBackedMarket
            
            # Helper to parse time from string
            def parse_time(val):
                if isinstance(val, dt_time):
                    return val
                if isinstance(val, str):
                    try:
                        return dt_time.fromisoformat(val)
                    except (ValueError, AttributeError):
                        parts = val.split(":")
                        return dt_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
                return val
            
            # Convert config dict to UniversalStrategyConfig
            universal_config = UniversalStrategyConfig(
                strategy_name=config.get("strategy_name", ""),
                strategy_version=config.get("strategy_version", "1.0"),
                exchange=config.get("exchange", ""),
                symbol=config.get("symbol", ""),
                instrument_type=config.get("instrument_type", "OPTIDX"),
                entry_time=parse_time(config.get("entry_time", "09:20")),
                exit_time=parse_time(config.get("exit_time", "15:20")),
                order_type=config.get("order_type", "MARKET"),
                product=config.get("product", "MIS"),
                lot_qty=int(config.get("lot_qty", 1)),
                params=config.get("params", {}),
                max_positions=int(config.get("max_positions", 1)),
                poll_interval=float(config.get("poll_interval", 2.0)),
                cooldown_seconds=int(config.get("cooldown_seconds", 0)),
            )
            
            # Create market instance (initial — will be re-created with resolved db_path in adapter)
            market = DBBackedMarket(
                exchange=universal_config.exchange,
                symbol=universal_config.symbol,
            )
            
            # Use adapter to create DNSS with proper parameters
            strategy = create_dnss_from_universal_config(
                universal_config=universal_config,
                market=market,
            )
        else:
            # Direct instantiation for other strategies
            strategy = strategy_class(config)
        
        # For DNSS: inject resolved db_path into market_config so the
        # strategy_runner creates a DatabaseMarketAdapter (not a stub)
        if strategy_type.lower() in ["dnss", "delta_neutral_short_strangle"]:
            if "market_config" not in config:
                config["market_config"] = {}
            config["market_config"]["market_type"] = "database_market"
            config["market_config"]["db_path"] = getattr(strategy, "db_path", None)
            config["market_config"]["exchange"] = config.get("exchange", "")
            config["market_config"]["symbol"] = config.get("symbol", "")

        # For ALL strategies: inject db_path if strategy resolved it
        # (covers non-DNSS strategies that resolve their own db_path)
        if hasattr(strategy, 'db_path') and strategy.db_path:
            if "market_config" not in config:
                config["market_config"] = {}
            if not config["market_config"].get("db_path"):
                config["market_config"]["db_path"] = strategy.db_path
                config["market_config"].setdefault("exchange", config.get("exchange", ""))
                config["market_config"].setdefault("symbol", config.get("symbol", ""))
                config["market_config"].setdefault("market_type", "database_market")
                logger.info(f"Injected db_path from strategy: {strategy.db_path}")

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
