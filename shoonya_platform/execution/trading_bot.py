#!/usr/bin/env python3
"""
Trading Bot Module — Hub
Main trading bot class with mixin-based modularisation.

Sub-modules:
  bot_alert_processing    – webhook parsing, intent routing, leg processing
  bot_execution           – process_alert, execute_command, strategy start
  bot_status_scheduling   – scheduler, reports, control consumers, account info
"""
# ======================================================================
# PRODUCTION FROZEN — BOT / OMS LAYER
# Date: 2026-2-03
#
# This file is client-isolated by design.
# Multi-client readiness depends ONLY on:
# - Client-scoped OrderRepository
# - Client-scoped Risk state storage
# - Dashboard command scoping
#
# Guarantees:
#   Single broker touchpoint via CommandService
#   EXIT intents registered only, never executed directly
#   OrderWatcherEngine is sole EXIT executor
#   ScriptMaster governs all order-type rules
#   Duplicate ENTRY blocked at memory, DB, broker & guard levels
#   Recovery-safe across restart, cancel, and partial fills
#
# Architecture:
#   Strategy / Risk → Intent → CommandService → OrderWatcher → Broker
#
# DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import logging
import os
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# -----------------SCRIPTMASTER---------
from scripts.scriptmaster import requires_limit_order  # noqa: F401 (used by mixin)

# ---------------- CORE ----------------
from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient

# ---------------- LOGGING ----------------
from shoonya_platform.logging.logger_config import get_component_logger

# ---------------- NOTIFICATIONS ----------------
from notifications.telegram import TelegramNotifier

# ---------------- PERSISTENCE ----------------
from shoonya_platform.persistence.repository import OrderRepository

# ---------------- RECOVERY ----------------
from shoonya_platform.services.recovery_service import RecoveryBootstrap
from shoonya_platform.services.orphan_position_manager import OrphanPositionManager

# ---------------- EXECUTION ----------------
from shoonya_platform.execution.execution_guard import ExecutionGuard

# ---------------- COMMAND PIPELINE ----------------
from shoonya_platform.execution.command_service import CommandService
from shoonya_platform.execution.order_watcher import OrderWatcherEngine

# ---------------- RISK ----------------
from shoonya_platform.risk.supreme_risk import SupremeRiskManager

# ----------------MODELS--------------
from shoonya_platform.domain.business_models import TradeRecord

# ----------------UTILS--------------
from shoonya_platform.utils.utils import log_exception
from shoonya_platform.utils.text_sanitize import sanitize_text

# ---------------------- dashboard session ----------------
from shoonya_platform.api.dashboard.services.broker_service import BrokerView

# ---------------------- option data writer ----------------
from shoonya_platform.market_data.option_chain.supervisor import OptionChainSupervisor
from shoonya_platform.market_data.feeds.live_feed import start_live_feed
from shoonya_platform.market_data.feeds import index_tokens_subscriber

# ---------------------- strategies runner ----------------
from shoonya_platform.strategy_runner.strategy_executor_service import (
    StrategyExecutorService,
)
from shoonya_platform.strategy_runner.market_reader import MarketReader  # noqa: F401
from shoonya_platform.analytics.historical_service import HistoricalAnalyticsService

# ---------------------- MIXINS ----------------
from shoonya_platform.execution.bot_alert_processing import AlertProcessingMixin
from shoonya_platform.execution.bot_execution import ExecutionMixin
from shoonya_platform.execution.bot_status_scheduling import StatusSchedulingMixin

logger = get_component_logger('trading_bot')


