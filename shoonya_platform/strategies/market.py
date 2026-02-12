#!/usr/bin/env python3
"""
Market Module - Backward Compatible Wrapper
=============================================

Provides simplified, backward-compatible interfaces for market data access.

Wraps:
- DatabaseMarketAdapter → DBBackedMarket
- LiveFeedMarketAdapter → LiveMarket

This module ensures imports like:
    from shoonya_platform.strategies.market import DBBackedMarket
work correctly while using the actual adapter implementations.
"""

import logging
from pathlib import Path
from datetime import date, timedelta
from typing import Optional, Dict, Any, Callable

from shoonya_platform.strategies.database_market.adapter import DatabaseMarketAdapter
from shoonya_platform.strategies.live_feed_market.adapter import LiveFeedMarketAdapter

logger = logging.getLogger(__name__)

# Default database path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = str(
    _PROJECT_ROOT / "shoonya_platform" / "persistence" / "data" / "orders.db"
)


def _get_current_weekly_expiry() -> str:
    """
    Calculate the next Thursday (current weekly expiry).
    
    Returns:
        Expiry date string in format "12FEB2026" (uppercase)
    """
    today = date.today()
    # Calculate days until Thursday (weekday 3)
    days_until_thursday = (3 - today.weekday()) % 7
    
    if days_until_thursday == 0:
        # Today is Thursday
        next_thursday = today
    else:
        next_thursday = today + timedelta(days=days_until_thursday)
    
    return next_thursday.strftime("%d%b%Y").upper()


class DBBackedMarket(DatabaseMarketAdapter):
    """
    Database-backed market data provider.
    
    Wrapper around DatabaseMarketAdapter with sensible defaults.
    Uses orders.db by default if not specified.
    Provides unified interface with expiry and get_nearest_option.
    
    Args:
        db_path: Path to SQLite database (optional, defaults to orders.db)
        exchange: NFO, MCX, NCDEX, etc.
        symbol: NIFTY, BANKNIFTY, etc.
    """
    
    def __init__(self, db_path: Optional[str] = None, exchange: Optional[str] = None, symbol: Optional[str] = None):
        """Initialize with optional db_path default."""
        # Support positional args for backward compatibility
        # If db_path not provided, use default
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        
        # Support keyword-only args
        if exchange is None:
            raise ValueError("exchange is required")
        if symbol is None:
            raise ValueError("symbol is required")
        
        super().__init__(db_path=db_path, exchange=exchange, symbol=symbol)
        self._cached_expiry = None
    
    @property
    def expiry(self) -> str:
        """
        Get current market expiry (weekly contract).
        
        Returns:
            Expiry date string in format "12FEB2026"
        """
        if self._cached_expiry is None:
            self._cached_expiry = _get_current_weekly_expiry()
        return self._cached_expiry
    
    def get_nearest_option(
        self,
        df,  # DataFrame or similar data source
        greek: str,
        target_value: float,
        option_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get nearest option by greek value.
        
        Unified interface for option selection.
        Wraps get_nearest_option_by_greek for backward compatibility.
        
        Args:
            df: Greeks DataFrame (not used - uses database instead)
            greek: Greek name ("Delta", "Theta", "Gamma", "Vega")
            target_value: Target greek value
            option_type: "CE" or "PE"
            
        Returns:
            Option details or None
        """
        # Normalize greek name to lowercase
        greek_lower = greek.lower()
        
        # Validate and normalize option_type
        option_type_upper = option_type.upper()
        if option_type_upper not in ("CE", "PE"):
            logger.error(f"Invalid option_type: {option_type}. Must be CE or PE")
            return None
        
        try:
            return self.get_nearest_option_by_greek(
                greek=greek_lower,
                target_value=target_value,
                option_type=option_type_upper,  # type: ignore
                use_absolute=True,
            )
        except Exception as e:
            logger.error(f"Error getting nearest option: {e}")
            return None


class LiveMarket(LiveFeedMarketAdapter):
    """
    Live WebSocket feed market data provider.
    
    Wrapper around LiveFeedMarketAdapter for backward compatibility.
    Provides unified interface with expiry and get_nearest_option.
    
    Args:
        exchange: NFO, MCX, NCDEX, etc.
        symbol: NIFTY, BANKNIFTY, etc.
    """
    
    def __init__(self, exchange: Optional[str] = None, symbol: Optional[str] = None):
        """Initialize with required parameters."""
        if exchange is None:
            raise ValueError("exchange is required")
        if symbol is None:
            raise ValueError("symbol is required")
        
        super().__init__(exchange=exchange, symbol=symbol)
        self._cached_expiry = None
    
    @property
    def expiry(self) -> str:
        """
        Get current market expiry (weekly contract).
        
        Returns:
            Expiry date string in format "12FEB2026"
        """
        if self._cached_expiry is None:
            self._cached_expiry = _get_current_weekly_expiry()
        return self._cached_expiry
    
    def get_nearest_option(
        self,
        df,  # DataFrame or similar data source
        greek: str,
        target_value: float,
        option_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get nearest option by greek value.
        
        Unified interface for option selection.
        Wraps get_nearest_option_by_greek for backward compatibility.
        
        Args:
            df: Greeks DataFrame (not used - uses live feed instead)
            greek: Greek name ("Delta", "Theta", "Gamma", "Vega")
            target_value: Target greek value
            option_type: "CE" or "PE"
            
        Returns:
            Option details or None
        """
        # Normalize greek name to lowercase
        greek_lower = greek.lower()
        
        # Validate and normalize option_type
        option_type_upper = option_type.upper()
        if option_type_upper not in ("CE", "PE"):
            logger.error(f"Invalid option_type: {option_type}. Must be CE or PE")
            return None
        
        try:
            return self.get_nearest_option_by_greek(
                greek=greek_lower,
                target_value=target_value,
                option_type=option_type_upper,  # type: ignore
                use_absolute=True,
            )
        except Exception as e:
            logger.error(f"Error getting nearest option: {e}")
            return None


__all__ = ["DBBackedMarket", "LiveMarket", "DEFAULT_DB_PATH"]
