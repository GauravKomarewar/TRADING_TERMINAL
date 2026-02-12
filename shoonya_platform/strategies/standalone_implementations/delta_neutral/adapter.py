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

from .dnss import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
)
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig


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
    
    # Calculate current expiry if not provided
    if expiry is None:
        expiry_mode = params.get("expiry_mode", "weekly_current")
        expiry = _calculate_expiry(expiry_mode)
    
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


def _calculate_expiry(expiry_mode: str) -> str:
    """
    Calculate current expiry based on mode
    
    Args:
        expiry_mode: "weekly_current" or "monthly_current"
    
    Returns:
        Expiry date string in format "12FEB2026"
    """
    today = date.today()
    
    if expiry_mode == "weekly_current":
        # Find next Thursday (or current if today is Thursday)
        days_until_thursday = (3 - today.weekday()) % 7
        
        if days_until_thursday == 0 and today.weekday() == 3:
            # Today is Thursday
            next_thursday = today
        else:
            next_thursday = today + timedelta(days=days_until_thursday)
        
        return next_thursday.strftime("%d%b%Y").upper()
    
    elif expiry_mode == "monthly_current":
        # Last Thursday of current month
        # Get first day of next month, then subtract 1 day to get last day of this month
        next_month = today.replace(day=28) + timedelta(days=4)
        last_day_of_month = (next_month - timedelta(days=next_month.day)).day
        
        # Find last Thursday working backward from last day
        for day in range(last_day_of_month, 0, -1):
            candidate = today.replace(day=day)
            if candidate.weekday() == 3:  # 3 = Thursday
                return candidate.strftime("%d%b%Y").upper()
        
        # Fallback (should not happen)
        return today.strftime("%d%b%Y").upper()
    
    else:
        # Default: closest weekly Thursday
        days_until_thursday = (3 - today.weekday()) % 7
        next_thursday = today + timedelta(days=days_until_thursday)
        return next_thursday.strftime("%d%b%Y").upper()


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