class ShoonyaApiProxy:
    """Thin, thread-safe proxy around ShoonyaClient.

    - Serializes all API calls with a single lock to avoid concurrent hits
    - Enforces session validation for Tier-1 operations
    - Delegates unknown attributes to the underlying client
    """

    TIER1_METHODS = {
        'get_positions',
        'get_limits',
        'get_order_book',
        'get_orderbook',
        'place_order',
        'modify_order',
        'cancel_order',
        'get_account_info',
        'ensure_session',
    }

    def __init__(self, client: ShoonyaClient):
        self._client = client
        self._lock = threading.RLock()
        self._logger = get_component_logger('trading_bot')

    def _call(self, name: str, *args, **kwargs):
        with self._lock:
            try:
                if name in self.TIER1_METHODS:
                    self._client.ensure_session()
            except Exception as e:
                self._logger.error("Session validation failed before %s: %s", name, e)
                raise

            func = getattr(self._client, name)
            try:
                return func(*args, **kwargs)
            except Exception:
                self._logger.error("API call failed: %s", name)
                raise

    def login(self, *args, **kwargs):
        return self._call('login', *args, **kwargs)

    def is_logged_in(self):
        return getattr(self._client, '_logged_in', False)

    def start_websocket(self, *args, **kwargs):
        return self._call('start_websocket', *args, **kwargs)

    def get_positions(self, *args, **kwargs):
        return self._call('get_positions', *args, **kwargs)

    def get_order_book(self, *args, **kwargs):
        if hasattr(self._client, 'get_order_book'):
            return self._call('get_order_book', *args, **kwargs)
        return self._call('get_orderbook', *args, **kwargs)

    def get_limits(self, *args, **kwargs):
        return self._call('get_limits', *args, **kwargs)

    def get_holdings(self, *args, **kwargs):
        return self._call('get_holdings', *args, **kwargs)

    def place_order(self, *args, **kwargs):
        return self._call('place_order', *args, **kwargs)

    def __getattr__(self, item):
        if hasattr(self._client, item) and callable(getattr(self._client, item)):
            def _wrapped(*args, **kwargs):
                return self._call(item, *args, **kwargs)
            return _wrapped
        return getattr(self._client, item)


# ---- module scope (TOP LEVEL) ----
_GLOBAL_BOT = None


def set_global_bot(bot):
    global _GLOBAL_BOT
    _GLOBAL_BOT = bot


def get_global_bot():
    if _GLOBAL_BOT is None:
        raise RuntimeError("ShoonyaBot not initialized")
    return _GLOBAL_BOT


