#!/usr/bin/env python3
"""
Test Strategy Runner

Tests:
- Strategy registration with database_market adapter
- Strategy registration with live_feed_market adapter
- Strategy context management
- Metrics collection
- Tick execution (without performing actual trades)
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

from shoonya_platform.strategies.strategy_runner import StrategyRunner, StrategyContext


class MockStrategy:
    """Mock strategy for testing"""
    def __init__(self):
        self.state = Mock()
        self.state.active = False
        self.config = Mock()
        self.on_tick_called = False
    
    def prepare(self):
        """Required strategy lifecycle method"""
        return True
    
    def on_tick(self):
        self.on_tick_called = True


class MockMarket:
    """Mock market for testing"""
    def __init__(self):
        self.data = {}
    
    def snapshot(self):
        return {"spot": 23500.0}


@pytest.fixture
def temp_db():
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


class TestStrategyRunner:
    """Test strategy runner registration and execution"""
    
    def test_strategy_runner_creates_instance(self):
        """Should create StrategyRunner instance"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        assert runner is not None
        assert hasattr(runner, "_strategies")
        assert isinstance(runner._strategies, dict)
    
    def test_register_strategy_with_database_market(self, temp_db):
        """Should register strategy with database_market adapter"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        config = {
            "strategy_name": "test_dnss",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        
        result = runner.register_with_config(
            name="test_1",
            strategy=strategy,
            market=market,
            config=config,
            market_type="database_market"
        )
        
        assert result is True
        assert "test_1" in runner._strategies
    
    def test_register_strategy_with_live_feed_market(self):
        """Should register strategy with live_feed_market adapter"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        config = {
            "strategy_name": "test_dnss",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        result = runner.register_with_config(
            name="test_2",
            strategy=strategy,
            market=market,
            config=config,
            market_type="live_feed_market"
        )
        
        assert result is True
        assert "test_2" in runner._strategies
    
    def test_register_creates_market_adapter(self, temp_db):
        """Should create and store market adapter in context"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        config = {
            "strategy_name": "test_dnss",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        
        runner.register_with_config(
            name="test_3",
            strategy=strategy,
            market=market,
            config=config,
            market_type="database_market"
        )
        
        context = runner._strategies["test_3"]
        assert context.market_adapter is not None
        assert context.market_type == "database_market"
    
    def test_register_validates_config(self, temp_db):
        """Should validate config before registration"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        # Invalid config - missing db_path
        config = {
            "strategy_name": "test_dnss",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        result = runner.register_with_config(
            name="test_4",
            strategy=strategy,
            market=market,
            config=config,
            market_type="database_market"
        )
        
        assert result is False
    
    def test_strategy_context_stores_metadata(self):
        """Should store strategy metadata in context"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        config = {
            "strategy_name": "test_dnss",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        runner.register_with_config(
            name="test_5",
            strategy=strategy,
            market=market,
            config=config,
            market_type="live_feed_market"
        )
        
        context = runner._strategies["test_5"]
        assert context.name == "test_5"
        assert context.strategy == strategy
        assert context.market == market
    
    def test_register_multiple_strategies(self, temp_db):
        """Should register multiple strategies simultaneously"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy1 = MockStrategy()
        strategy2 = MockStrategy()
        market = MockMarket()
        
        config_db = {
            "strategy_name": "dnss_1",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        config_live = {
            "strategy_name": "dnss_2",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        result1 = runner.register_with_config(
            name="multi_1",
            strategy=strategy1,
            market=market,
            config=config_db,
            market_type="database_market"
        )
        result2 = runner.register_with_config(
            name="multi_2",
            strategy=strategy2,
            market=market,
            config=config_live,
            market_type="live_feed_market"
        )
        
        assert result1 is True
        assert result2 is True
        assert len(runner._strategies) == 2
    
    def test_can_access_registered_strategy(self, temp_db):
        """Should be able to access registered strategy from _strategies"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        config = {
            "strategy_name": "test",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        
        runner.register_with_config(
            name="get_test",
            strategy=strategy,
            market=market,
            config=config,
            market_type="database_market"
        )
        
        context = runner._strategies["get_test"]
        assert context is not None
        assert context.name == "get_test"
    
    def test_nonexistent_strategy_not_in_dict(self):
        """Nonexistent strategy should not be in _strategies dict"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        assert "nonexistent" not in runner._strategies
    
    def test_access_multiple_strategies(self, temp_db):
        """Should access all registered strategies from dict"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy1 = MockStrategy()
        strategy2 = MockStrategy()
        market = MockMarket()
        
        config1 = {
            "strategy_name": "one",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        config2 = {
            "strategy_name": "two",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        runner.register_with_config(
            name="list_1",
            strategy=strategy1,
            market=market,
            config=config1,
            market_type="database_market"
        )
        runner.register_with_config(
            name="list_2",
            strategy=strategy2,
            market=market,
            config=config2,
            market_type="live_feed_market"
        )
        
        assert len(runner._strategies) == 2
        assert "list_1" in runner._strategies
        assert "list_2" in runner._strategies
    
    def test_strategy_metrics_recorded(self, temp_db):
        """Should record strategy metrics"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        config = {
            "strategy_name": "metrics_test",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        
        runner.register_with_config(
            name="metrics_1",
            strategy=strategy,
            market=market,
            config=config,
            market_type="database_market"
        )
        
        context = runner._strategies["metrics_1"]
        assert context.metrics is not None
        assert context.metrics.name == "metrics_1"
        assert context.metrics.total_ticks == 0


class TestStrategyContext:
    """Test StrategyContext data model"""
    
    def test_context_requires_name(self):
        """Context should require name parameter"""
        with pytest.raises(TypeError):
            # Omit name from required parameters - should raise TypeError
            StrategyContext(strategy=Mock(), market=Mock())  # type: ignore
    
    def test_context_stores_market_types(self):
        """Context should store both market types"""
        context_db = StrategyContext(
            name="db_context",
            strategy=Mock(),
            market=Mock(),
            market_type="database_market"
        )
        
        context_live = StrategyContext(
            name="live_context",
            strategy=Mock(),
            market=Mock(),
            market_type="live_feed_market"
        )
        
        assert context_db.market_type == "database_market"
        assert context_live.market_type == "live_feed_market"
    
    def test_context_has_thread_lock(self):
        """Context should have thread lock for safety"""
        context = StrategyContext(
            name="lock_context",
            strategy=Mock(),
            market=Mock()
        )
        
        assert hasattr(context, "lock")
        assert context.lock is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
