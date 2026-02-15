#!/usr/bin/env python3
"""
STRATEGY RUN WRITER
===================
DB-backed runtime truth recorder

Works with BOTH market types:
- live_feed_market adapters (WebSocket-based)
- database_market adapters (SQLite-based)

ROLE:
- Persist resolved config (including market_type selection)
- Persist lifecycle events
- Persist metrics
- Persist adjustments
- NO execution authority

The writer is market-type agnostic. It records which market adapter
is active (market_type field) but doesn't care how it works internally.
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, Optional


class StrategyRunWriter:
    """
    Write strategy run data to SQLite database.
    
    Compatible with:
    - DeltaNeutralShortStrangleStrategy
    - Any strategy using MarketAdapterFactory
    - Both database_market and live_feed_market adapters
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    # -------------------------------------------------
    # SCHEMA
    # -------------------------------------------------
    def _init_schema(self):
        """Initialize database schema (idempotent)"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()

            c.execute("""
            CREATE TABLE IF NOT EXISTS strategy_runs (
                run_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                strategy_version TEXT,
                exchange TEXT,
                symbol TEXT,
                market_type TEXT,
                started_at TEXT,
                stopped_at TEXT,
                resolved_config TEXT
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS strategy_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                ts TEXT,
                event_type TEXT,
                payload TEXT
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS strategy_metrics (
                run_id TEXT PRIMARY KEY,
                max_mtm REAL,
                max_drawdown REAL,
                adjustments INTEGER,
                entry_time TEXT,
                exit_time TEXT
            )
            """)

            conn.commit()

    # -------------------------------------------------
    # RUN LIFECYCLE
    # -------------------------------------------------
    def start_run(
        self,
        *,
        run_id: str,
        resolved_config: Dict[str, Any],
        market_type: Optional[str] = None,
    ):
        """
        Record strategy run start.
        
        Args:
            run_id: Unique run identifier
            resolved_config: Full configuration dict
            market_type: "database_market" or "live_feed_market" or None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategy_runs
                (run_id, strategy_name, strategy_version, exchange, symbol, market_type, started_at, resolved_config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    resolved_config.get("strategy_name", "unknown"),
                    resolved_config.get("strategy_version", "1.0"),
                    resolved_config.get("exchange", "NFO"),
                    resolved_config.get("symbol", "NIFTY"),
                    market_type,
                    datetime.utcnow().isoformat(),
                    json.dumps(resolved_config),
                ),
            )
            conn.commit()

    def stop_run(self, run_id: str):
        """Record strategy run stop"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE strategy_runs
                SET stopped_at = ?
                WHERE run_id = ?
                """,
                (datetime.utcnow().isoformat(), run_id),
            )
            conn.commit()

    # -------------------------------------------------
    # EVENTS (for any market adapter)
    # -------------------------------------------------
    def log_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ):
        """
        Log strategy event.
        
        Common event types:
        - "entry": Entry leg opened
        - "adjustment": Adjustment executed
        - "exit": Exit leg closed
        - "error": Error occurred
        - "adapter_switch": Market adapter switched (if applicable)
        
        Args:
            run_id: Run identifier
            event_type: Type of event
            payload: Event data dict
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategy_events
                (run_id, ts, event_type, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    datetime.utcnow().isoformat(),
                    event_type,
                    json.dumps(payload or {}),
                ),
            )
            conn.commit()

    # -------------------------------------------------
    # METRICS (UPDATE-IN-PLACE)
    # -------------------------------------------------
    def update_metrics(
        self,
        *,
        run_id: str,
        max_mtm: float,
        max_drawdown: float,
        adjustments: int,
        entry_time: Optional[str] = None,
        exit_time: Optional[str] = None,
    ):
        """
        Update strategy metrics (upsert).
        
        Args:
            run_id: Run identifier
            max_mtm: Maximum mark-to-market profit
            max_drawdown: Maximum drawdown percentage
            adjustments: Number of adjustments executed
            entry_time: ISO timestamp of entry
            exit_time: ISO timestamp of exit
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategy_metrics
                (run_id, max_mtm, max_drawdown, adjustments, entry_time, exit_time)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    max_mtm=excluded.max_mtm,
                    max_drawdown=excluded.max_drawdown,
                    adjustments=excluded.adjustments,
                    entry_time=excluded.entry_time,
                    exit_time=excluded.exit_time
                """,
                (
                    run_id,
                    max_mtm,
                    max_drawdown,
                    adjustments,
                    entry_time,
                    exit_time,
                ),
            )
            conn.commit()

    # -------------------------------------------------
    # QUERY HELPERS
    # -------------------------------------------------
    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve run details"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM strategy_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_run_events(self, run_id: str) -> list:
        """Retrieve all events for a run"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM strategy_events WHERE run_id = ? ORDER BY ts",
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_run_metrics(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve metrics for a run"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM strategy_metrics WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None
