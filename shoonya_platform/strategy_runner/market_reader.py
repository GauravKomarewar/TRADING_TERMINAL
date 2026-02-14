#!/usr/bin/env python3
"""
market_reader.py — Live SQLite Option Chain Reader
====================================================

Reads live option chain data from the SQLite databases in:
    market_data/option_chain/data/{EXCHANGE}_{SYMBOL}_{DD-MMM-YYYY}.sqlite

The OptionChainSupervisor thread writes snapshots into these DBs continuously.
This reader opens them in read-only WAL mode and queries live data.

Auto-resolves the correct database file based on exchange + symbol + expiry logic.
"""

import glob
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fresh_strategy.market_reader")

# Path to DB folder
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_FOLDER = _PROJECT_ROOT / "shoonya_platform" / "market_data" / "option_chain" / "data"


class MarketReader:
    """
    Reads live option chain data from SQLite database.

    Auto-resolves the correct .sqlite file.
    Exposes simple query methods for the condition engine.
    """

    def __init__(self, exchange: str, symbol: str, db_path: Optional[str] = None):
        """
        Args:
            exchange: NFO, MCX, etc.
            symbol: NIFTY, BANKNIFTY, etc.
            db_path: Explicit path to .sqlite file. If None, auto-resolves.
        """
        self.exchange = exchange.upper()
        self.symbol = symbol.upper()
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def db_path(self) -> Optional[str]:
        """Resolved database path."""
        if self._db_path and Path(self._db_path).exists():
            return self._db_path
        resolved = self._resolve_db_path()
        if resolved:
            self._db_path = resolved
        return self._db_path

    def _resolve_db_path(self) -> Optional[str]:
        """
        Auto-resolve the correct .sqlite file from the data folder.

        Strategy:
        1. List all files matching {EXCHANGE}_{SYMBOL}_*.sqlite
        2. Parse the expiry date from each filename
        3. Pick the one whose expiry is >= today and nearest (current weekly)
        4. If none in the future, pick the most recent one
        """
        folder = DB_FOLDER
        if not folder.exists():
            logger.error(f"DB folder not found: {folder}")
            return None

        pattern = f"{self.exchange}_{self.symbol}_*.sqlite"
        matches = list(folder.glob(pattern))

        if not matches:
            logger.error(f"No database files matching {pattern} in {folder}")
            return None

        # Parse dates from filenames: {EXCHANGE}_{SYMBOL}_{DD-MMM-YYYY}.sqlite
        today = date.today()
        candidates = []

        for f in matches:
            name = f.stem  # e.g. NFO_NIFTY_17-FEB-2026
            parts = name.split("_", 2)  # ['NFO', 'NIFTY', '17-FEB-2026']
            if len(parts) < 3:
                continue
            date_str = parts[2]
            try:
                expiry_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                candidates.append((f, expiry_date))
            except ValueError:
                logger.debug(f"Skipping file with unparseable date: {f.name}")
                continue

        if not candidates:
            # Fallback: just use the first match
            logger.warning(f"Could not parse dates, using first match: {matches[0].name}")
            return str(matches[0])

        # Future or today expiries
        future = [(f, d) for f, d in candidates if d >= today]
        if future:
            # Pick nearest future expiry
            future.sort(key=lambda x: x[1])
            chosen = future[0]
        else:
            # All expired, pick most recent
            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[0]

        logger.info(f"Resolved DB: {chosen[0].name} (expiry: {chosen[1]})")
        return str(chosen[0])

    def connect(self) -> bool:
        """Open connection with validation."""
        path = self.db_path
        if not path:
            logger.error(f"No DB found for {self.exchange}_{self.symbol}")
            return False
        
        # CRITICAL: Verify file exists and is not empty
        path_obj = Path(path)
        if not path_obj.exists():
            logger.error(f"DB file does not exist: {path}")
            return False
        
        if path_obj.stat().st_size < 1024:  # Less than 1KB = likely empty
            logger.error(f"DB file too small (corrupt?): {path} ({path_obj.stat().st_size} bytes)")
            return False
        
        try:
            uri = f"file:{path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, timeout=5)
            self._conn.row_factory = sqlite3.Row
            
            # VALIDATE schema exists
            tables = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            
            table_names = {row[0] for row in tables}
            required_tables = {"option_chain", "meta"}
            
            if not required_tables.issubset(table_names):
                logger.error(f"Missing required tables: {required_tables - table_names}")
                self.close()
                return False
            
            # VALIDATE has data
            row_count = self._conn.execute("SELECT COUNT(*) FROM option_chain").fetchone()[0]
            if row_count == 0:
                logger.error(f"option_chain table is empty in {path}")
                self.close()
                return False
            
            logger.info(f"Connected to DB: {path_obj.name} ({row_count} rows)")
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {path} | {e}")
            return False

    def close(self):
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _ensure_conn(self) -> bool:
        """Ensure we have a connection, reconnect if needed."""
        if self._conn is None:
            return self.connect()
        # Test connection is alive
        try:
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            self.close()
            return self.connect()

    # ─── Queries ─────────────────────────────────────────────────────────────

    def get_full_chain(self) -> List[Dict[str, Any]]:
        """Read the entire option chain as a list of dicts."""
        if not self._ensure_conn():
            return []
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM option_chain WHERE ltp > 0 ORDER BY strike, option_type")
            return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"get_full_chain error: {e}")
            return []

    def get_meta(self) -> Dict[str, str]:
        """Read the meta table as a dict."""
        if not self._ensure_conn():
            return {}
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT key, value FROM meta")
            return {row["key"]: row["value"] for row in cur.fetchall()}
        except Exception as e:
            logger.error(f"get_meta error: {e}")
            return {}

    def get_spot_price(self) -> float:
        """Get current spot price from meta table."""
        meta = self.get_meta()
        try:
            return float(meta.get("spot_ltp", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_atm_strike(self) -> float:
        """Get ATM strike from meta table."""
        meta = self.get_meta()
        try:
            return float(meta.get("atm", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_fut_ltp(self) -> float:
        """Get futures LTP from meta table."""
        meta = self.get_meta()
        try:
            return float(meta.get("fut_ltp", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_snapshot_age_seconds(self) -> float:
        """How old is the latest snapshot (seconds ago)."""
        meta = self.get_meta()
        try:
            ts = float(meta.get("snapshot_ts", 0))
            return datetime.now().timestamp() - ts
        except (ValueError, TypeError):
            return 99999.0

    def find_option_by_delta(
        self,
        option_type: str,
        target_delta: float,
        tolerance: float = 0.05,
    ) -> Optional[Dict[str, Any]]:
        """
        Find the option with delta closest to target.

        Args:
            option_type: 'CE' or 'PE'
            target_delta: Target absolute delta (e.g. 0.30)
            tolerance: Max acceptable distance from target

        Returns:
            Option row dict or None
        """
        if not self._ensure_conn():
            return None
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("""
                SELECT * FROM option_chain
                WHERE option_type = ?
                  AND delta IS NOT NULL
                  AND ltp > 0
                  AND ABS(ABS(delta) - ?) <= ?
                ORDER BY ABS(ABS(delta) - ?) ASC
                LIMIT 1
            """, (option_type.upper(), target_delta, tolerance, target_delta))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"find_option_by_delta error: {e}")
            return None

    def find_option_by_premium(
        self,
        option_type: str,
        target_premium: float,
        tolerance: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """Find option with LTP closest to target premium."""
        if not self._ensure_conn():
            return None
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("""
                SELECT * FROM option_chain
                WHERE option_type = ?
                  AND ltp > 0
                  AND ABS(ltp - ?) <= ?
                ORDER BY ABS(ltp - ?) ASC
                LIMIT 1
            """, (option_type.upper(), target_premium, tolerance, target_premium))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"find_option_by_premium error: {e}")
            return None

    def get_option_at_strike(
        self, strike: float, option_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get option data for a specific strike and type."""
        if not self._ensure_conn():
            return None
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("""
                SELECT * FROM option_chain
                WHERE strike = ? AND option_type = ?
            """, (strike, option_type.upper()))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_option_at_strike error: {e}")
            return None

    def find_option_by_strike_offset(
        self,
        option_type: str,
        offset_from_atm: float,
    ) -> Optional[Dict[str, Any]]:
        """Find option at ATM ± offset."""
        atm = self.get_atm_strike()
        if atm <= 0:
            return None
        target_strike = atm + offset_from_atm
        return self.get_option_at_strike(target_strike, option_type)

    def find_option_by_iv(
        self,
        option_type: str,
        target_iv: float,
        tolerance: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        """Find option with IV closest to target."""
        if not self._ensure_conn():
            return None
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("""
                SELECT * FROM option_chain
                WHERE option_type = ?
                  AND iv IS NOT NULL AND iv > 0
                  AND ltp > 0
                  AND ABS(iv - ?) <= ?
                ORDER BY ABS(iv - ?) ASC
                LIMIT 1
            """, (option_type.upper(), target_iv, tolerance, target_iv))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"find_option_by_iv error: {e}")
            return None

    def get_atm_options(self) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Get ATM CE and PE at the same strike.

        Returns:
            (ce_option_dict, pe_option_dict) — either may be None
        """
        atm = self.get_atm_strike()
        if atm <= 0:
            return None, None
        ce = self.get_option_at_strike(atm, "CE")
        pe = self.get_option_at_strike(atm, "PE")
        return ce, pe

    def find_option_by_premium_range(
        self,
        option_type: str,
        min_premium: float,
        max_premium: float,
    ) -> Optional[Dict[str, Any]]:
        """Find option with LTP within a premium range, closest to midpoint."""
        if not self._ensure_conn():
            return None
        assert self._conn is not None
        mid = (min_premium + max_premium) / 2.0
        try:
            cur = self._conn.cursor()
            cur.execute("""
                SELECT * FROM option_chain
                WHERE option_type = ?
                  AND ltp >= ? AND ltp <= ?
                ORDER BY ABS(ltp - ?) ASC
                LIMIT 1
            """, (option_type.upper(), min_premium, max_premium, mid))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"find_option_by_premium_range error: {e}")
            return None

    def get_lot_size(self) -> int:
        """Get lot size from first row of option chain, or fallback."""
        if not self._ensure_conn():
            return 1
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT lot_size FROM option_chain WHERE lot_size IS NOT NULL LIMIT 1")
            row = cur.fetchone()
            if row and row["lot_size"]:
                return int(row["lot_size"])
        except Exception:
            pass
        # Fallback lookup
        from shoonya_platform.fresh_strategy.config_schema import LOT_SIZES
        return LOT_SIZES.get(self.symbol, 1)
