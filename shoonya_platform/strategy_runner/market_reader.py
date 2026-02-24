#!/usr/bin/env python3
"""
market_reader.py — Live SQLite Option Chain Reader (Production‑Ready)
======================================================================

Reads live option chain data from SQLite databases in:
    market_data/option_chain/data/{EXCHANGE}_{SYMBOL}_{DD-MMM-YYYY}.sqlite

Supports multiple expiries, strike step auto‑detection, snapshot freshness checks,
and robust match_leg attribute handling. Fully compatible with the Universal
Multi‑Leg Strategy Execution Engine.
"""

import glob
import logging
import re
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import StrikeConfig, OptionType, StrikeMode

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_FOLDER = _PROJECT_ROOT / "shoonya_platform" / "market_data" / "option_chain" / "data"

# Allowed match parameters for strike selection (map to SQL expressions)
MATCH_PARAM_TO_SQL = {
    "delta": "delta",
    "abs_delta": "ABS(delta)",
    "gamma": "gamma",
    "theta": "theta",
    "abs_theta": "ABS(theta)",
    "vega": "vega",
    "iv": "iv",
    "ltp": "ltp",
    "oi": "oi",
    "volume": "volume",
    "strike": "strike",
    # Proxy mapping; exact moneyness matching is handled in resolve_strike().
    "moneyness": "strike",
}