class ShoonyaBot(AlertProcessingMixin, ExecutionMixin, StatusSchedulingMixin):
    """Main trading bot class with integrated Telegram notifications.

    Methods are split across mixins:
      AlertProcessingMixin   – webhook/alert processing, intent routing, leg execution
      ExecutionMixin         – process_alert, execute_command, strategy start
      StatusSchedulingMixin  – scheduler, reports, control consumers, account info
    """

    def __init__(self, config: Optional[Config] = None):
        """Initialize the Shoonya trading bot (PRODUCTION)"""
        logger.info("\U0001f525 ShoonyaBot INIT STARTED")

        # -------------------------------------------------
        # CORE CONFIG
        # -------------------------------------------------
        self.config = config or Config()

        # Canonical client identity (SINGLE SOURCE OF TRUTH)
        self.client_identity = self.config.get_client_identity()
        self.client_id = self.client_identity["client_id"]

        self.trade_records: List[TradeRecord] = []

        # -------------------------------------------------
        # BROKER CLIENT (LAZY LOGIN)
        # -------------------------------------------------
        self.api = ShoonyaClient(self.config)
        self.api_proxy = ShoonyaApiProxy(self.api)

        # -------------------------------------------------
        # TELEGRAM FLAGS (MUST EXIST BEFORE LOGIN)
        # -------------------------------------------------
        self.telegram_enabled = False
        self.telegram = None

        # -------------------------------------------------
        # INITIAL LOGIN (ONCE, BLOCKING)
        # -------------------------------------------------
        login_ok = self.login()
        if not login_ok:
            logger.warning("\u26a0\ufe0f First login failed — waiting 35s for fresh TOTP window and retrying")
            time.sleep(35)
            login_ok = self.login()

        if not login_ok:
            logger.critical("\u274c Broker login failed after 2 attempts — aborting startup")
            raise RuntimeError("BROKER_LOGIN_FAILED")

        # -------------------------------------------------
        # LIVE FEED STARTUP (with retry + re-login)
        # -------------------------------------------------
        feed_started = False
        max_feed_attempts = 3
        for attempt in range(1, max_feed_attempts + 1):
            timeout = 15.0 + (attempt - 1) * 5.0
            logger.info(f"\U0001f504 Feed startup attempt {attempt}/{max_feed_attempts} (timeout={timeout}s)")

            try:
                if start_live_feed(self.api_proxy, timeout=timeout):
                    logger.info("\u2705 Live feed initialized successfully")

                    try:
                        try:
                            index_tokens_subscriber.resolve_futures_tokens(self.api_proxy)
                        except Exception as e:
                            logger.warning(f"\u26a0\ufe0f  MCX futures token resolution failed: {e}")

                        count, symbols = index_tokens_subscriber.subscribe_index_tokens(
                            self.api_proxy
                        )
                        logger.info(f"\U0001f4ca Index tokens subscribed: {count} indices ({symbols})")
                    except Exception as e:
                        logger.warning(f"\u26a0\ufe0f  Index token subscription failed: {e}")

                    feed_started = True
                    break
            except Exception as e:
                logger.warning(f"\u26a0\ufe0f Feed attempt {attempt} exception: {e}")

            if attempt < max_feed_attempts:
                logger.warning(f"\u26a0\ufe0f Feed attempt {attempt} failed, retrying...")
                if not self.api.is_logged_in():
                    logger.info("\U0001f504 Session lost — re-logging before next feed attempt")
                    time.sleep(5)
                    self.login()
                else:
                    time.sleep(3)

        if not feed_started:
            logger.critical("\u274c Failed to start live feed after %d attempts", max_feed_attempts)
            raise RuntimeError("Live feed startup failed — check broker session and network")

        # -------------------------------------------------
        self.broker_view = BrokerView(self.api_proxy)
        self.option_supervisor = OptionChainSupervisor(self.api_proxy)
        self.option_supervisor.bootstrap_defaults()

        def _start_option_supervisor():
            try:
                self.option_supervisor.run()
            except Exception:
                logger.exception("\u274c OptionChainSupervisor crashed")

        self._option_supervisor_thread = threading.Thread(
            target=_start_option_supervisor,
            name="OptionChainSupervisorThread",
            daemon=False,
        )
        self._option_supervisor_thread.start()

        # Strategy executor service
        executor_db = str(
            Path(__file__).resolve().parents[1]
            / "persistence"
            / "data"
            / "strategy_executor_state.db"
        )
        self.strategy_executor_service = StrategyExecutorService(
            bot=self,
            state_db_path=executor_db,
        )
        self.strategy_executor_service.start()
        logger.info("\u2705 StrategyExecutorService initialized and started")
        self.historical_analytics_service = HistoricalAnalyticsService(self)
        self.historical_analytics_service.start()

        # -------------------------------------------------
        # PERSISTENCE
        # -------------------------------------------------
        self.order_repo = OrderRepository(client_id=self.client_id)

        # -------------------------------------------------
        # ORDER WATCHER (SINGLE EXIT AUTHORITY)
        # -------------------------------------------------
        self.order_watcher = OrderWatcherEngine(self)
        self.order_watcher.start()
        logger.info("\U0001f9e0 OrderWatcher thread started")

        # -------------------------------------------------
        # EXECUTION & COMMAND LAYER
        # -------------------------------------------------
        self.execution_guard = ExecutionGuard()

        # STARTUP GUARD RECONCILIATION
        try:
            self._ensure_login()
            self.broker_view.invalidate_cache("positions")
            positions = self.broker_view.get_positions(force_refresh=True) or []
            broker_map: Dict[str, Dict[str, int]] = {}
            for p in positions:
                sym = p.get("tsym")
                net = int(p.get("netqty", 0))
                if not sym or net == 0:
                    continue
                broker_map.setdefault(sym, {"BUY": 0, "SELL": 0})
                if net > 0:
                    broker_map[sym]["BUY"] = net
                else:
                    broker_map[sym]["SELL"] = abs(net)

            if broker_map:
                self.execution_guard.reconcile_with_broker(
                    strategy_id="__STARTUP__",
                    broker_positions=broker_map,
                )
                logger.info(
                    "STARTUP_GUARD_RECONCILE | symbols=%d | %s",
                    len(broker_map),
                    list(broker_map.keys()),
                )
            else:
                logger.info("STARTUP_GUARD_RECONCILE | No live positions at startup")
        except Exception as e:
            logger.warning("STARTUP_GUARD_RECONCILE FAILED | %s — guard starts empty", e)

        self.command_service = CommandService(self)
        self.pending_commands = []
        self._cmd_lock = threading.Lock()
        self._alert_locks: Dict[str, threading.Lock] = {}
        self._alert_locks_guard = threading.Lock()
        self._atomic_locks: Dict[str, threading.Lock] = {}
        self._atomic_locks_guard = threading.Lock()

        # -------------------------------------------------
        # RISK MANAGER
        # -------------------------------------------------
        self.risk_manager = SupremeRiskManager(self)

        # -------------------------------------------------
        # TELEGRAM (OPTIONAL, NON-BLOCKING)
        # -------------------------------------------------
        self.telegram_enabled = self.config.is_telegram_enabled()
        self.telegram = None
        if self.telegram_enabled:
            try:
                telegram_config = self.config.get_telegram_config()
                bot_token = telegram_config.get("bot_token") if telegram_config else None
                chat_id = telegram_config.get("chat_id") if telegram_config else None

                if not bot_token or not chat_id:
                    raise ValueError("Telegram bot_token and chat_id must be configured")

                self.telegram = TelegramNotifier(bot_token, chat_id)
                logger.info("Telegram integration enabled")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram: {e}")
                self.telegram_enabled = False
                self.telegram = None
        else:
            logger.warning("Telegram configuration missing - notifications disabled")

        # -------------------------------------------------
        # STRATEGY REGISTRY (THREAD-SAFE)
        # -------------------------------------------------
        self._live_strategies = {}
        self._live_strategies_lock = threading.Lock()

        # -------------------------------------------------
        # PHASE-2 RECOVERY
        # -------------------------------------------------
        RecoveryBootstrap(self).run()

        # -------------------------------------------------
        # DASHBOARD / API CONTROL CONSUMERS
        # -------------------------------------------------
        self._shutdown_event = threading.Event()
        self.start_control_intent_consumers()

        # -------------------------------------------------
        # STRATEGY RUNNER (CLOCK + DISPATCHER ONLY)
        # -------------------------------------------------
        self.strategy_runner = None
        logger.info("StrategyRunner path disabled; using StrategyExecutorService only")

        # -------------------------------------------------
        # ORPHAN POSITION MANAGER
        # -------------------------------------------------
        self.orphan_manager = OrphanPositionManager(self)
        self.orphan_manager.load_active_rules()
        logger.info("\U0001f514 OrphanPositionManager initialized")

        # -------------------------------------------------
        # SCHEDULER
        # -------------------------------------------------
        self.start_scheduler()
        self._announce_startup_complete()

    def register_live_strategy(self, strategy_name, strategy, market):
        with self._live_strategies_lock:
            logger.warning(
                "register_live_strategy is retired; use start_strategy_executor | strategy=%s",
                strategy_name,
            )

    def _announce_startup_complete(self) -> None:
        """Emit one canonical startup-complete message to logs and Telegram."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client = str(getattr(self, "client_id", "unknown"))
        logger.info(
            "\u2705 BOT STARTUP COMPLETE | client=%s | ts=%s | telegram=%s",
            client,
            ts,
            self.telegram_enabled,
        )
        if self.telegram_enabled:
            try:
                self.send_telegram(
                    "\U0001f680 <b>BOT STARTED</b>\n"
                    f"\U0001f4c5 {ts}\n"
                    f"\U0001f464 Client: <code>{client}</code>\n"
                    "\u2705 Systems initialized and ready"
                )
            except Exception as e:
                logger.warning("Startup Telegram notification failed: %s", e)

    def _announce_shutdown_start(self) -> None:
        """Emit one canonical shutdown-start message to logs and Telegram."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client = str(getattr(self, "client_id", "unknown"))
        logger.info(
            "\U0001f6d1 BOT SHUTDOWN STARTED | client=%s | ts=%s",
            client,
            ts,
        )
        if self.telegram_enabled:
            try:
                self.send_telegram(
                    "\U0001f6d1 <b>BOT SHUTDOWN STARTED</b>\n"
                    f"\U0001f4c5 {ts}\n"
                    f"\U0001f464 Client: <code>{client}</code>\n"
                    "\u2139\ufe0f Graceful shutdown in progress"
                )
            except Exception as e:
                logger.warning("Shutdown-start Telegram notification failed: %s", e)

    def send_telegram(self, message: str) -> bool:
        """Safe wrapper for sending Telegram messages"""
        if self.telegram_enabled and self.telegram:
            try:
                normalized = sanitize_text(message, ascii_only=False)
                return self.telegram.send_message(normalized)
            except Exception as e:
                logger.error(f"Telegram send error: {e}")
                return False
        return False

    def login(self) -> bool:
        """Explicit Shoonya login. Called during service startup or manual re-login."""
        try:
            if self.api.is_logged_in():
                logger.info(
                    "\U0001f510 LOGIN SKIPPED | service=signal_processor | reason=already_logged_in"
                )
                return True

            logger.info(
                "\U0001f510 LOGIN ATTEMPT | service=signal_processor | reason=startup"
            )

            success = self.api.login()

            if success:
                logger.info(
                    "\u2705 LOGIN SUCCESS | service=signal_processor | session_active=True"
                )

                if self.telegram_enabled and self.telegram and self.config.user_id:
                    try:
                        self.telegram.send_login_success(self.config.user_id)
                    except Exception as e:
                        logger.warning(f"Failed to send login success message: {e}")

                return True

            logger.error(
                "\u274c LOGIN FAILED | service=signal_processor | reason=api.login() returned falsy"
            )

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_login_failed("Shoonya login failed")
                except Exception as e:
                    logger.warning(f"Failed to send login failed message: {e}")

            return False

        except Exception as e:
            log_exception("login", e)

            logger.error(
                "\u274c LOGIN EXCEPTION | service=signal_processor | error=%s", e
            )

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_login_failed(str(e))
                except Exception as tg_e:
                    logger.warning(f"Failed to send login failed message: {tg_e}")

            return False

    def is_healthy(self) -> bool:
        """Health check for monitoring.

        Returns True only when the broker API object exists and a
        quick session probe succeeds.  Returns False and logs on
        any failure so issues are observable.
        """
        try:
            if not hasattr(self, 'api'):
                return False
            # Minimal probe: ensure_session returns bool
            if hasattr(self.api, 'ensure_session'):
                return bool(self.api.ensure_session())
            return True
        except Exception as exc:
            logger.warning("is_healthy check failed: %s", exc)
            return False

    def _ensure_login(self):
        """SINGLE SOURCE OF TRUTH FOR SESSION VALIDITY"""
        if not self.api.ensure_session():
            logger.critical(
                "\u274c BROKER SESSION INVALID | auto-recovery failed"
            )
            raise RuntimeError("Broker session invalid and recovery failed")

    def force_login(self) -> bool:
        """Force re-login to API.  Returns the real session outcome."""
        try:
            self.api.logout()
            return bool(self.api.ensure_session())
        except Exception as exc:
            logger.error("force_login failed: %s", exc)
            return False

    def shutdown(self):
        """Shutdown bot gracefully with 30-second timeout"""
        shutdown_start = time.time()
        shutdown_timeout = 30.0

        try:
            self._announce_shutdown_start()
            logger.info("\U0001f6d1 Shutting down bot...")

            # 0. Set global shutdown event FIRST
            self._shutdown_event.set()

            # 1. STOP ORDER WATCHER (BLOCKING)
            try:
                elapsed = time.time() - shutdown_start
                remaining = shutdown_timeout - elapsed
                if remaining > 5:
                    logger.info(f"\u23f3 Stopping OrderWatcher (timeout={remaining:.1f}s)")
                    self.order_watcher.stop()
                else:
                    logger.warning("\u26a0\ufe0f OrderWatcher shutdown timeout - skipping")
            except Exception as e:
                logger.error(f"\u274c OrderWatcher shutdown error: {e}")

            # 2. NOTIFY SUPERVISOR
            if hasattr(self, "option_supervisor"):
                try:
                    self.option_supervisor._stop_event.set()
                    logger.info("Option supervisor stop signal sent")
                except Exception as e:
                    logger.error(f"Option supervisor signal error: {e}")

            # 3. STOP STRATEGY RUNNER
            runner = getattr(self, "strategy_runner", None)
            if runner is not None and hasattr(runner, "stop"):
                try:
                    elapsed = time.time() - shutdown_start
                    remaining = shutdown_timeout - elapsed
                    if remaining > 5:
                        logger.info(f"\u23f3 Stopping StrategyRunner (timeout={remaining:.1f}s)")
                        runner.stop(timeout=int(remaining))
                    else:
                        logger.warning("\u26a0\ufe0f StrategyRunner shutdown timeout - skipping")
                except Exception as e:
                    logger.error(f"\u274c StrategyRunner shutdown error: {e}")

            # Stop strategy executor service
            if hasattr(self, "strategy_executor_service"):
                try:
                    logger.info("\u23f3 Stopping StrategyExecutorService")
                    self.strategy_executor_service.stop()
                    logger.info("\u2705 StrategyExecutorService stopped")
                except Exception as e:
                    logger.error(f"StrategyExecutorService shutdown error: {e}")

            if hasattr(self, "historical_analytics_service"):
                try:
                    logger.info("\u23f3 Stopping HistoricalAnalyticsService")
                    self.historical_analytics_service.stop()
                    logger.info("\u2705 HistoricalAnalyticsService stopped")
                except Exception as e:
                    logger.error(f"HistoricalAnalyticsService shutdown error: {e}")

            # 4. TELEGRAM SHUTDOWN (NON-BLOCKING)
            if self.telegram_enabled:
                try:
                    def send_shutdown_msg():
                        try:
                            shutdown_msg = (
                                f"\U0001f6d1 <b>BOT SHUTDOWN</b>\n"
                                f"\U0001f4c5 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"\U0001f916 Graceful shutdown complete\n"
                                f"\U0001f4ca Session stats:\n"
                                f"\u2022 Total trades: {len(self.trade_records)}\n"
                                f"\u2022 Uptime: Until shutdown"
                            )
                            self.telegram.send_message(shutdown_msg, timeout=3.0)
                        except Exception as tg_e:
                            logger.debug(f"Telegram send timeout (expected): {tg_e}")

                    tg_thread = threading.Thread(target=send_shutdown_msg, daemon=True)
                    tg_thread.start()
                except Exception as e:
                    logger.debug(f"Telegram notification skipped: {e}")

            # 5. LOGOUT FROM API
            try:
                elapsed = time.time() - shutdown_start
                remaining = shutdown_timeout - elapsed
                if remaining > 2:
                    logger.info(f"\u23f3 Logging out from broker (timeout={remaining:.1f}s)")
                    self.api.logout()
                else:
                    logger.warning("\u26a0\ufe0f API logout timeout - skipping")
            except Exception as e:
                logger.debug(f"API logout error (expected): {e}")

            elapsed = time.time() - shutdown_start
            logger.info(f"\u2705 Bot shutdown completed in {elapsed:.1f}s")

        except Exception as e:
            elapsed = time.time() - shutdown_start
            logger.error(f"\u274c Shutdown error after {elapsed:.1f}s: {e}")
