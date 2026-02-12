"""
DNSS Adapter - Converts UniversalStrategyConfig to DNSS Strategy Instance
===========================================================================

Enables DNSS to work seamlessly with:
- UniversalStrategyConfig (standard format)
- StrategyRunner (universal executor)
- Dashboard integration
- Unified execution pipeline
"""

from datetime import time as dt_time, datetime, date, timedelta
from typing import Optional, Callable
from pathlib import Path

from .dnss import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
)
from shoonya_platform.strategies.universal_settings.universal_config.universal_strategy_config import UniversalStrategyConfig
from shoonya_platform.strategies.config_resolution_service import ConfigResolutionService
from shoonya_platform.logging.logger_config import get_component_logger

logger = get_component_logger('dnss_adapter')


def create_dnss_from_universal_config(
    universal_config: UniversalStrategyConfig,
    market,  # DBBackedMarket instance
    get_option_func: Optional[Callable] = None,
    expiry: Optional[str] = None,
) -> DeltaNeutralShortStrangleStrategy:
    """
    Convert UniversalStrategyConfig to DNSS Strategy Instance
    
    This adapter bridges the standardized UniversalStrategyConfig
    with DNSS-specific StrategyConfig requirements.
    
    Args:
        universal_config: Standard config from dashboard/database
        market: DBBackedMarket instance for option chain lookup
        get_option_func: Custom option getter (default: market.get_nearest_option)
        expiry: Manual expiry override (default: auto-calculate from mode in params)
    
    Returns:
        DeltaNeutralShortStrangleStrategy fully initialized and ready to trade
    
    Raises:
        ValueError: If required params are missing
        
    Example:
        >>> from shoonya_platform.strategies.universal_config import UniversalStrategyConfig
        >>> from shoonya_platform.strategies.market import DBBackedMarket
        >>> 
        >>> # Create config
        >>> config = UniversalStrategyConfig(
        ...     strategy_name="dnss_nifty_v1",
        ...     exchange="NFO",
        ...     symbol="NIFTY",
        ...     entry_time=time(9, 18),
        ...     exit_time=time(15, 28),
        ...     order_type="MARKET",
        ...     product="MIS",
        ...     lot_qty=1,
        ...     params={
        ...         "target_entry_delta": 0.4,
        ...         "delta_adjust_trigger": 0.10,
        ...         "max_leg_delta": 0.65,
        ...         "profit_step": 1000.0,
        ...         "cooldown_seconds": 300,
        ...     }
        ... )
        >>> 
        >>> # Create market
        >>> market = DBBackedMarket(db_path, "NFO", "NIFTY")
        >>> 
        >>> # Create strategy
        >>> strategy = create_dnss_from_universal_config(config, market)
        >>> 
        >>> # Use with runner
        >>> runner.register("dnss_nifty_v1", strategy, market)
    """
    
    # Validate input
    if not universal_config:
        raise ValueError("UniversalStrategyConfig required")
    
    if not market:
        raise ValueError("DBBackedMarket instance required")
    
    # Extract DNSS-specific parameters
    params = universal_config.params or {}
    
    # Validate required DNSS parameters exist
    required_params = [
        "target_entry_delta",
        "delta_adjust_trigger",
        "max_leg_delta",
        "profit_step",
        "cooldown_seconds",
    ]
    
    missing = [p for p in required_params if p not in params]
    if missing:
        raise ValueError(f"Missing required DNSS params: {missing}")
    
    # Create DNSS-specific strategy config
    dnss_config = StrategyConfig(
        entry_time=universal_config.entry_time,
        exit_time=universal_config.exit_time,
        
        target_entry_delta=float(params["target_entry_delta"]),
        delta_adjust_trigger=float(params["delta_adjust_trigger"]),
        max_leg_delta=float(params["max_leg_delta"]),
        
        profit_step=float(params["profit_step"]),
        cooldown_seconds=int(params["cooldown_seconds"]),
    )
    
    # Get option selection function
    if get_option_func is None:
        get_option_func = market.get_nearest_option
    
    # ============================================================
    # 🔧 RESOLVE & VALIDATE CONFIG (CRITICAL)
    # ============================================================
    # Validate exchange, symbol, instrument type
    # Resolve expiry from ScriptMaster (not date math)
    # Determine correct .sqlite database file
    # Validate order_type rules
    # ============================================================
    resolver = ConfigResolutionService()
    
    resolved = resolver.resolve(
        config={},  # Pass full config if available for validation
        exchange=universal_config.exchange,
        symbol=universal_config.symbol,
        instrument_type=params.get("instrument_type", "OPTIDX"),
        expiry_mode=params.get("expiry_mode", "weekly_current"),
    )
    
    if not resolved["valid"]:
        error_msg = f"Config resolution failed: {'; '.join(resolved['errors'])}"
        logger.error(f"❌ {error_msg}")
        raise ValueError(error_msg)
    
    # Use resolved values
    expiry = resolved["expiry"]
    db_path = resolved["db_path"]
    order_type = resolved["order_type_resolved"]
    
    logger.info(
        f"✅ Config RESOLVED: {universal_config.symbol} "
        f"Expiry={expiry}, OrderType={order_type}, DB={Path(db_path).name}"
    )
    
    # Create and return fully initialized DNSS strategy
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=universal_config.exchange,
        symbol=universal_config.symbol,
        expiry=expiry,
        lot_qty=universal_config.lot_qty,
        get_option_func=get_option_func,
        config=dnss_config,
    )
    
    return strategy



# ============================================================
# INTEGRATION HELPERS
# ============================================================

def dnss_config_to_universal(
    strategy_name: str,
    exchange: str,
    symbol: str,
    entry_time: dt_time,
    exit_time: dt_time,
    order_type: str,
    product: str,
    lot_qty: int,
    dnss_params: dict,
) -> UniversalStrategyConfig:
    """
    Convert DNSS parameters to UniversalStrategyConfig
    
    Reverse of create_dnss_from_universal_config
    Useful for dashboard form → config conversion
    """
    
    return UniversalStrategyConfig(
        strategy_name=strategy_name,
        strategy_version="1.0.0",
        
        exchange=exchange,
        symbol=symbol,
        instrument_type="OPTIDX",  # DNSS is OPTIDX only
        
        entry_time=entry_time,
        exit_time=exit_time,
        
        order_type=order_type,
        product=product,
        
        lot_qty=lot_qty,
        
        params=dnss_params,
    )
