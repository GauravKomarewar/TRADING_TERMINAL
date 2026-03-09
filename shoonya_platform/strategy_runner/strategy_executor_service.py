#!/usr/bin/env python3
"""
strategy_executor_service.py — Drop‑in replacement using Universal Engine
==========================================================================
Implements the same interface as the old service, but uses the new engine.
"""

import json
import logging
import sqlite3
import threading
import time
import copy
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .models import (
    InstrumentType, OptionType, Side, OrderType, StrikeMode, StrikeConfig
)
from .state import StrategyState, LegState
from .condition_engine import ConditionEngine
from .market_reader import MarketReader
from .entry_engine import EntryEngine
from .adjustment_engine import AdjustmentEngine
from .exit_engine import ExitEngine
from .reconciliation import BrokerReconciliation
from .persistence import StatePersistence
from scripts.scriptmaster import requires_limit_order

logger = logging.getLogger("STRATEGY_EXECUTOR_SERVICE")

_DB_FILE_EXPIRY_RE = re.compile(
    r"^[A-Za-z0-9]+_[A-Za-z0-9]+_(\d{2}-[A-Za-z]{3}-\d{4})\.sqlite$"
)


@dataclass
class ExecutionState:
    """
    execution snapshot used by dashboard/runtime recovery paths.
    """
    strategy_name: str
    run_id: str
    has_position: bool = False
    entry_timestamp: float = 0.0

    ce_symbol: Optional[str] = None
    ce_side: Optional[str] = None
    ce_qty: int = 0
    ce_entry_price: float = 0.0
    ce_strike: float = 0.0
    ce_delta: float = 0.0

    pe_symbol: Optional[str] = None
    pe_side: Optional[str] = None
    pe_qty: int = 0
    pe_entry_price: float = 0.0
    pe_strike: float = 0.0
    pe_delta: float = 0.0

    updated_at: float = 0.0


