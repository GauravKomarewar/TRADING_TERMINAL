#!/usr/bin/env python3
"""
Integration Test: Complete Strategy System

End-to-end tests for:
- Strategy discovery via registry
- Market adapter creation via factory
- Strategy registration via runner
- Reporter and Writer integration
- Both market types (database_market and live_feed_market)

This test demonstrates how the complete system works together.
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime

from shoonya_platform.strategies.universal_settings.universal_registry import list_strategy_templates
from shoonya_platform.strategies.market_adapter_factory import MarketAdapterFactory
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.strategies.universal_settings.universal_strategy_reporter import build_strategy_report
from shoonya_platform.strategies.universal_settings.writer import StrategyRunWriter


@pytest.fixture
def temp_db():
    """Create temporary database"""
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
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def run_db():
    """Database for strategy runs"""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    
    yield db_path
    Path(db_path).unlink(missing_ok=True)


class MockStrategy:
    """Mock strategy for integration testing"""
    def __init__(self, name="test_strategy"):
        self.name = name
        self.state = Mock()
        self.state.active = True
        self.state.ce_leg = Mock(
            symbol="NFO_NIFTY_25FEB_23500_CE",
            delta=0.5,
            entry_price=100.0,
            current_price=120.0
        )
        self.state.pe_leg = Mock(
            symbol="NFO_NIFTY_25FEB_23500_PE",
            delta=-0.5,
            entry_price=100.0,
            current_price=120.0
        )
        self.state.adjustment_phase = None
        self.state.total_unrealized_pnl = Mock(return_value=4000.0)
        self.state.total_delta = Mock(return_value=0.0)
        self.state.ce_leg.unrealized_pnl = Mock(return_value=2000.0)
        self.state.pe_leg.unrealized_pnl = Mock(return_value=2000.0)
        self.state.realized_pnl = 0.0
        self.state.next_profit_target = None
        self.config = Mock()
        self.config.cooldown_seconds = 30
    
    def prepare(self):
        """Required strategy lifecycle method"""
        return True
    
    def on_tick(self):
        """Required strategy tick method"""
        pass


class MockMarket:
    """Mock market for testing"""
    def __init__(self):
        pass
    
    def snapshot(self):
        return {"spot": 23500.0}


class TestIntegrationSystemFlow:
    """End-to-end system workflow tests"""
    
    def test_full_workflow_discover_register_report_database(self, temp_db, run_db):
        """
        Full workflow with database_market:
        1. Discover strategies
        2. Create database adapter
        3. Register strategy
        4. Generate report
        5. Write results
        """
        # 1. DISCOVER STRATEGIES
        templates = list_strategy_templates()
        assert len(templates) > 0
        dnss_template = next(
            (t for t in templates if t["slug"] == "dnss"),
            None
        )
        assert dnss_template is not None
        
        # 2. CREATE DATABASE ADAPTER
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": temp_db,
        }
        is_valid, msg = MarketAdapterFactory.validate_config_for_market(
            "database_market", config
        )
        assert is_valid, msg
        
        adapter = MarketAdapterFactory.create("database_market", config)
        assert adapter is not None
        assert adapter.db_path == temp_db
        
        # 3. REGISTER STRATEGY
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        result = runner.register_with_config(
            name="integration_db",
            strategy=strategy,
            market=market,
            config={
                "strategy_name": "dnss_db_test",
                "exchange": "NFO",
                "symbol": "NIFTY",
                "db_path": temp_db,
            },
            market_type="database_market"
        )
        assert result is True
        
        # Verify context
        context = runner._strategies["integration_db"]
        assert context is not None
        assert context.market_type == "database_market"
        assert context.market_adapter is not None
        
        # 4. GENERATE REPORT
        report = build_strategy_report(
            strategy,
            market_adapter=context.market_adapter
        )
        assert report is not None
        assert "DELTA NEUTRAL" in report
        assert "23500" in report  # Should include spot
        
        # 5. WRITE RESULTS
        writer = StrategyRunWriter(run_db)
        writer.start_run(
            run_id="workflow_db_1",
            resolved_config={
                "strategy_name": "dnss_db_test",
                "exchange": "NFO",
                "symbol": "NIFTY",
            },
            market_type="database_market"
        )
        writer.log_event(
            run_id="workflow_db_1",
            event_type="entry",
            payload={"price": 100.0}
        )
        writer.update_metrics(
            run_id="workflow_db_1",
            max_mtm=4000.0,
            max_drawdown=0.0,
            adjustments=0,
        )
        
        # Verify persistence
        run = writer.get_run("workflow_db_1")
        assert run is not None
        assert run["market_type"] == "database_market"
        assert run["strategy_name"] == "dnss_db_test"
    
    def test_full_workflow_discover_register_report_live(self, run_db):
        """
        Full workflow with live_feed_market:
        1. Discover strategies
        2. Create live adapter
        3. Register strategy
        4. Generate report
        5. Write results
        """
        # 1. DISCOVER STRATEGIES
        templates = list_strategy_templates()
        assert len(templates) > 0
        
        # 2. CREATE LIVE ADAPTER
        config = {
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        is_valid, msg = MarketAdapterFactory.validate_config_for_market(
            "live_feed_market", config
        )
        assert is_valid, msg
        
        adapter = MarketAdapterFactory.create("live_feed_market", config)
        assert adapter is not None
        
        # 3. REGISTER STRATEGY
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        strategy = MockStrategy()
        market = MockMarket()
        
        result = runner.register_with_config(
            name="integration_live",
            strategy=strategy,
            market=market,
            config={
                "strategy_name": "dnss_live_test",
                "exchange": "NFO",
                "symbol": "NIFTY",
            },
            market_type="live_feed_market"
        )
        assert result is True
        
        # Verify context
        context = runner._strategies["integration_live"]
        assert context is not None
        assert context.market_type == "live_feed_market"
        
        # 4. GENERATE REPORT
        report = build_strategy_report(
            strategy,
            market_adapter=context.market_adapter
        )
        assert report is not None
        
        # 5. WRITE RESULTS
        writer = StrategyRunWriter(run_db)
        writer.start_run(
            run_id="workflow_live_1",
            resolved_config={
                "strategy_name": "dnss_live_test",
                "exchange": "NFO",
                "symbol": "NIFTY",
            },
            market_type="live_feed_market"
        )
        
        run = writer.get_run("workflow_live_1")
        assert run is not None
        assert run["market_type"] == "live_feed_market"
    
    def test_multiple_strategies_both_market_types(self, temp_db, run_db):
        """Register multiple strategies with different market types"""
        bot = Mock()
        runner = StrategyRunner(bot=bot)
        writer = StrategyRunWriter(run_db)
        
        # Strategy 1: Database market
        strategy1 = MockStrategy("strategy_1")
        result1 = runner.register_with_config(
            name="multi_db",
            strategy=strategy1,
            market=MockMarket(),
            config={
                "strategy_name": "dnss_1",
                "exchange": "NFO",
                "symbol": "NIFTY",
                "db_path": temp_db,
            },
            market_type="database_market"
        )
        assert result1 is True
        
        # Strategy 2: Live market
        strategy2 = MockStrategy("strategy_2")
        result2 = runner.register_with_config(
            name="multi_live",
            strategy=strategy2,
            market=MockMarket(),
            config={
                "strategy_name": "dnss_2",
                "exchange": "NFO",
                "symbol": "NIFTY",
            },
            market_type="live_feed_market"
        )
        assert result2 is True
        
        # Verify strategies registered
        assert len(runner._strategies) == 2
        
        # Verify context details
        context1 = runner._strategies["multi_db"]
        context2 = runner._strategies["multi_live"]
        
        assert context1.market_type == "database_market"
        assert context2.market_type == "live_feed_market"
        
        # Write both runs
        writer.start_run(
            run_id="multi_1",
            resolved_config={"strategy_name": "dnss_1"},
            market_type="database_market"
        )
        writer.start_run(
            run_id="multi_2",
            resolved_config={"strategy_name": "dnss_2"},
            market_type="live_feed_market"
        )
        
        run1 = writer.get_run("multi_1")
        run2 = writer.get_run("multi_2")
        
        assert run1 is not None
        assert run2 is not None
        assert run1["market_type"] == "database_market"
        assert run2["market_type"] == "live_feed_market"
    
    def test_strategy_adapter_polymorphism(self, temp_db):
        """
        Verify adapters have same interface (polymorphic substitution)
        Strategy shouldn't know which adapter it's using
        """
        db_adapter = MarketAdapterFactory.create(
            "database_market",
            {"exchange": "NFO", "symbol": "NIFTY", "db_path": temp_db}
        )
        live_adapter = MarketAdapterFactory.create(
            "live_feed_market",
            {"exchange": "NFO", "symbol": "NIFTY"}
        )
        
        # Both should have same public interface
        required_methods = [
            "get_market_snapshot",
            "get_nearest_option_by_greek",
            "get_nearest_option_by_premium",
            "get_instrument_price",
            "get_instrument_prices_batch",
        ]
        
        for method in required_methods:
            assert hasattr(db_adapter, method), f"DB adapter missing {method}"
            assert hasattr(live_adapter, method), f"Live adapter missing {method}"
    
    def test_registry_strategy_can_be_loaded(self):
        """Registry strategies should be importable"""
        templates = list_strategy_templates()
        
        # Try importing DeltaNeutralShortStrangleStrategy
        dnss_template = next(
            (t for t in templates if t["slug"] == "dnss"),
            None
        )
        assert dnss_template is not None
        
        # Module name should be importable
        module_name = dnss_template["module"]
        assert module_name == "shoonya_platform.strategies.delta_neutral.dnss"
        assert "shoonya_platform" in module_name
        assert "delta_neutral" in module_name
        assert "dnss" in module_name


class TestIntegrationErrorHandling:
    """Error handling in integrated system"""
    
    def test_missing_database_handled(self):
        """System should handle missing database files"""
        with pytest.raises(FileNotFoundError):
            MarketAdapterFactory.create(
                "database_market",
                {
                    "exchange": "NFO",
                    "symbol": "NIFTY",
                    "db_path": "/nonexistent/path/database.sqlite"
                }
            )
    
    def test_missing_config_handled(self):
        """System should handle missing config fields"""
        config = {"symbol": "NIFTY"}  # Missing exchange
        
        is_valid, msg = MarketAdapterFactory.validate_config_for_market(
            "live_feed_market", config
        )
        
        assert not is_valid
        assert "exchange" in msg.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