class MarketReader:
    """
    Production‑ready market reader with connection pooling, freshness checks,
    and dynamic strike step detection.
    """

    def __init__(self, exchange: str, symbol: str, max_stale_seconds: int = 30):
        """
        Args:
            exchange: NFO, MCX, etc.
            symbol: NIFTY, BANKNIFTY, etc.
            max_stale_seconds: Maximum allowed age of snapshot (seconds) before
                                raising an exception in data retrieval.
        """
        self.exchange = exchange.upper()
        self.symbol = symbol.upper()
        self.max_stale_seconds = max_stale_seconds
        self._conns: Dict[str, Optional[sqlite3.Connection]] = {}
        self._strike_step_cache: Dict[str, float] = {}  # expiry -> strike step

    # ----------------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------------
    def _resolve_db_path(self, expiry: Optional[str] = None) -> Optional[str]:
        """Resolve full path to SQLite file; if expiry None, pick nearest future."""
        folder = DB_FOLDER
        if not folder.exists():
            logger.error(f"DB folder not found: {folder}")
            return None

        if expiry is not None:
            filename = f"{self.exchange}_{self.symbol}_{expiry}.sqlite"
            file_path = folder / filename
            return str(file_path) if file_path.exists() else None

        # No expiry: auto-resolve to nearest future expiry
        pattern = f"{self.exchange}_{self.symbol}_*.sqlite"
        matches = list(folder.glob(pattern))
        if not matches:
            logger.error(f"No database files matching {pattern}")
            return None

        today = date.today()
        candidates = []
        for f in matches:
            name = f.stem
            parts = name.split("_", 2)
            if len(parts) < 3:
                continue
            date_str = parts[2]
            try:
                expiry_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                candidates.append((f, expiry_date))
            except ValueError:
                continue

        if not candidates:
            logger.warning(f"Using first match: {matches[0].name}")
            return str(matches[0])

        future = [(f, d) for f, d in candidates if d >= today]
        if future:
            future.sort(key=lambda x: x[1])
            chosen = future[0]
        else:
            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[0]

        logger.info(f"Resolved default DB: {chosen[0].name} (expiry: {chosen[1]})")
        return str(chosen[0])

    def _get_connection(self, expiry: Optional[str] = None) -> Optional[sqlite3.Connection]:
        key = expiry or "default"
        # Try to reuse an existing connection
        conn = self._conns.get(key)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                self._close_connection(key)

        path = self._resolve_db_path(expiry)
        if not path:
            return None

        path_obj = Path(path)
        if not path_obj.exists() or path_obj.stat().st_size < 1024:
            logger.error(f"DB file missing or too small: {path}")
            return None

        try:
            uri = f"file:{path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            conn.row_factory = sqlite3.Row

            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row[0] for row in tables}
            required_tables = {"option_chain", "meta"}
            if not required_tables.issubset(table_names):
                logger.error(f"Missing tables: {required_tables - table_names}")
                conn.close()
                return None

            row_count = conn.execute("SELECT COUNT(*) FROM option_chain").fetchone()[0]
            if row_count == 0:
                logger.error(f"option_chain table empty in {path}")
                conn.close()
                return None

            logger.info(f"Connected to DB: {path_obj.name} ({row_count} rows)")
            self._conns[key] = conn
            return conn
        except Exception as e:
            logger.error(f"Connection failed: {path} | {e}")
            return None

    def _close_connection(self, key: str):
        conn = self._conns.pop(key, None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self):
        for key in list(self._conns.keys()):
            self._close_connection(key)

    def __del__(self):
        self.close_all()

    def _get_strike_step(self, expiry: Optional[str] = None) -> float:
        """
        Determine the strike price step (minimum difference between consecutive strikes)
        from the option chain. Caches the result per expiry.
        """
        key = expiry or "default"
        if key in self._strike_step_cache:
            return self._strike_step_cache[key]

        conn = self._get_connection(expiry)
        if not conn:
            return 50.0  # fallback
        assert conn is not None  # for type checker

        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT strike FROM option_chain ORDER BY strike")
            strikes = [row[0] for row in cur.fetchall()]
            if len(strikes) < 2:
                return 50.0

            diffs = [strikes[i+1] - strikes[i] for i in range(len(strikes)-1)]
            # Filter out zero (shouldn't happen, but safe)
            diffs = [d for d in diffs if d > 0]
            if not diffs:
                return 50.0

            # Use most common difference (mode)
            step = Counter(diffs).most_common(1)[0][0]
            self._strike_step_cache[key] = step
            logger.debug(f"Strike step for {key}: {step}")
            return step
        except Exception as e:
            logger.error(f"Failed to compute strike step: {e}")
            return 50.0

    def _check_freshness(self, expiry: Optional[str] = None):
        """Raise an exception if snapshot is older than max_stale_seconds."""
        age = self.get_snapshot_age_seconds(expiry)
        if age > self.max_stale_seconds:
            raise RuntimeError(
                f"Snapshot too old: {age:.1f}s > {self.max_stale_seconds}s"
            )

    # ----------------------------------------------------------------------
    # Public data retrieval methods (with optional expiry)
    # ----------------------------------------------------------------------
    def get_meta(self, expiry: Optional[str] = None) -> Dict[str, str]:
        conn = self._get_connection(expiry)
        if not conn:
            return {}
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM meta")
            return {row["key"]: row["value"] for row in cur.fetchall()}
        except Exception as e:
            logger.error(f"get_meta error: {e}")
            return {}

    def get_spot_price(self, expiry: Optional[str] = None) -> float:
        meta = self.get_meta(expiry)
        try:
            return float(meta.get("spot_ltp", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_atm_strike(self, expiry: Optional[str] = None) -> float:
        meta = self.get_meta(expiry)
        try:
            return float(meta.get("atm", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_fut_ltp(self, expiry: Optional[str] = None) -> float:
        meta = self.get_meta(expiry)
        try:
            return float(meta.get("fut_ltp", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_snapshot_age_seconds(self, expiry: Optional[str] = None) -> float:
        meta = self.get_meta(expiry)
        try:
            ts = float(meta.get("snapshot_ts", 0))
            return datetime.now().timestamp() - ts
        except (ValueError, TypeError):
            return 99999.0

    def get_lot_size(self, expiry: Optional[str] = None) -> int:
        conn = self._get_connection(expiry)
        if not conn:
            return 1
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute("SELECT lot_size FROM option_chain WHERE lot_size IS NOT NULL LIMIT 1")
            row = cur.fetchone()
            if row and row["lot_size"]:
                return int(row["lot_size"])
        except Exception:
            pass
        from shoonya_platform.strategy_runner.config_schema import LOT_SIZES
        return LOT_SIZES.get(self.symbol, 1)

    def get_full_chain(self, expiry: Optional[str] = None) -> List[Dict[str, Any]]:
        self._check_freshness(expiry)   # optional safety
        conn = self._get_connection(expiry)
        if not conn:
            return []
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM option_chain WHERE ltp > 0 ORDER BY strike, option_type")
            return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"get_full_chain error: {e}")
            return []

    def get_option_at_strike(
        self, strike: float, option_type: Union[str, OptionType], expiry: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        self._check_freshness(expiry)
        if isinstance(option_type, OptionType):
            option_type = option_type.value
        conn = self._get_connection(expiry)
        if not conn:
            return None
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM option_chain WHERE strike = ? AND option_type = ?",
                (strike, option_type.upper())
            )
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_option_at_strike error: {e}")
            return None

    def find_option_by_delta(
        self,
        option_type: Union[str, OptionType],
        target_delta: float,
        tolerance: float = 0.05,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._check_freshness(expiry)
        if isinstance(option_type, OptionType):
            option_type = option_type.value
        conn = self._get_connection(expiry)
        if not conn:
            return None
        assert conn is not None
        try:
            cur = conn.cursor()
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
            if row:
                return dict(row)

            # Fallback: if strict tolerance has no hit, choose nearest available
            # non-null delta. This keeps strategy entry/adjustment alive on sparse
            # chains (common in commodities) instead of failing every tick.
            cur.execute(
                """
                SELECT * FROM option_chain
                WHERE option_type = ?
                  AND delta IS NOT NULL
                  AND ltp > 0
                ORDER BY ABS(ABS(delta) - ?) ASC
                LIMIT 1
                """,
                (option_type.upper(), target_delta),
            )
            row = cur.fetchone()
            if row:
                best = dict(row)
                logger.warning(
                    "Delta target %.4f not found within tolerance %.4f for %s; "
                    "using nearest strike=%s delta=%s",
                    target_delta,
                    tolerance,
                    option_type.upper(),
                    best.get("strike"),
                    best.get("delta"),
                )
                return best
            return None
        except Exception as e:
            logger.error(f"find_option_by_delta error: {e}")
            return None

    def find_option_by_premium(
        self,
        option_type: Union[str, OptionType],
        target_premium: float,
        tolerance: float = 10.0,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._check_freshness(expiry)
        if isinstance(option_type, OptionType):
            option_type = option_type.value
        conn = self._get_connection(expiry)
        if not conn:
            return None
        assert conn is not None
        try:
            cur = conn.cursor()
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

    def find_option_by_iv(
        self,
        option_type: Union[str, OptionType],
        target_iv: float,
        tolerance: float = 5.0,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._check_freshness(expiry)
        if isinstance(option_type, OptionType):
            option_type = option_type.value
        conn = self._get_connection(expiry)
        if not conn:
            return None
        assert conn is not None
        try:
            cur = conn.cursor()
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

    def find_option_by_criteria(
        self,
        option_type: Union[str, OptionType],
        target_attr: str,
        target_value: float,
        tolerance: float = 0.01,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find option where an attribute (delta, abs_delta, iv, etc.) is closest to target.
        Uses a mapping to convert attribute name to SQL expression.
        """
        self._check_freshness(expiry)
        if isinstance(option_type, OptionType):
            option_type = option_type.value

        if target_attr not in MATCH_PARAM_TO_SQL:
            raise ValueError(f"Unsupported attribute for match: {target_attr}")

        sql_expr = MATCH_PARAM_TO_SQL[target_attr]
        conn = self._get_connection(expiry)
        if not conn:
            return None
        assert conn is not None
        try:
            cur = conn.cursor()
            # Safe because sql_expr comes from our controlled mapping
            query = f"""
                SELECT * FROM option_chain
                WHERE option_type = ?
                  AND ltp > 0
                  AND ABS({sql_expr} - ?) <= ?
                ORDER BY ABS({sql_expr} - ?) ASC
                LIMIT 1
            """
            cur.execute(query, (option_type.upper(), target_value, tolerance, target_value))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"find_option_by_criteria error: {e}")
            return None

    def get_atm_options(
        self, expiry: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        atm = self.get_atm_strike(expiry)
        if atm <= 0:
            return None, None
        ce = self.get_option_at_strike(atm, "CE", expiry)
        pe = self.get_option_at_strike(atm, "PE", expiry)
        return ce, pe

    # ----------------------------------------------------------------------
    # High-level strike resolution (used by EntryEngine / AdjustmentEngine)
    # ----------------------------------------------------------------------
    def resolve_strike(
        self,
        config: StrikeConfig,
        symbol: str,  # kept for interface compatibility
        expiry: Optional[str] = None,
        reference_leg_state=None,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Resolve strike and option data from StrikeConfig.
        Raises RuntimeError if snapshot too old or data not found.
        """
        # Freshness check
        self._check_freshness(expiry)

        mode = config.mode
        opt_type = config.option_type
        # Read ATM strike once for efficiency
        atm = self.get_atm_strike(expiry)

        opt_data: Optional[Dict[str, Any]] = None
        strike: float = 0.0  # will be assigned in each branch

        if mode == StrikeMode.STANDARD:
            sel = config.strike_selection
            if sel is None:
                raise ValueError("Standard strike mode requires 'strike_selection'")

            val = config.strike_value

            # Handle atm±n with arbitrary offset
            if sel == "atm":
                strike = atm
            elif sel.startswith("atm+") or sel.startswith("atm-"):
                match = re.match(r"atm([+-]\d+)", sel)
                if match:
                    offset = int(match.group(1))
                    step = self._get_strike_step(expiry)
                    strike = atm + offset * step
                else:
                    raise ValueError(f"Malformed atm offset: {sel}")
            elif sel == "delta":
                target = float(val) if val else 0.3
                opt_data = self.find_option_by_delta(opt_type, target, expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for delta={target}")
                strike = opt_data["strike"]
            elif sel == "theta":
                target = float(val) if val else 0.0
                opt_data = self.find_option_by_criteria(opt_type, "theta", target, tolerance=5.0, expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for theta={target}")
                strike = opt_data["strike"]
            elif sel == "vega":
                target = float(val) if val else 0.0
                opt_data = self.find_option_by_criteria(opt_type, "vega", target, tolerance=5.0, expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for vega={target}")
                strike = opt_data["strike"]
            elif sel == "gamma":
                target = float(val) if val else 0.0
                opt_data = self.find_option_by_criteria(opt_type, "gamma", target, tolerance=5.0, expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for gamma={target}")
                strike = opt_data["strike"]
            elif sel == "premium":
                target = float(val) if val else 50
                opt_data = self.find_option_by_premium(opt_type, target, expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for premium={target}")
                strike = opt_data["strike"]
            elif sel == "oi":
                target = float(val) if val else 0.0
                opt_data = self.find_option_by_criteria(opt_type, "oi", target, tolerance=max(1000.0, target * 0.25), expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for oi={target}")
                strike = opt_data["strike"]
            elif sel == "volume":
                target = float(val) if val else 0.0
                opt_data = self.find_option_by_criteria(opt_type, "volume", target, tolerance=max(1000.0, target * 0.25), expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for volume={target}")
                strike = opt_data["strike"]
            elif sel == "iv":
                target = float(val) if val else 15.0
                opt_data = self.find_option_by_iv(opt_type, target, expiry=expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for IV={target}")
                strike = opt_data["strike"]
            elif sel == "otm_pct":
                target_pct = float(val) if val else 0.5
                if opt_type == OptionType.CE:
                    strike = atm * (1 + target_pct / 100.0)
                else:
                    strike = atm * (1 - target_pct / 100.0)
                step = self._get_strike_step(expiry)
                strike = round(strike / step) * step
            elif sel == "exact_strike":
                if val is None or str(val).strip() == "":
                    raise ValueError("exact_strike selection requires strike_value")
                strike = float(val)
            elif sel == "atm_points":
                points = float(val) if val else 0.0
                strike = atm + points
                step = self._get_strike_step(expiry)
                strike = round(strike / step) * step
            elif sel == "atm_pct":
                pct = float(val) if val else 0.0
                strike = atm * (1 + pct / 100.0)
                step = self._get_strike_step(expiry)
                strike = round(strike / step) * step
            elif sel in ("max_pain", "pcr_inflection"):
                strike = self.get_max_pain_strike(expiry) if sel == "max_pain" else self.get_pcr_inflection_strike(expiry)
                if strike <= 0:
                    strike = atm
            else:
                raise ValueError(f"Unsupported standard selection: {sel}")

            if sel not in ["delta", "theta", "vega", "gamma", "premium", "oi", "volume", "iv"]:
                # For simple strike selections, get option data now
                opt_data = self.get_option_at_strike(strike, opt_type, expiry)
                if opt_data is None:
                    raise ValueError(f"No option data at strike {strike}")

        elif mode == StrikeMode.EXACT:
            exact = config.exact_strike
            if exact is None:
                raise ValueError("Exact strike mode requires 'exact_strike'")
            strike = exact
            if config.rounding:
                strike = round(strike / config.rounding) * config.rounding
            opt_data = self.get_option_at_strike(strike, opt_type, expiry)
            if opt_data is None:
                raise ValueError(f"No option data at exact strike {strike}")

        elif mode == StrikeMode.ATM_POINTS:
            offset = config.atm_offset_points or 0
            strike = atm + offset
            if config.rounding:
                strike = round(strike / config.rounding) * config.rounding
            opt_data = self.get_option_at_strike(strike, opt_type, expiry)
            if opt_data is None:
                raise ValueError(f"No option data at ATM+{offset} (strike {strike})")

        elif mode == StrikeMode.ATM_PCT:
            pct = config.atm_offset_pct or 0
            strike = atm * (1 + pct / 100)
            if config.rounding:
                strike = round(strike / config.rounding) * config.rounding
            opt_data = self.get_option_at_strike(strike, opt_type, expiry)
            if opt_data is None:
                raise ValueError(f"No option data at ATM+{pct}% (strike {strike})")

        elif mode == StrikeMode.MATCH_LEG:
            if reference_leg_state is None:
                raise ValueError("Match leg mode requires a reference leg state")
            match_param = config.match_param
            if match_param is None:
                raise ValueError("Match leg mode requires 'match_param'")
            if match_param == "moneyness":
                if reference_leg_state.strike is None:
                    raise ValueError("Reference leg has no strike for moneyness matching")
                offset = reference_leg_state.strike - atm
                strike = atm + offset
                step = self._get_strike_step(expiry)
                strike = round(strike / step) * step
                opt_data = self.get_option_at_strike(strike, opt_type, expiry)
                if opt_data is None:
                    raise ValueError(f"No option found for moneyness-preserved strike {strike}")
                assert opt_data is not None
                return strike, opt_data
            if not hasattr(reference_leg_state, match_param):
                raise ValueError(
                    f"Reference leg has no attribute '{match_param}'. "
                    f"Available: delta, abs_delta, iv, theta, abs_theta, vega, gamma, pnl, pnl_pct, ltp, strike"
                )
            attr_value = getattr(reference_leg_state, match_param)
            target = attr_value * config.match_multiplier + config.match_offset
            opt_data = self.find_option_by_criteria(
                opt_type,
                match_param,
                target,
                tolerance=0.1,
                expiry=expiry
            )
            if opt_data is None:
                raise ValueError(f"No option found matching {match_param}={target}")
            strike = opt_data["strike"]

        else:
            raise ValueError(f"Unknown strike mode: {mode}")

        # At this point, strike must be a numeric value and opt_data must be set.
        assert isinstance(strike, (int, float)), "Strike must be numeric"
        assert opt_data is not None, "Internal error: opt_data not assigned"
        return strike, opt_data

    def get_max_pain_strike(self, expiry: Optional[str] = None) -> float:
        """
        Compute max-pain strike (minimum aggregate option writer payout at expiry).
        """
        self._check_freshness(expiry)
        conn = self._get_connection(expiry)
        if not conn:
            return 0.0
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT strike, option_type, oi
                FROM option_chain
                WHERE strike IS NOT NULL AND option_type IN ('CE','PE')
                """
            )
            rows = cur.fetchall()
            if not rows:
                return 0.0

            strikes: List[float] = sorted({float(r["strike"]) for r in rows if r["strike"] is not None})
            ce_oi: Dict[float, float] = {}
            pe_oi: Dict[float, float] = {}
            for r in rows:
                k = float(r["strike"])
                oi = float(r["oi"] or 0.0)
                if r["option_type"] == "CE":
                    ce_oi[k] = ce_oi.get(k, 0.0) + oi
                else:
                    pe_oi[k] = pe_oi.get(k, 0.0) + oi

            best_strike = 0.0
            best_pain = float("inf")
            for s in strikes:
                pain = 0.0
                for k, oi in ce_oi.items():
                    pain += max(0.0, s - k) * oi
                for k, oi in pe_oi.items():
                    pain += max(0.0, k - s) * oi
                if pain < best_pain:
                    best_pain = pain
                    best_strike = s
            return best_strike
        except Exception as e:
            logger.error(f"get_max_pain_strike error: {e}")
            return 0.0

    def get_pcr_inflection_strike(self, expiry: Optional[str] = None) -> float:
        """
        Find strike where PCR (PE_OI / CE_OI) is closest to 1, preferring near-ATM.
        """
        self._check_freshness(expiry)
        conn = self._get_connection(expiry)
        if not conn:
            return 0.0
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT strike,
                       SUM(CASE WHEN option_type='CE' THEN COALESCE(oi,0) ELSE 0 END) AS ce_oi,
                       SUM(CASE WHEN option_type='PE' THEN COALESCE(oi,0) ELSE 0 END) AS pe_oi
                FROM option_chain
                WHERE strike IS NOT NULL
                GROUP BY strike
                """
            )
            rows = cur.fetchall()
            if not rows:
                return 0.0
            atm = self.get_atm_strike(expiry)
            best_strike = 0.0
            best_score = float("inf")
            for r in rows:
                strike = float(r["strike"])
                ce_oi = float(r["ce_oi"] or 0.0)
                pe_oi = float(r["pe_oi"] or 0.0)
                if ce_oi <= 0:
                    continue
                pcr = pe_oi / ce_oi
                score = abs(pcr - 1.0) + (abs(strike - atm) / max(1.0, atm))
                if score < best_score:
                    best_score = score
                    best_strike = strike
            if best_strike > 0:
                return best_strike
            return atm
        except Exception as e:
            logger.error(f"get_pcr_inflection_strike error: {e}")
            return 0.0

    def resolve_expiry_mode(self, mode: str) -> str:
        """
        Convert an expiry mode string (e.g., 'weekly_current', 'weekly_next')
        into an actual expiry date string (format DD-MMM-YYYY) by scanning
        the available DB files.

        Raises ValueError if mode cannot be resolved.
        """
        # If it's already a date-like string (contains digits and hyphens), assume it's a date.
        if re.match(r'\d{1,2}-[A-Za-z]{3}-\d{4}', mode):
            return mode

        # Determine target based on mode
        today = date.today()
        pattern = f"{self.exchange}_{self.symbol}_*.sqlite"
        folder = DB_FOLDER
        if not folder.exists():
            raise ValueError(f"DB folder not found: {folder}")

        matches = list(folder.glob(pattern))
        if not matches:
            raise ValueError(f"No database files for {self.exchange}_{self.symbol}")

        # Parse expiry dates from filenames
        expiries = []
        for f in matches:
            name = f.stem
            parts = name.split("_", 2)
            if len(parts) < 3:
                continue
            date_str = parts[2]
            try:
                exp_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                expiries.append((exp_date, date_str))
            except ValueError:
                continue

        if not expiries:
            raise ValueError("No valid expiry dates found in filenames")

        expiries.sort(key=lambda x: x[0])  # sort by date

        if mode == "weekly_current" or mode == "monthly_current":
            # Find the nearest future expiry (>= today)
            future = [d for d in expiries if d[0] >= today]
            if future:
                return future[0][1]
            # If none future, return the latest (last of the year)
            return expiries[-1][1]

        elif mode == "weekly_auto":
            # Rule:
            # - if nearest expiry day is today -> use next expiry
            # - otherwise -> use nearest expiry
            current = self.resolve_expiry_mode("weekly_current")
            cur_date = datetime.strptime(current, "%d-%b-%Y").date()
            if cur_date != today:
                return current
            for exp_date, exp_str in expiries:
                if exp_date > cur_date:
                    return exp_str
            # Wrap if only one expiry exists
            return expiries[0][1]

        elif mode == "weekly_next":
            # Find the first expiry after the current weekly (which we take as the first future expiry)
            current = self.resolve_expiry_mode("weekly_current")  # recursive but safe
            cur_date = datetime.strptime(current, "%d-%b-%Y").date()
            for exp_date, exp_str in expiries:
                if exp_date > cur_date:
                    return exp_str
            # Wrap to first of next year? Or raise? We'll return first.
            return expiries[0][1]

        elif mode == "monthly_next":
            current = self.resolve_expiry_mode("monthly_current")
            cur_date = datetime.strptime(current, "%d-%b-%Y").date()
            for exp_date, exp_str in expiries:
                if exp_date > cur_date:
                    return exp_str
            return expiries[0][1]

        else:
            raise ValueError(f"Unsupported expiry mode: {mode}")

    def get_next_expiry(self, current_expiry: str, mode: str = "weekly_next") -> str:
        """
        Given a current expiry string (format DD-MMM-YYYY) and a mode
        ('weekly_next', 'monthly_next', 'weekly_current', 'monthly_current'),
        return the next available expiry date string from the DB folder.
        """
        # If mode is *_current, return current_expiry (assumed to be a valid date)
        if mode in ("weekly_current", "monthly_current"):
            return current_expiry

        # For next modes, find the next expiry after current_expiry
        pattern = f"{self.exchange}_{self.symbol}_*.sqlite"
        folder = DB_FOLDER
        if not folder.exists():
            raise RuntimeError(f"DB folder not found: {folder}")

        matches = list(folder.glob(pattern))
        if not matches:
            raise RuntimeError(f"No database files for {self.exchange}_{self.symbol}")

        # Parse expiry dates from filenames
        expiries = []
        for f in matches:
            name = f.stem
            parts = name.split("_", 2)
            if len(parts) < 3:
                continue
            date_str = parts[2]
            try:
                exp_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                expiries.append((exp_date, date_str))
            except ValueError:
                continue

        if not expiries:
            raise RuntimeError("No valid expiry dates found in filenames")

        expiries.sort(key=lambda x: x[0])  # sort by date

        # Parse current_expiry
        try:
            cur_date = datetime.strptime(current_expiry, "%d-%b-%Y").date()
        except ValueError:
            # Fallback: return the first future expiry
            today = datetime.now().date()
            future = [d for d in expiries if d[0] >= today]
            if future:
                return future[0][1]
            return expiries[-1][1]

        # Find the next expiry after cur_date
        for exp_date, exp_str in expiries:
            if exp_date > cur_date:
                return exp_str

        # If none after, wrap to the first (next year)
        return expiries[0][1]


# ==============================================================================
# The following mock class is used in unit tests to simulate the MarketReader
# behavior without needing actual database files. It provides hardcoded responses
# for all methods, with signatures matching the base class exactly.
# ==============================================================================

class MockMarketReader(MarketReader):
    """Simple mock for testing."""

    def __init__(self, exchange: str = "NFO", symbol: str = "NIFTY"):
        super().__init__(exchange, symbol)
        self._spot = 25000.0
        self._atm = 25000.0
        self._fut = 25050.0
        self._chain_cache = {}

    def get_spot_price(self, expiry: Optional[str] = None) -> float:
        return self._spot

    def get_atm_strike(self, expiry: Optional[str] = None) -> float:
        return self._atm

    def get_fut_ltp(self, expiry: Optional[str] = None) -> float:
        return self._fut

    def get_option_at_strike(
        self, strike: float, option_type: Union[str, OptionType], expiry: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if isinstance(option_type, OptionType):
            opt_type = option_type.value
        else:
            opt_type = option_type
        return {
            "strike": strike,
            "option_type": opt_type.upper(),
            "ltp": 100.0,
            "delta": 0.5 if opt_type.upper() == "CE" else -0.5,
            "gamma": 0.005,
            "theta": -10,
            "vega": 20,
            "iv": 15.0,
            "oi": 10000,
            "volume": 500,
        }

    def find_option_by_delta(
        self,
        option_type: Union[str, OptionType],
        target_delta: float,
        tolerance: float = 0.05,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if isinstance(option_type, OptionType):
            opt_type = option_type.value
        else:
            opt_type = option_type
        # Crude linear approximation
        strike = self._atm - (target_delta * 2000) if opt_type.upper() == "CE" else self._atm + (target_delta * 2000)
        return self.get_option_at_strike(strike, opt_type)

    def find_option_by_premium(
        self,
        option_type: Union[str, OptionType],
        target_premium: float,
        tolerance: float = 10.0,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if isinstance(option_type, OptionType):
            opt_type = option_type.value
        else:
            opt_type = option_type
        strike = self._atm - (target_premium * 5) if opt_type.upper() == "CE" else self._atm + (target_premium * 5)
        return self.get_option_at_strike(strike, opt_type)

    def find_option_by_iv(
        self,
        option_type: Union[str, OptionType],
        target_iv: float,
        tolerance: float = 5.0,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if isinstance(option_type, OptionType):
            opt_type = option_type.value
        else:
            opt_type = option_type
        return self.get_option_at_strike(self._atm, opt_type)

    def find_option_by_criteria(
        self,
        option_type: Union[str, OptionType],
        target_attr: str,
        target_value: float,
        tolerance: float = 0.01,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if isinstance(option_type, OptionType):
            opt_type = option_type.value
        else:
            opt_type = option_type
        return self.get_option_at_strike(self._atm, opt_type)

    def resolve_strike(
        self,
        config: StrikeConfig,
        symbol: str,
        expiry: Optional[str] = None,
        reference_leg_state=None,
    ) -> Tuple[float, Dict[str, Any]]:
        if config.mode == StrikeMode.STANDARD:
            sel = (config.strike_selection or "atm").lower()
            if sel == "atm":
                strike = self._atm
            elif sel.startswith("atm+") or sel.startswith("atm-"):
                m = re.match(r"atm([+-]\d+)", sel)
                step = float(config.rounding or 50)
                off = int(m.group(1)) if m else 0
                strike = self._atm + (off * step)
            else:
                strike = self._atm
        elif config.mode == StrikeMode.EXACT:
            strike = float(config.exact_strike if config.exact_strike is not None else self._atm)
            if config.rounding:
                strike = round(strike / config.rounding) * config.rounding
        elif config.mode == StrikeMode.ATM_POINTS:
            strike = self._atm + float(config.atm_offset_points or 0)
            if config.rounding:
                strike = round(strike / config.rounding) * config.rounding
        elif config.mode == StrikeMode.ATM_PCT:
            strike = self._atm * (1 + float(config.atm_offset_pct or 0.0) / 100.0)
            if config.rounding:
                strike = round(strike / config.rounding) * config.rounding
        else:
            strike = self._atm
        opt_data = self.get_option_at_strike(strike, config.option_type)
        assert opt_data is not None
        return strike, opt_data
