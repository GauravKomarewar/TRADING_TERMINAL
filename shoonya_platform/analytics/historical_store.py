#!/usr/bin/env python3
"""PostgreSQL historical store for analytics/replay."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PostgresHistoricalStore:
    def __init__(self, dsn: str):
        self.dsn = str(dsn or "").strip()
        if not self.dsn:
            raise RuntimeError("Empty PostgreSQL DSN")

        self._driver = None
        self._module = None
        self._conn = None
        self._lock = threading.RLock()
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

            try:
                import psycopg  # type: ignore

                self._driver = "psycopg"
                self._module = psycopg
                self._conn = psycopg.connect(self.dsn, autocommit=True)
                return
            except Exception:
                pass

            try:
                import psycopg2  # type: ignore

                self._driver = "psycopg2"
                self._module = psycopg2
                self._conn = psycopg2.connect(self.dsn)
                self._conn.autocommit = True
                return
            except Exception as e:
                raise RuntimeError(
                    "PostgreSQL driver missing. Install `psycopg[binary]` or `psycopg2-binary`."
                ) from e

    def _cursor(self):
        if self._conn is None:
            self._connect()
        return self._conn.cursor()

    def _exec(self, sql: str, params: Optional[tuple] = None):
        with self._lock:
            try:
                cur = self._cursor()
                cur.execute(sql, params or ())
                return cur
            except Exception:
                logger.exception("PostgreSQL execute failed; reconnecting")
                self._connect()
                cur = self._cursor()
                cur.execute(sql, params or ())
                return cur

    def _exec_many(self, sql: str, rows: List[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            cur = self._cursor()
            try:
                cur.executemany(sql, rows)
            except Exception:
                logger.exception("PostgreSQL executemany failed; reconnecting")
                self._connect()
                cur = self._cursor()
                cur.executemany(sql, rows)

    def _init_schema(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS strategy_samples (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL,
                strategy_name TEXT NOT NULL,
                underlying TEXT,
                mode TEXT,
                is_active BOOLEAN NOT NULL,
                spot_price DOUBLE PRECISION,
                total_pnl DOUBLE PRECISION,
                realized_pnl DOUBLE PRECISION,
                unrealized_pnl DOUBLE PRECISION,
                combined_delta DOUBLE PRECISION,
                combined_gamma DOUBLE PRECISION,
                combined_theta DOUBLE PRECISION,
                combined_vega DOUBLE PRECISION,
                adjustments_today INTEGER,
                lifetime_adjustments INTEGER,
                runtime_seconds INTEGER
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_strategy_samples_name_ts ON strategy_samples(strategy_name, ts)",
            """
            CREATE TABLE IF NOT EXISTS strategy_events (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL,
                strategy_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details JSONB
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_strategy_events_name_ts ON strategy_events(strategy_name, ts)",
            """
            CREATE TABLE IF NOT EXISTS index_ticks (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL,
                symbol TEXT NOT NULL,
                ltp DOUBLE PRECISION,
                pc DOUBLE PRECISION,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                oi DOUBLE PRECISION
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_index_ticks_symbol_ts ON index_ticks(symbol, ts)",
            """
            CREATE TABLE IF NOT EXISTS option_chain_metrics (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                expiry TEXT NOT NULL,
                spot_price DOUBLE PRECISION,
                atm_strike DOUBLE PRECISION,
                max_pain_strike DOUBLE PRECISION,
                atm_straddle DOUBLE PRECISION,
                pcr_oi DOUBLE PRECISION,
                pcr_volume DOUBLE PRECISION,
                total_oi_ce DOUBLE PRECISION,
                total_oi_pe DOUBLE PRECISION,
                total_vol_ce DOUBLE PRECISION,
                total_vol_pe DOUBLE PRECISION,
                oi_buildup_ce DOUBLE PRECISION,
                oi_buildup_pe DOUBLE PRECISION,
                snapshot_age DOUBLE PRECISION,
                is_stale BOOLEAN
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_option_chain_metrics_ese_ts ON option_chain_metrics(exchange, symbol, expiry, ts)",
        ]
        for sql in ddl:
            self._exec(sql)

    def health(self) -> Dict[str, Any]:
        try:
            cur = self._exec("SELECT 1")
            _ = cur.fetchone()
            return {"ok": True, "driver": self._driver}
        except Exception as e:
            return {"ok": False, "driver": self._driver, "error": str(e)}

    def insert_strategy_samples(self, rows: List[Dict[str, Any]]) -> None:
        sql = """
        INSERT INTO strategy_samples(
            ts, strategy_name, underlying, mode, is_active, spot_price,
            total_pnl, realized_pnl, unrealized_pnl,
            combined_delta, combined_gamma, combined_theta, combined_vega,
            adjustments_today, lifetime_adjustments, runtime_seconds
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        payload = [
            (
                r.get("ts"),
                r.get("strategy_name"),
                r.get("underlying"),
                r.get("mode"),
                bool(r.get("is_active", False)),
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
        sql = "INSERT INTO strategy_events(ts, strategy_name, event_type, details) VALUES (%s, %s, %s, %s::jsonb)"
        payload = [
            (
                r.get("ts"),
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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        payload = [
            (
                r.get("ts"),
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
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        payload = [
            (
                r.get("ts"),
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
                bool(r.get("is_stale", False)),
            )
            for r in rows
        ]
        self._exec_many(sql, payload)

    @staticmethod
    def _rows_to_dict(cur) -> List[Dict[str, Any]]:
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            ts = item.get("ts")
            if isinstance(ts, datetime):
                item["ts"] = ts.isoformat()
            out.append(item)
        return out

    def fetch_strategy_samples(
        self,
        strategy_name: str,
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        cur = self._exec(
            """
            SELECT ts, strategy_name, underlying, mode, is_active, spot_price,
                   total_pnl, realized_pnl, unrealized_pnl,
                   combined_delta, combined_gamma, combined_theta, combined_vega,
                   adjustments_today, lifetime_adjustments, runtime_seconds
            FROM strategy_samples
            WHERE strategy_name = %s
              AND (%s IS NULL OR ts >= %s)
              AND (%s IS NULL OR ts <= %s)
            ORDER BY ts ASC
            LIMIT %s
            """,
            (strategy_name, from_ts, from_ts, to_ts, to_ts, max(1, min(limit, 20000))),
        )
        return self._rows_to_dict(cur)

    def fetch_strategy_events(
        self,
        strategy_name: str,
        from_ts: Optional[datetime],
        to_ts: Optional[datetime],
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        cur = self._exec(
            """
            SELECT ts, strategy_name, event_type, details
            FROM strategy_events
            WHERE strategy_name = %s
              AND (%s IS NULL OR ts >= %s)
              AND (%s IS NULL OR ts <= %s)
            ORDER BY ts ASC
            LIMIT %s
            """,
            (strategy_name, from_ts, from_ts, to_ts, to_ts, max(1, min(limit, 20000))),
        )
        rows = self._rows_to_dict(cur)
        for row in rows:
            details = row.get("details")
            if isinstance(details, str):
                try:
                    row["details"] = json.loads(details)
                except Exception:
                    pass
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
        cur = self._exec(
            """
            SELECT ts, symbol, ltp, pc, open, high, low, close, volume, oi
            FROM index_ticks
            WHERE symbol = ANY(%s)
              AND (%s IS NULL OR ts >= %s)
              AND (%s IS NULL OR ts <= %s)
            ORDER BY ts ASC
            LIMIT %s
            """,
            (symbols, from_ts, from_ts, to_ts, to_ts, max(1, min(limit, 50000))),
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
        cur = self._exec(
            """
            SELECT ts, exchange, symbol, expiry,
                   spot_price, atm_strike, max_pain_strike, atm_straddle,
                   pcr_oi, pcr_volume,
                   total_oi_ce, total_oi_pe, total_vol_ce, total_vol_pe,
                   oi_buildup_ce, oi_buildup_pe,
                   snapshot_age, is_stale
            FROM option_chain_metrics
            WHERE (%s IS NULL OR exchange = %s)
              AND (%s IS NULL OR symbol = %s)
              AND (%s IS NULL OR expiry = %s)
              AND (%s IS NULL OR ts >= %s)
              AND (%s IS NULL OR ts <= %s)
            ORDER BY ts ASC
            LIMIT %s
            """,
            (
                exchange,
                exchange,
                symbol,
                symbol,
                expiry,
                expiry,
                from_ts,
                from_ts,
                to_ts,
                to_ts,
                max(1, min(limit, 20000)),
            ),
        )
        return self._rows_to_dict(cur)
