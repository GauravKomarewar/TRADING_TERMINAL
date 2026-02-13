#!/usr/bin/env python3
"""
Market Adapter Factory
======================

Factory for creating market adapters based on market type (latch pattern).

Handles:
- Selection between live_feed_market and database_market
- Adapter initialization
- Configuration validation
"""

import logging
from typing import Literal, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class MarketAdapterFactory:
    """
    Factory for creating appropriate market adapter.
    
    Implements latch pattern for market type selection.
    """

    @staticmethod
    def create(
        market_type: Literal["database_market", "live_feed_market"],
        config: Dict[str, Any],
    ) -> Any:
        """
        Create market adapter based on market_type.
        
        Args:
            market_type: "database_market" or "live_feed_market"
            config: Strategy config with exchange, symbol, db_path, etc.
            
        Returns:
            Initialized adapter instance (DatabaseMarketAdapter or LiveFeedMarketAdapter)
            
        Raises:
            ValueError: If market_type is invalid or config is incomplete
        """
        
        exchange = config.get("exchange")
        symbol = config.get("symbol")
        
        if not exchange or not symbol:
            raise ValueError("Config must have 'exchange' and 'symbol'")
        
        # ========================================================
        # LATCH: Select market backend
        # ========================================================
        
        if market_type == "database_market":
            logger.info(f"🔄 Selecting: DATABASE_MARKET for {exchange}:{symbol}")
            
            db_path = config.get("db_path")
            if not db_path:
                raise ValueError("database_market requires 'db_path' in config")
            
            # Verify database exists
            if not Path(db_path).exists():
                raise FileNotFoundError(f"Database not found: {db_path}")
            
            # Import here to avoid circular imports
            from shoonya_platform.strategies.database_market.adapter import (
                DatabaseMarketAdapter,
            )
            
            adapter = DatabaseMarketAdapter(
                db_path=db_path,
                exchange=exchange,
                symbol=symbol,
            )
            logger.info(f"✓ Database adapter initialized for {exchange}:{symbol}")
            return adapter
        
        elif market_type == "live_feed_market":
            logger.info(f"🔄 Selecting: LIVE_FEED_MARKET for {exchange}:{symbol}")
            
            # Import here to avoid circular imports
            from shoonya_platform.strategies.live_feed_market.adapter import (
                LiveFeedMarketAdapter,
            )
            
            adapter = LiveFeedMarketAdapter(
                exchange=exchange,
                symbol=symbol,
                db_path=config.get("db_path"),
            )
            logger.info(f"✓ Live feed adapter initialized for {exchange}:{symbol}")
            return adapter
        
        else:
            raise ValueError(
                f"Unknown market_type: {market_type}. "
                f"Must be 'database_market' or 'live_feed_market'"
            )

    @staticmethod
    def validate_config_for_market(
        market_type: Literal["database_market", "live_feed_market"],
        config: Dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Validate config for selected market type.
        
        Args:
            market_type: Market type to validate for
            config: Configuration to validate
            
        Returns:
            (is_valid, error_message)
        """
        
        # Check common required fields
        if not config.get("exchange"):
            return False, "Missing 'exchange' in config"
        
        if not config.get("symbol"):
            return False, "Missing 'symbol' in config"
        
        # Check market-specific fields
        if market_type == "database_market":
            db_path = config.get("db_path")
            if not db_path:
                return False, "database_market requires 'db_path' in config"
            
            if not Path(db_path).exists():
                return False, f"Database file not found: {db_path}"
        
        elif market_type == "live_feed_market":
            # Live feed markets don't have additional required config
            pass
        
        else:
            return False, f"Unknown market_type: {market_type}"
        
        return True, ""
