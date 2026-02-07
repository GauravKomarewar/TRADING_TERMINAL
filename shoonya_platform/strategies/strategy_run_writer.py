#!/usr/bin/env python3
"""
STRATEGY RUN WRITER
==================
DB-backed runtime truth recorder

ROLE:
- Persist resolved config
- Persist lifecycle events
- Persist metrics
- Persist adjustments
- NO execution authority
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, Optional


class StrategyRunWriter:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    # -------------------------------------------------
    # SCHEMA
    # -------------------------------------------------
    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()

            c.execute("""
            CREATE TABLE IF NOT EXISTS strategy_runs (
                run_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                strategy_version TEXT,
                exchange TEXT,
                symbol TEXT,
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
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO strategy_runs
                (run_id, strategy_name, strategy_version, exchange, symbol, started_at, resolved_config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    resolved_config["strategy_name"],
                    resolved_config["strategy_version"],
                    resolved_config["exchange"],
                    resolved_config["symbol"],
                    datetime.utcnow().isoformat(),
                    json.dumps(resolved_config),
                ),
            )
            conn.commit()

    def stop_run(self, run_id: str):
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
    # EVENTS
    # -------------------------------------------------
    def log_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ):
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
        entry_time: Optional[str],
        exit_time: Optional[str],
    ):
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
