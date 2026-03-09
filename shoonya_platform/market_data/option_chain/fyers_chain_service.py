#!/usr/bin/env python3
"""
FyersChainService — Parallel Fyers Data Pipeline for Option Chains
===================================================================

Enriches the primary (Shoonya) option-chain data with Fyers API snapshots.
Operates in TWO modes:

 1. **Enrichment** (Shoonya active):
    UPDATE oi, volume, bid, ask on existing rows in the chain's SQLite DB.

 2. **Fallback** (Shoonya stale > STALE_THRESHOLD seconds):
    Full snapshot write so the dashboard + strategies always have fresh data.

Lifecycle:
    Managed by TradingBot — started AFTER OptionChainSupervisor so it can
    discover active chains at runtime.

Requirements:
    • pyotp, fyers_apiv3 (already in venv)
    • Fyers credentials at the configured path
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("FYERS_CHAIN")

# ---------------------------------------------------------------------------
# DEFAULTS
# ---------------------------------------------------------------------------
DEFAULT_CREDS_PATH = (
    Path(__file__).resolve().parents[4]  # → /home/ubuntu
    / "option_trading_system_fyers"
    / "config"
    / "credentials.env"
)
TOKEN_FILE = (
    Path(__file__).resolve().parents[4]
    / "option_trading_system_fyers"
    / "fyers_token.json"
)

POLL_INTERVAL = 5          # seconds between full poll cycles
STALE_THRESHOLD = 8.0      # seconds: if Shoonya snapshot older → fallback write
STRIKE_COUNT = 20          # strikes each side of ATM from Fyers
MAX_CONSECUTIVE_ERRORS = 10

# ---------------------------------------------------------------------------
# Fyers symbol mapping  (supervisor chain key prefix → Fyers API symbol)
# ---------------------------------------------------------------------------
_INDEX_MAP: Dict[str, str] = {
    "NFO:NIFTY":      "NSE:NIFTY50-INDEX",
    "NFO:BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "NFO:FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "NFO:MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "BFO:SENSEX":     "BSE:SENSEX-INDEX",
}

# Month abbreviation → two-char numeric
_MONTH_NUM = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

_MONTH_ABBR = {
    "JAN": "JAN", "FEB": "FEB", "MAR": "MAR", "APR": "APR",
    "MAY": "MAY", "JUN": "JUN", "JUL": "JUL", "AUG": "AUG",
    "SEP": "SEP", "OCT": "OCT", "NOV": "NOV", "DEC": "DEC",
}


# =====================================================================
# HELPERS
# =====================================================================

def _expiry_str_to_date(expiry: str) -> Optional[datetime]:
    """Parse '17-MAR-2026' into a datetime object."""
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(expiry.upper(), fmt)
        except ValueError:
            continue
    return None


def _expiry_to_epoch(expiry: str) -> str:
    """Convert '17-MAR-2026' to Fyers API timestamp string."""
    dt = _expiry_str_to_date(expiry)
    if dt is None:
        return ""
    return str(int(dt.timestamp()))


def _build_mcx_futures_symbol(symbol: str, expiry: str) -> Optional[str]:
    """
    Build MCX futures symbol for Fyers optionchain API.

    Example: symbol='CRUDEOILM', expiry='17-MAR-2026'
             → 'MCX:CRUDEOILM26MARFUT'
    """
    dt = _expiry_str_to_date(expiry)
    if dt is None:
        return None
    yy = dt.strftime("%y")             # '26'
    mmm = dt.strftime("%b").upper()    # 'MAR'
    return f"MCX:{symbol}{yy}{mmm}FUT"


def _map_chain_to_fyers(exchange: str, symbol: str, expiry: str) -> Optional[str]:
    """
    Map a supervisor chain key to the Fyers optionchain API symbol.

    Returns None if the mapping is unknown.
    """
    prefix = f"{exchange}:{symbol}"

    # NSE / BSE indices
    if prefix in _INDEX_MAP:
        return _INDEX_MAP[prefix]

    # MCX commodities
    if exchange == "MCX":
        return _build_mcx_futures_symbol(symbol, expiry)

    # NFO stock options: NSE:<SYMBOL>-EQ
    if exchange == "NFO":
        return f"NSE:{symbol}-EQ"

    return None


# =====================================================================
# SERVICE
# =====================================================================

class FyersChainService:
    """
    Background service that polls Fyers optionchain API and writes data
    into the supervisor's SQLite DB files.
    """

    def __init__(
        self,
        supervisor,
        *,
        creds_path: Optional[Path] = None,
        poll_interval: float = POLL_INTERVAL,
        enabled: bool = True,
    ):
        self._supervisor = supervisor
        self._creds_path = Path(creds_path) if creds_path else DEFAULT_CREDS_PATH
        self._poll_interval = poll_interval
        self._enabled = enabled

        self._fyers_client = None   # FyersV3Client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_errors = 0

        # Telemetry
        self._stats = {
            "started_at": None,
            "total_polls": 0,
            "total_writes": 0,
            "total_enrichments": 0,
            "total_fallbacks": 0,
            "total_errors": 0,
            "last_poll_ts": None,
            "last_error": None,
            "connected": False,
        }

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Connect to Fyers and begin background polling."""
        if not self._enabled:
            logger.info("Fyers chain service DISABLED (FYERS_CHAIN_ENABLED != 1)")
            return False

        if not self._connect():
            logger.error("Fyers chain service failed to connect — will NOT start")
            return False

        self._stats["started_at"] = time.time()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="FyersChainServiceThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("✅ FyersChainService started (interval=%.1fs)", self._poll_interval)
        return True

    def stop(self) -> None:
        """Signal the poll thread to stop and wait."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)
        logger.info("FyersChainService stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Return telemetry snapshot."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # FYERS CONNECTION
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Authenticate with Fyers and cache the client."""
        try:
            # Add path so we can import from the fyers project
            fyers_project = str(self._creds_path.parent.parent)
            if fyers_project not in sys.path:
                sys.path.insert(0, fyers_project)

            from core.fyers_final import FyersV3Client  # noqa

            client = FyersV3Client(
                fyers_id=self._get_cred("FYERS_ID"),
                totp_key=self._get_cred("T_OTP_KEY"),
                pin=self._get_cred("PIN"),
                redirect_url=self._get_cred("REDIRECT_URL"),
                app_id=self._get_cred("APP_ID"),
                secret_id=self._get_cred("SECRETE_ID"),
                token_file=str(TOKEN_FILE),
            )
            client.connect()
            self._fyers_client = client
            self._stats["connected"] = True
            logger.info("Fyers authentication successful (FYERS_ID=%s)", client.fyers_id)
            return True
        except Exception as e:
            logger.exception("Fyers connection failed: %s", e)
            self._stats["last_error"] = str(e)
            return False

    def _get_cred(self, key: str) -> str:
        """Read a credential from the .env file."""
        # Load env file each time (in case it's updated)
        from dotenv import dotenv_values
        vals = dotenv_values(self._creds_path)
        value = vals.get(key, "")
        if not value:
            raise ValueError(f"Missing credential {key} in {self._creds_path}")
        return value

    def _ensure_session(self) -> bool:
        """Re-authenticate if token is expired."""
        try:
            if self._fyers_client._is_token_expired():
                logger.info("Fyers token expired — re-authenticating")
                self._fyers_client.connect(force_relogin=True)
                self._stats["connected"] = True
            return True
        except Exception as e:
            logger.error("Fyers re-auth failed: %s", e)
            self._stats["connected"] = False
            self._stats["last_error"] = str(e)
            return False

    # ------------------------------------------------------------------
    # MAIN POLL LOOP
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background loop: poll all supervisor chains via Fyers."""
        logger.info("Fyers poll loop running")

        while not self._stop_event.is_set():
            try:
                if not self._ensure_session():
                    self._stop_event.wait(30)
                    continue

                chains = self._get_supervisor_chains()
                if not chains:
                    self._stop_event.wait(self._poll_interval)
                    continue

                for key, bundle in chains.items():
                    if self._stop_event.is_set():
                        break
                    self._poll_one_chain(key, bundle)

                self._stats["total_polls"] += 1
                self._stats["last_poll_ts"] = time.time()
                self._consecutive_errors = 0

            except Exception as e:
                self._consecutive_errors += 1
                self._stats["total_errors"] += 1
                self._stats["last_error"] = str(e)
                logger.error(
                    "Fyers poll cycle error (%d consecutive): %s",
                    self._consecutive_errors, e,
                )

                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical(
                        "Fyers pipeline halted — %d consecutive failures",
                        self._consecutive_errors,
                    )
                    self._stop_event.wait(60)
                    self._consecutive_errors = 0  # allow retry

            self._stop_event.wait(self._poll_interval)

    # ------------------------------------------------------------------
    # CHAIN DISCOVERY
    # ------------------------------------------------------------------

    def _get_supervisor_chains(self) -> Dict[str, Dict]:
        """Return a snapshot of active supervisor chains."""
        with self._supervisor._lock:
            return dict(self._supervisor._chains)

    # ------------------------------------------------------------------
    # PER-CHAIN POLL
    # ------------------------------------------------------------------

    def _poll_one_chain(self, key: str, bundle: Dict) -> None:
        """Fetch Fyers data for one chain and write to its SQLite DB."""
        parts = key.split(":")
        if len(parts) != 3:
            return
        exchange, symbol, expiry = parts

        fyers_symbol = _map_chain_to_fyers(exchange, symbol, expiry)
        if not fyers_symbol:
            logger.debug("No Fyers mapping for %s — skipping", key)
            return

        expiry_ts = _expiry_to_epoch(expiry)

        # Call Fyers API
        try:
            response = self._fyers_client.fyers.optionchain(
                data={
                    "symbol": fyers_symbol,
                    "strikecount": STRIKE_COUNT,
                    "timestamp": expiry_ts,
                }
            )
        except Exception as e:
            logger.warning("Fyers API call failed for %s: %s", key, e)
            self._stats["total_errors"] += 1
            return

        if not isinstance(response, dict) or response.get("s") != "ok":
            msg = response.get("message", "unknown") if isinstance(response, dict) else str(response)
            logger.debug("Fyers API non-ok for %s: %s", key, msg)
            return

        raw = response.get("data", {})
        options_chain = raw.get("optionsChain", [])
        if not options_chain:
            return

        # Extract spot price from underlying row
        spot_price = 0.0
        for item in options_chain:
            if not item.get("option_type"):
                spot_price = float(item.get("ltp", 0))
                break

        db_path = bundle.get("db_path")
        if not db_path or not Path(db_path).exists():
            return

        # Parse option rows
        rows = self._parse_option_rows(options_chain, exchange)
        if not rows:
            return

        # Determine write mode
        snapshot_age = self._get_snapshot_age(db_path)

        if snapshot_age is not None and snapshot_age < STALE_THRESHOLD:
            # Shoonya is active — enrich only
            self._enrich_db(db_path, rows)
            self._stats["total_enrichments"] += 1
        else:
            # Shoonya stale or DB empty — full fallback write
            self._fallback_write(db_path, rows, exchange, symbol, expiry, spot_price)
            self._stats["total_fallbacks"] += 1

        self._stats["total_writes"] += 1

    # ------------------------------------------------------------------
    # PARSE FYERS RESPONSE
    # ------------------------------------------------------------------

    def _parse_option_rows(
        self,
        chain: List[Dict],
        exchange: str,
    ) -> List[Dict[str, Any]]:
        """Convert Fyers optionsChain items to flat row dicts."""
        rows: List[Dict[str, Any]] = []
        now_ts = time.time()

        for item in chain:
            opt_type = item.get("option_type", "")
            if opt_type not in ("CE", "PE"):
                continue

            strike = float(item.get("strike_price", 0))
            if strike <= 0:
                continue

            rows.append({
                "strike": strike,
                "option_type": opt_type,
                "token": item.get("fyToken"),
                "trading_symbol": item.get("symbol", ""),
                "exchange": exchange,
                "lot_size": None,
                "ltp": float(item.get("ltp", 0)),
                "change_pct": float(item.get("ltpchp", 0)),
                "volume": int(item.get("volume", 0)),
                "oi": int(item.get("oi", 0)),
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "bid": float(item.get("bid", 0)),
                "ask": float(item.get("ask", 0)),
                "bid_qty": None,
                "ask_qty": None,
                "last_update": now_ts,
                "iv": None,
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None,
            })

        return rows

    # ------------------------------------------------------------------
    # DB I/O
    # ------------------------------------------------------------------

    def _get_snapshot_age(self, db_path: Path) -> Optional[float]:
        """Return age (seconds) of the last snapshot, or None if unknown."""
        try:
            conn = sqlite3.connect(str(db_path), timeout=2)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT value FROM meta WHERE key='snapshot_ts'"
            ).fetchone()
            conn.close()
            if row:
                return time.time() - float(row[0])
        except Exception:
            pass
        return None

    def _enrich_db(self, db_path: Path, rows: List[Dict]) -> None:
        """UPDATE oi, volume, bid, ask on existing rows (enrichment mode)."""
        try:
            conn = sqlite3.connect(str(db_path), timeout=3)
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")

            for r in rows:
                cur.execute(
                    """
                    UPDATE option_chain
                    SET oi = ?, volume = ?, bid = ?, ask = ?,
                        change_pct = ?, ltp = COALESCE(
                            CASE WHEN ltp IS NULL OR ltp = 0 THEN ? ELSE ltp END,
                            ?
                        )
                    WHERE strike = ? AND option_type = ?
                    """,
                    (
                        r["oi"], r["volume"], r["bid"], r["ask"],
                        r["change_pct"],
                        r["ltp"], r["ltp"],
                        r["strike"], r["option_type"],
                    ),
                )

            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("Fyers enrich failed for %s: %s", db_path, e)
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass

    def _fallback_write(
        self,
        db_path: Path,
        rows: List[Dict],
        exchange: str,
        symbol: str,
        expiry: str,
        spot_price: float,
    ) -> None:
        """Full snapshot write when Shoonya is stale (fallback mode)."""
        snapshot_ts = time.time()

        try:
            conn = sqlite3.connect(str(db_path), timeout=3)
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")

            cur.execute("DELETE FROM option_chain")

            cur.executemany(
                """
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
                """,
                [
                    (
                        r["strike"], r["option_type"],
                        r["token"], r["trading_symbol"], r["exchange"], r["lot_size"],
                        r["ltp"], r["change_pct"], r["volume"], r["oi"],
                        r["open"], r["high"], r["low"], r["close"],
                        r["bid"], r["ask"], r["bid_qty"], r["ask_qty"],
                        r["last_update"],
                        r["iv"], r["delta"], r["gamma"], r["theta"], r["vega"],
                    )
                    for r in rows
                ],
            )

            # Meta
            now_spot = str(spot_price) if spot_price > 0 else ""
            cur.execute("DELETE FROM meta")
            cur.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [
                    ("exchange", exchange),
                    ("symbol", symbol),
                    ("expiry", expiry),
                    ("atm", ""),
                    ("spot_ltp", now_spot),
                    ("fut_ltp", ""),
                    ("snapshot_ts", str(snapshot_ts)),
                    ("source", "fyers"),
                ],
            )

            conn.commit()
            conn.close()
            logger.debug(
                "Fyers fallback write | %s:%s:%s | %d rows",
                exchange, symbol, expiry, len(rows),
            )
        except Exception as e:
            logger.warning("Fyers fallback write failed for %s: %s", db_path, e)
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
