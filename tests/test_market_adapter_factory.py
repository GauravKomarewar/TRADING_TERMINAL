#!/usr/bin/env python3
"""
Test Market Adapter Factory

Tests:
- Factory creates correct adapter for database_market
- Factory creates correct adapter for live_feed_market
- Factory validates config per market type
- Factory handles errors gracefully
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import Mock, MagicMock

from shoonya_platform.strategies.market_adapter_factory import MarketAdapterFactory
from shoonya_platform.strategies.database_market.adapter import DatabaseMarketAdapter
from shoonya_platform.strategies.live_feed_market.adapter import LiveFeedMarketAdapter


class TestMarketAdapterFactory:
    """Test market adapter factory and latch pattern"""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary SQLite database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name
        
        # Initialize schema
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS option_chain (
                symbol TEXT,
                strike_price REAL,
                expiry TEXT,
                option_type TEXT,
                token INTEGER,
                delta REAL,
                gamma REAL,
                theta REAL,
                vega REAL,
                premium REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                token INTEGER,
                symbol TEXT,
                ltp REAL
            )
        """)
        conn.commit()
        conn.close()
        
        yield db_path
        
        # Cleanup
        Path(db_path).unlink(missing_ok=True)
    
    def test_factory_creates_database_adapter(self, temp_db):
        """Factory should create DatabaseMarketAdapter for 'database_market'"""
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        
        adapter = MarketAdapterFactory.create("database_market", config)
        
        assert isinstance(adapter, DatabaseMarketAdapter)
    
    def test_factory_creates_live_feed_adapter(self):
        """Factory should create LiveFeedMarketAdapter for 'live_feed_market'"""
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        adapter = MarketAdapterFactory.create("live_feed_market", config)
        
        assert isinstance(adapter, LiveFeedMarketAdapter)
    
    def test_factory_raises_error_for_invalid_market_type(self, temp_db):
        """Factory should raise ValueError for invalid market_type"""
        config = {"exchange": "NFO", "symbol": "NIFTY", "db_path": temp_db}
        
        with pytest.raises(ValueError) as exc_info:
            MarketAdapterFactory.create("invalid_market", config)  # type: ignore
        
        assert "invalid_market" in str(exc_info.value)
    
    def test_factory_database_requires_db_path(self):
        """Factory should require db_path for database_market"""
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
            # Missing: db_path
        }
        
        is_valid, msg = MarketAdapterFactory.validate_config_for_market("database_market", config)
        assert not is_valid
        assert "db_path" in msg.lower()
    
    def test_factory_database_validates_db_exists(self):
        """Factory should validate database file exists"""
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": "/nonexistent/path/to/database.sqlite",
        }
        
        with pytest.raises(FileNotFoundError):
            MarketAdapterFactory.create("database_market", config)
    
    def test_factory_live_feed_requires_exchange(self):
        """Factory should require exchange for live_feed_market"""
        config = {
            "symbol": "NIFTY",
            # Missing: exchange
        }
        
        is_valid, msg = MarketAdapterFactory.validate_config_for_market("live_feed_market", config)
        assert not is_valid
        assert "exchange" in msg.lower()
    
    def test_factory_live_feed_requires_symbol(self):
        """Factory should require symbol for live_feed_market"""
        config = {
            "exchange": "NFO",
            # Missing: symbol
        }
        
        is_valid, msg = MarketAdapterFactory.validate_config_for_market("live_feed_market", config)
        assert not is_valid
        assert "symbol" in msg.lower()
    
    def test_factory_validate_returns_tuple(self):
        """Validate method should return (bool, str) tuple"""
        config = {"exchange": "NFO", "symbol": "NIFTY"}
        
        result = MarketAdapterFactory.validate_config_for_market("live_feed_market", config)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        is_valid, msg = result
        assert isinstance(is_valid, bool)
        assert isinstance(msg, str)
    
    def test_factory_database_adapter_initialized(self, temp_db):
        """Database adapter should be properly initialized"""
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        
        adapter = MarketAdapterFactory.create("database_market", config)
        
        assert adapter.db_path == temp_db
        assert adapter.exchange == "NFO"
        assert adapter.symbol == "NIFTY"
    
    def test_factory_live_feed_adapter_initialized(self):
        """Live feed adapter should be properly initialized"""
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        adapter = MarketAdapterFactory.create("live_feed_market", config)
        
        assert adapter.exchange == "NFO"
        assert adapter.symbol == "NIFTY"
    
    def test_latch_pattern_market_type_selection(self, temp_db):
        """Latch pattern: market_type parameter determines adapter type"""
        config_db = {
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        config_live = {
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        # Same config, different market_type
        db_adapter = MarketAdapterFactory.create("database_market", config_db)
        live_adapter = MarketAdapterFactory.create("live_feed_market", config_live)
        
        # Should be different types
        assert type(db_adapter) != type(live_adapter)
        assert isinstance(db_adapter, DatabaseMarketAdapter)
        assert isinstance(live_adapter, LiveFeedMarketAdapter)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
