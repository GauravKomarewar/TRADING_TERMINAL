#!/usr/bin/env python3
"""
Option Chain DB Access (PRODUCTION)
==================================

Unified SQLite access layer for option-chain snapshots.

This module is the ONLY place allowed to:
- Read option-chain snapshots
- Initialize option-chain DB files

Used by:
- Dashboard APIs (read-only)
- Strategies (read-only)
- Market-data bootstrap (init only)

STRICT RULES:
- ❌ No calculations
- ❌ No Greeks
- ❌ No Shoonya / WebSocket access
- ❌ No live feed control
"""

import sqlite3
import time
from pathlib import Path
from typing import Tuple, List, Dict, Any

from shoonya_platform.market_data.option_chain.store import OptionChainStore


# =====================================================================
# READ-ONLY SNAPSHOT READER
# =====================================================================

class OptionChainDBReader:
    """
    Read-only option-chain snapshot reader.

    Guarantees:
    - Snapshot-based reads
    - Freshness enforcement
    - Safe for concurrent readers
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    # --------------------------------------------------
    # CORE READ
    # --------------------------------------------------
    def read(
        self,
        *,
        max_age: float = 2.0,
        require_fresh: bool = True,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Read option-chain snapshot from DB.

        Args:
            max_age: Maximum allowed snapshot age (seconds)
            require_fresh: Raise error if snapshot is stale

        Returns:
            meta: Snapshot metadata
            rows: Option-chain rows
        """

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # ----------------------------
        # META
        # ----------------------------
        meta = {
            r["key"]: r["value"]
            for r in cur.execute("SELECT key, value FROM meta")
        }

        snapshot_ts = float(meta.get("snapshot_ts", 0))
        age = time.time() - snapshot_ts

        if require_fresh and age > max_age:
            conn.close()
            raise RuntimeError(
                f"Option chain snapshot stale | age={age:.2f}s"
            )

        # ----------------------------
        # OPTION CHAIN ROWS
        # ----------------------------
        rows = cur.execute(
            "SELECT * FROM option_chain ORDER BY strike"
        ).fetchall()

        conn.close()

        return meta, [dict(r) for r in rows]

    # --------------------------------------------------
    # CONVENIENCE HELPERS
    # --------------------------------------------------
    def read_rows(
        self,
        *,
        max_age: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """Return only option-chain rows"""
        _, rows = self.read(max_age=max_age)
        return rows

    def read_meta(
        self,
        *,
        max_age: float = 2.0,
    ) -> Dict[str, Any]:
        """Return only snapshot metadata"""
        meta, _ = self.read(max_age=max_age)
        return meta


# =====================================================================
# DB INITIALIZER (WRITE-ONCE UTILITY)
# =====================================================================

def init_option_chain_db(path: str) -> None:
    """
    Initialize an empty option-chain DB file.

    Used by:
    - Market-data bootstrap
    - Deployment scripts
    - One-time setup

    IMPORTANT:
    - This does NOT start live feeds
    - This does NOT write market data
    """

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = OptionChainStore(db_path)
    store.close()
