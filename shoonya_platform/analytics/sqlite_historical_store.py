#!/usr/bin/env python3
"""SQLite fallback historical store – used when PostgreSQL is not configured."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SQLiteHistoricalStore:
    """Drop-in replacement for PostgresHistoricalStore backed by a local SQLite DB."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.row_factory = sqlite3.Row

    def _cursor(self):
        if self._conn is None:
            self._connect()
        return self._conn.cursor()

    def _exec(self, sql: str, params: tuple = ()):
        with self._lock:
            try:
                cur = self._cursor()
                cur.execute(sql, params)
                self._conn.commit()
                return cur
            except sqlite3.OperationalError:
                logger.exception("SQLite execute failed; reconnecting")
                self._connect()
                cur = self._cursor()
                cur.execute(sql, params)
                self._conn.commit()
                return cur

    def _exec_many(self, sql: str, rows: List[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            cur = self._cursor()
            try:
                cur.executemany(sql, rows)
                self._conn.commit()
            except sqlite3.OperationalError:
                logger.exception("SQLite executemany failed; reconnecting")
                self._connect()
                cur = self._cursor()
                cur.executemany(sql, rows)
                self._conn.commit()

    def _init_schema(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS strategy_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                underlying TEXT,
                mode TEXT,
                is_active INTEGER NOT NULL DEFAULT 0,
                spot_price REAL,
                total_pnl REAL,
                realized_pnl REAL,
                unrealized_pnl REAL,
                combined_delta REAL,
                combined_gamma REAL,
                combined_theta REAL,
                combined_vega REAL,
                adjustments_today INTEGER,
                lifetime_adjustments INTEGER,
                runtime_seconds INTEGER
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ss_name_ts ON strategy_samples(strategy_name, ts)",
            """
            CREATE TABLE IF NOT EXISTS strategy_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_se_name_ts ON strategy_events(strategy_name, ts)",
            """
            CREATE TABLE IF NOT EXISTS index_ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                ltp REAL,
                pc REAL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                oi REAL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_it_sym_ts ON index_ticks(symbol, ts)",
            """
            CREATE TABLE IF NOT EXISTS option_chain_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                expiry TEXT NOT NULL,
                spot_price REAL,
                atm_strike REAL,
                max_pain_strike REAL,
                atm_straddle REAL,
                pcr_oi REAL,
                pcr_volume REAL,
                total_oi_ce REAL,
                total_oi_pe REAL,
                total_vol_ce REAL,
                total_vol_pe REAL,
                oi_buildup_ce REAL,
                oi_buildup_pe REAL,
                snapshot_age REAL,
                is_stale INTEGER DEFAULT 0
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ocm_ese_ts ON option_chain_metrics(exchange, symbol, expiry, ts)",
        ]
        for sql in ddl:
            self._exec(sql)

    def health(self) -> Dict[str, Any]:
        try:
            cur = self._exec("SELECT 1")
            _ = cur.fetchone()
            return {"ok": True, "driver": "sqlite"}
        except Exception as e:
            return {"ok": False, "driver": "sqlite", "error": str(e)}

    @staticmethod
    def _ts_str(val) -> str:
        if val is None:
            raise ValueError("ts must not be None")
        if isinstance(val, datetime):
            return val.isoformat()
        return str(val)

    # ── inserts ──
    def insert_strategy_samples(self, rows: List[Dict[str, Any]]) -> None:
        sql = """
        INSERT INTO strategy_samples(
            ts, strategy_name, underlying, mode, is_active, spot_price,
            total_pnl, realized_pnl, unrealized_pnl,
            combined_delta, combined_gamma, combined_theta, combined_vega,
            adjustments_today, lifetime_adjustments, runtime_seconds
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        payload = [
            (
                self._ts_str(r.get("ts")),
                r.get("strategy_name"),
                r.get("underlying"),
                r.get("mode"),
                int(bool(r.get("is_active", False))),
                r.get("spot_price"),
                r.get("total_pnl"),
                r.get("realized_pnl"),
                r.get("unrealized_pnl"),
                r.get("combined_delta"),
                r.get("combined_gamma"),
                r.get("combined_theta"),
                r.get("combined_vega"),
                int(r.get("adjustments_today", 0) or 0),
                int(r.get("lifetime_adjustments", 0) or 0),
                int(r.get("runtime_seconds", 0) or 0),
            )
            for r in rows
        ]
        self._exec_many(sql, payload)

    def insert_strategy_events(self, rows: List[Dict[str, Any]]) -> None:
        sql = "INSERT INTO strategy_events(ts, strategy_name, event_type, details) VALUES (?,?,?,?)"
        payload = [
            (
                self._ts_str(r.get("ts")),
                r.get("strategy_name"),
                r.get("event_type"),
                json.dumps(r.get("details") or {}),
            )
            for r in rows
        ]
        self._exec_many(sql, payload)

    def insert_index_ticks(self, rows: List[Dict[str, Any]]) -> None:
        sql = """
        INSERT INTO index_ticks(ts, symbol, ltp, pc, open, high, low, close, volume, oi)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """
        payload = [
            (
                self._ts_str(r.get("ts")),
                r.get("symbol"),
                r.get("ltp"),
                r.get("pc"),
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("volume"),
                r.get("oi"),
            )
            for r in rows
        ]
        self._exec_many(sql, payload)

    def insert_option_chain_metrics(self, rows: List[Dict[str, Any]]) -> None:
        sql = """
        INSERT INTO option_chain_metrics(
            ts, exchange, symbol, expiry,
            spot_price, atm_strike, max_pain_strike, atm_straddle,
            pcr_oi, pcr_volume,
            total_oi_ce, total_oi_pe, total_vol_ce, total_vol_pe,
            oi_buildup_ce, oi_buildup_pe,
            snapshot_age, is_stale
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        payload = [
            (
                self._ts_str(r.get("ts")),
                r.get("exchange"),
                r.get("symbol"),
                r.get("expiry"),
                r.get("spot_price"),
                r.get("atm_strike"),
                r.get("max_pain_strike"),
                r.get("atm_straddle"),
                r.get("pcr_oi"),
                r.get("pcr_volume"),
                r.get("total_oi_ce"),
                r.get("total_oi_pe"),
                r.get("total_vol_ce"),
                r.get("total_vol_pe"),
                r.get("oi_buildup_ce"),
                r.get("oi_buildup_pe"),
                r.get("snapshot_age"),
                int(bool(r.get("is_stale", False))),
            )
            for r in rows
        ]
        self._exec_many(sql, payload)

    # ── fetches ──
    @staticmethod
    def _rows_to_dict(cur) -> List[Dict[str, Any]]:
        rows = cur.fetchall()
        if not rows:
            return []
        cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            item = dict(zip(cols, row))
            # Convert is_active back to bool for API compatibility
            if "is_active" in item:
                item["is_active"] = bool(item["is_active"])
            if "is_stale" in item:
                item["is_stale"] = bool(item["is_stale"])
            out.append(item)
        return out

    def fetch_strategy_samples(
        self,
        strategy_name: str,
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        from_iso = from_ts.isoformat() if from_ts else None
        to_iso = to_ts.isoformat() if to_ts else None
        cur = self._exec(
            """
            SELECT ts, strategy_name, underlying, mode, is_active, spot_price,
                   total_pnl, realized_pnl, unrealized_pnl,
                   combined_delta, combined_gamma, combined_theta, combined_vega,
                   adjustments_today, lifetime_adjustments, runtime_seconds
            FROM strategy_samples
            WHERE strategy_name = ?
              AND (? IS NULL OR ts >= ?)
              AND (? IS NULL OR ts <= ?)
            ORDER BY ts ASC
            LIMIT ?
            """,
            (strategy_name, from_iso, from_iso, to_iso, to_iso, max(1, min(limit, 20000))),
        )
        return self._rows_to_dict(cur)

    def fetch_strategy_events(
        self,
        strategy_name: str,
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        from_iso = from_ts.isoformat() if from_ts else None
        to_iso = to_ts.isoformat() if to_ts else None
        cur = self._exec(
            """
            SELECT ts, strategy_name, event_type, details
            FROM strategy_events
            WHERE strategy_name = ?
              AND (? IS NULL OR ts >= ?)
              AND (? IS NULL OR ts <= ?)
            ORDER BY ts ASC
            LIMIT ?
            """,
            (strategy_name, from_iso, from_iso, to_iso, to_iso, max(1, min(limit, 20000))),
        )
        rows = self._rows_to_dict(cur)
        for row in rows:
            details = row.get("details")
            if isinstance(details, str):
                try:
                    row["details"] = json.loads(details)
                except Exception:
                    logger.warning(
                        "Malformed JSON in strategy_events.details for strategy=%s ts=%s: %s",
                        row.get("strategy_name"), row.get("ts"), details[:200] if details else details,
                        exc_info=True,
                    )
        return rows

    def fetch_index_ticks(
        self,
        symbols: List[str],
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        limit: int = 20000,
    ) -> List[Dict[str, Any]]:
        if not symbols:
            return []
        from_iso = from_ts.isoformat() if from_ts else None
        to_iso = to_ts.isoformat() if to_ts else None
        placeholders = ",".join("?" for _ in symbols)
        params = list(symbols) + [from_iso, from_iso, to_iso, to_iso, max(1, min(limit, 50000))]
        cur = self._exec(
            f"""
            SELECT ts, symbol, ltp, pc, open, high, low, close, volume, oi
            FROM index_ticks
            WHERE symbol IN ({placeholders})
              AND (? IS NULL OR ts >= ?)
              AND (? IS NULL OR ts <= ?)
            ORDER BY ts ASC
            LIMIT ?
            """,
            tuple(params),
        )
        return self._rows_to_dict(cur)

    def fetch_option_metrics(
        self,
        exchange: Optional[str],
        symbol: Optional[str],
        expiry: Optional[str],
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        from_iso = from_ts.isoformat() if from_ts else None
        to_iso = to_ts.isoformat() if to_ts else None
        cur = self._exec(
            """
            SELECT ts, exchange, symbol, expiry,
                   spot_price, atm_strike, max_pain_strike, atm_straddle,
                   pcr_oi, pcr_volume,
                   total_oi_ce, total_oi_pe, total_vol_ce, total_vol_pe,
                   oi_buildup_ce, oi_buildup_pe,
                   snapshot_age, is_stale
            FROM option_chain_metrics
            WHERE (? IS NULL OR exchange = ?)
              AND (? IS NULL OR symbol = ?)
              AND (? IS NULL OR expiry = ?)
              AND (? IS NULL OR ts >= ?)
              AND (? IS NULL OR ts <= ?)
            ORDER BY ts ASC
            LIMIT ?
            """,
            (exchange, exchange, symbol, symbol, expiry, expiry,
             from_iso, from_iso, to_iso, to_iso, max(1, min(limit, 20000))),
        )
        return self._rows_to_dict(cur)

    def cleanup_old_data(self, days: int = 7) -> None:
        """Remove data older than N days to prevent SQLite bloat."""
        from datetime import timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        for table in ("strategy_samples", "strategy_events", "index_ticks", "option_chain_metrics"):
            self._exec(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))  # noqa: S608
