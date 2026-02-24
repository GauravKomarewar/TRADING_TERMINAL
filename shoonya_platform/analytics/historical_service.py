#!/usr/bin/env python3
"""Background historical analytics ingestor (PostgreSQL layer)."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shoonya_platform.analytics.historical_store import PostgresHistoricalStore
from shoonya_platform.market_data.feeds import index_tokens_subscriber

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OPTION_DATA_DIR = _PROJECT_ROOT / "shoonya_platform" / "market_data" / "option_chain" / "data"
_DB_NAME_RE = re.compile(r"^([A-Z]+)_([A-Z0-9]+)_(\d{2}-[A-Za-z]{3}-\d{4})\.sqlite$")


class HistoricalAnalyticsService:
    def __init__(self, bot: Any):
        self.bot = bot
        self.enabled = str(os.getenv("HISTORICAL_PG_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self.dsn = str(os.getenv("HISTORICAL_PG_DSN", "")).strip()
        self.sampling_sec = max(1, int(os.getenv("HISTORICAL_SAMPLING_SEC", "3") or 3))
        self.option_sampling_sec = max(2, int(os.getenv("HISTORICAL_OPTION_SAMPLING_SEC", "10") or 10))

        self.store: Optional[PostgresHistoricalStore] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._last_strategy_state: Dict[str, Dict[str, Any]] = {}
        self._last_option_totals: Dict[Tuple[str, str, str], Dict[str, float]] = {}

        if not self.enabled:
            logger.info("Historical analytics disabled (HISTORICAL_PG_ENABLED != 1)")
            return
        if not self.dsn:
            logger.warning("Historical analytics enabled but HISTORICAL_PG_DSN missing; disabling")
            self.enabled = False
            return

        try:
            self.store = PostgresHistoricalStore(self.dsn)
            logger.info("Historical analytics PostgreSQL store initialized")
        except Exception as e:
            logger.error("Historical analytics store init failed: %s", e)
            self.enabled = False

    def start(self) -> None:
        if not self.enabled or self.store is None or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="HistoricalAnalyticsService", daemon=True)
        self._thread.start()
        logger.info("Historical analytics service started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Historical analytics service stopped")

    def health(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "ok": False, "reason": "disabled"}
        if self.store is None:
            return {"enabled": True, "ok": False, "reason": "store_unavailable"}
        h = self.store.health()
        h["enabled"] = True
        return h

    def _run_loop(self) -> None:
        next_option_at = 0.0
        while not self._stop_event.is_set():
            started = time.time()
            try:
                self._collect_strategy_and_index()
                if started >= next_option_at:
                    self._collect_option_chain_metrics()
                    next_option_at = started + self.option_sampling_sec
            except Exception:
                logger.exception("Historical analytics loop error")

            elapsed = time.time() - started
            sleep_for = max(0.2, self.sampling_sec - elapsed)
            self._stop_event.wait(sleep_for)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _collect_strategy_and_index(self) -> None:
        if self.store is None:
            return

        ts = self._utcnow()
        rows: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []

        svc = getattr(self.bot, "strategy_executor_service", None)
        if svc is not None:
            cfgs = dict(getattr(svc, "_strategies", {}) or {})
            states = dict(getattr(svc, "_exec_states", {}) or {})

            for name, cfg in cfgs.items():
                state = states.get(name)
                identity = (cfg or {}).get("identity", {}) or {}
                underlying = str(identity.get("underlying", "") or "").upper()
                mode = "LIVE"
                try:
                    mode_getter = getattr(svc, "get_strategy_mode", None)
                    if callable(mode_getter):
                        mode = str(mode_getter(name) or "LIVE").upper()
                except Exception:
                    pass

                is_active = bool(getattr(state, "any_leg_active", False)) if state else False
                lifetime_adj = int(getattr(state, "lifetime_adjustments", 0) or 0) if state else 0
                total_pnl = float(getattr(state, "combined_pnl", 0.0) or 0.0) if state else 0.0
                realized = float(getattr(state, "realised_pnl", 0.0) or 0.0) if state else 0.0
                unrealized = float(getattr(state, "unrealised_pnl", 0.0) or 0.0) if state else 0.0
                runtime_seconds = 0
                entry_time = getattr(state, "entry_time", None) if state else None
                if isinstance(entry_time, datetime):
                    runtime_seconds = max(0, int((ts - entry_time.astimezone(timezone.utc)).total_seconds()))

                spot = 0.0
                if underlying:
                    try:
                        idx = index_tokens_subscriber.get_index_price(underlying)
                        if isinstance(idx, dict):
                            spot = float(idx.get("ltp", 0) or 0)
                    except Exception:
                        pass
                if (not spot) and state is not None:
                    spot = float(getattr(state, "spot_price", 0.0) or 0.0)

                rows.append(
                    {
                        "ts": ts,
                        "strategy_name": name,
                        "underlying": underlying,
                        "mode": mode,
                        "is_active": is_active,
                        "spot_price": spot,
                        "total_pnl": total_pnl,
                        "realized_pnl": realized,
                        "unrealized_pnl": unrealized,
                        "combined_delta": float(getattr(state, "net_delta", 0.0) or 0.0) if state else 0.0,
                        "combined_gamma": float(getattr(state, "portfolio_gamma", 0.0) or 0.0) if state else 0.0,
                        "combined_theta": float(getattr(state, "portfolio_theta", 0.0) or 0.0) if state else 0.0,
                        "combined_vega": float(getattr(state, "portfolio_vega", 0.0) or 0.0) if state else 0.0,
                        "adjustments_today": int(getattr(state, "adjustments_today", 0) or 0) if state else 0,
                        "lifetime_adjustments": lifetime_adj,
                        "runtime_seconds": runtime_seconds,
                    }
                )

                prev = self._last_strategy_state.get(name)
                if prev is None:
                    if is_active:
                        events.append({"ts": ts, "strategy_name": name, "event_type": "ENTRY", "details": {"source": "bootstrap"}})
                else:
                    if (not prev.get("is_active")) and is_active:
                        events.append({"ts": ts, "strategy_name": name, "event_type": "ENTRY", "details": {"source": "state_transition"}})
                    if prev.get("is_active") and (not is_active):
                        events.append({"ts": ts, "strategy_name": name, "event_type": "EXIT", "details": {"source": "state_transition"}})
                    prev_adj = int(prev.get("lifetime_adjustments", 0) or 0)
                    if lifetime_adj > prev_adj:
                        events.append(
                            {
                                "ts": ts,
                                "strategy_name": name,
                                "event_type": "ADJUSTMENT",
                                "details": {"count_delta": int(lifetime_adj - prev_adj)},
                            }
                        )

                self._last_strategy_state[name] = {"is_active": is_active, "lifetime_adjustments": lifetime_adj}

        if rows:
            self.store.insert_strategy_samples(rows)
        if events:
            self.store.insert_strategy_events(events)

        idx_rows = self._collect_index_ticks(ts)
        if idx_rows:
            self.store.insert_index_ticks(idx_rows)

    def _collect_index_ticks(self, ts: datetime) -> List[Dict[str, Any]]:
        symbols = set(index_tokens_subscriber.get_subscribed_indices() or [])
        symbols.update(getattr(index_tokens_subscriber, "TICKER_SYMBOLS", []) or [])
        if not symbols:
            return []
        try:
            prices = index_tokens_subscriber.get_index_prices(indices=sorted(symbols), include_missing=False) or {}
        except Exception:
            logger.exception("Failed reading index prices for historical store")
            return []

        rows: List[Dict[str, Any]] = []
        for sym, payload in prices.items():
            if not isinstance(payload, dict):
                continue
            rows.append(
                {
                    "ts": ts,
                    "symbol": str(sym).upper(),
                    "ltp": float(payload.get("ltp", 0) or 0),
                    "pc": float(payload.get("pc", 0) or 0),
                    "open": float(payload.get("o", 0) or 0),
                    "high": float(payload.get("h", 0) or 0),
                    "low": float(payload.get("l", 0) or 0),
                    "close": float(payload.get("c", 0) or 0),
                    "volume": float(payload.get("v", 0) or 0),
                    "oi": float(payload.get("oi", 0) or 0),
                }
            )
        return rows

    def _collect_option_chain_metrics(self) -> None:
        if self.store is None:
            return
        ts = self._utcnow()
        rows: List[Dict[str, Any]] = []

        if not _OPTION_DATA_DIR.exists():
            return

        for db_path in _OPTION_DATA_DIR.glob("*.sqlite"):
            m = _DB_NAME_RE.match(db_path.name)
            if not m:
                continue
            exchange, symbol, expiry = m.groups()
            metrics = self._extract_metrics_from_db(exchange, symbol, expiry, db_path)
            if not metrics:
                continue
            metrics["ts"] = ts
            rows.append(metrics)

        if rows:
            self.store.insert_option_chain_metrics(rows)

    def _extract_metrics_from_db(
        self,
        exchange: str,
        symbol: str,
        expiry: str,
        db_path: Path,
    ) -> Optional[Dict[str, Any]]:
        try:
            conn = sqlite3.connect(db_path, timeout=2, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            meta_rows = cur.execute("SELECT key, value FROM meta").fetchall()
            meta = {str(r["key"]): str(r["value"]) for r in meta_rows}
            snapshot_ts = float(meta.get("snapshot_ts", 0) or 0)
            snapshot_age = max(0.0, time.time() - snapshot_ts) if snapshot_ts else 0.0

            agg = cur.execute(
                """
                SELECT
                    SUM(CASE WHEN option_type='CE' THEN COALESCE(oi,0) ELSE 0 END) AS ce_oi,
                    SUM(CASE WHEN option_type='PE' THEN COALESCE(oi,0) ELSE 0 END) AS pe_oi,
                    SUM(CASE WHEN option_type='CE' THEN COALESCE(volume,0) ELSE 0 END) AS ce_vol,
                    SUM(CASE WHEN option_type='PE' THEN COALESCE(volume,0) ELSE 0 END) AS pe_vol
                FROM option_chain
                """
            ).fetchone()

            strike_rows = cur.execute(
                """
                SELECT strike,
                       SUM(CASE WHEN option_type='CE' THEN COALESCE(oi,0) ELSE 0 END) AS ce_oi,
                       SUM(CASE WHEN option_type='PE' THEN COALESCE(oi,0) ELSE 0 END) AS pe_oi,
                       SUM(CASE WHEN option_type='CE' THEN COALESCE(ltp,0) ELSE 0 END) AS ce_ltp,
                       SUM(CASE WHEN option_type='PE' THEN COALESCE(ltp,0) ELSE 0 END) AS pe_ltp
                FROM option_chain
                GROUP BY strike
                ORDER BY strike ASC
                """
            ).fetchall()
            conn.close()

            total_ce_oi = float((agg["ce_oi"] if agg else 0) or 0)
            total_pe_oi = float((agg["pe_oi"] if agg else 0) or 0)
            total_ce_vol = float((agg["ce_vol"] if agg else 0) or 0)
            total_pe_vol = float((agg["pe_vol"] if agg else 0) or 0)

            pcr_oi = (total_pe_oi / total_ce_oi) if total_ce_oi > 0 else 0.0
            pcr_volume = (total_pe_vol / total_ce_vol) if total_ce_vol > 0 else 0.0

            atm_strike = float(meta.get("atm_strike", 0) or 0)
            spot_price = float(meta.get("spot_price", 0) or 0)

            max_pain_strike = 0.0
            atm_straddle = 0.0
            if strike_rows:
                strikes = [float(r["strike"] or 0) for r in strike_rows]
                # Max pain (simple total payoff minimization)
                best_pain = float("inf")
                for k in strikes:
                    pain = 0.0
                    for r in strike_rows:
                        s = float(r["strike"] or 0)
                        ce_oi = float(r["ce_oi"] or 0)
                        pe_oi = float(r["pe_oi"] or 0)
                        pain += max(0.0, s - k) * ce_oi
                        pain += max(0.0, k - s) * pe_oi
                    if pain < best_pain:
                        best_pain = pain
                        max_pain_strike = k

                if atm_strike:
                    nearest = min(strike_rows, key=lambda r: abs(float(r["strike"] or 0) - atm_strike))
                else:
                    nearest = strike_rows[len(strike_rows) // 2]
                atm_straddle = float(nearest["ce_ltp"] or 0) + float(nearest["pe_ltp"] or 0)

            key = (exchange, symbol, expiry)
            prev = self._last_option_totals.get(key, {})
            prev_ce_oi = float(prev.get("ce_oi", total_ce_oi) or total_ce_oi)
            prev_pe_oi = float(prev.get("pe_oi", total_pe_oi) or total_pe_oi)
            oi_buildup_ce = ((total_ce_oi - prev_ce_oi) / prev_ce_oi * 100.0) if prev_ce_oi > 0 else 0.0
            oi_buildup_pe = ((total_pe_oi - prev_pe_oi) / prev_pe_oi * 100.0) if prev_pe_oi > 0 else 0.0

            self._last_option_totals[key] = {"ce_oi": total_ce_oi, "pe_oi": total_pe_oi}

            return {
                "exchange": exchange,
                "symbol": symbol,
                "expiry": expiry,
                "spot_price": spot_price,
                "atm_strike": atm_strike,
                "max_pain_strike": max_pain_strike,
                "atm_straddle": atm_straddle,
                "pcr_oi": pcr_oi,
                "pcr_volume": pcr_volume,
                "total_oi_ce": total_ce_oi,
                "total_oi_pe": total_pe_oi,
                "total_vol_ce": total_ce_vol,
                "total_vol_pe": total_pe_vol,
                "oi_buildup_ce": oi_buildup_ce,
                "oi_buildup_pe": oi_buildup_pe,
                "snapshot_age": snapshot_age,
                "is_stale": bool(snapshot_age > 300),
            }
        except Exception:
            logger.debug("Failed extracting option metrics from %s", db_path, exc_info=True)
            return None
