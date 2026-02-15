#!/usr/bin/env python3
"""
Test Strategy Run Writer

Tests:
- Writer initializes database schema
- Writer records strategy runs
- Writer logs events
- Writer updates metrics
- Writer works with both market types
- Query helpers work correctly
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime

from shoonya_platform.strategy_runner.universal_settings.writer import StrategyRunWriter


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


class TestStrategyRunWriter:
    """Test strategy run writer functionality"""
    
    def test_writer_initializes_database(self, temp_db):
        """Writer should initialize database schema"""
        writer = StrategyRunWriter(temp_db)
        
        # Schema should exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        # Check tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_runs'"
        )
        assert cursor.fetchone() is not None
        
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_events'"
        )
        assert cursor.fetchone() is not None
        
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_metrics'"
        )
        assert cursor.fetchone() is not None
        
        conn.close()
    
    def test_writer_records_run_start(self, temp_db):
        """Writer should record run start"""
        writer = StrategyRunWriter(temp_db)
        
        config = {
            "strategy_name": "test_dnss",
            "strategy_version": "1.0",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        
        writer.start_run(
            run_id="run_001",
            resolved_config=config,
            market_type="database_market"
        )
        
        # Verify in database
        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        row = cursor.execute(
            "SELECT * FROM strategy_runs WHERE run_id = ?",
            ("run_001",)
        ).fetchone()
        
        assert row is not None
        assert row["strategy_name"] == "test_dnss"
        assert row["market_type"] == "database_market"
        
        conn.close()
    
    def test_writer_records_market_type_database(self, temp_db):
        """Writer should record database_market runs"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        
        writer.start_run(
            run_id="db_run",
            resolved_config=config,
            market_type="database_market"
        )
        
        run = writer.get_run("db_run")
        assert run is not None
        assert run["market_type"] == "database_market"
    
    def test_writer_records_market_type_live(self, temp_db):
        """Writer should record live_feed_market runs"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        
        writer.start_run(
            run_id="live_run",
            resolved_config=config,
            market_type="live_feed_market"
        )
        
        run = writer.get_run("live_run")
        assert run is not None
        assert run["market_type"] == "live_feed_market"
    
    def test_writer_records_stop_time(self, temp_db):
        """Writer should record run stop time"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        
        writer.start_run(run_id="run_stop", resolved_config=config)
        writer.stop_run("run_stop")
        
        run = writer.get_run("run_stop")
        assert run is not None
        assert run["stopped_at"] is not None
    
    def test_writer_logs_events(self, temp_db):
        """Writer should log strategy events"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer.start_run(run_id="event_run", resolved_config=config)
        
        writer.log_event(
            run_id="event_run",
            event_type="entry",
            payload={"leg": "CE", "price": 100.0}
        )
        
        events = writer.get_run_events("event_run")
        assert len(events) == 1
        assert events[0]["event_type"] == "entry"
    
    def test_writer_logs_multiple_events(self, temp_db):
        """Writer should log multiple events per run"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer.start_run(run_id="multi_event", resolved_config=config)
        
        writer.log_event(run_id="multi_event", event_type="entry")
        writer.log_event(run_id="multi_event", event_type="adjustment")
        writer.log_event(run_id="multi_event", event_type="exit")
        
        events = writer.get_run_events("multi_event")
        assert len(events) == 3
        event_types = [e["event_type"] for e in events]
        assert "entry" in event_types
        assert "adjustment" in event_types
        assert "exit" in event_types
    
    def test_writer_updates_metrics(self, temp_db):
        """Writer should update metrics"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer.start_run(run_id="metrics_run", resolved_config=config)
        
        writer.update_metrics(
            run_id="metrics_run",
            max_mtm=5000.0,
            max_drawdown=10.0,
            adjustments=2,
            entry_time="2026-02-12T09:00:00",
            exit_time="2026-02-12T15:00:00"
        )
        
        metrics = writer.get_run_metrics("metrics_run")
        assert metrics is not None
        assert metrics["max_mtm"] == 5000.0
        assert metrics["max_drawdown"] == 10.0
        assert metrics["adjustments"] == 2
    
    def test_writer_upserts_metrics(self, temp_db):
        """Writer should update metrics in place"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer.start_run(run_id="upsert_run", resolved_config=config)
        
        # First update
        writer.update_metrics(
            run_id="upsert_run",
            max_mtm=1000.0,
            max_drawdown=5.0,
            adjustments=1,
        )
        
        # Second update (should replace)
        writer.update_metrics(
            run_id="upsert_run",
            max_mtm=2000.0,
            max_drawdown=8.0,
            adjustments=2,
        )
        
        metrics = writer.get_run_metrics("upsert_run")
        assert metrics is not None
        assert metrics["max_mtm"] == 2000.0
        assert metrics["adjustments"] == 2
    
    def test_writer_get_run_returns_dict(self, temp_db):
        """get_run should return dict with run data"""
        writer = StrategyRunWriter(temp_db)
        
        config = {
            "strategy_name": "dnss_v1",
            "strategy_version": "1.1",
            "exchange": "NFO",
            "symbol": "NIFTY",
        }
        writer.start_run(run_id="dict_run", resolved_config=config)
        
        run = writer.get_run("dict_run")
        assert isinstance(run, dict)
        assert run is not None
        assert run["run_id"] == "dict_run"
        assert run["strategy_name"] == "dnss_v1"
    
    def test_writer_get_run_returns_none_missing(self, temp_db):
        """get_run should return None for missing runs"""
        writer = StrategyRunWriter(temp_db)
        
        run = writer.get_run("nonexistent")
        assert run is None
    
    def test_writer_get_events_returns_list(self, temp_db):
        """get_run_events should return list"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer.start_run(run_id="events_run", resolved_config=config)
        writer.log_event(run_id="events_run", event_type="entry")
        
        events = writer.get_run_events("events_run")
        assert isinstance(events, list)
        assert len(events) > 0
    
    def test_writer_get_metrics_returns_dict(self, temp_db):
        """get_run_metrics should return dict"""
        writer = StrategyRunWriter(temp_db)
        
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer.start_run(run_id="metrics_dict", resolved_config=config)
        writer.update_metrics(
            run_id="metrics_dict",
            max_mtm=1000.0,
            max_drawdown=5.0,
            adjustments=1,
        )
        
        metrics = writer.get_run_metrics("metrics_dict")
        assert isinstance(metrics, dict)
    
    def test_writer_stores_resolved_config(self, temp_db):
        """Writer should store resolved config as JSON"""
        writer = StrategyRunWriter(temp_db)
        
        config = {
            "strategy_name": "complex_test",
            "strategy_version": "1.5",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "extra_field": "custom_value",
        }
        writer.start_run(run_id="config_run", resolved_config=config)
        
        run = writer.get_run("config_run")
        assert run is not None
        # Config is stored as JSON string
        assert run["resolved_config"] is not None
    
    def test_writer_schema_idempotent(self, temp_db):
        """Writer initialization should be idempotent"""
        writer1 = StrategyRunWriter(temp_db)
        writer2 = StrategyRunWriter(temp_db)
        
        # Both should work without errors
        config = {"strategy_name": "test", "strategy_version": "1.0",
                  "exchange": "NFO", "symbol": "NIFTY"}
        writer1.start_run(run_id="idem_1", resolved_config=config)
        writer2.start_run(run_id="idem_2", resolved_config=config)
        
        # Both runs should exist
        assert writer1.get_run("idem_1") is not None
        assert writer2.get_run("idem_2") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
