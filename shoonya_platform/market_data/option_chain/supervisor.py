#!/usr/bin/env python3
# ======================================================================
# 🔒 PRODUCTION FROZEN v3.0
#
# Component : OptionChainSupervisor
# ROLE: Component (non-service)
# OWNERSHIP: ShoonyaBot
# DATE : 06-02-2026
#
# Guarantees:
#   ✔ Single owner of WebSocket feed
#   ✔ ScriptMaster-only expiry resolution
#   ✔ Expiry-day safe (no stale chains)
#   ✔ Supervisor never crashes on chain failure
#   ✔ Deterministic DB lifecycle & cleanup
#   ✔ Feed stall detection WITH recovery
#   ✔ Session-expiry safe with auto re-login
#   ✔ Heartbeat for external monitoring
#   ✔ Graceful degradation on failures
#
# v3.0 Changes:
#   ✅ Fixed: Heartbeat file for process monitoring
#   ✅ Fixed: Feed stall recovery (not just detection)
#   ✅ Fixed: Chain startup retry with backoff
#   ✅ Fixed: Session validation in main loop
#   ✅ Fixed: Chain health monitoring
#   ✅ Fixed: Graceful degradation
#   ✅ Fixed: Periodic ScriptMaster refresh
#   ✅ Fixed: Resource cleanup on errors
#   ✅ Fixed: Safe DB operations
# ======================================================================

from datetime import datetime, timedelta, time as dtime
import time
import threading
import logging
import os
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Any

from shoonya_platform.market_data.option_chain.option_chain import live_option_chain
from shoonya_platform.market_data.option_chain.store import OptionChainStore
from scripts.scriptmaster import refresh_scriptmaster

from shoonya_platform.market_data.feeds.live_feed import (
    restart_feed,
    check_feed_health,
    subscribe_livedata,
)
from shoonya_platform.market_data.instruments.instruments import get_expiry


logger = logging.getLogger(__name__)

# =====================================================================
# CONFIG (PRODUCTION DEFAULTS)
# =====================================================================

DB_BASE_DIR = (
    Path(__file__).resolve().parent / "data"
)

SNAPSHOT_INTERVAL = 1.0          # seconds
DEFAULT_EXPIRIES_PER_SYMBOL = 1  # nearest N expiries (fallback)
# Per-symbol default overrides (customizable):
# NIFTY -> 2 expiries, others -> DEFAULT_EXPIRIES_PER_SYMBOL
SYMBOL_EXPIRY_OVERRIDES: Dict[str, int] = {
    "NIFTY": 2,
}
RETENTION_DAYS = 1               # cleanup policy

# Feed monitoring
FEED_STALL_THRESHOLD = 30        # seconds without DB update → CRITICAL
FEED_RECOVERY_COOLDOWN = 300     # 5 minutes between recovery attempts

# Session monitoring
SESSION_CHECK_INTERVAL = 300     # 5 minutes

# ScriptMaster refresh
SCRIPTMASTER_REFRESH_INTERVAL = 3600  # 1 hour

# Heartbeat
HEARTBEAT_INTERVAL = 5           # seconds

# Chain retry
MAX_CHAIN_RETRY_ATTEMPTS = 3
CHAIN_RETRY_BASE_DELAY = 2       # seconds

# Staleness checks should only run while the exchange session is active.
# Times are interpreted in server local time (IST on EC2 deployment).
EXCHANGE_MARKET_HOURS: Dict[str, Tuple[dtime, dtime]] = {
    "NFO": (dtime(9, 15), dtime(15, 30)),
    "BFO": (dtime(9, 15), dtime(15, 30)),
    "MCX": (dtime(9, 0), dtime(23, 30)),
}

# Default instruments traded most
DEFAULT_INSTRUMENTS = [
    {"exchange": "NFO", "symbol": "NIFTY"},
    {"exchange": "NFO", "symbol": "BANKNIFTY"},
    {"exchange": "MCX", "symbol": "CRUDEOILM"},
]


