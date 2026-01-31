#!/usr/bin/env python3
"""
OptionChainStore (PRODUCTION)
=============================

SQLite-backed snapshot store for OptionChainData.

RULES:
- SINGLE writer only
- READ-ONLY for all consumers
- NO calculations
- NO live feed control
- Mirrors OptionChainData fields exactly
"""

import sqlite3
import time
from pathlib import Path
import threading
import logging

logger = logging.getLogger(__name__)


class OptionChainStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()

        self._conn = sqlite3.connect(
            self.db_path,
            timeout=3,
            isolation_level=None,
            check_same_thread=False,
        )

        self._configure_db(self._conn)
        self._init_schema()

    # --------------------------------------------------
    # DB CONFIGURATION (WAL + PERFORMANCE)
    # --------------------------------------------------

    def _configure_db(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()

        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA foreign_keys=OFF;")
        cur.execute("PRAGMA locking_mode=NORMAL;")
        cur.execute("PRAGMA busy_timeout=3000;")

        # ~200MB cache (negative = KB units)
        cur.execute("PRAGMA cache_size=-200000;")

        conn.commit()

    # --------------------------------------------------
    # SCHEMA
    # --------------------------------------------------

    def _init_schema(self) -> None:
        cur = self._conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,

            token TEXT,
            trading_symbol TEXT,
            exchange TEXT,
            lot_size INTEGER,

            ltp REAL,
            change_pct REAL,
            volume INTEGER,
            oi INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            bid REAL,
            ask REAL,
            bid_qty INTEGER,
            ask_qty INTEGER,

            last_update REAL,

            -- Greeks (persisted)
            iv REAL,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,

            PRIMARY KEY (strike, option_type)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        self._conn.commit()

    # --------------------------------------------------
    # SNAPSHOT WRITE (ATOMIC)
    # --------------------------------------------------

    def write_snapshot(self, oc) -> None:
        """
        Atomically mirror OptionChainData into SQLite.
        """
        df = oc.get_dataframe(copy=True)
        stats = oc.get_stats()

        if df is None or df.empty:
            return

        snapshot_ts = time.time()

        rows = []
        for _, r in df.iterrows():
            rows.append((
                r["strike"],
                r["option_type"],

                r.get("token"),
                r.get("trading_symbol"),
                r.get("exchange"),
                r.get("lot_size"),

                r.get("ltp"),
                r.get("change_pct"),
                r.get("volume"),
                r.get("oi"),
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("bid"),
                r.get("ask"),
                r.get("bid_qty"),
                r.get("ask_qty"),

                r.get("last_update"),

                # Greeks
                r.get("iv"),
                r.get("delta"),
                r.get("gamma"),
                r.get("theta"),
                r.get("vega"),
            ))

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")

                cur.execute("DELETE FROM option_chain")

                cur.executemany("""
                    INSERT INTO option_chain (
                        strike, option_type,
                        token, trading_symbol, exchange, lot_size,
                        ltp, change_pct, volume, oi,
                        open, high, low, close,
                        bid, ask, bid_qty, ask_qty,
                        last_update,
                        iv, delta, gamma, theta, vega
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?,
                        ?, ?, ?, ?, ?
                    )
                """, rows)

                cur.execute("DELETE FROM meta")
                cur.executemany(
                    "INSERT INTO meta VALUES (?, ?)",
                    [
                        ("exchange", str(stats.get("exchange"))),
                        ("symbol", str(stats.get("symbol"))),
                        ("expiry", str(stats.get("expiry"))),
                        ("atm", str(stats.get("atm"))),
                        ("spot_ltp", str(stats.get("spot_ltp"))),
                        ("fut_ltp", str(stats.get("fut_ltp"))),
                        ("snapshot_ts", str(snapshot_ts)),
                    ],
                )

                cur.execute("COMMIT")

            except Exception:
                cur.execute("ROLLBACK")
                logger.exception("❌ OptionChain snapshot write failed")
                raise

    # --------------------------------------------------
    # LIFECYCLE
    # --------------------------------------------------

    def close(self) -> None:
        self._conn.close()
