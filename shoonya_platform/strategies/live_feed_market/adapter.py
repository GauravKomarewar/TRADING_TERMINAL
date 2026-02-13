#!/usr/bin/env python3
"""
Live Feed Market Adapter
========================

Adapter for strategies to access live WebSocket market data.

Provides:
- Market snapshot retrieval
- Option selection by greek (delta, theta, gamma, vega) using find_option.py
- Option selection by premium using find_option.py
- Real-time instrument data

Uses:
- shoonya_platform.strategies.find_option (centralized option lookup)
- shoonya_platform.market_data.feeds.live_feed (WebSocket data)
"""

import logging
from typing import Dict, Literal, Optional, Any

from shoonya_platform.strategies.find_option import (
    find_option,
    find_options,
)

logger = logging.getLogger(__name__)


class LiveFeedMarketAdapter:
    """
    Adapter for live WebSocket market data.
    
    Normalizes live feed data for strategy consumption.
    Handles real-time option chain snapshots.
    """

    def __init__(self, exchange: str, symbol: str, db_path: Optional[str] = None):
        """
        Initialize live feed market adapter.
        
        Args:
            exchange: NFO, MCX, etc.
            symbol: NIFTY, BANKNIFTY, etc.
            db_path: Optional path to SQLite DB for option lookups
        """
        self.exchange = exchange
        self.symbol = symbol
        self.db_path = db_path
        self.logger = logger

    def get_market_snapshot(
        self,
        *,
        include_greeks: bool = True,
    ) -> Dict[str, Any]:
        """
        Get current live option chain snapshot.
        
        Args:
            include_greeks: Include Greek calculations
            
        Returns:
            Snapshot dict with option data
        
        NOTE: Strategy caller must provide live_option_chain instance
        """
        try:
            # Strategy should have access to live market data
            # This is a placeholder - strategy will provide the data
            self.logger.info("Requesting live market snapshot...")
            
            return {
                "snapshot_type": "live_feed",
                "symbol": self.symbol,
                "exchange": self.exchange,
            }
            
        except Exception as e:
            self.logger.error(f"Error getting market snapshot: {e}")
            return {}

    def get_nearest_option_by_greek(
        self,
        *,
        greek: str,
        target_value: float,
        option_type: Literal["CE", "PE"],
        use_absolute: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Find option with greek closest to target (live data).
        
        Uses find_option.py as centralized lookup to avoid code duplication.
        
        Args:
            greek: Greek to match (delta, theta, gamma, vega)
            target_value: Target greek value
            option_type: CE or PE
            use_absolute: Use absolute value for matching (ignored, find_option handles this)
            
        Returns:
            Selected option details or None
        """
        try:
            # Delegate to find_option.py (single source of truth)
            option = find_option(
                field=greek,
                value=target_value,
                symbol=self.symbol,
                option_type=option_type,
                db_path=self.db_path,
            )
            
            if option:
                greek_val = option.get(greek, 'N/A')
                self.logger.info(
                    f"✓ Found {greek} option: "
                    f"{option.get('trading_symbol', option.get('symbol'))} {option_type} "
                    f"{greek}={greek_val}"
                )
                return option
            
            self.logger.warning(f"⚠️ No option found for {greek}={target_value} {option_type}")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error finding option by greek: {e}")
            return None

    def get_nearest_option_by_premium(
        self,
        *,
        target_premium: float,
        option_type: Literal["CE", "PE"],
    ) -> Optional[Dict[str, Any]]:
        """
        Find option with premium (LTP) closest to target (live data).
        
        Uses find_option.py as centralized lookup to avoid code duplication.
        
        Args:
            target_premium: Target premium value
            option_type: CE or PE
            
        Returns:
            Selected option details or None
        """
        try:
            # Delegate to find_option.py (single source of truth)
            option = find_option(
                field="ltp",
                value=target_premium,
                symbol=self.symbol,
                option_type=option_type,
                db_path=self.db_path,
            )
            
            if option:
                ltp_val = option.get('ltp', 'N/A')
                self.logger.info(
                    f"✓ Found premium option: "
                    f"{option.get('trading_symbol', option.get('symbol'))} {option_type} "
                    f"LTP={ltp_val}"
                )
                return option
            
            self.logger.warning(f"⚠️ No option found for premium={target_premium} {option_type}")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error finding option by premium: {e}")
            return None

    def get_instrument_price(self, token: str) -> Optional[float]:
        """
        Get real-time price for instrument token.
        
        Args:
            token: Instrument token
            
        Returns:
            Last traded price or None
        """
        try:
            # This would require WebSocket integration
            # For now, find_option.py handles direct database lookups
            self.logger.debug(f"get_instrument_price not yet implemented for live feed: {token}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting price for token {token}: {e}")
            return None

    def get_instrument_prices_batch(
        self,
        tokens: list[str],
    ) -> Dict[str, float]:
        """
        Get real-time prices for multiple instrument tokens.
        
        Args:
            tokens: List of instrument tokens
            
        Returns:
            Dict of token -> price
        """
        try:
            # This would require WebSocket integration
            # For now, find_option.py handles direct database lookups
            self.logger.debug(f"get_instrument_prices_batch not yet implemented for live feed: {len(tokens)} tokens")
            return {}
        except Exception as e:
            self.logger.error(f"Error getting batch prices: {e}")
            return {}