def _parse_symbol_expiry_overrides(raw: str) -> Dict[str, int]:
    """
    Parse overrides from env string.

    Format:
      OPTION_CHAIN_EXPIRIES_PER_SYMBOL="NIFTY=2,BANKNIFTY=1,DEFAULT=1"
    """
    parsed: Dict[str, int] = {}
    if not raw:
        return parsed

    for token in raw.split(","):
        item = token.strip()
        if not item or "=" not in item:
            continue
        symbol, value = item.split("=", 1)
        key = symbol.strip().upper()
        if not key:
            continue
        try:
            parsed[key] = max(1, int(value.strip()))
        except Exception:
            logger.warning("Invalid expiry override token ignored: %s", item)
    return parsed


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def cleanup_expired_option_chain_dbs(
    base_dir: Path,
    *,
    keep_days: int = 1,
    active_dbs: Optional[set] = None,
) -> None:
    """
    🔥 IMPROVED: Cleanup expired option-chain DB files safely.

    RULES:
    - Must be called ONLY by supervisor
    - Never while live feed is actively writing
    - Skips databases currently in use

    Args:
        base_dir: Directory containing DB files
        keep_days: Keep DBs modified within this many days
        active_dbs: Set of DB paths currently in use (won't delete these)
    """
    cutoff = datetime.now() - timedelta(days=keep_days)
    active_dbs = active_dbs or set()

    for db in base_dir.glob("*.sqlite"):
        try:
            # 🔥 NEW: Skip active databases
            if db in active_dbs:
                logger.debug("Skipping active DB: %s", db.name)
                continue

            mtime = datetime.fromtimestamp(db.stat().st_mtime)
            if mtime < cutoff:
                logger.info("🧹 Removing expired option-chain DB: %s", db)

                # Remove sqlite + WAL + SHM
                for suffix in ("", "-wal", "-shm"):
                    p = db.with_name(db.name + suffix)
                    if p.exists():
                        p.unlink()

        except Exception:
            logger.exception("Failed to cleanup DB: %s", db)


# =====================================================================
# SUPERVISOR
# =====================================================================