class StateManager:
    """
    Minimal SQLite-backed state store for strategy lifecycle state.
    """

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_states (
                    strategy_name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_leg_rows (
                    strategy_name TEXT NOT NULL,
                    leg_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (strategy_name, leg_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_monitor_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    archived_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_completed_monitor_history_archived_at
                ON completed_monitor_history(archived_at DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, state: ExecutionState):
        state.updated_at = time.time()
        payload = json.dumps(asdict(state), default=str)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO execution_states(strategy_name, payload, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(strategy_name) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (state.strategy_name, payload, state.updated_at),
            )
            conn.commit()
        finally:
            conn.close()

    def load(self, strategy_name: str) -> Optional[ExecutionState]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM execution_states WHERE strategy_name = ?",
                (strategy_name,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["payload"])
            return ExecutionState(**data)
        finally:
            conn.close()

    def delete(self, strategy_name: str):
        conn = self._connect()
        try:
            conn.execute("DELETE FROM execution_states WHERE strategy_name = ?", (strategy_name,))
            conn.commit()
        finally:
            conn.close()

    def list_all(self) -> List[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT strategy_name FROM execution_states ORDER BY strategy_name"
            ).fetchall()
            return [r["strategy_name"] for r in rows]
        finally:
            conn.close()

    def load_monitor_snapshot(self, strategy_name: str) -> Dict[str, Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT leg_key, payload
                FROM monitor_leg_rows
                WHERE strategy_name = ?
                ORDER BY updated_at DESC
                """,
                (strategy_name,),
            ).fetchall()
            out: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                try:
                    out[str(row["leg_key"])] = json.loads(row["payload"])
                except Exception:
                    continue
            return out
        finally:
            conn.close()

    def save_monitor_snapshot(self, strategy_name: str, cache: Dict[str, Dict[str, Any]]) -> None:
        conn = self._connect()
        try:
            keys = list(cache.keys())
            conn.execute("BEGIN")
            if not keys:
                conn.execute(
                    "DELETE FROM monitor_leg_rows WHERE strategy_name = ?",
                    (strategy_name,),
                )
            else:
                placeholders = ",".join("?" for _ in keys)
                conn.execute(
                    f"""
                    DELETE FROM monitor_leg_rows
                    WHERE strategy_name = ?
                      AND leg_key NOT IN ({placeholders})
                    """,
                    [strategy_name, *keys],
                )
                for leg_key, row in cache.items():
                    updated_at = time.time()
                    try:
                        raw_updated = row.get("updated_at")
                        if raw_updated:
                            updated_at = datetime.fromisoformat(str(raw_updated)).timestamp()
                    except Exception:
                        pass
                    conn.execute(
                        """
                        INSERT INTO monitor_leg_rows(strategy_name, leg_key, payload, updated_at)
                        VALUES(?, ?, ?, ?)
                        ON CONFLICT(strategy_name, leg_key) DO UPDATE SET
                            payload=excluded.payload,
                            updated_at=excluded.updated_at
                        """,
                        (
                            strategy_name,
                            str(leg_key),
                            json.dumps(row, default=str),
                            float(updated_at),
                        ),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_monitor_snapshot(self, strategy_name: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM monitor_leg_rows WHERE strategy_name = ?",
                (strategy_name,),
            )
            conn.commit()
        finally:
            conn.close()

    def append_completed_monitor_history(self, history_row: Dict[str, Any], max_rows: int = 100) -> None:
        conn = self._connect()
        try:
            archived_at = time.time()
            try:
                raw_archived = history_row.get("archived_at")
                if raw_archived:
                    archived_at = datetime.fromisoformat(str(raw_archived)).timestamp()
            except Exception:
                pass
            conn.execute(
                """
                INSERT INTO completed_monitor_history(strategy_name, payload, archived_at)
                VALUES (?, ?, ?)
                """,
                (
                    str(history_row.get("strategy_name") or ""),
                    json.dumps(history_row, default=str),
                    float(archived_at),
                ),
            )
            if int(max_rows) > 0:
                conn.execute(
                    """
                    DELETE FROM completed_monitor_history
                    WHERE id NOT IN (
                        SELECT id
                        FROM completed_monitor_history
                        ORDER BY archived_at DESC, id DESC
                        LIMIT ?
                    )
                    """,
                    (int(max_rows),),
                )
            conn.commit()
        finally:
            conn.close()

    def get_completed_monitor_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            normalized_limit = max(1, int(limit or 20))
            rows = conn.execute(
                """
                SELECT payload
                FROM completed_monitor_history
                ORDER BY archived_at DESC, id DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    out.append(json.loads(row["payload"]))
                except Exception:
                    continue
            return out
        finally:
            conn.close()

    def delete_completed_monitor_history(self, strategy_name: str = None, archived_at: str = None) -> int:
        """Delete completed monitor history entries. If strategy_name and archived_at given, delete one entry. If only strategy_name, delete all for that strategy. If neither, delete all."""
        conn = self._connect()
        try:
            if strategy_name and archived_at:
                # The archived_at DB column is stored as a Unix timestamp float.
                # The frontend passes back an ISO-string from the payload JSON
                # (e.g. "2026-03-09T15:33:36.123456"). SQLite's type affinity
                # rules mean a REAL column value never equals a TEXT literal,
                # so the WHERE clause matched 0 rows every time.
                # Convert the incoming value to float before comparing.
                archived_at_float: Optional[float] = None
                try:
                    archived_at_float = float(archived_at)  # already a float string
                except (ValueError, TypeError):
                    pass
                if archived_at_float is None:
                    try:
                        archived_at_float = datetime.fromisoformat(str(archived_at)).timestamp()
                    except Exception:
                        pass
                if archived_at_float is not None:
                    cursor = conn.execute(
                        "DELETE FROM completed_monitor_history WHERE strategy_name = ? AND ABS(archived_at - ?) < 1.0",
                        (strategy_name, archived_at_float),
                    )
                else:
                    # Cannot parse archived_at; delete all entries for this strategy
                    cursor = conn.execute(
                        "DELETE FROM completed_monitor_history WHERE strategy_name = ?",
                        (strategy_name,),
                    )
            elif strategy_name:
                cursor = conn.execute(
                    "DELETE FROM completed_monitor_history WHERE strategy_name = ?",
                    (strategy_name,),
                )
            else:
                cursor = conn.execute("DELETE FROM completed_monitor_history")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

class StrategyExecutorService:
    """
    Service that manages multiple strategies using the Universal Engine.
    """

    def __init__(self, bot, state_db_path: str):
        self.bot = bot
        self.state_db_path = state_db_path
        self.state_mgr = StateManager(state_db_path)
        self._strategies: Dict[str, Dict] = {}          # name -> config
        self._executors: Dict[str, 'PerStrategyExecutor'] = {}
        self._exec_states: Dict[str, StrategyState] = {}  # name -> live state
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._mode_change_dict_lock = threading.Lock()
        self._mode_change_lock: Dict[str, threading.Lock] = {}
        self._monitor_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._completed_monitor_history: List[Dict[str, Any]] = []
        self._max_completed_monitor_history = 100
        try:
            self._completed_monitor_history = self.state_mgr.get_completed_monitor_history(
                limit=self._max_completed_monitor_history
            )
        except Exception as e:
            logger.debug("Could not load completed monitor history from DB: %s", e)

    def _ensure_strategy_chain(self, name: str, config: dict):
        """Auto-load the option chain required by a strategy if not already active."""
        sup = getattr(self.bot, "option_supervisor", None)
        if sup is None:
            logger.warning("No option_supervisor on bot — cannot auto-load chain for %s", name)
            return

        identity = config.get("identity", {}) or {}
        exchange = str(identity.get("exchange", "NFO")).strip().upper()
        symbol = str(identity.get("underlying", "")).strip().upper()
        if not symbol:
            return

        # Determine the expiry the strategy needs
        db_file = str(identity.get("db_file") or (config.get("market_data", {}) or {}).get("db_file") or "").strip()
        expiry = None
        if db_file:
            m = _DB_FILE_EXPIRY_RE.match(db_file)
            if m:
                expiry = m.group(1)

        if not expiry:
            # Try resolving from MarketReader's expiry mode (reads existing DB files)
            # If no DB exists yet, fall back to ScriptMaster expiry lookup
            try:
                from scripts.scriptmaster import options_expiry as sm_options_expiry
                expiries = sm_options_expiry(symbol, exchange) or []
                if expiries:
                    expiry = expiries[0]  # nearest expiry
                    logger.info("Strategy %s: resolved expiry %s from ScriptMaster for %s:%s", name, expiry, exchange, symbol)
            except Exception as e:
                logger.warning("Strategy %s: ScriptMaster expiry lookup failed for %s:%s: %s", name, exchange, symbol, e)

        if not expiry:
            logger.warning("Strategy %s: could not determine expiry, skipping auto-load", name)
            return

        key = f"{exchange}:{symbol}:{expiry}"
        # Check if already active
        with sup._lock:
            if key in sup._chains:
                logger.debug("Strategy %s: chain %s already active", name, key)
                return

        logger.info("Strategy %s: auto-loading option chain %s", name, key)
        ok = sup.ensure_chain(exchange=exchange, symbol=symbol, expiry=expiry, source="strategy")
        if ok:
            logger.info("Strategy %s: ✅ chain %s loaded successfully", name, key)
        else:
            logger.error("Strategy %s: ❌ failed to auto-load chain %s", name, key)

    def register_strategy(self, name: str, config_path: str):
        """Register a strategy with the service."""
        with self._lock:
            if name in self._strategies:
                logger.warning(f"Strategy {name} already registered, overwriting")
            # Load config – assume it's valid (validation should be done by caller)
            with open(config_path, 'r') as f:
                config = json.load(f)

            # Auto-load required option chain if not already active
            self._ensure_strategy_chain(name, config)

            self._strategies[name] = config
            # Create per‑strategy executor
            executor = PerStrategyExecutor(
                name=name,
                config=config,
                bot=self.bot,
                state_db_path=self.state_db_path
            )
            self._executors[name] = executor
            self._exec_states[name] = executor.state
            persisted_cache = {}
            try:
                persisted_cache = self.state_mgr.load_monitor_snapshot(name)
            except Exception as e:
                logger.debug("Could not load monitor cache for %s: %s", name, e)
            self._monitor_cache[name] = persisted_cache if isinstance(persisted_cache, dict) else {}
            logger.info(f"Registered strategy: {name}")

    def unregister_strategy(self, name: str):
        """Remove a strategy from the service."""
        with self._lock:
            self._executors.pop(name, None)
            self._strategies.pop(name, None)
            self._exec_states.pop(name, None)
            self._monitor_cache.pop(name, None)
            try:
                self.state_mgr.clear_monitor_snapshot(name)
            except Exception as e:
                logger.debug("Could not clear persisted monitor snapshot for %s: %s", name, e)
            logger.info(f"Strategy unregistered: {name}")

    # ------------------------------------------------------------------
    # CRASH-RECOVERY: AUTO-RESUME STRATEGIES
    # ------------------------------------------------------------------

    def auto_resume_strategies(self) -> List[str]:
        """
        Scan saved_configs/ for strategies that were RUNNING before a
        crash/restart and re-register them so monitoring, adjustments,
        and exits continue from the persisted state.

        A strategy is eligible for auto-resume when ALL of:
          1. Its config JSON has ``"status": "RUNNING"``
          2. A state file exists with at least one active (FILLED) leg
          3. The state was persisted today (not stale from a previous day)

        After re-registration the executor picks up the persisted
        StrategyState (with legs, entered_today, adjustment history, etc.)
        and the normal tick loop resumes exit/adjustment monitoring.

        Returns:
            List of strategy names that were successfully resumed.
        """
        config_dir = (
            Path(__file__).resolve().parent / "saved_configs"
        )
        if not config_dir.exists():
            return []

        state_base = Path(self.state_db_path).parent
        today = datetime.now().date()
        resumed: List[str] = []

        for cfg_path in sorted(config_dir.glob("*.json")):
            if cfg_path.name.endswith(".schema.json"):
                continue
            try:
                config = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            status = str(config.get("status", "")).strip().upper()
            if status != "RUNNING":
                continue

            strategy_key = cfg_path.stem

            # Already running — skip
            if strategy_key in self._strategies:
                continue

            # Check for valid state file with active legs
            state_file = state_base / f"{strategy_key}_state.pkl"
            if not state_file.exists():
                logger.debug("auto_resume: no state file for %s", strategy_key)
                continue

            try:
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("auto_resume: could not read state for %s: %s", strategy_key, e)
                continue

            # Must have at least one active, filled leg
            legs_raw = state_data.get("legs") or {}
            has_active = False
            for leg in legs_raw.values():
                if not isinstance(leg, dict):
                    continue
                if bool(leg.get("is_active")) and str(leg.get("order_status", "")).upper() == "FILLED":
                    has_active = True
                    break

            if not has_active:
                logger.debug("auto_resume: no active legs for %s — skipping", strategy_key)
                continue

            # Staleness check: state must be from today
            entry_time_raw = state_data.get("entry_time")
            if entry_time_raw:
                try:
                    entry_date = datetime.fromisoformat(str(entry_time_raw)).date()
                    if entry_date != today:
                        logger.info(
                            "auto_resume: %s entry_time=%s is not today (%s) — skipping",
                            strategy_key, entry_date, today,
                        )
                        continue
                except (ValueError, TypeError):
                    pass

            # Re-register strategy
            try:
                logger.warning(
                    "♻️ AUTO-RESUME | Recovering strategy '%s' with active legs from state file",
                    strategy_key,
                )
                self.register_strategy(name=strategy_key, config_path=str(cfg_path))
                resumed.append(strategy_key)
            except Exception as e:
                logger.error("auto_resume: failed to register %s: %s", strategy_key, e)

        # Force immediate broker reconciliation for all resumed strategies
        if resumed:
            broker_view = getattr(self.bot, "broker_view", None)
            for name in resumed:
                executor = self._executors.get(name)
                if executor and broker_view and not executor._resolve_test_mode():
                    try:
                        warnings = executor.reconciliation.reconcile_from_broker(broker_view)
                        if warnings:
                            logger.warning(
                                "♻️ AUTO-RESUME RECONCILE [%s]: %d mismatch(es) — %s",
                                name, len(warnings), "; ".join(warnings),
                            )
                        else:
                            logger.info("♻️ AUTO-RESUME RECONCILE [%s]: broker in sync ✅", name)
                        # Persist reconciled state immediately
                        executor.persistence.save(executor.state, str(executor.state_file))
                    except Exception as e:
                        logger.error("♻️ AUTO-RESUME RECONCILE [%s] failed: %s", name, e)

            # Send telegram notification
            telegram = getattr(self.bot, "telegram", None)
            if telegram:
                try:
                    msg = (
                        f"<b>♻️ STRATEGY AUTO-RESUME</b>\n"
                        f"Strategies recovered: {len(resumed)}\n"
                        f"Names: {', '.join(resumed)}\n"
                        f"Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                        f"Monitoring, adjustments, and exits will continue "
                        f"from last persisted state."
                    )
                    telegram.send_message(msg, parse_mode="HTML")
                except Exception:
                    pass

            logger.warning(
                "♻️ AUTO-RESUME COMPLETE | %d strategy(ies) recovered: %s",
                len(resumed), resumed,
            )

        return resumed

    @staticmethod
    def _mark_config_status(strategy_key: str, status: str) -> None:
        """Update the ``status`` field in a strategy's saved config JSON."""
        config_dir = Path(__file__).resolve().parent / "saved_configs"
        cfg_path = config_dir / f"{strategy_key}.json"
        if not cfg_path.exists():
            return
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["status"] = status
            cfg["status_updated_at"] = datetime.now().isoformat()
            tmp = str(cfg_path) + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, indent=2)
                f.write("\n")
                f.flush()
            import os
            os.replace(tmp, str(cfg_path))
        except Exception as e:
            logger.debug("Could not update config status for %s: %s", strategy_key, e)

    def start(self):
        """Start the background processing thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("StrategyExecutorService started")

    def stop(self):
        """Stop the background thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("StrategyExecutorService stopped")

    def _run_loop(self):
        """Main loop: iterate over all strategies and process each."""
        while self._running and not self._stop_event.is_set():
            with self._lock:
                names = list(self._executors.keys())
            completed_names: List[str] = []
            for name in names:
                executor = self._executors.get(name)
                if executor:
                    try:
                        executor.process_tick()
                        if getattr(executor, "cycle_completed", False) and not executor.state.any_leg_active:
                            completed_names.append(name)
                    except Exception as e:
                        logger.exception(f"Error processing strategy {name}: {e}")
            for name in completed_names:
                try:
                    self._archive_completed_strategy(name)
                    self._mark_config_status(name, "COMPLETED")
                    self.unregister_strategy(name)
                    logger.info(f"Strategy cycle completed and auto-stopped: {name}")
                except Exception as e:
                    logger.error(f"Failed to auto-stop completed strategy {name}: {e}")
            time.sleep(2)  # same as old service

    def acquire_mode_change_lock(self, strategy_name: str) -> threading.Lock:
        with self._mode_change_dict_lock:
            if strategy_name not in self._mode_change_lock:
                self._mode_change_lock[strategy_name] = threading.Lock()
            return self._mode_change_lock[strategy_name]

    def notify_fill(self, strategy_name: str, **kwargs):
        """Delegate fill notification to the appropriate executor."""
        executor = self._executors.get(strategy_name)
        if executor:
            executor.notify_fill(**kwargs)
        else:
            logger.warning(f"Fill notification for unknown strategy: {strategy_name}")

    def _validate_mode_change_allowed(self, strategy_name: str) -> Tuple[bool, str]:
        """Return (allowed, reason)."""
        if self.has_position(strategy_name):
            return False, "Strategy has active positions"
        return True, ""

    def has_position(self, strategy_name: str) -> bool:
        state = self._exec_states.get(strategy_name)
        if not state:
            return False
        return state.any_leg_active

    def _is_paper_mode(self, config: Dict[str, Any]) -> bool:
        identity = config.get("identity", {}) or {}
        return bool(
            identity.get("paper_mode")
            or identity.get("test_mode")
        )

    # BUG-014 FIX: get_strategy_mode() was called by router but never existed in service.
    # The router used hasattr guard so it silently fell back to "LIVE" for all strategies —
    # paper-mode strategies appeared as LIVE in the dashboard.
    def get_strategy_mode(self, strategy_name: str) -> str:
        """Return 'MOCK' or 'LIVE' based on strategy config paper_mode / test_mode flags."""
        config = self._strategies.get(strategy_name, {})
        return "MOCK" if self._is_paper_mode(config) else "LIVE"

    def get_strategy_leg_monitor_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Build monitor-ready leg snapshot from current executor state.
        """
        snapshot: Dict[str, Dict[str, Any]] = {}
        now_iso = datetime.now().isoformat()
        with self._lock:
            names = list(self._exec_states.keys())
            for strategy_name in names:
                state = self._exec_states.get(strategy_name)
                if state is None:
                    continue

                config = self._strategies.get(strategy_name, {}) or {}
                identity = config.get("identity", {}) or {}
                mode = "MOCK" if self._is_paper_mode(config) else "LIVE"
                cache = self._monitor_cache.setdefault(strategy_name, {})
                executor = self._executors.get(strategy_name)
                seen_keys: set[str] = set()

                for leg in list((getattr(state, "legs", {}) or {}).values()):
                    side_val = getattr(getattr(leg, "side", None), "value", getattr(leg, "side", ""))
                    side = str(side_val or "").upper()
                    qty = int(getattr(leg, "qty", 0) or 0)
                    order_qty = qty
                    try:
                        if executor is not None and hasattr(executor, "_lots_to_order_qty"):
                            order_qty = int(executor._lots_to_order_qty(int(qty), leg))
                    except Exception:
                        order_qty = qty
                    is_active = bool(getattr(leg, "is_active", False)) and qty > 0
                    status = "ACTIVE" if is_active else "CLOSED"
                    leg_pnl = float(getattr(leg, "pnl", 0) or 0)
                    unrealized = leg_pnl if is_active else 0.0
                    symbol = str(
                        getattr(leg, "trading_symbol", None)
                        or getattr(leg, "symbol", "")
                        or ""
                    ).strip()
                    if not symbol:
                        continue

                    tag = str(getattr(leg, "tag", "") or symbol)
                    leg_key = f"{tag}::{symbol}"
                    seen_keys.add(leg_key)

                    row = cache.get(leg_key)
                    if row is None:
                        row = {
                            "strategy_name": strategy_name,
                            "opened_at": now_iso,
                            "closed_at": None,
                            "source": "ENTRY" if tag.startswith("LEG@") else "ADJUSTMENT",
                            "realized_pnl": 0.0,
                        }
                        cache[leg_key] = row

                    was_active = str(row.get("status", "")).upper() == "ACTIVE"
                    if was_active and not is_active and row.get("closed_at") is None:
                        row["closed_at"] = now_iso
                        row["realized_pnl"] = float(row.get("realized_pnl", 0) or 0) + float(leg_pnl)

                    display_qty = max(0, int(order_qty))
                    if not is_active:
                        try:
                            prior_qty = int(row.get("qty", display_qty) or display_qty)
                            display_qty = max(display_qty, prior_qty)
                        except Exception:
                            pass

                    row.update({
                        "strategy_name": strategy_name,
                        "exchange": identity.get("exchange", ""),
                        "symbol": symbol,
                        "side": side,
                        "qty": max(0, display_qty),
                        "entry_price": float(getattr(leg, "entry_price", 0) or 0),
                        "exit_price": None,
                        "ltp": float(getattr(leg, "ltp", 0) or 0),
                        "status": status,
                        "unrealized_pnl": (unrealized if is_active else 0.0),
                        "delta": float(getattr(leg, "delta", 0) or 0),
                        "gamma": float(getattr(leg, "gamma", 0) or 0),
                        "theta": float(getattr(leg, "theta", 0) or 0),
                        "vega": float(getattr(leg, "vega", 0) or 0),
                        "opened_at": row.get("opened_at") or (getattr(state, "entry_time", None).isoformat() if getattr(state, "entry_time", None) else now_iso),
                        "closed_at": None if is_active else (row.get("closed_at") or now_iso),
                        "updated_at": now_iso,
                        "mode": mode,
                    })
                    row["total_pnl"] = float(row.get("realized_pnl", 0) or 0) + float(row.get("unrealized_pnl", 0) or 0)
                    if is_active:
                        row["closed_at"] = None

                # Keep cached closed legs for lifecycle visibility; drop stale never-seen rows.
                for k in list(cache.keys()):
                    if k in seen_keys:
                        continue
                    stale = cache.get(k) or {}
                    if str(stale.get("status", "")).upper() != "CLOSED":
                        cache.pop(k, None)

                legs_payload: List[Dict[str, Any]] = list(cache.values())
                active_legs = len([r for r in legs_payload if str(r.get("status", "")).upper() == "ACTIVE"])
                closed_legs = len([r for r in legs_payload if str(r.get("status", "")).upper() == "CLOSED"])
                unrealized_pnl = sum(float(r.get("unrealized_pnl", 0) or 0) for r in legs_payload if str(r.get("status", "")).upper() == "ACTIVE")
                realized_leg_pnl = sum(float(r.get("realized_pnl", 0) or 0) for r in legs_payload if str(r.get("status", "")).upper() == "CLOSED")
                snapshot[strategy_name] = {
                    "mode": mode,
                    "active_legs": active_legs,
                    "closed_legs": closed_legs,
                    "realized_pnl": float(realized_leg_pnl),
                    "unrealized_pnl": float(unrealized_pnl),
                    "adjustments_today": int(getattr(state, "adjustments_today", 0) or 0),
                    "lifetime_adjustments": int(getattr(state, "lifetime_adjustments", 0) or 0),
                    "last_adjustment_time": (
                        getattr(state, "last_adjustment_time", None).isoformat()
                        if getattr(state, "last_adjustment_time", None)
                        else None
                    ),
                    "legs": legs_payload,
                }
                try:
                    self.state_mgr.save_monitor_snapshot(strategy_name, cache)
                except Exception as e:
                    logger.debug("Could not persist monitor cache for %s: %s", strategy_name, e)
        return snapshot

    def _archive_completed_strategy(self, strategy_name: str, runtime_state: str = "COMPLETED") -> None:
        """
        Persist a completed strategy monitor snapshot before unregistering it.
        Always saves a record, even for short/no-trade runs, so history is never lost.
        """
        # Force-refresh monitor cache from current state so that any
        # legs that were deactivated (e.g. by exit) since the last
        # polling snapshot are properly captured as CLOSED with their
        # final PnL values.
        try:
            self.get_strategy_leg_monitor_snapshot()
        except Exception:
            pass

        with self._lock:
            cache = dict((self._monitor_cache.get(strategy_name) or {}))
            state = self._exec_states.get(strategy_name)
            config = self._strategies.get(strategy_name, {}) or {}

            mode = "MOCK" if self._is_paper_mode(config) else "LIVE"
            legs_payload: List[Dict[str, Any]] = list(cache.values())
            legs_payload.sort(
                key=lambda row: str(row.get("updated_at") or row.get("opened_at") or ""),
                reverse=True,
            )

            active_rows = [r for r in legs_payload if str(r.get("status", "")).upper() == "ACTIVE"]
            closed_rows = [r for r in legs_payload if str(r.get("status", "")).upper() == "CLOSED"]
            unrealized_pnl = sum(float(r.get("unrealized_pnl", 0) or 0) for r in active_rows)
            realized_leg_pnl = sum(float(r.get("realized_pnl", 0) or 0) for r in closed_rows)
            realized_pnl = float(realized_leg_pnl)

            opened_ts_all: List[float] = []
            closed_ts_all: List[float] = []
            for row in legs_payload:
                raw_opened = row.get("opened_at")
                raw_closed = row.get("closed_at")
                try:
                    if raw_opened:
                        opened_ts_all.append(datetime.fromisoformat(str(raw_opened)).timestamp())
                except Exception:
                    pass
                try:
                    if raw_closed:
                        closed_ts_all.append(datetime.fromisoformat(str(raw_closed)).timestamp())
                except Exception:
                    pass

            if opened_ts_all and closed_ts_all:
                runtime_seconds = int(max(0, max(closed_ts_all) - min(opened_ts_all)))
            else:
                runtime_seconds = 0

            history_row = {
                "strategy_name": strategy_name,
                "mode": mode,
                "active": False,
                "runtime_state": runtime_state,
                "runtime_seconds": runtime_seconds,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": float(unrealized_pnl),
                "total_pnl": float(realized_pnl + unrealized_pnl),
                "combined_delta": sum(float(r.get("delta", 0) or 0) for r in active_rows),
                "combined_gamma": sum(float(r.get("gamma", 0) or 0) for r in active_rows),
                "combined_theta": sum(float(r.get("theta", 0) or 0) for r in active_rows),
                "combined_vega": sum(float(r.get("vega", 0) or 0) for r in active_rows),
                "adjustments_today": int(getattr(state, "adjustments_today", 0) or 0) if state else 0,
                "lifetime_adjustments": int(getattr(state, "lifetime_adjustments", 0) or 0) if state else 0,
                "last_adjustment_time": (
                    getattr(state, "last_adjustment_time", None).isoformat()
                    if state and getattr(state, "last_adjustment_time", None)
                    else None
                ),
                "leg_count": len(legs_payload),
                "active_legs": len(active_rows),
                "closed_legs": len(closed_rows),
                "positions": [],
                "all_legs": legs_payload,
                "active_leg_rows": active_rows,
                "closed_leg_rows": closed_rows,
                "archived_at": datetime.now().isoformat(),
            }

            self._completed_monitor_history.insert(0, history_row)
            if len(self._completed_monitor_history) > self._max_completed_monitor_history:
                self._completed_monitor_history = self._completed_monitor_history[: self._max_completed_monitor_history]
            try:
                self.state_mgr.append_completed_monitor_history(
                    history_row,
                    max_rows=self._max_completed_monitor_history,
                )
                self.state_mgr.clear_monitor_snapshot(strategy_name)
            except Exception as e:
                logger.debug("Could not persist completed monitor history for %s: %s", strategy_name, e)

            # Reset cumulative counters in the persisted state file so that
            # the next run of this strategy starts with a clean slate.
            if state is not None:
                state.cumulative_daily_pnl = 0.0
                executor = self._executors.get(strategy_name)
                if executor and hasattr(executor, "persistence") and hasattr(executor, "state_file"):
                    try:
                        executor.persistence.save(str(executor.state_file), state)
                    except Exception:
                        pass

    def get_completed_strategy_monitor_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        normalized_limit = max(1, int(limit or 20))
        with self._lock:
            try:
                rows = self.state_mgr.get_completed_monitor_history(limit=normalized_limit)
                if rows:
                    self._completed_monitor_history = rows[: self._max_completed_monitor_history]
                    return copy.deepcopy(rows)
            except Exception as e:
                logger.debug("Could not load completed monitor history from DB: %s", e)
            rows = self._completed_monitor_history[:normalized_limit]
            return copy.deepcopy(rows)

    def delete_completed_strategy_monitor_history(self, strategy_name: str = None, archived_at: str = None) -> int:
        """Delete completed strategy monitor history. Supports deleting specific entry, all for a strategy, or all."""
        with self._lock:
            count = self.state_mgr.delete_completed_monitor_history(
                strategy_name=strategy_name, archived_at=archived_at
            )
            if strategy_name and archived_at:
                self._completed_monitor_history = [
                    r for r in self._completed_monitor_history
                    if not (r.get("strategy_name") == strategy_name and r.get("archived_at") == archived_at)
                ]
            elif strategy_name:
                self._completed_monitor_history = [
                    r for r in self._completed_monitor_history
                    if r.get("strategy_name") != strategy_name
                ]
            else:
                self._completed_monitor_history.clear()
            return count

    # BUG-026 FIX: STRATEGY_RECOVER_RESUME intent was submitted by the dashboard but
    # had NO consumer anywhere. The intent was stored in DB forever; recovery never happened.
    def handle_recover_resume(self, payload: dict) -> dict:
        """
        Handle a STRATEGY_RECOVER_RESUME intent submitted by the dashboard.

        Sets the strategy state to 'already entered' so the executor monitors
        exits/adjustments rather than waiting for a fresh entry signal.

        Args:
            payload: {
                "strategy_name": str,      # strategy to recover
                "symbol": str,             # broker symbol with open position
                "resume_monitoring": bool  # True = skip re-entry, monitor only
            }
        """
        strategy_name = payload.get("strategy_name", "").strip()
        symbol = payload.get("symbol", "").strip()
        resume_monitoring = payload.get("resume_monitoring", True)

        if not strategy_name:
            logger.error("RECOVER_RESUME: strategy_name is required")
            return {"status": "error", "reason": "strategy_name required"}

        with self._lock:
            executor = self._executors.get(strategy_name)
            if executor is None:
                logger.warning(f"RECOVER_RESUME: strategy '{strategy_name}' not registered; "
                               f"cannot apply until strategy is loaded via /runner/start")
                return {"status": "not_registered", "strategy_name": strategy_name}

            state = executor.state
            if resume_monitoring:
                # Mark as entered so executor skips fresh ENTRY and monitors exits/adjustments
                state.entered_today = True
                if state.entry_time is None:
                    state.entry_time = datetime.now()

                # If symbol provided and not already tracked, create a placeholder leg
                # so the exit engine can monitor it until full reconciliation happens
                if symbol and symbol not in [leg.symbol for leg in state.legs.values()]:
                    from .state import LegState
                    from .models import InstrumentType, Side
                    recovery_tag = f"RECOVERED_{symbol}"
                    recovery_leg = LegState(
                        tag=recovery_tag,
                        symbol=symbol,
                        trading_symbol=symbol,
                        instrument=InstrumentType.OPT,
                        option_type=None,
                        strike=None,
                        expiry="UNKNOWN",
                        side=Side.SELL,   # default; reconciliation will correct this
                        qty=0,            # qty=0 signals "needs reconciliation"
                        entry_price=0.0,
                        ltp=0.0,
                        is_active=True,
                    )
                    state.legs[recovery_tag] = recovery_leg
                    logger.info(f"RECOVER_RESUME: placeholder leg created for '{symbol}' "
                                f"in strategy '{strategy_name}'")

                # Persist the recovery state immediately
                try:
                    executor.persistence.save(state, str(executor.state_file))
                    logger.info(f"RECOVER_RESUME: state persisted for '{strategy_name}'")
                except Exception as e:
                    logger.error(f"RECOVER_RESUME: state persist failed: {e}")

            logger.warning(f"♻️ RECOVER_RESUME APPLIED | strategy={strategy_name} | "
                           f"symbol={symbol} | resume_monitoring={resume_monitoring}")
            return {
                "status": "resumed",
                "strategy_name": strategy_name,
                "symbol": symbol,
                "resume_monitoring": resume_monitoring,
            }

    @staticmethod
    def _adjustment_roll_leg(
        svc,
        name: str,
        exec_state: ExecutionState,
        engine_state: Any,
        leg: str,
        config: Dict[str, Any],
        reader: Any,
        qty: int,
    ) -> bool:
        """
        Roll helper used by hardening tests and adjustment flow.
        """
        leg_key = leg.strip().upper()
        if leg_key not in ("CE", "PE"):
            return False

        prefix = leg_key.lower()
        opposite = "pe" if prefix == "ce" else "ce"
        cur_symbol = getattr(exec_state, f"{prefix}_symbol", None)
        side = getattr(exec_state, f"{prefix}_side", None) or "SELL"
        raw_delta = getattr(engine_state, f"{opposite}_delta", 0.3)
        try:
            target_abs_delta = abs(float(raw_delta))
        except (TypeError, ValueError):
            target_abs_delta = 0.3

        candidate = reader.find_option_by_delta(
            option_type=leg_key,
            target_delta=target_abs_delta,
            tolerance=0.1,
        )
        if not candidate:
            logger.error("Roll failed for %s: no candidate by delta %.4f", name, target_abs_delta)
            return False

        new_symbol = candidate.get("trading_symbol") or candidate.get("symbol")
        if not new_symbol:
            return False
        if cur_symbol and new_symbol == cur_symbol:
            return True

        exchange = ((config or {}).get("basic", {}) or {}).get("exchange", "NFO")
        try:
            lot_size = int(reader.get_lot_size())
            if lot_size <= 0:
                lot_size = 1
        except Exception:
            lot_size = 1
        order_qty = int(qty) * lot_size
        alert = {
            "execution_type": "ADJUSTMENT",
            "strategy_name": name,
            "exchange": exchange,
            "legs": [
                {
                    "tradingsymbol": cur_symbol,
                    "direction": "BUY" if str(side).upper() == "SELL" else "SELL",
                    "qty": order_qty,
                    "order_type": "MARKET",
                    "price": 0.0,
                    "product_type": "NRML",
                },
                {
                    "tradingsymbol": new_symbol,
                    "direction": str(side).upper(),
                    "qty": order_qty,
                    "order_type": "MARKET",
                    "price": 0.0,
                    "product_type": "NRML",
                },
            ],
        }
        result = svc.bot.process_alert(alert)
        if isinstance(result, dict) and str(result.get("status", "")).strip().upper() in ("FAILED", "BLOCKED", "ERROR"):
            return False

        setattr(exec_state, f"{prefix}_symbol", new_symbol)
        setattr(exec_state, f"{prefix}_strike", float(candidate.get("strike", 0.0) or 0.0))
        setattr(exec_state, f"{prefix}_qty", int(qty))
        if candidate.get("ltp") is not None:
            setattr(exec_state, f"{prefix}_entry_price", float(candidate.get("ltp") or 0.0))

        try:
            svc.state_mgr.save(exec_state)
        except Exception as e:
            logger.warning("Roll state persist failed for %s: %s", name, e)
        return True


class PerStrategyExecutor:
    """
    Encapsulates the engine components for a single strategy.
    """

    def __init__(self, name: str, config: Dict[str, Any], bot, state_db_path: str):
        self.name = name
        self.config = config
        self.bot = bot
        # BUG-H4 FIX: Reentrant lock for thread-safe access to state between
        # process_tick (main loop thread) and notify_fill (OrderWatcher thread).
        # Must be RLock (reentrant) because MOCK fills fire synchronously:
        # process_tick → _execute_entry → bot.process_alert → execute_command
        # → notify_fill, all on the same thread while _tick_lock is held.
        import threading
        self._tick_lock = threading.RLock()

        # State persistence (use name‑based file)
        state_file = Path(state_db_path).parent / f"{name}_state.pkl"
        self.persistence = StatePersistence()
        self.state = self.persistence.load(str(state_file)) or StrategyState()

        # Market reader – db_path not needed, auto-resolves
        identity = config.get("identity", {})
        exchange = identity.get("exchange", "NFO")
        symbol = identity.get("underlying", "NIFTY")
        self.market = MarketReader(exchange, symbol, max_stale_seconds=30)
        self._fixed_expiry_date = self._extract_expiry_from_db_file(config)
        self._cycle_expiry_date = self._resolve_cycle_expiry(config)

        # Engines
        self.condition_engine = ConditionEngine(self.state)
        self.entry_engine = EntryEngine(self.state, self.market)
        self.adjustment_engine = AdjustmentEngine(self.state, self.market)
        self.exit_engine = ExitEngine(self.state)
        self.exit_engine.load_config(config.get("exit", {}))
        self.adjustment_engine.load_rules(config.get("adjustment", {}).get("rules", []))
        self.reconciliation = BrokerReconciliation(
            self.state,
            lot_size_resolver=self.market.get_lot_size,
        )

        self.state_file = state_file

        # Resolve lot_size once and stamp on any existing legs (recovery path).
        try:
            self._lot_size = max(1, int(self.market.get_lot_size(self._cycle_expiry_date)))
        except Exception:
            self._lot_size = 1
        for leg in self.state.legs.values():
            if getattr(leg, "lot_size", 1) <= 1 and self._lot_size > 1:
                leg.lot_size = self._lot_size

        # Daily reset tracking
        self._last_date = datetime.now().date()
        self.cycle_completed = False
        adjustment_cfg = self.config.get("adjustment", {})
        self._adjustment_validation_backoff_sec = max(
            5,
            int(adjustment_cfg.get("validation_retry_cooldown_sec", 60) or 60),
        )
        self._adjustment_validation_alert_cooldown_sec = max(
            5,
            int(adjustment_cfg.get("validation_alert_cooldown_sec", 60) or 60),
        )
        self._adjustment_block_until: Optional[datetime] = None
        self._adjustment_block_reason: str = ""
        self._adjustment_block_announced: bool = False
        self._last_persist_at: Optional[datetime] = None
        self._last_adjustment_validation_alert_at: Optional[datetime] = None
        self._last_entry_skip_reason: str = ""
        self._last_entry_skip_log_at: Optional[datetime] = None

    def process_tick(self):
        """Called by the service loop each tick."""
        with self._tick_lock:
            self._process_tick_inner()

    def _process_tick_inner(self):
        """Core tick logic (runs under _tick_lock)."""
        now = datetime.now()

        # Daily reset
        if self._last_date != now.date():
            self.state.adjustments_today = 0
            self.state.total_trades_today = 0
            self.state.entered_today = False
            # BUG-H3 FIX: Reset trailing stop and profit step state on new day.
            self.state.trailing_stop_active = False
            self.state.trailing_stop_level = 0.0
            self.state.peak_pnl = 0.0
            self.state.current_profit_step = -1
            self.state.cumulative_daily_pnl = 0.0
            self._last_date = now.date()
            logger.info(f"Daily counters reset for {self.name}")

        self.state.current_time = now
        self._update_time_context(now)

        # --- NEW: Reconcile pending orders ---
        self._reconcile_pending_orders()

        # Update market data (including leg data)
        self._update_market_data()

        # Check exits first
        exit_action = self.exit_engine.check_exits(now)
        if exit_action and exit_action != "profit_step_adj":
            logger.info(
                "EXIT_TRIGGERED | strategy=%s | action=%s | reason=%s",
                self.name,
                exit_action,
                self.exit_engine.last_exit_reason or "unspecified",
            )
            self._execute_exit(exit_action, source=exit_action)
            # ✅ BUG FIX(9): Persist state after exit so legs are marked
            # inactive on disk. Without this the early `return` skips the
            # periodic save at the bottom of process_tick, leaving a stale
            # state file with active legs that confuses the next session.
            try:
                self.persistence.save(self.state, str(self.state_file))
            except Exception as _e:
                logger.warning("State persist after exit failed for %s: %s", self.name, _e)
            return

        # Check entry (if not already entered today)
        if not self.state.entered_today:
            should_enter, reason = self._should_enter_with_reason(now)
            if should_enter:
                self._execute_entry()
            else:
                self._log_entry_skip(reason, now)

        # Check adjustments (unchanged)
        if self._adjustment_block_until and now < self._adjustment_block_until:
            if not self._adjustment_block_announced:
                logger.warning(
                    "Adjustment dispatch temporarily blocked for %s until %s due to validation guard: %s",
                    self.name,
                    self._adjustment_block_until.strftime("%H:%M:%S"),
                    self._adjustment_block_reason,
                )
                self._adjustment_block_announced = True
        else:
            if self._adjustment_block_until and now >= self._adjustment_block_until:
                self._adjustment_block_until = None
                self._adjustment_block_reason = ""
                self._adjustment_block_announced = False
            pre_adjustment_legs = copy.deepcopy(self.state.legs)
            pre_adjustments_today = self.state.adjustments_today
            pre_lifetime_adjustments = self.state.lifetime_adjustments
            pre_last_adjustment_time = self.state.last_adjustment_time
            # ✅ BUG FIX: Do not run adjustments if no legs are active yet.
            # Conditions like 'adj_count_today >= 0' are always true, so without
            # this guard the adjustment engine fires before entry and crashes when
            # dynamic leg selectors (LOWER_DELTA_LEG etc.) resolve to None.
            if not self.state.any_leg_active:
                actions = []
            else:
                actions = self.adjustment_engine.check_and_apply(now)
            for action in actions:
                logger.info(f"Adjustment: {action}")
            if actions:
                if not self._dispatch_adjustment_orders(pre_adjustment_legs):
                    # Roll back local state if broker rejected adjustment orders.
                    self.state.legs = pre_adjustment_legs
                    self.state.adjustments_today = pre_adjustments_today
                    self.state.lifetime_adjustments = pre_lifetime_adjustments
                    self.state.last_adjustment_time = pre_last_adjustment_time
                    # Set cooldown to prevent spamming rejected adjustments every tick
                    self._adjustment_block_until = now + timedelta(seconds=self._adjustment_validation_backoff_sec)
                    self._adjustment_block_reason = "dispatch_rejected"
                    self._adjustment_block_announced = False
                    logger.warning(f"Adjustment rollback applied for {self.name}, blocking for {self._adjustment_validation_backoff_sec}s")
                else:
                    # Stamp lot_size on any newly created adjustment legs
                    for leg in self.state.legs.values():
                        if getattr(leg, "lot_size", 1) <= 1 and self._lot_size > 1:
                            leg.lot_size = self._lot_size
                    self.persistence.save(self.state, str(self.state_file))

        # Broker reconciliation (every 5 minutes)
        # BUG-14 FIX: Widened from second==0 (1s window) to second<5 (5s window)
        # to avoid missing the reconciliation window due to tick processing delays.
        # Added _last_reconcile_minute guard to ensure it still only fires once per window.
        if now.second < 5 and now.minute % 5 == 0 and not self._resolve_test_mode():
            last_rec = getattr(self, "_last_reconcile_minute", -1)
            current_window = now.hour * 60 + now.minute
            if current_window != last_rec:
                self._last_reconcile_minute = current_window
                try:
                    broker_view = getattr(self.bot, "broker_view", None)
                    if broker_view is not None:
                        warnings = self.reconciliation.reconcile_from_broker(broker_view)
                        if warnings:
                            logger.warning(f"RECONCILE [{self.name}]: {len(warnings)} mismatch(es) corrected")
                except Exception as e:
                    logger.error(f"Broker reconciliation failed for {self.name}: {e}")

        # Persist state periodically (every ~30 seconds)
        # NOTE: previous `now.second == 0` condition was fragile — the 2-second
        # tick loop could stay on odd seconds and never hit 0.
        elapsed = (now - self._last_persist_at).total_seconds() if self._last_persist_at else 999
        if elapsed >= 30:
            self._last_persist_at = now
            self.persistence.save(self.state, str(self.state_file))

    # ==================== NEW METHODS ====================

    def _reconcile_pending_orders(self):
        """Query repository for orders and update pending legs."""
        if not hasattr(self.bot, "order_repo"):
            return

        # Get all orders for this strategy with non-final status.
        # NOTE: this excludes EXECUTED/FAILED rows by contract, so pending legs
        # must also reconcile through command_id / broker_order_id lookups.
        orders = self.bot.order_repo.get_open_orders_by_strategy(self.name)
        open_order_map = {(str(o.symbol or "").strip(), str(o.side or "").upper()): o for o in orders}

        broker_positions = None
        if not self._resolve_test_mode():
            try:
                broker_view = getattr(self.bot, "broker_view", None)
                if broker_view is not None:
                    broker_view.invalidate_cache("positions")
                    broker_positions = broker_view.get_positions(force_refresh=True) or []
            except Exception:
                broker_positions = None

        for leg in list(self.state.legs.values()):
            if leg.order_status != "PENDING":
                continue

            leg_symbols = self._leg_symbols(leg)
            # Prefer symbol+side for open orders, then exact command/broker IDs for terminal statuses.
            matching_order = None
            for sym in leg_symbols:
                matching_order = open_order_map.get((sym, leg.side.value))
                if matching_order is not None:
                    break
            if matching_order is None and getattr(leg, "command_id", None):
                matching_order = self.bot.order_repo.get_by_id(leg.command_id)
            if matching_order is None and getattr(leg, "order_id", None):
                matching_order = self.bot.order_repo.get_by_broker_id(leg.order_id)

            if matching_order:
                leg.command_id = matching_order.command_id
                leg.order_id = matching_order.broker_order_id

                if matching_order.status == "EXECUTED":
                    leg.order_status = "FILLED"
                    leg.is_active = True
                    leg.filled_qty = int(matching_order.quantity or 0)
                    logger.info(f"FILLED via reconciliation | {leg.tag}")
                elif matching_order.status in ("FAILED", "CANCELLED", "REJECTED"):
                    leg.order_status = "FAILED"
                    leg.is_active = False
                    logger.warning(f"FAILED via reconciliation | {leg.tag}")
                # else SENT_TO_BROKER or CREATED – remain pending
            else:
                # Final fallback from broker truth: if position exists for leg symbol+direction,
                # treat pending leg as filled to keep monitor state aligned with live account.
                if broker_positions:
                    for p in broker_positions:
                        sym = str(p.get("tsym") or "").strip()
                        if sym not in leg_symbols:
                            continue
                        netqty = int(p.get("netqty", 0) or 0)
                        if netqty == 0:
                            continue
                        if leg.side.value == "SELL" and netqty < 0:
                            leg.order_status = "FILLED"
                            leg.is_active = True
                            leg.filled_qty = abs(netqty)
                            leg.entry_price = float(p.get("avgprc", leg.entry_price) or leg.entry_price)
                            leg.ltp = float(p.get("lp", leg.ltp) or leg.ltp)
                            logger.warning(
                                "FILLED via broker-position fallback | %s | symbol=%s qty=%s",
                                leg.tag,
                                sym,
                                abs(netqty),
                            )
                            break
                        if leg.side.value == "BUY" and netqty > 0:
                            leg.order_status = "FILLED"
                            leg.is_active = True
                            leg.filled_qty = abs(netqty)
                            leg.entry_price = float(p.get("avgprc", leg.entry_price) or leg.entry_price)
                            leg.ltp = float(p.get("lp", leg.ltp) or leg.ltp)
                            logger.warning(
                                "FILLED via broker-position fallback | %s | symbol=%s qty=%s",
                                leg.tag,
                                sym,
                                abs(netqty),
                            )
                            break
                if leg.order_status != "PENDING":
                    continue

                # MOCK safety net: before timeout, search DB for any EXECUTED
                # orders matching this leg's symbol+side (MOCK fills may have been
                # committed to DB even if notify_fill was missed).
                if self._resolve_test_mode():
                    try:
                        all_orders = self.bot.order_repo.get_open_orders_by_strategy(self.name)
                        # get_open_orders_by_strategy only returns CREATED/SENT_TO_BROKER;
                        # also try get_by_id for any command_id we may have.
                        cid = getattr(leg, "command_id", None)
                        if cid:
                            db_order = self.bot.order_repo.get_by_id(cid)
                            if db_order and db_order.status == "EXECUTED":
                                leg.order_status = "FILLED"
                                leg.is_active = True
                                leg.filled_qty = int(db_order.quantity or 0)
                                if db_order.executed_price:
                                    leg.entry_price = float(db_order.executed_price)
                                    leg.ltp = float(db_order.executed_price)
                                logger.info("MOCK FILLED via DB reconciliation | %s", leg.tag)
                                continue
                    except Exception as mock_recon_err:
                        logger.debug("MOCK reconciliation fallback failed: %s", mock_recon_err)

                # No matching order – check timeout
                if leg.order_placed_at and (datetime.now() - leg.order_placed_at).total_seconds() > 60:
                    logger.warning(f"PENDING TIMEOUT | {leg.tag} – marking FAILED")
                    leg.order_status = "FAILED"
                    leg.is_active = False

        # Handle CLOSE_PENDING timeout (adjustment close orders)
        for leg in list(self.state.legs.values()):
            if leg.order_status != "CLOSE_PENDING":
                continue
            if leg.order_placed_at and (datetime.now() - leg.order_placed_at).total_seconds() > 60:
                logger.warning(f"CLOSE_PENDING TIMEOUT | {leg.tag} – marking CLOSED")
                leg.order_status = "CLOSED"
                leg.is_active = False

    def notify_fill(self, symbol: str, side: str, qty: int, price: float,
                    delta: Optional[float], broker_order_id: str, command_id: Optional[str] = None):
        """Immediate fill notification from OrderWatcher (runs on watcher thread)."""
        with self._tick_lock:
            self._notify_fill_inner(symbol, side, qty, price, delta, broker_order_id, command_id)

    def _notify_fill_inner(self, symbol: str, side: str, qty: int, price: float,
                           delta: Optional[float], broker_order_id: str, command_id: Optional[str] = None):
        """Core fill logic (runs under _tick_lock)."""
        fill_symbol = str(symbol or "").strip()
        fill_side = str(side or "").upper()
        # Pass 1: match PENDING legs (entry / adjustment open orders)
        for leg in self.state.legs.values():
            if leg.order_status != "PENDING":
                continue
            if leg.side.value != fill_side:
                continue
            if fill_symbol not in self._leg_symbols(leg):
                continue
            leg.order_status = "FILLED"
            leg.is_active = True
            leg.order_id = broker_order_id
            leg.command_id = command_id
            leg.filled_qty = qty  # qty in contracts; may need conversion to lots
            leg.entry_price = price
            leg.ltp = price
            leg.delta = delta if delta is not None else leg.delta
            logger.info(f"FILL NOTIFIED | {self.name} | {symbol} {side} {qty} @ {price}")
            return
        # Pass 2: match CLOSE_PENDING legs (adjustment close orders – opposite side)
        for leg in self.state.legs.values():
            if leg.order_status != "CLOSE_PENDING":
                continue
            expected_close_side = "BUY" if leg.side.value == "SELL" else "SELL"
            if fill_side != expected_close_side:
                continue
            if fill_symbol not in self._leg_symbols(leg):
                continue
            leg.order_status = "CLOSED"
            leg.is_active = False
            leg.order_id = broker_order_id
            logger.info(f"CLOSE FILL NOTIFIED | {self.name} | {symbol} {side} {qty} @ {price}")
            return
        logger.warning(f"FILL NOTIFICATION: No matching pending leg for {symbol} {side}")

    @staticmethod
    def _leg_symbols(leg: LegState) -> set:
        out = set()
        if getattr(leg, "symbol", None):
            out.add(str(leg.symbol).strip())
        if getattr(leg, "trading_symbol", None):
            out.add(str(leg.trading_symbol).strip())
        return {s for s in out if s}

    # ==================== MODIFIED EXISTING METHODS ====================

    def _update_market_data(self):
        """Refresh spot, ATM, and per‑leg data, but only for filled legs."""
        self.state.spot_price = self.market.get_spot_price(self._cycle_expiry_date)
        if not self.state.spot_open and self.state.spot_price:
            self.state.spot_open = self.state.spot_price
        self.state.atm_strike = self.market.get_atm_strike(self._cycle_expiry_date)
        self.state.fut_ltp = self.market.get_fut_ltp(self._cycle_expiry_date)
        try:
            chain_metrics = self.market.get_chain_metrics(self._cycle_expiry_date)
        except Exception as e:
            logger.warning(
                "MARKET_METRICS_UNAVAILABLE | strategy=%s | expiry=%s | error=%s",
                self.name,
                self._cycle_expiry_date,
                e,
            )
            chain_metrics = {}
        self.state.pcr = float(chain_metrics.get("pcr", 0.0) or 0.0)
        self.state.pcr_volume = float(chain_metrics.get("pcr_volume", 0.0) or 0.0)
        self.state.max_pain_strike = float(chain_metrics.get("max_pain_strike", 0.0) or 0.0)
        self.state.total_oi_ce = float(chain_metrics.get("total_oi_ce", 0.0) or 0.0)
        self.state.total_oi_pe = float(chain_metrics.get("total_oi_pe", 0.0) or 0.0)
        self.state.oi_buildup_ce = float(chain_metrics.get("oi_buildup_ce", 0.0) or 0.0)
        self.state.oi_buildup_pe = float(chain_metrics.get("oi_buildup_pe", 0.0) or 0.0)

        # Update each active leg – only if it is FILLED
        for leg in self.state.legs.values():
            if not leg.is_active or leg.order_status != "FILLED":
                continue
            if leg.instrument == InstrumentType.OPT:
                if leg.strike is None or leg.option_type is None:
                    logger.warning(f"Leg {leg.tag} is active but missing strike or option_type")
                    continue
                opt_data = self.market.get_option_at_strike(leg.strike, leg.option_type, leg.expiry)
                if opt_data:
                    leg.ltp = opt_data.get("ltp") or leg.ltp
                    leg.delta = opt_data.get("delta") if opt_data.get("delta") is not None else leg.delta
                    leg.gamma = opt_data.get("gamma") if opt_data.get("gamma") is not None else leg.gamma
                    leg.theta = opt_data.get("theta") if opt_data.get("theta") is not None else leg.theta
                    leg.vega = opt_data.get("vega") if opt_data.get("vega") is not None else leg.vega
                    leg.iv = opt_data.get("iv") if opt_data.get("iv") is not None else leg.iv
                    leg.oi = opt_data.get("oi") or leg.oi
                    leg.volume = opt_data.get("volume") or leg.volume
            # For futures legs, we could update via a different method, but not implemented here

        # ✅ BUG-001 FIX: Record PnL snapshots for all active filled legs
        for leg in self.state.legs.values():
            if leg.is_active and leg.order_status == "FILLED":
                try:
                    leg.record_pnl_snapshot(self.state.spot_price)
                except Exception:
                    pass  # Non-critical - don't let snapshot recording break the loop

    def _execute_entry(self):
        """Run entry engine and send orders via bot."""
        symbol = self.config["identity"]["underlying"]
        default_expiry = self._cycle_expiry_date
        new_legs = self.entry_engine.process_entry(
            self.config["entry"], symbol, default_expiry
        )
        if not new_legs:
            logger.info(
                "ENTRY_NOT_PLACED | strategy=%s | reason=entry_engine_returned_zero_legs",
                self.name,
            )
            return

        identity = self.config.get("identity", {})
        product_type = identity.get("product_type", "NRML")

        # Resolve lot_size and stamp on each leg for accurate PnL.
        try:
            lot_size = max(1, int(self.market.get_lot_size(self._cycle_expiry_date)))
        except Exception:
            lot_size = 1

        # --- Register legs in state FIRST so notify_fill() can find them ---
        # MOCK fills fire synchronously during process_alert(); if legs are
        # not yet in self.state.legs the fill notification is lost and legs
        # time-out to FAILED after 60 s.
        now = datetime.now()
        for leg in new_legs:
            leg.lot_size = lot_size
            leg.order_status = "PENDING"
            leg.is_active = False
            leg.order_placed_at = now
            self.state.legs[leg.tag] = leg

        # Convert each LegState to an alert leg. Leg qty is tracked in lots internally;
        # alert payload qty must be broker contract quantity.
        alert_legs = []
        for leg in new_legs:
            payload = self._build_alert_leg(
                leg=leg,
                direction=leg.side.value,
                qty=int(leg.qty),
            )
            payload["product_type"] = product_type
            alert_legs.append(payload)

        alert = {
            "secret_key": self._resolve_webhook_secret(),
            "execution_type": "ENTRY",
            "strategy_name": self.name,
            "exchange": identity.get("exchange", "NFO"),
            "legs": alert_legs,
            "test_mode": self._resolve_test_mode(),
        }

        result = self.bot.process_alert(alert)
        if self._is_failure_status((result or {}).get("status")):
            # Rollback: remove legs we pre-registered
            for leg in new_legs:
                self.state.legs.pop(leg.tag, None)
            logger.error(
                "ENTRY_REJECTED | strategy=%s | reason=alert_rejected | result=%s",
                self.name,
                result,
            )
            return

        self.state.entered_today = True
        self.state.entry_time = now
        self.cycle_completed = False

        # Log final status of each leg (may already be FILLED via notify_fill)
        filled = sum(1 for l in new_legs if l.order_status == "FILLED")
        pending = sum(1 for l in new_legs if l.order_status == "PENDING")
        logger.info(
            "ENTRY_PLACED | strategy=%s | legs=%s | filled=%s | pending=%s",
            self.name,
            len(new_legs),
            filled,
            pending,
        )

        # Persist state immediately after entry so crash-recovery can find it
        try:
            self.persistence.save(self.state, str(self.state_file))
        except Exception as _e:
            logger.warning("State persist after entry failed for %s: %s", self.name, _e)

    def _extract_expiry_from_db_file(self, config: Dict[str, Any]) -> Optional[str]:
        """
        Extract concrete expiry date from configured DB filename, if present.
        Example: NFO_NIFTY_02-MAR-2026.sqlite -> 02-MAR-2026
        """
        identity = config.get("identity", {}) or {}
        market_data = config.get("market_data", {}) or {}
        db_file = str(identity.get("db_file") or market_data.get("db_file") or "").strip()
        if not db_file:
            return None
        match = _DB_FILE_EXPIRY_RE.match(db_file)
        if not match:
            logger.warning(
                "Could not parse expiry from db_file '%s' for strategy %s; falling back to schedule.expiry_mode",
                db_file,
                self.name,
            )
            return None
        return match.group(1)

    def _resolve_cycle_expiry(self, config: Dict[str, Any]) -> str:
        """
        Resolve one concrete expiry for this strategy run and keep it fixed.
        Rules:
          1) If schedule.expiry_mode == custom -> use db_file-derived expiry
          2) Otherwise resolve schedule.expiry_mode dynamically from available DBs
             and lock that resolved date for the full cycle.
        """
        schedule_mode = str(
            (config.get("schedule", {}) or {}).get("expiry_mode", "weekly_current")
        ).strip() or "weekly_current"

        if schedule_mode == "custom":
            if self._fixed_expiry_date:
                logger.info(
                    "Using custom db_file expiry for %s: %s",
                    self.name,
                    self._fixed_expiry_date,
                )
                return self._fixed_expiry_date
            logger.warning(
                "schedule.expiry_mode=custom but db_file expiry is missing/invalid for %s; falling back to weekly_current",
                self.name,
            )
            schedule_mode = "weekly_current"

        try:
            resolved = self.market.resolve_expiry_mode(schedule_mode)
            logger.info(
                "Resolved cycle expiry for %s: %s (mode=%s)",
                self.name,
                resolved,
                schedule_mode,
            )
            if self._fixed_expiry_date and schedule_mode != "custom":
                logger.info(
                    "Ignoring db_file expiry for %s because mode=%s is dynamic (db_file=%s)",
                    self.name,
                    schedule_mode,
                    self._fixed_expiry_date,
                )
            return resolved
        except Exception as e:
            logger.error(
                "Failed to resolve cycle expiry for %s with mode=%s: %s; using weekly_current",
                self.name,
                schedule_mode,
                e,
            )
            return self.market.resolve_expiry_mode("weekly_current")

    def _update_time_context(self, now: datetime) -> None:
        """Refresh runtime time fields consumed by condition parameters."""
        exit_time_str = (
            (self.config.get("exit", {}) or {})
            .get("time", {})
            .get("strategy_exit_time")
        )
        if not exit_time_str:
            self.state.minutes_to_exit = 0
            return
        try:
            exit_t = datetime.strptime(str(exit_time_str), "%H:%M").time()
            exit_dt = datetime.combine(now.date(), exit_t)
            if now >= exit_dt:
                self.state.minutes_to_exit = 0
            else:
                self.state.minutes_to_exit = max(
                    0, int((exit_dt - now).total_seconds() / 60)
                )
        except Exception:
            self.state.minutes_to_exit = 0

    def _should_enter_with_reason(self, now: datetime) -> Tuple[bool, str]:
        """Check if entry is allowed and return explicit reason."""
        if self.state.entered_today:
            return False, "already_entered_today"

        # Wait for option chain data to become available (spot & ATM must be non-zero).
        spot = getattr(self.state, "spot_price", 0) or 0
        atm = getattr(self.state, "atm_strike", 0) or 0
        if spot <= 0 or atm <= 0:
            return False, "waiting_for_chain_data"

        timing = self.config.get("timing", {})
        entry_start = timing.get("entry_window_start", "09:15")
        entry_end = timing.get("entry_window_end", "14:00")
        try:
            start_t = datetime.strptime(entry_start, "%H:%M").time()
            end_t = datetime.strptime(entry_end, "%H:%M").time()
        except ValueError:
            return False, f"invalid_entry_window:{entry_start}-{entry_end}"
        if not (start_t <= now.time() <= end_t):
            return False, f"outside_entry_window:{entry_start}-{entry_end}"

        # Respect configured trading days from schedule.
        active_days = self.config.get("schedule", {}).get("active_days", [])
        if active_days:
            day_name = now.strftime("%a").lower()[:3]
            if day_name not in [str(d).lower()[:3] for d in active_days]:
                return False, f"inactive_day:{day_name}"
        return True, "ok"

    def _should_enter(self, now: datetime) -> bool:
        allowed, _ = self._should_enter_with_reason(now)
        return allowed

    def _log_entry_skip(self, reason: str, now: datetime) -> None:
        same_reason = reason == self._last_entry_skip_reason
        if (
            same_reason
            and self._last_entry_skip_log_at is not None
            and (now - self._last_entry_skip_log_at).total_seconds() < 60
        ):
            return
        self._last_entry_skip_reason = reason
        self._last_entry_skip_log_at = now
        logger.info(
            "ENTRY_SKIPPED | strategy=%s | reason=%s | time=%s",
            self.name,
            reason,
            now.strftime("%H:%M:%S"),
        )

    def _execute_exit(self, action: str, source: str = "unknown"):
        """Execute exit via bot."""
        if action == "combined_conditions":
            action = "exit_all"

        if action.startswith("exit_all"):
            # In paper mode, route through process_alert(EXIT) so mock runs
            # exercise the same alert pipeline (including test_mode handling).
            if self._resolve_test_mode():
                active_legs = [leg for leg in self.state.legs.values() if leg.is_active and int(leg.qty) > 0]
                if active_legs:
                    alert_legs = [
                        self._build_alert_leg(
                            leg=leg,
                            direction="BUY" if leg.side.value == "SELL" else "SELL",
                            qty=int(leg.qty),
                        )
                        for leg in active_legs
                    ]
                    result = self._submit_alert(execution_type="EXIT", legs=alert_legs)
                    status = str((result or {}).get("status", "")).upper()
                    # When broker already has no open qty for a leg, executor should
                    # treat that as effectively closed to avoid infinite exit retries.
                    if self._is_failure_status(status) and not self._is_no_position_exit_result(result):
                        logger.error(f"Exit rejected for {self.name}: {result}")
                        return
            else:
                self.bot.request_exit(
                    scope="strategy",
                    strategy_name=self.name,
                    product_type="ALL",
                    reason=source,
                    source="STRATEGY_EXECUTOR"
                )
            # ✅ BUG FIX: Capture PnL BEFORE deactivating legs.
            # combined_pnl only sums active legs; reading after deactivation returns 0.
            pnl_snapshot = self.state.combined_pnl
            # Mark all legs inactive
            for leg in self.state.legs.values():
                leg.is_active = False
            self.state.cumulative_daily_pnl += pnl_snapshot
            # BUG-H3 FIX: Reset trailing stop and profit step state for clean re-entry.
            self.state.trailing_stop_active = False
            self.state.trailing_stop_level = 0.0
            self.state.peak_pnl = 0.0
            self.state.current_profit_step = -1
            # ✅ BUG FIX: Detect stop-loss exit via exit_engine.last_exit_reason
            # (the 'source' param is the action string like 'exit_all', not 'stop_loss').
            exit_reason = getattr(self.exit_engine, 'last_exit_reason', '') or ''
            is_stop_loss_exit = exit_reason.startswith('stop_loss')
            if is_stop_loss_exit:
                sl_cfg = self.config.get("exit", {}).get("stop_loss", {})
                if sl_cfg.get("allow_reentry"):
                    self.state.entered_today = False
                else:
                    self.state.entered_today = True
            else:
                self.state.entered_today = True
                self.cycle_completed = True
            logger.info(f"Exit executed for {self.name}")
        elif action.startswith("leg_rule_"):
            self._execute_leg_rule_exit(action)
        elif action == "partial_50":
            # BUG-C3 FIX: Submit broker orders for the closed half, then update local state.
            alert_legs = []
            reductions: List[Tuple[LegState, int]] = []
            for leg in self.state.legs.values():
                if leg.is_active and leg.qty > 0:
                    close_qty = max(1, int(leg.qty // 2))
                    alert_legs.append(
                        self._build_alert_leg(
                            leg=leg,
                            direction="BUY" if leg.side.value == "SELL" else "SELL",
                            qty=close_qty,
                        )
                    )
                    reductions.append((leg, close_qty))
            if alert_legs:
                result = self._submit_alert(execution_type="EXIT", legs=alert_legs)
                if not self._is_failure_status((result or {}).get("status")):
                    for leg, qty in reductions:
                        leg.qty = max(0, int(leg.qty) - qty)
                        if leg.qty == 0:
                            leg.is_active = False
            logger.info(f"Partial 50% exit for {self.name} — {len(alert_legs)} legs submitted")

    @staticmethod
    def _is_no_position_exit_result(result: Dict[str, Any]) -> bool:
        """Return True when all failed exits are benign 'no position' outcomes."""
        if not isinstance(result, dict):
            return False
        legs = result.get("legs")
        if not isinstance(legs, list) or not legs:
            return False
        saw_failed = False
        for leg in legs:
            if not isinstance(leg, dict):
                return False
            leg_status = str(leg.get("status", "")).upper()
            if leg_status not in ("FAILED", "BLOCKED"):
                continue
            saw_failed = True
            msg = str(leg.get("message", "") or "").upper()
            if "NO POSITION" not in msg and "POSITION NOT FOUND" not in msg:
                return False
        return saw_failed

    def _execute_leg_rule_exit(self, action: str):
        """Execute per-leg exit actions configured in exit.leg_rules."""
        rule = self.exit_engine.last_triggered_leg_rule or {}
        rule_action = str(rule.get("action") or action.replace("leg_rule_", "")).strip().lower()
        targets = self._resolve_leg_rule_targets(rule)
        if not targets:
            logger.warning(f"Leg-rule exit had no active targets: {self.name} action={rule_action}")
            return

        if rule_action == "close_all":
            self._execute_exit("exit_all", source="leg_rule_close_all")
            # ✅ BUG FIX(9): Persist after leg-rule exit so state is clean on disk.
            try:
                self.persistence.save(self.state, str(self.state_file))
            except Exception as _e:
                logger.warning("State persist after leg-rule exit failed for %s: %s", self.name, _e)
            return

        close_qty_map: Dict[str, int] = {}
        if rule_action == "close_leg":
            close_qty_map = {leg.tag: int(leg.qty) for leg in targets}
        elif rule_action == "reduce_50pct":
            close_qty_map = {leg.tag: max(0, int(leg.qty // 2)) for leg in targets}
        elif rule_action == "partial_lots":
            lots = int(rule.get("lots") or rule.get("qty") or 1)
            close_qty_map = {leg.tag: max(0, min(int(leg.qty), lots)) for leg in targets}
        elif rule_action == "roll_next":
            # Roll selected legs to next expiry at same strike/side.
            alert_legs: List[Dict[str, Any]] = []
            updates: List[Tuple[LegState, str, float, float, str]] = []
            for leg in targets:
                if leg.qty <= 0:
                    continue
                close_payload = self._build_alert_leg(
                    leg=leg,
                    direction="BUY" if leg.side.value == "SELL" else "SELL",
                    qty=int(leg.qty),
                )
                alert_legs.append(close_payload)

                if leg.option_type is None or leg.strike is None:
                    continue
                try:
                    new_expiry = self.market.get_next_expiry(leg.expiry, "weekly_next")
                    opt_data = self.market.get_option_at_strike(leg.strike, leg.option_type, new_expiry) or {}
                except Exception as e:
                    logger.error(f"Roll-next lookup failed for {leg.tag}: {e}")
                    continue

                open_payload = self._build_alert_leg(
                    leg=leg,
                    direction=leg.side.value,
                    qty=int(leg.qty),
                    tradingsymbol_override=(
                        opt_data.get("trading_symbol")
                        or opt_data.get("tsym")
                        or opt_data.get("symbol")
                        or leg.trading_symbol
                        or leg.symbol
                    ),
                    price_override=float(opt_data.get("ltp", leg.ltp) or leg.ltp),
                )
                alert_legs.append(open_payload)

                updates.append((
                    leg,
                    new_expiry,
                    float(opt_data.get("ltp", leg.entry_price) or leg.entry_price),
                    float(opt_data.get("ltp", leg.ltp) or leg.ltp),
                    str(open_payload.get("tradingsymbol") or leg.trading_symbol),
                ))

            if alert_legs:
                result = self._submit_alert(execution_type="ADJUSTMENT", legs=alert_legs)
                if not self._is_failure_status((result or {}).get("status")):
                    for leg, new_expiry, new_entry, new_ltp, tsym in updates:
                        leg.expiry = new_expiry
                        leg.entry_price = new_entry
                        leg.ltp = new_ltp
                        if tsym:
                            leg.trading_symbol = tsym
            return
        else:
            logger.warning(f"Unsupported leg rule action '{rule_action}' in strategy {self.name}")
            return

        alert_legs = []
        reductions: List[Tuple[LegState, int]] = []
        for leg in targets:
            qty = int(close_qty_map.get(leg.tag, 0))
            if qty <= 0:
                continue
            alert_legs.append(
                self._build_alert_leg(
                    leg=leg,
                    direction="BUY" if leg.side.value == "SELL" else "SELL",
                    qty=qty,
                )
            )
            reductions.append((leg, qty))

        if alert_legs:
            result = self._submit_alert(execution_type="EXIT", legs=alert_legs)
            if not self._is_failure_status((result or {}).get("status")):
                for leg, qty in reductions:
                    leg.qty = max(0, int(leg.qty) - qty)
                    if leg.qty == 0:
                        leg.is_active = False

    def _resolve_leg_rule_targets(self, rule: Dict[str, Any]) -> List[LegState]:
        ref = rule.get("exit_leg_ref", "all")
        group = rule.get("group")
        if ref == "all":
            return [leg for leg in self.state.legs.values() if leg.is_active]
        if ref == "group" and group:
            return [leg for leg in self.state.legs.values() if leg.is_active and leg.group == group]
        leg = self.state.legs.get(ref)
        if leg and leg.is_active:
            return [leg]
        return []

    def _dispatch_adjustment_orders(self, before_legs: Dict[str, LegState]) -> bool:
        """
        Translate state transitions from adjustment engine into broker orders.
        Returns False when broker rejects the adjustment payload.
        """
        tags = sorted(set(before_legs.keys()) | set(self.state.legs.keys()))
        legs_payload: List[Dict[str, Any]] = []
        close_by_symbol: Dict[str, int] = {}
        open_by_symbol: Dict[str, int] = {}

        for tag in tags:
            before = before_legs.get(tag)
            after = self.state.legs.get(tag)
            before_qty = int(before.qty) if (before and before.is_active) else 0
            # Include PENDING legs that are NEW (not in before_legs) — these are
            # adjustment-created legs awaiting fill dispatch.
            after_qty = int(after.qty) if after and (
                after.is_active or (after.order_status == "PENDING" and before is None)
            ) else 0
            delta = after_qty - before_qty

            if delta < 0:
                ref = before or after
                if ref is None:
                    continue
                payload = self._build_alert_leg(
                    leg=ref,
                    direction="BUY" if ref.side.value == "SELL" else "SELL",
                    qty=abs(delta),
                )
                legs_payload.append(payload)
                sym = str(payload.get("tradingsymbol") or "").strip()
                if sym:
                    close_by_symbol[sym] = close_by_symbol.get(sym, 0) + int(payload.get("qty", 0) or 0)
                # Mark the closing leg for fill tracking so notify_fill can match it
                if after and after.order_status not in ("PENDING",):
                    after.order_status = "CLOSE_PENDING"
                    after.order_placed_at = datetime.now()
            elif delta > 0:
                if after is None:
                    continue
                payload = self._build_alert_leg(
                    leg=after,
                    direction=after.side.value,
                    qty=delta,
                )
                legs_payload.append(payload)
                sym = str(payload.get("tradingsymbol") or "").strip()
                if sym:
                    open_by_symbol[sym] = open_by_symbol.get(sym, 0) + int(payload.get("qty", 0) or 0)

        if not legs_payload:
            return True

        # Smart overlap netting: when close and open resolve to the same
        # symbol (e.g. same-strike no-op from adjustment engine), net the
        # quantities.  Equal qty → remove both (no order needed).
        # Unequal qty → keep only the net difference.
        overlap = sorted(set(close_by_symbol.keys()) & set(open_by_symbol.keys()))
        if overlap:
            for sym in overlap:
                cq = close_by_symbol.get(sym, 0)
                oq = open_by_symbol.get(sym, 0)
                net = oq - cq  # positive = net open, negative = net close
                if net == 0:
                    # Perfect cancel — remove both entries from payload
                    logger.info(
                        "ADJUSTMENT_NOOP_NETTED | strategy=%s | symbol=%s | close=%s open=%s → netted to 0, removing both",
                        self.name, sym, cq, oq,
                    )
                    legs_payload = [
                        lp for lp in legs_payload
                        if str(lp.get("tradingsymbol") or "").strip() != sym
                    ]
                else:
                    # Partial overlap — keep net difference
                    logger.info(
                        "ADJUSTMENT_PARTIAL_NET | strategy=%s | symbol=%s | close=%s open=%s → net=%s",
                        self.name, sym, cq, oq, net,
                    )
                    # Remove all legs for this symbol, then add back the net
                    # Find a representative leg to build from
                    rep_leg = None
                    for lp in legs_payload:
                        if str(lp.get("tradingsymbol") or "").strip() == sym:
                            rep_leg = lp
                            break
                    legs_payload = [
                        lp for lp in legs_payload
                        if str(lp.get("tradingsymbol") or "").strip() != sym
                    ]
                    if rep_leg is not None:
                        net_leg = dict(rep_leg)
                        net_leg["qty"] = abs(net)
                        if net > 0:
                            # Net open: same direction as the opening leg
                            for lp in [l for l in legs_payload]:
                                pass  # already removed
                            # Use the open direction — find original open direction
                            net_leg["direction"] = rep_leg.get("direction", "SELL")
                        else:
                            # Net close: opposite of position side
                            # Use the close direction
                            net_leg["direction"] = rep_leg.get("direction", "BUY")
                        legs_payload.append(net_leg)

            if not legs_payload:
                logger.info(
                    "ADJUSTMENT_ALL_NETTED | strategy=%s | all overlapping legs cancelled out, no orders to send",
                    self.name,
                )
                return True

        result = self._submit_alert(execution_type="ADJUSTMENT", legs=legs_payload)
        return not self._is_failure_status((result or {}).get("status"))

    def _build_alert_leg(
        self,
        leg: LegState,
        direction: str,
        qty: int,
        tradingsymbol_override: Optional[str] = None,
        price_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        identity = self.config.get("identity", {})
        default_order_type = str(identity.get("order_type", "MARKET")).upper()
        order_type = "LIMIT" if default_order_type == "LIMIT" else "MARKET"
        exchange = str(identity.get("exchange", "NFO")).upper()

        tradingsymbol = tradingsymbol_override or leg.trading_symbol or leg.symbol
        # ScriptMaster rule: certain instruments (OPTSTK/OPTFUT) must use LIMIT.
        try:
            if requires_limit_order(exchange=exchange, tradingsymbol=tradingsymbol):
                order_type = "LIMIT"
        except Exception:
            pass

        if price_override is not None:
            price = float(price_override)
        else:
            price = float(leg.ltp) if order_type == "LIMIT" else 0.0

        if tradingsymbol == leg.symbol and leg.instrument == InstrumentType.OPT and leg.strike is not None and leg.option_type is not None:
            try:
                opt_data = self.market.get_option_at_strike(leg.strike, leg.option_type, leg.expiry) or {}
                resolved = opt_data.get("trading_symbol") or opt_data.get("tsym") or opt_data.get("symbol")
                if resolved:
                    tradingsymbol = str(resolved)
                    leg.trading_symbol = tradingsymbol
            except Exception:
                pass
        # ✅ BUG FIX: Resolve futures trading_symbol via ScriptMaster when it was not
        # set during entry (e.g. "NIFTY" -> "NIFTY26MARFUT").  Without this, the
        # broker order is placed with the bare underlying name and gets rejected.
        if tradingsymbol == leg.symbol and leg.instrument == InstrumentType.FUT:
            try:
                from scripts.scriptmaster import get_future
                fut_info = get_future(leg.symbol, exchange, result=0)
                if isinstance(fut_info, dict):
                    resolved = str(fut_info.get("TradingSymbol") or fut_info.get("tsym") or "")
                    if resolved:
                        tradingsymbol = resolved
                        leg.trading_symbol = tradingsymbol
            except Exception:
                pass

        return {
            "tradingsymbol": tradingsymbol,
            "direction": str(direction).upper(),
            "qty": self._lots_to_order_qty(int(qty), leg),
            "order_type": order_type,
            "price": price,
            "product_type": identity.get("product_type", "NRML"),
            # ── Extended leg info for Telegram / audit ──
            "tag": leg.tag,
            "option_type": leg.option_type.value if leg.option_type else None,
            "strike": leg.strike,
            "expiry": leg.expiry,
            "delta": round(leg.delta, 4) if leg.delta else None,
            "iv": round(leg.iv, 2) if leg.iv else None,
            "lots": int(qty),
        }

    def _lots_to_order_qty(self, lots: int, leg: Optional[LegState] = None) -> int:
        """
        Convert lots (internal state unit) to broker order quantity (contract units).
        """
        try:
            normalized_lots = max(0, int(lots))
        except (TypeError, ValueError):
            normalized_lots = 0
        if normalized_lots == 0:
            return 0

        lot_size = 1
        expiry = getattr(leg, "expiry", None) if leg is not None else None
        try:
            resolved = int(self.market.get_lot_size(expiry))
            if resolved > 0:
                lot_size = resolved
        except Exception as e:
            logger.warning("Failed to resolve lot_size for expiry %s: %s, defaulting to 1", expiry, e)
            lot_size = 1
        return normalized_lots * lot_size

    def _submit_alert(self, execution_type: str, legs: List[Dict[str, Any]]) -> Dict[str, Any]:
        identity = self.config.get("identity", {})
        alert = {
            "secret_key": self._resolve_webhook_secret(),
            "execution_type": execution_type,
            "strategy_name": self.name,
            "exchange": identity.get("exchange", "NFO"),
            "legs": legs,
            "test_mode": self._resolve_test_mode(),
        }
        result = self.bot.process_alert(alert)
        if isinstance(result, dict) and self._is_failure_status(result.get("status")):
            logger.error(f"{execution_type} order rejected for {self.name}: {result}")
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _is_failure_status(status: Any) -> bool:
        normalized = str(status or "").strip().upper()
        return normalized in ("FAILED", "BLOCKED", "ERROR")

    def _resolve_webhook_secret(self) -> str:
        """Get webhook secret from bot config or env."""
        bot_cfg = getattr(self.bot, "config", None)
        if bot_cfg and hasattr(bot_cfg, "webhook_secret"):
            return str(bot_cfg.webhook_secret)
        import os
        return os.getenv("WEBHOOK_SECRET_KEY", os.getenv("WEBHOOK_SECRET", ""))

    def _resolve_test_mode(self) -> Optional[str]:
        """Return test_mode if paper mode or test mode is enabled."""
        identity = self.config.get("identity", {})
        if identity.get("paper_mode") or identity.get("test_mode"):
            return "SUCCESS"
        return None
