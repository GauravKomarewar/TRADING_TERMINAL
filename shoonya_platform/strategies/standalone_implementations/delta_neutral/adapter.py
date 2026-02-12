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
from shoonya_platform.strategies.universal_settings.universal_config.universal_strategy_config import UniversalStrategyConfig
from scripts.scriptmaster import options_expiry


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
        expiry = _calculate_expiry(
            exchange=universal_config.exchange,
            symbol=universal_config.symbol,
            expiry_mode=expiry_mode
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


def _calculate_expiry(exchange: str, symbol: str, expiry_mode: str) -> str:
    """
    Get current option expiry from ScriptMaster (NOT date calculation)
    
    DNSS trades option strangles, so we query OPTION expiries, not futures.
    ScriptMaster has the ACTUAL expiry dates per exchange:
    - NFO NIFTY: Weekly Thursdays
    - MCX CRUDEOILM: Different dates (17-FEB, 17-MAR, 16-APR, etc.)
    - MCX has no fixed day pattern - use scriptmaster truth
    
    Args:
        exchange: "NFO", "BFO", or "MCX"
        symbol: "NIFTY", "BANKNIFTY", "CRUDEOILM", etc.
        expiry_mode: "weekly_current" or "monthly_current" (hint for selection)
    
    Returns:
        Expiry date string in format "12FEB2026" (from ScriptMaster)
    
    Raises:
        ValueError: If no option expiry found for the symbol
    """
    try:
        exchange = exchange.upper()
        symbol = symbol.upper()
        
        # Query ScriptMaster for ACTUAL option expiry dates
        expiries = options_expiry(symbol, exchange)
        
        if not expiries:
            raise ValueError(
                f"No option expiries found for {symbol} on {exchange}. "
                f"Check if instrument is tradable."
            )
        
        # Find appropriate expiry based on mode
        today = date.today()
        today_str = today.strftime("%d-%b-%Y").upper()
        
        # Filter expiries >= today (upcoming expiries only)
        upcoming = []
        for exp_str in expiries:
            try:
                exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                if exp_date >= today:
                    upcoming.append(exp_str)
            except ValueError:
                continue
        
        if not upcoming:
            # No upcoming expiry today, use first available
            upcoming = expiries
        
        # Select based on mode
        if expiry_mode == "weekly_current":
            # For weekly: use 1st upcoming expiry (nearest)
            selected = upcoming[0]
        elif expiry_mode == "monthly_current":
            # For monthly: find the LAST expiry of current month
            current_month = today.month
            current_year = today.year
            
            month_expiries = []
            for exp_str in upcoming:
                try:
                    exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                    if exp_date.month == current_month and exp_date.year == current_year:
                        month_expiries.append(exp_str)
                except ValueError:
                    continue
            
            if month_expiries:
                # Use last expiry of current month
                selected = month_expiries[-1]
            else:
                # No monthly expiry in current month, use first upcoming
                selected = upcoming[0]
        else:
            # Default: first upcoming
            selected = upcoming[0]
        
        # Return in format "12FEB2026" (uppercase, no dashes)
        return selected.replace("-", "").upper()
    
    except Exception as e:
        raise ValueError(
            f"Failed to get option expiry for {symbol} on {exchange}: {e}"
        )


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