class OptionChainSupervisor:
    """
    🔥 v3.0: Production-hardened central authority for live option-chain lifecycle.
    
    New features:
    - Heartbeat monitoring
    - Feed recovery
    - Chain retry logic
    - Session validation
    - Health monitoring
    - Graceful degradation
    """

    def __init__(self, api_client):
        self.api_client = api_client
        self._last_snapshot_ts = None

        self._chains: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        # 🔥 NEW: Failed chain tracking
        self._failed_chains: Dict[str, Tuple[float, int]] = {}
        
        # 🔥 NEW: Heartbeat file
        self._heartbeat_file = DB_BASE_DIR / ".supervisor_heartbeat"
        
        # 🔥 NEW: Recovery tracking
        self._last_feed_recovery = 0.0
        self._feed_stall_count = 0
        
        # Expiry customization:
        # - defaults from code
        # - optional env override per symbol
        # Env format: OPTION_CHAIN_EXPIRIES_PER_SYMBOL="NIFTY=2,DEFAULT=1"
        env_overrides = _parse_symbol_expiry_overrides(
            os.getenv("OPTION_CHAIN_EXPIRIES_PER_SYMBOL", "")
        )
        self._symbol_expiry_overrides: Dict[str, int] = dict(SYMBOL_EXPIRY_OVERRIDES)
        self._symbol_expiry_overrides.update(env_overrides)
        self._default_expiries = max(
            1,
            int(self._symbol_expiry_overrides.get("DEFAULT", DEFAULT_EXPIRIES_PER_SYMBOL)),
        )

    def _get_expiry_count(self, exchange: str, symbol: str) -> int:
        """
        Get configured expiry count for a symbol.
        """
        _ = exchange  # Reserved for future exchange-specific rules.
        key = str(symbol or "").strip().upper()
        return max(1, int(self._symbol_expiry_overrides.get(key, self._default_expiries)))

    def _is_market_session_active(self, exchange: str) -> bool:
        """
        Return True only when the given exchange is in active trading hours.
        """
        exch = str(exchange or "").upper()
        session = EXCHANGE_MARKET_HOURS.get(exch)
        if not session:
            # Unknown exchanges keep permissive behavior (check staleness always).
            return True

        now = datetime.now()
        if now.weekday() >= 5:
            return False

        start_t, end_t = session
        now_t = now.time()
        return start_t <= now_t <= end_t

    # --------------------------------------------------
    # BOOTSTRAP (MARKET OPEN)
    # --------------------------------------------------
    
    def bootstrap_defaults(self) -> None:
        """
        🔥 IMPROVED: Start default option chains with graceful degradation.
        
        Now continues even if some chains fail to start.
        """
        DB_BASE_DIR.mkdir(parents=True, exist_ok=True)

        successful = 0
        failed = 0

        for inst in DEFAULT_INSTRUMENTS:
            exchange = inst["exchange"]
            symbol = inst["symbol"]
            expiry_count = self._get_expiry_count(exchange, symbol)
            logger.info(
                "Bootstrap expiry count | %s %s | expiries=%d",
                exchange,
                symbol,
                expiry_count,
            )

            for i in range(expiry_count):
                try:
                    expiry = get_expiry(
                        exchange=exchange,
                        symbol=symbol,
                        kind="option",
                        index=i,
                    )

                    if not expiry:
                        logger.warning(
                            "No valid option expiry | %s %s | index=%d",
                            exchange, symbol, i
                        )
                        failed += 1
                        continue

                    if self._start_chain(exchange, symbol, expiry):
                        time.sleep(0.5)  # 500ms between chain startups
                        successful += 1
                    else:
                        failed += 1

                except Exception as e:
                    logger.error(
                        "Failed to bootstrap chain | %s %s | %s",
                        exchange, symbol, e
                    )
                    failed += 1
                    continue

        logger.info(
            "✅ Default option chains bootstrapped | "
            f"Success: {successful} | Failed: {failed}"
        )
        
        # 🔥 IMPROVED: Continue even with partial failure
        if successful == 0:
            logger.critical("❌ No chains started successfully!")
        elif failed > 0:
            logger.warning("⚠️ Some chains failed to start")

    # --------------------------------------------------
    # INTERNAL: START ONE CHAIN (WITH RETRY)
    # --------------------------------------------------
    def _start_chain(
        self, 
        exchange: str, 
        symbol: str, 
        expiry: str,
        retry: bool = True,
    ) -> bool:
        key = f"{exchange}:{symbol}:{expiry}"

        with self._lock:
            if key in self._chains:
                return True
            
            if key in self._failed_chains:
                last_attempt, attempt_count = self._failed_chains[key]
                backoff = min(CHAIN_RETRY_BASE_DELAY * (2 ** min(attempt_count, 5)), 60)
                if time.time() - last_attempt < backoff:
                    logger.debug("Chain %s in backoff period", key)
                    return False

        logger.info("🚀 Starting option chain | %s %s | Expiry=%s", exchange, symbol, expiry)

        max_attempts = MAX_CHAIN_RETRY_ATTEMPTS if retry else 1
        
        for attempt in range(1, max_attempts + 1):
            try:
                oc = live_option_chain(
                    api_client=self.api_client,
                    exchange=exchange,
                    symbol=symbol,
                    expiry=expiry,
                    auto_start_feed=False,
                )
                
                db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
                store = OptionChainStore(db_path)

                # ⚠️ CRITICAL: Re-acquire lock and check if another thread beat us
                with self._lock:
                    if key in self._chains:
                        # Another thread already started this chain – clean up ours
                        oc.cleanup()
                        store.close()
                        return True
                    
                    self._chains[key] = {
                        "oc": oc,
                        "store": store,
                        "db_path": db_path,
                        "start_time": time.time(),
                        "last_health_check": time.time(),
                    }
                    self._failed_chains.pop(key, None)
                
                logger.info("✅ Option chain started | %s", key)
                return True

            except Exception as e:
                logger.warning("⚠️ Chain start attempt %d/%d failed | %s | %s", attempt, max_attempts, key, str(e))
                
                if attempt < max_attempts:
                    delay = CHAIN_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.info("Retrying in %.0fs...", delay)
                    time.sleep(delay)
                else:
                    with self._lock:
                        if key in self._failed_chains:
                            _, count = self._failed_chains[key]
                            self._failed_chains[key] = (time.time(), count + 1)
                        else:
                            self._failed_chains[key] = (time.time(), 1)
                    logger.error("❌ Chain failed after %d attempts | %s", max_attempts, key)
                    return False

        return False
    # --------------------------------------------------
    # PUBLIC: ADD CHAIN (DASHBOARD / STRATEGY REQUEST)
    # --------------------------------------------------

    def ensure_chain(
        self,
        *,
        exchange: str,
        symbol: str,
        expiry: str,
    ) -> bool:
        """
        🔥 IMPROVED: Ensure an option chain exists (with retry).
        
        Safe to call repeatedly.
        
        Returns:
            True if chain exists or was started, False otherwise
        """
        return self._start_chain(exchange, symbol, expiry, retry=True)

    # --------------------------------------------------
    # 🔥 NEW: FEED RECOVERY
    # --------------------------------------------------
    def _recover_from_feed_stall(self) -> bool:
        """
        Attempt to recover from feed stall.
        
        Returns:
            True if recovery successful, False otherwise
        """
        now = time.time()
        
        # Cooldown check
        if now - self._last_feed_recovery < FEED_RECOVERY_COOLDOWN:
            logger.debug(
                "Feed recovery cooldown active (%.0fs remaining)",
                FEED_RECOVERY_COOLDOWN - (now - self._last_feed_recovery)
            )
            return False
        
        logger.warning("🔄 Attempting feed recovery...")
        self._last_feed_recovery = now
        
        try:
            if restart_feed(self.api_client):
                logger.info("✅ Feed recovered successfully")
                self._last_snapshot_ts = time.time()
                self._feed_stall_count = 0
                
                # Resubscribe all chains
                self._resubscribe_all_chains()
                
                return True
            else:
                logger.error("❌ Feed recovery failed")
                return False
                
        except Exception as e:
            logger.exception("Feed recovery exception: %s", e)
            return False

    def _resubscribe_all_chains(self) -> None:
        """
        Resubscribe all option tokens for every active chain after feed recovery.
        """
        with self._lock:
            # Copy the list of chains to avoid holding lock while subscribing
            chains = list(self._chains.values())
        
        if not chains:
            logger.debug("No active chains to resubscribe")
            return
        
        logger.info("🔄 Resubscribing %d chains...", len(chains))
        
        # Group tokens by exchange to minimize subscribe calls
        by_exchange = {}
        for bundle in chains:
            oc = bundle["oc"]
            exchange = oc._exchange or oc.get_stats().get("exchange")
            if not exchange:
                logger.warning("Chain missing exchange, skipping resubscription")
                continue
            
            tokens = oc.get_tokens()
            if tokens:
                by_exchange.setdefault(exchange, []).extend(tokens)
        
        # Subscribe each exchange's tokens
        for exchange, tokens in by_exchange.items():
            if tokens:
                logger.debug("Resubscribing %d tokens for %s", len(tokens), exchange)
                try:
                    subscribe_livedata(self.api_client, tokens, exchange=exchange)
                except Exception as e:
                    logger.error("Failed to resubscribe %s tokens: %s", exchange, e)
        
        logger.info("✅ Chain resubscription complete")

    # --------------------------------------------------
    # 🔥 NEW: HEARTBEAT
    # --------------------------------------------------

    def _write_heartbeat(self) -> None:
        """
        🔥 NEW: Write heartbeat file for external monitoring.
        
        ✅ BUG-038 FIX: Write as JSON instead of bare line-per-field format.
        The old format was read by line index (lines[0], lines[1]...) which
        broke silently on any format change.
        """
        try:
            import json
            with self._lock:
                chain_count = len(self._chains)
            
            logged_in = self.api_client.is_logged_in() if self.api_client else False
            last_snap = self._last_snapshot_ts or 0.0

            heartbeat = {
                "timestamp": time.time(),
                "chain_count": chain_count,
                "login_status": "logged_in" if logged_in else "logged_out",
                "last_snapshot": last_snap,
                "stall_count": self._feed_stall_count,
            }

            # Write atomically via temp file
            tmp = str(self._heartbeat_file) + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(heartbeat, f)
            import os
            os.replace(tmp, str(self._heartbeat_file))

        except Exception as exc:
            logger.error("Failed to write heartbeat: %s", exc)

    # --------------------------------------------------
    # 🔥 NEW: CHAIN HEALTH MONITORING
    # --------------------------------------------------

    def _check_chain_health(self, key: str, bundle: Dict) -> bool:
        """
        🔥 NEW: Check if a specific chain is healthy.
        
        Args:
            key: Chain key (exchange:symbol:expiry)
            bundle: Chain bundle dict
            
        Returns:
            True if healthy, False otherwise
        """
        try:
            oc = bundle["oc"]
            
            # Use new health check method from v5.0
            health = oc.get_health_status()
            
            if not health["healthy"]:
                logger.warning(
                    "⚠️ Chain %s unhealthy | Issues: %s | Warnings: %s",
                    key, health.get("issues", []), health.get("warnings", [])
                )
                return False
            
            # Check snapshot staleness only during market session.
            # Outside session, unchanged prices are expected.
            exchange = key.split(":", 1)[0] if ":" in key else ""
            if self._is_market_session_active(exchange):
                if not oc.validate_data_freshness(max_age_seconds=30):
                    logger.warning("⚠️ Chain %s has stale data", key)
                    return False
            
            return True
            
        except Exception as e:
            logger.error("Health check failed for %s: %s", key, e)
            return False

    def _monitor_all_chains(self) -> Dict[str, bool]:
        """
        🔥 NEW: Monitor health of all chains.
        
        Returns:
            Dict mapping chain key to health status
        """
        health_status = {}
        
        with self._lock:
            items = list(self._chains.items())
        
        for key, bundle in items:
            # Only check periodically (every 60 seconds)
            last_check = bundle.get("last_health_check", 0)
            if time.time() - last_check < 60:
                continue
            
            is_healthy = self._check_chain_health(key, bundle)
            health_status[key] = is_healthy
            
            # Update last check time
            with self._lock:
                if key in self._chains:
                    self._chains[key]["last_health_check"] = time.time()
        
        # Log summary if any unhealthy
        unhealthy = [k for k, v in health_status.items() if not v]
        if unhealthy:
            logger.warning(
                "⚠️ %d unhealthy chains: %s",
                len(unhealthy), unhealthy
            )
        
        return health_status

    # --------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------
    
    def run(self) -> None:
        """
        🔥 IMPROVED: Main supervisor loop with comprehensive monitoring.
        
        New features:
        - Heartbeat writing
        - Session validation
        - Feed stall detection + recovery
        - Chain health monitoring
        - Periodic ScriptMaster refresh
        - Graceful error handling
        """
        logger.info("📡 OptionChainSupervisor v3.0 running")

        last_cleanup = 0.0
        last_session_check = 0.0
        last_scriptmaster_refresh = 0.0
        last_heartbeat = 0.0

        try:
            while not self._stop_event.is_set():
                now = time.time()
                
                # --------------------------------------------------
                # 🔥 NEW: HEARTBEAT (every 5 seconds)
                # --------------------------------------------------
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    self._write_heartbeat()
                    last_heartbeat = now

                # --------------------------------------------------
                # 🔥 NEW: SESSION VALIDATION (every 5 minutes)
                # --------------------------------------------------
                if now - last_session_check > SESSION_CHECK_INTERVAL:
                    try:
                        # Validate session via centralized API proxy; avoid calling
                        # login() directly from supervisors. `ensure_session()` will
                        # raise on unrecoverable failures and is safe to call.
                        self.api_client.ensure_session()
                    except Exception as e:
                        logger.exception("Session validation failed: %s", e)
                    last_session_check = now

                # --------------------------------------------------
                # SNAPSHOT WRITES (existing)
                # --------------------------------------------------
                with self._lock:
                    items = list(self._chains.items())

                for key, bundle in items:
                    try:
                        bundle["store"].write_snapshot(bundle["oc"])
                        self._last_snapshot_ts = now
                    except Exception as e:
                        logger.error(
                            "Snapshot write failed | %s | %s", key, e
                        )
                        # 🔥 IMPROVED: Continue with other chains
                        continue

                # --------------------------------------------------
                # 🔥 IMPROVED: FEED STALL DETECTION + RECOVERY
                # --------------------------------------------------
                if (
                    self._last_snapshot_ts is not None
                    and now - self._last_snapshot_ts > FEED_STALL_THRESHOLD
                ):
                    self._feed_stall_count += 1
                    
                    logger.critical(
                        "🚨 OPTION FEED STALLED | "
                        f"No snapshots for {now - self._last_snapshot_ts:.1f}s | "
                        f"Stall count: {self._feed_stall_count}"
                    )
                    
                    # 🔥 NEW: Attempt recovery
                    self._recover_from_feed_stall()

                # --------------------------------------------------
                # 🔥 NEW: CHAIN HEALTH MONITORING
                # --------------------------------------------------
                self._monitor_all_chains()

                # --------------------------------------------------
                # 🔥 NEW: PERIODIC SCRIPTMASTER REFRESH (hourly)
                # --------------------------------------------------
                if now - last_scriptmaster_refresh > SCRIPTMASTER_REFRESH_INTERVAL:
                    try:
                        logger.info("🔄 Refreshing ScriptMaster...")
                        refresh_scriptmaster()
                        logger.info("✅ ScriptMaster refreshed")
                    except Exception as e:
                        logger.error("ScriptMaster refresh failed: %s", e)
                    last_scriptmaster_refresh = now

                # --------------------------------------------------
                # PERIODIC CLEANUP (hourly)
                # --------------------------------------------------
                if now - last_cleanup > 3600:
                    try:
                        # 🔥 IMPROVED: Pass active DBs to avoid deletion
                        with self._lock:
                            active_dbs = {
                                bundle["db_path"]
                                for bundle in self._chains.values()
                            }
                        
                        cleanup_expired_option_chain_dbs(
                            DB_BASE_DIR,
                            keep_days=RETENTION_DAYS,
                            active_dbs=active_dbs,
                        )
                    except Exception:
                        logger.exception("Periodic cleanup failed")
                    last_cleanup = now

                # Sleep
                self._stop_event.wait(SNAPSHOT_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Supervisor interrupted by user")
        except Exception as e:
            logger.exception("Supervisor main loop error: %s", e)
        finally:
            self.shutdown()

    # --------------------------------------------------
    # 🔥 NEW: DIAGNOSTICS
    # --------------------------------------------------

    def get_health_report(self) -> Dict[str, Any]:
        """
        🔥 NEW: Get comprehensive health report.
        
        Returns:
            Dictionary with supervisor health metrics
        """
        with self._lock:
            active_chains = len(self._chains)
            failed_chains = len(self._failed_chains)
        
        logged_in = self.api_client.is_logged_in() if self.api_client else False
        
        # Feed health
        feed_health = None
        try:
            feed_health = check_feed_health()
        except Exception as e:
            logger.error("Feed health check failed: %s", e)
        
        # Snapshot staleness
        stale = False
        if self._last_snapshot_ts:
            age = time.time() - self._last_snapshot_ts
            stale = age > FEED_STALL_THRESHOLD
        
        return {
            "supervisor": {
                "running": not self._stop_event.is_set(),
                "active_chains": active_chains,
                "failed_chains": failed_chains,
            },
            "client": {
                "logged_in": logged_in,
            },
            "feed": {
                "health": feed_health,
                "snapshot_age_seconds": time.time() - self._last_snapshot_ts if self._last_snapshot_ts else None,
                "stale": stale,
                "stall_count": self._feed_stall_count,
            },
            "timestamp": datetime.now().isoformat(),
        }

    def get_chain_status(self, key: str) -> Optional[Dict[str, Any]]:
        """
        🔥 NEW: Get status of a specific chain.
        
        Args:
            key: Chain key (exchange:symbol:expiry)
            
        Returns:
            Status dict or None if not found
        """
        with self._lock:
            if key not in self._chains:
                return None
            
            bundle = self._chains[key]
        
        try:
            oc = bundle["oc"]
            stats = oc.get_stats()
            health = oc.get_health_status()
            
            return {
                "key": key,
                "stats": stats,
                "health": health,
                "db_path": str(bundle["db_path"]),
                "start_time": bundle["start_time"],
                "uptime_seconds": time.time() - bundle["start_time"],
            }
        except Exception as e:
            logger.error("Failed to get chain status for %s: %s", key, e)
            return None

    # --------------------------------------------------
    # SHUTDOWN / CLEANUP
    # --------------------------------------------------

    def shutdown(self) -> None:
        """
        🔥 IMPROVED: Graceful shutdown with enhanced cleanup.
        """
        logger.info("🛑 Supervisor shutting down")

        with self._lock:
            bundles = list(self._chains.values())

        # Close all stores
        for b in bundles:
            try:
                oc = b.get("oc")
                if oc and hasattr(oc, "cleanup"):
                    oc.cleanup()
            except Exception as e:
                logger.error("Error cleaning up option chain: %s", e)
            
            try:
                b["store"].close()
            except Exception as e:
                logger.error("Error closing store: %s", e)

        # Final cleanup
        try:
            with self._lock:
                active_dbs = {
                    bundle["db_path"]
                    for bundle in self._chains.values()
                }
            
            cleanup_expired_option_chain_dbs(
                DB_BASE_DIR,
                keep_days=RETENTION_DAYS,
                active_dbs=active_dbs,
            )
        except Exception as e:
            logger.error("Final cleanup error: %s", e)
        
        # 🔥 NEW: Remove heartbeat file
        try:
            if self._heartbeat_file.exists():
                self._heartbeat_file.unlink()
        except Exception as e:
            logger.error("Failed to remove heartbeat file: %s", e)
        
        logger.info("✅ Shutdown complete")
