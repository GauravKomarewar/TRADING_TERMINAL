#!/usr/bin/env python3
"""
Database Market Adapter
=======================

Adapter for strategies to access SQLite-backed market data.

Provides:
- Market snapshot retrieval from SQLite
- Option selection by greek (delta, theta, gamma, vega) using find_option.py
- Option selection by premium using find_option.py
- Database-backed instrument data

Uses:
- shoonya_platform.strategies.find_option (centralized option lookup)
- SQLite database for market data persistence
"""

import logging
import sqlite3
from typing import Dict, Literal, Optional, Any
from pathlib import Path

from shoonya_platform.strategies.find_option import (
    find_option,
    find_options,
)

logger = logging.getLogger(__name__)


class DatabaseMarketAdapter:
    """
    Adapter for SQLite-backed market data.
    
    Normalizes database data for strategy consumption.
    Provides snapshot-based option chain access.
    """

    def __init__(self, db_path: str, exchange: str, symbol: str):
        """
        Initialize database market adapter.
        
        Args:
            db_path: Path to SQLite database file
            exchange: NFO, MCX, etc.
            symbol: NIFTY, BANKNIFTY, etc.
        """
        self.db_path = db_path
        self.exchange = exchange
        self.symbol = symbol
        self.logger = logger
        
        # Verify database exists
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_market_snapshot(
        self,
        *,
        include_greeks: bool = True,
        max_age_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Get current option chain snapshot from database.
        
        The .sqlite file is per-symbol (e.g. NFO_NIFTY_13-Feb-2026.sqlite),
        so all rows in option_chain belong to this symbol already.
        
        Returns:
            Snapshot dict with option data, spot_price from meta table
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # option_chain table has no 'symbol' column — all rows are this symbol
            rows = cur.execute("SELECT * FROM option_chain").fetchall()
            
            # Read spot price and metadata from meta table
            spot_price = None
            meta = {}
            try:
                meta_rows = cur.execute("SELECT key, value FROM meta").fetchall()
                for row in meta_rows:
                    meta[row[0]] = row[1]
                spot_price = float(meta.get("spot_ltp", 0)) or None
            except Exception:
                pass
            
            conn.close()
            
            if not rows:
                self.logger.warning(f"No data for {self.symbol} in database")
                return {}
            
            # Convert to list of dicts
            data = [dict(row) for row in rows]
            
            return {
                "option_chain": data,
                "symbol": self.symbol,
                "exchange": self.exchange,
                "spot_price": spot_price,
                "expiry": meta.get("expiry"),
                "count": len(data),
            }
            
        except Exception as e:
            self.logger.error(f"Error getting snapshot: {e}")
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
        Find option with greek closest to target (database).
        
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
                self.logger.info(
                    f"✓ Found {greek} option: "
                    f"{option.get('trading_symbol')} {option_type} "
                    f"{greek}={option.get(greek, 'N/A')}"
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
        Find option with premium (LTP) closest to target (database).
        
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
                self.logger.info(
                    f"✓ Found premium option: "
                    f"{option.get('trading_symbol')} {option_type} "
                    f"LTP={option.get('ltp', 'N/A')}"
                )
                return option
            
            self.logger.warning(f"⚠️ No option found for premium={target_premium} {option_type}")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error finding option by premium: {e}")
            return None

    def get_instrument_price(self, token: str) -> Optional[float]:
        """
        Get price for instrument token from database.
        
        Args:
            token: Instrument token (or trading_symbol)
            
        Returns:
            Last traded price or None
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Try token first, then trading_symbol in option_chain table
            result = cur.execute(
                "SELECT ltp FROM option_chain WHERE token = ? OR trading_symbol = ? LIMIT 1",
                (token, token)
            ).fetchone()
            conn.close()
            
            if result:
                return float(result[0])
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting price for token {token}: {e}")
            return None

    def get_instrument_prices_batch(
        self,
        tokens: list[str],
    ) -> Dict[str, float]:
        """
        Get prices for multiple instrument tokens from database.
        
        Args:
            tokens: List of instrument tokens
            
        Returns:
            Dict of token -> price
        """
        try:
            if not tokens:
                return {}
            
            conn = self._get_connection()
            cur = conn.cursor()
            
            placeholders = ",".join("?" * len(tokens))
            query = f"SELECT token, ltp FROM option_chain WHERE token IN ({placeholders})"
            
            rows = cur.execute(query, tokens).fetchall()
            conn.close()
            
            prices = {}
            for row in rows:
                if row and len(row) >= 2:
                    prices[str(row[0])] = float(row[1])
            
            return prices
            
        except Exception as e:
            self.logger.error(f"Error getting batch prices: {e}")
            return {}
