#!/usr/bin/env python3
"""
FyersChainService — Parallel Fyers Data Pipeline for Option Chains
===================================================================

Enriches the primary (Shoonya) option-chain data **in memory** via the
OptionChainData objects managed by the OptionChainSupervisor.

Architecture
------------
  Shoonya WebSocket -> OptionChainData._df  (real-time ticks)
  Fyers REST API    -> OptionChainData._df  (fills gaps: OI, bid/ask, ltp)
                         |
  Supervisor loop   -> SQLite DB snapshots  (single writer -- no races)

Key Guarantees
--------------
* **Zero SQLite writes** -- all DB persistence is done by the supervisor
  through OptionChainStore, eliminating dual-writer race conditions.
* **Fill-only enrichment** -- Fyers never overwrites non-zero Shoonya data;
  it only fills null / zero / NaN fields so live WebSocket data is preserved.
* **Thread-safe** -- enrichment acquires ``OptionChainData._lock`` (RLock),
  the same lock used by ``pull_ticks_efficient()``.
* **No namespace pollution** -- FyersV3Client is imported via the existing
  ``_import_fyers_client()`` helper in ``brokers/fyers/client.py``.

Lifecycle:
    Managed by TradingBot -- started AFTER OptionChainSupervisor.

Requirements:
    * pyotp, fyers_apiv3 (already in venv)
    * Fyers credentials at the configured path
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("FYERS_CHAIN")

# ---------------------------------------------------------------------------
# DEFAULTS
# ---------------------------------------------------------------------------
DEFAULT_CREDS_PATH = (
    Path(__file__).resolve().parents[4]  # -> /home/ubuntu
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
STRIKE_COUNT = 20          # strikes each side of ATM from Fyers
MAX_CONSECUTIVE_ERRORS = 10

# ---------------------------------------------------------------------------
# Fyers symbol mapping  (supervisor chain key -> Fyers API symbol)
# ---------------------------------------------------------------------------
_INDEX_MAP: Dict[str, str] = {
    "NFO:NIFTY":      "NSE:NIFTY50-INDEX",
    "NFO:BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "NFO:FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "NFO:MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "BFO:SENSEX":     "BSE:SENSEX-INDEX",
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
    """MCX:CRUDEOILM, 17-MAR-2026 -> 'MCX:CRUDEOILM26MARFUT'"""
    dt = _expiry_str_to_date(expiry)
    if dt is None:
        return None
    return f"MCX:{symbol}{dt.strftime('%y')}{dt.strftime('%b').upper()}FUT"


def _map_chain_to_fyers(exchange: str, symbol: str, expiry: str) -> Optional[str]:
    """Map a supervisor chain key to the Fyers optionchain API symbol."""
    prefix = f"{exchange}:{symbol}"
    if prefix in _INDEX_MAP:
        return _INDEX_MAP[prefix]
    if exchange == "MCX":
        return _build_mcx_futures_symbol(symbol, expiry)
    if exchange == "NFO":
        return f"NSE:{symbol}-EQ"
    return None


def _is_null_or_zero(val) -> bool:
    """Return True if value is None, NaN, or <= 0."""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    try:
        return float(val) <= 0
    except (TypeError, ValueError):
        return True


# =====================================================================
# SERVICE
# =====================================================================

class FyersChainService:
    """
    Background service that polls Fyers optionchain API and enriches
    the supervisor's in-memory OptionChainData objects.

    The supervisor's existing snapshot-write loop persists the enriched
    data to SQLite -- this service never touches the DB directly.
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

        self._fyers_client = None          # FyersV3Client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_errors = 0

        # Telemetry
        self._stats: Dict[str, Any] = {
            "started_at": None,
            "total_polls": 0,
            "total_enrichments": 0,
            "total_rows_filled": 0,
            "total_spot_fills": 0,
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
            logger.error("Fyers chain service failed to connect -- will NOT start")
            return False

        self._stats["started_at"] = time.time()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="FyersChainServiceThread",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "FyersChainService started (interval=%.1fs)", self._poll_interval
        )
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
            # Use the existing safe import helper from the broker adapter.
            # This avoids sys.path pollution that could shadow
            # shoonya_platform.core with option_trading_system_fyers/core.
            from shoonya_platform.brokers.fyers.client import _import_fyers_client

            FyersV3Client = _import_fyers_client()

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
            logger.info(
                "Fyers authentication successful (FYERS_ID=%s)", client.fyers_id
            )
            return True
        except Exception as e:
            logger.exception("Fyers connection failed: %s", e)
            self._stats["last_error"] = str(e)
            return False

    def _get_cred(self, key: str) -> str:
        """Read a single credential from the .env file."""
        from dotenv import dotenv_values

        vals = dotenv_values(self._creds_path)
        value = vals.get(key, "")
        if not value:
            raise ValueError(f"Missing credential {key} in {self._creds_path}")
        return value

    def _ensure_session(self) -> bool:
        """Re-authenticate if Fyers token is expired."""
        try:
            if self._fyers_client._is_token_expired():
                logger.info("Fyers token expired -- re-authenticating")
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
        """Background loop: poll Fyers and enrich all supervisor chains."""
        logger.info("Fyers poll loop running")

        while not self._stop_event.is_set():
            try:
                if not self._ensure_session():
                    self._stop_event.wait(30)
                    continue

                # Snapshot chain keys + OptionChainData refs under the lock
                chain_items = self._snapshot_chains()
                if not chain_items:
                    self._stop_event.wait(self._poll_interval)
                    continue

                for key, oc in chain_items:
                    if self._stop_event.is_set():
                        break
                    self._poll_one_chain(key, oc)

                self._stats["total_polls"] += 1
                self._stats["last_poll_ts"] = time.time()
                self._consecutive_errors = 0

            except Exception as e:
                self._consecutive_errors += 1
                self._stats["total_errors"] += 1
                self._stats["last_error"] = str(e)
                logger.error(
                    "Fyers poll cycle error (%d consecutive): %s",
                    self._consecutive_errors,
                    e,
                )
                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical(
                        "Fyers pipeline paused -- %d consecutive failures",
                        self._consecutive_errors,
                    )
                    self._stop_event.wait(60)
                    self._consecutive_errors = 0

            self._stop_event.wait(self._poll_interval)

    # ------------------------------------------------------------------
    # CHAIN DISCOVERY  (safe snapshot)
    # ------------------------------------------------------------------

    def _snapshot_chains(self) -> List[tuple]:
        """
        Return [(key, OptionChainData), ...] for every live chain.

        Only holds the supervisor lock long enough to copy references.
        If a chain is removed before enrichment runs, the enrichment
        simply operates on an orphaned OptionChainData -- no side effects.
        """
        with self._supervisor._lock:
            return [
                (key, bundle["oc"])
                for key, bundle in self._supervisor._chains.items()
                if bundle.get("oc") is not None
            ]

    # ------------------------------------------------------------------
    # PER-CHAIN POLL
    # ------------------------------------------------------------------

    def _poll_one_chain(self, key: str, oc) -> None:
        """Fetch Fyers data and enrich the OptionChainData in memory."""
        parts = key.split(":")
        if len(parts) != 3:
            return
        exchange, symbol, expiry = parts

        fyers_symbol = _map_chain_to_fyers(exchange, symbol, expiry)
        if not fyers_symbol:
            return

        # -- Call Fyers API -------------------------------------------
        try:
            response = self._fyers_client.fyers.optionchain(
                data={
                    "symbol": fyers_symbol,
                    "strikecount": STRIKE_COUNT,
                    "timestamp": _expiry_to_epoch(expiry),
                }
            )
        except Exception as e:
            logger.warning("Fyers API call failed for %s: %s", key, e)
            self._stats["total_errors"] += 1
            return

        if not isinstance(response, dict) or response.get("s") != "ok":
            msg = (
                response.get("message", "unknown")
                if isinstance(response, dict)
                else str(response)
            )
            logger.debug("Fyers API non-ok for %s: %s", key, msg)
            return

        raw = response.get("data", {})
        options_chain = raw.get("optionsChain", [])
        if not options_chain:
            return

        # -- Extract spot from underlying row -------------------------
        spot_price = 0.0
        for item in options_chain:
            if not item.get("option_type"):
                spot_price = float(item.get("ltp", 0))
                break

        # -- Parse option rows ----------------------------------------
        fyers_rows = self._parse_option_rows(options_chain)
        if not fyers_rows:
            return

        # -- Enrich OptionChainData in memory -------------------------
        filled = self._enrich_chain_data(oc, fyers_rows, spot_price)
        if filled > 0:
            self._stats["total_enrichments"] += 1
            self._stats["total_rows_filled"] += filled
            logger.debug("Fyers enriched %s | %d fields filled", key, filled)

    # ------------------------------------------------------------------
    # PARSE FYERS RESPONSE
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_option_rows(chain: List[Dict]) -> List[Dict[str, Any]]:
        """Convert optionsChain items to compact dicts."""
        rows: List[Dict[str, Any]] = []
        for item in chain:
            opt_type = item.get("option_type", "")
            if opt_type not in ("CE", "PE"):
                continue
            strike = float(item.get("strike_price", 0))
            if strike <= 0:
                continue
            rows.append(
                {
                    "strike": strike,
                    "option_type": opt_type,
                    "ltp": float(item.get("ltp", 0)),
                    "change_pct": float(item.get("ltpchp", 0)),
                    "volume": int(item.get("volume", 0)),
                    "oi": int(item.get("oi", 0)),
                    "bid": float(item.get("bid", 0)),
                    "ask": float(item.get("ask", 0)),
                }
            )
        return rows

    # ------------------------------------------------------------------
    # IN-MEMORY ENRICHMENT  (the sole write path)
    # ------------------------------------------------------------------

    def _enrich_chain_data(
        self,
        oc,
        fyers_rows: List[Dict[str, Any]],
        spot_price: float,
    ) -> int:
        """
        Enrich OptionChainData._df with Fyers REST snapshot data.

        Rules
        -----
        * Fyers NEVER overwrites a non-zero / non-null Shoonya value.
        * It only FILLS fields that are missing (None / NaN / 0).
        * Greeks, OHLC, lot_size, token, trading_symbol are untouched.
        * This preserves real-time WebSocket data while filling gaps
          (e.g. OI / bid / ask for strikes Shoonya missed).

        Returns
        -------
        int : total number of individual field cells filled.
        """
        filled = 0

        with oc._lock:
            df = oc._df
            if df is None or df.empty:
                return 0

            # -- Spot price -------------------------------------------
            if spot_price > 0 and _is_null_or_zero(oc._spot_ltp):
                oc._spot_ltp = spot_price
                filled += 1
                self._stats["total_spot_fills"] += 1

            # -- Build (strike, option_type) -> row-indices lookup ----
            lookup: Dict[tuple, List[int]] = {}
            strikes_col = df["strike"]
            opt_col = df["option_type"]
            for idx in range(len(df)):
                lk = (strikes_col.iat[idx], opt_col.iat[idx])
                lookup.setdefault(lk, []).append(idx)

            # -- Fields to fill (only where Shoonya value is null/zero)
            fill_fields = ("ltp", "change_pct", "volume", "oi", "bid", "ask")

            # Pre-resolve column positions for fast .iat access
            col_locs = {}
            for f in fill_fields:
                if f in df.columns:
                    col_locs[f] = df.columns.get_loc(f)
            last_update_loc = df.columns.get_loc("last_update") if "last_update" in df.columns else None

            now_ts = time.time()

            for frow in fyers_rows:
                row_key = (frow["strike"], frow["option_type"])
                indices = lookup.get(row_key)
                if not indices:
                    continue

                for idx in indices:
                    row_filled = False
                    for field in fill_fields:
                        col_loc = col_locs.get(field)
                        if col_loc is None:
                            continue

                        fyers_val = frow.get(field)
                        if fyers_val is None or fyers_val == 0:
                            continue

                        cur_val = df.iat[idx, col_loc]
                        if _is_null_or_zero(cur_val):
                            df.iat[idx, col_loc] = fyers_val
                            filled += 1
                            row_filled = True

                    if row_filled and last_update_loc is not None:
                        df.iat[idx, last_update_loc] = now_ts

        return filled
