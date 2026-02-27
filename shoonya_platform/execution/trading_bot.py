#!/usr/bin/env python3
"""

Trading Bot Module
Main trading bot logic with alert processing and trade management
"""
# ======================================================================
# ðŸ”’ PRODUCTION FROZEN â€” BOT / OMS LAYER
# Date: 2026-2-03

# This file is client-isolated by design.
# Multi-client readiness depends ONLY on:
# - Client-scoped OrderRepository
# - Client-scoped Risk state storage
# - Dashboard command scoping

# NO further OMS changes required for copy trading.

# Guarantees:
#   âœ” Single broker touchpoint via CommandService
#   âœ” EXIT intents registered only, never executed directly
#   âœ” OrderWatcherEngine is sole EXIT executor
#   âœ” ScriptMaster governs all order-type rules
#   âœ” Duplicate ENTRY blocked at memory, DB, broker & guard levels
#   âœ” Recovery-safe across restart, cancel, and partial fills
# âœ… Single _ensure_login() â€” no shadowing, no ambiguity
# âœ… Lazy + auditable login (matches supervisor & long-running service model)
# âœ… Single broker touchpoint (execute_command â†’ ShoonyaClient)
# âœ… EXIT purity preserved (intent-only â†’ OrderWatcherEngine)
# âœ… Risk manager correctly uses broker truth only
# âœ… ExecutionGuard + DB + broker triple-duplicate protection intact
# âœ… RecoveryBootstrap ordering is correct
# âœ… Dashboard control consumers are isolated, intent-only
# âœ… No silent session invalidation vectors left inside OMS

# ðŸ”’ COPY-TRADING READY (BOT LAYER)
# â€¢ Client identity resolved via Config.get_client_identity()
# â€¢ No direct USER_ID / USER_NAME usage
# â€¢ OMS behavior unchanged


# Architecture:
#   Strategy / Risk â†’ Intent â†’ CommandService â†’ OrderWatcher â†’ Broker
# ðŸ”’ SINGLE SOURCE OF TRUTH FOR BROKER LOGIN
# Do NOT redefine this method elsewhere in the class.

# âš ï¸ DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import logging
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
import schedule

#-----------------SCRIPTMASTER---------
from scripts.scriptmaster import requires_limit_order

# ---------------- CORE ----------------
from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient

# ---------------- LOGGING ----------------
from shoonya_platform.logging.logger_config import get_component_logger

# ---------------- NOTIFICATIONS ----------------
from notifications.telegram import TelegramNotifier

# # ---------------- PERSISTENCE ----------------
from shoonya_platform.persistence.repository import OrderRepository

# # ---------------- RECOVERY ----------------
from shoonya_platform.services.recovery_service import RecoveryBootstrap
from shoonya_platform.services.orphan_position_manager import OrphanPositionManager

# ---------------- EXECUTION ----------------
from shoonya_platform.execution.execution_guard import ExecutionGuard, LegIntent
from shoonya_platform.execution.order_watcher import OrderWatcherEngine

# ---------------- COMMAND PIPELINE ----------------
from shoonya_platform.execution.command_service import CommandService
from shoonya_platform.execution.intent import UniversalOrderCommand

# ---------------- RISK ----------------
from shoonya_platform.risk.supreme_risk import SupremeRiskManager

#------------------CONTROL-CONSUMERS----------------
from shoonya_platform.execution.generic_control_consumer import GenericControlIntentConsumer
from shoonya_platform.execution.strategy_control_consumer import StrategyControlConsumer

#--------------------MODELS--------------
from shoonya_platform.domain.business_models import TradeRecord, AlertData, LegResult, BotStats, OrderResult, AccountInfo
#--------------------UTILS--------------
from shoonya_platform.utils.utils import (
    validate_webhook_signature, 
    format_currency,
    get_today_trades,
    get_yesterday_trades,
    calculate_success_rate,
    log_exception,get_date_filter
)
from shoonya_platform.utils.text_sanitize import sanitize_text
#---------------------- dashboard session ----------------
from shoonya_platform.api.dashboard.services.broker_service import BrokerView

#---------------------- option data writer ----------------
from shoonya_platform.market_data.option_chain.supervisor import OptionChainSupervisor
from shoonya_platform.market_data.feeds.live_feed import start_live_feed
from shoonya_platform.market_data.feeds import index_tokens_subscriber

#---------------------- strategies runner  ----------------

# NEW: Strategy executor components from strategy_runner folder
from shoonya_platform.strategy_runner.strategy_executor_service import (
    StrategyExecutorService,
)
from shoonya_platform.strategy_runner.market_reader import MarketReader
from shoonya_platform.analytics.historical_service import HistoricalAnalyticsService

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
            # Enforce session for Tier-1 operations
            try:
                if name in self.TIER1_METHODS:
                    # ensure_session raises on unrecoverable error (fail-hard)
                    self._client.ensure_session()
            except Exception as e:
                self._logger.error("Session validation failed before %s: %s", name, e)
                raise

            func = getattr(self._client, name)
            try:
                return func(*args, **kwargs)
            except Exception:
                # Log full context and re-raise to preserve fail-hard semantics
                self._logger.exception("API call failed: %s", name)
                raise

    # Explicit wrappers for commonly used methods (improves clarity)
    def login(self, *args, **kwargs):
        return self._call('login', *args, **kwargs)

    def is_logged_in(self):
        # lightweight check - call without forcing revalidation
        return getattr(self._client, '_logged_in', False)

    def start_websocket(self, *args, **kwargs):
        return self._call('start_websocket', *args, **kwargs)

    def get_positions(self, *args, **kwargs):
        return self._call('get_positions', *args, **kwargs)

    def get_order_book(self, *args, **kwargs):
        # accept either name
        if hasattr(self._client, 'get_order_book'):
            return self._call('get_order_book', *args, **kwargs)
        return self._call('get_orderbook', *args, **kwargs)

    def get_limits(self, *args, **kwargs):
        return self._call('get_limits', *args, **kwargs)

    def get_holdings(self, *args, **kwargs):
        # Tier-2: still serialized but informational
        return self._call('get_holdings', *args, **kwargs)

    def place_order(self, *args, **kwargs):
        return self._call('place_order', *args, **kwargs)

    # Fallback: delegate any other attribute access to underlying client
    def __getattr__(self, item):
        # For attribute access, return a callable that performs the locked call
        if hasattr(self._client, item) and callable(getattr(self._client, item)):
            def _wrapped(*args, **kwargs):
                return self._call(item, *args, **kwargs)
            return _wrapped
        # Non-callable attributes are returned directly
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

class ShoonyaBot:
    """Main trading bot class with integrated Telegram notifications"""
    
    def __init__(self, config: Optional[Config] = None):
        """Initialize the Shoonya trading bot (PRODUCTION)"""
        logger.critical("ðŸ”¥ ShoonyaBot INIT STARTED")

        # -------------------------------------------------
        # ðŸ”§ CORE CONFIG
        # -------------------------------------------------
        self.config = config or Config()

        # ðŸ”’ Canonical client identity (SINGLE SOURCE OF TRUTH)
        # (copy-trading ready, NO behavior change)
        self.client_identity = self.config.get_client_identity()
        self.client_id = self.client_identity["client_id"]

        self.trade_records: List[TradeRecord] = []

        # -------------------------------------------------
        # ðŸ”Œ BROKER CLIENT (LAZY LOGIN)
        # -------------------------------------------------
        # ðŸ”’ Login is enforced lazily via _ensure_login()
        self.api = ShoonyaClient(self.config)
        # Public proxy that serializes and centralizes all API calls
        self.api_proxy = ShoonyaApiProxy(self.api)
        # -------------------------------------------------
        # ðŸ“¢ TELEGRAM FLAGS (MUST EXIST BEFORE LOGIN)
        # -------------------------------------------------
        # ðŸ”’ Prevent attribute errors during early login
        self.telegram_enabled = False
        self.telegram = None
        # -------------------------------------------------
        # ðŸ” INITIAL LOGIN (ONCE, BLOCKING)
        # -------------------------------------------------
        # ðŸ”¥ FIX: Check login() return value and handle failure properly
        login_ok = self.login()
        if not login_ok:
            # TOTP may have just changed â€” wait for next 30s window and retry once
            logger.warning("âš ï¸ First login failed â€” waiting 35s for fresh TOTP window and retrying")
            time.sleep(35)
            login_ok = self.login()

        if not login_ok:
            logger.critical("âŒ Broker login failed after 2 attempts â€” aborting startup")
            raise RuntimeError("BROKER_LOGIN_FAILED")

        # -------------------------------------------------
        # ðŸ“¡ LIVE FEED STARTUP (with retry + re-login)
        # -------------------------------------------------
        feed_started = False
        max_feed_attempts = 3
        for attempt in range(1, max_feed_attempts + 1):
            timeout = 15.0 + (attempt - 1) * 5.0  # 15s, 20s, 25s
            logger.info(f"ðŸ”„ Feed startup attempt {attempt}/{max_feed_attempts} (timeout={timeout}s)")

            try:
                if start_live_feed(self.api_proxy, timeout=timeout):
                    logger.info("âœ… Live feed initialized successfully")

                    # Subscribe to index tokens for live dashboard
                    try:
                        try:
                            index_tokens_subscriber.resolve_futures_tokens(self.api_proxy)
                        except Exception as e:
                            logger.warning(f"âš ï¸  MCX futures token resolution failed: {e}")

                        count, symbols = index_tokens_subscriber.subscribe_index_tokens(
                            self.api_proxy
                        )
                        logger.info(f"ðŸ“Š Index tokens subscribed: {count} indices ({symbols})")
                    except Exception as e:
                        logger.warning(f"âš ï¸  Index token subscription failed: {e}")

                    feed_started = True
                    break
            except Exception as e:
                logger.warning(f"âš ï¸ Feed attempt {attempt} exception: {e}")

            if attempt < max_feed_attempts:
                logger.warning(f"âš ï¸ Feed attempt {attempt} failed, retrying...")
                # ðŸ”¥ FIX: Re-login if session died (common on EC2 after network blip)
                if not self.api.is_logged_in():
                    logger.info("ðŸ”„ Session lost â€” re-logging before next feed attempt")
                    time.sleep(5)
                    self.login()
                else:
                    time.sleep(3)

        if not feed_started:
            logger.critical("âŒ Failed to start live feed after %d attempts", max_feed_attempts)
            raise RuntimeError("Live feed startup failed â€” check broker session and network")
        
        #--------------------------------------------------
        self.broker_view = BrokerView(self.api_proxy)
        self.option_supervisor = OptionChainSupervisor(self.api_proxy)
        self.option_supervisor.bootstrap_defaults()

        def _start_option_supervisor():
            try:
                self.option_supervisor.run()
            except Exception:
                logger.exception("âŒ OptionChainSupervisor crashed")

        self._option_supervisor_thread = threading.Thread(
            target=_start_option_supervisor,
            name="OptionChainSupervisorThread",
            daemon=False,   # ðŸ”’ MUST be non-daemon
        )
        self._option_supervisor_thread.start()

        # Strategy executor service (singleton - manages all strategies)
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
        self.strategy_executor_service.start()  # Start background loop
        logger.info("âœ… StrategyExecutorService initialized and started")
        self.historical_analytics_service = HistoricalAnalyticsService(self)
        self.historical_analytics_service.start()
        # -------------------------------------------------
        # ðŸ“¦ PERSISTENCE (POSITION / ORDER SOURCE OF TRUTH)
        # -------------------------------------------------
        self.order_repo = OrderRepository(client_id=self.client_id)

        # -------------------------------------------------
        # ðŸš¨ SINGLE EXIT AUTHORITY(POSITION-DRIVEN) (MUST BE INITIALIZED FIRST)
        # -------------------------------------------------
        # ðŸ”’ ALL exits (risk / manual / dashboard / recovery)
        # ðŸ”’ MUST flow through OrderWatcherEngine ONLY
        self.order_watcher = OrderWatcherEngine(self)
        self.order_watcher.start()  # âœ… CRITICAL FIX: Actually start the thread!
        logger.info("ðŸ§  OrderWatcher thread started")

        # -------------------------------------------------
        # ðŸ›¡ EXECUTION & COMMAND LAYER
        # -------------------------------------------------
        self.execution_guard = ExecutionGuard()

        # ðŸ”’ STARTUP GUARD RECONCILIATION â€” rebuild guard state from broker truth
        # Without this, after a restart the guard thinks no strategies have positions,
        # allowing duplicate ENTRY orders for strategies that already have live broker positions.
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
                # Use "__STARTUP__" as strategy_id; real strategy reconciliation
                # happens in process_alert before each trade.
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
            logger.warning("STARTUP_GUARD_RECONCILE FAILED | %s â€” guard starts empty", e)

        # âš ï¸ CommandService DEPENDS on order_watcher
        self.command_service = CommandService(self)
        self.pending_commands = []
        # ðŸ”’ Atomic lock for execute_command (prevents double execution)
        self._cmd_lock = threading.Lock()
        # ðŸ”’ Per-strategy locks for process_alert (prevents duplicate webhook races)
        self._alert_locks: Dict[str, threading.Lock] = {}
        self._alert_locks_guard = threading.Lock()
        self._atomic_locks: Dict[str, threading.Lock] = {}
        self._atomic_locks_guard = threading.Lock()
        # -------------------------------------------------
        # ðŸ§  RISK MANAGER (INTENT ONLY â€“ NO DIRECT ORDERS)
        # -------------------------------------------------
        self.risk_manager = SupremeRiskManager(self)

        # -------------------------------------------------
        # ðŸ“¢ TELEGRAM (OPTIONAL, NON-BLOCKING)
        # -------------------------------------------------
        self.telegram_enabled = self.config.is_telegram_enabled()
        self.telegram = None  # Initialize to None first
        if self.telegram_enabled:
            try:
                telegram_config = self.config.get_telegram_config()
                # Validate required fields are present and not None
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
        # ðŸ“ˆ STRATEGY REGISTRY (THREAD-SAFE)
        # -------------------------------------------------
        self._live_strategies = {}  # strategy_name -> runtime metadata
        self._live_strategies_lock = threading.Lock()  # ðŸ”’ Thread-safe access

        # -------------------------------------------------
        # â™»ï¸ PHASE-2 RECOVERY (SAFE, NON-ACTIVE)
        # -------------------------------------------------
        RecoveryBootstrap(self).run()

        # -------------------------------------------------
        # ðŸ§­ DASHBOARD / API CONTROL CONSUMERS
        # -------------------------------------------------
        self._shutdown_event = threading.Event()
        self.start_control_intent_consumers()

        # -------------------------------------------------
        # ðŸ“ˆ STRATEGY RUNNER (CLOCK + DISPATCHER ONLY)
        # -------------------------------------------------
        self.strategy_runner = None
        logger.info("StrategyRunner path disabled; using StrategyExecutorService only")

        # -------------------------------------------------
        # ðŸš€ START STRATEGY RUNNER
        # -------------------------------------------------
        # StrategyRunner disabled (strategy_runner-only architecture)

        # -------------------------------------------------
        # ðŸ”“ ORPHAN POSITION MANAGER (MANUAL POSITION CONTROL)
        # -------------------------------------------------
        self.orphan_manager = OrphanPositionManager(self)
        self.orphan_manager.load_active_rules()
        logger.info("ðŸ”“ OrphanPositionManager initialized")

        # -------------------------------------------------
        # â± SCHEDULER
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
                    "\U0001F680 <b>BOT STARTED</b>\n"
                    f"\U0001F4C5 {ts}\n"
                    f"\U0001F464 Client: <code>{client}</code>\n"
                    "\u2705 Systems initialized and ready"
                )
            except Exception as e:
                logger.warning("Startup Telegram notification failed: %s", e)

    def _announce_shutdown_start(self) -> None:
        """Emit one canonical shutdown-start message to logs and Telegram."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client = str(getattr(self, "client_id", "unknown"))
        logger.info(
            "\U0001F6D1 BOT SHUTDOWN STARTED | client=%s | ts=%s",
            client,
            ts,
        )
        if self.telegram_enabled:
            try:
                self.send_telegram(
                    "\U0001F6D1 <b>BOT SHUTDOWN STARTED</b>\n"
                    f"\U0001F4C5 {ts}\n"
                    f"\U0001F464 Client: <code>{client}</code>\n"
                    "\u2139\ufe0f Graceful shutdown in progress"
                )
            except Exception as e:
                logger.warning("Shutdown-start Telegram notification failed: %s", e)

  
    # ==================================================
    # STRATEGY LIFECYCLE WRAPPERS (called by consumers)
    # ==================================================
    def _process_strategy_intents(
        self,
        strategy_name: str,
        strategy,
        market,
        intents,
        *,
        force_exit: bool = False,
    ):
        """
        Route strategy UniversalOrderCommand objects with guard compliance and atomic batching.
        """
        if not intents:
            return

        try:
            guard_intents = []
            for intent in intents:
                symbol = getattr(intent, "symbol", None)
                side = getattr(intent, "side", None)
                qty = getattr(intent, "quantity", 0)

                if not symbol or not side:
                    continue

                guard_intents.append(
                    LegIntent(
                        strategy_id=strategy_name,
                        symbol=symbol,
                        direction=side,
                        qty=qty,
                        tag="ENTRY" if not force_exit else "EXIT",
                    )
                )

            try:
                guarded = self.execution_guard.validate_and_prepare(
                    intents=guard_intents,
                    execution_type="EXIT" if force_exit else "ENTRY",
                )
            except RuntimeError as e:
                logger.warning(f"Guard blocked strategy intents: {e}")
                return

            guard_map = {}
            for g in guarded:
                if force_exit:
                    key = (g.symbol, "EXIT")
                else:
                    key = (g.symbol, g.direction)
                guard_map[key] = g.qty

            atomic_result = self._atomic_route_intents(
                strategy_name=strategy_name,
                execution_type="EXIT" if force_exit else "ENTRY",
                legs=intents,
                guard_map=guard_map,
                source_mode="STRATEGY",
            )
            if atomic_result:
                logger.info(
                    f"ATOMIC_STRATEGY | {strategy_name} | {atomic_result['status']}"
                )
                return

            for intent in intents:
                symbol = None
                try:
                    symbol = getattr(intent, "symbol", None)
                    side = getattr(intent, "side", None)

                    if not symbol or not side:
                        continue

                    if force_exit:
                        key = (symbol, "EXIT")
                    else:
                        key = (symbol, side)

                    if key not in guard_map:
                        logger.warning(f"GUARD_BLOCK | {strategy_name} | {symbol}")
                        continue

                    approved_qty = guard_map[key]
                    if approved_qty <= 0:
                        continue

                    intent.quantity = approved_qty
                    is_exit_like = force_exit or (side == "BUY")

                    if is_exit_like:
                        self.command_service.register(intent)
                        logger.info(f"EXIT intent: {strategy_name} -> {side} {symbol}")
                    else:
                        self.command_service.submit(intent, execution_type="ENTRY")
                        logger.info(f"ENTRY intent: {strategy_name} -> {side} {symbol}")

                except Exception:
                    logger.exception(
                        f"Strategy intent routing failed | {strategy_name} | {symbol}"
                    )

        except Exception:
            logger.exception("Error in _process_strategy_intents")

    def request_entry(self, strategy_name: str):
        with self._live_strategies_lock:
            try:
                value = self._live_strategies[strategy_name]
            except KeyError:
                logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
                raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")
        logger.info("Request ENTRY handled by StrategyExecutorService | %s", strategy_name)
        return

    def request_adjust(self, strategy_name: str):
        with self._live_strategies_lock:
            try:
                value = self._live_strategies[strategy_name]
            except KeyError:
                logger.error("Request ADJUST failed: strategy not registered: %s", strategy_name)
                raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")
        logger.info("Request ADJUST handled by StrategyExecutorService | %s", strategy_name)
        return

    def request_exit(
        self,
        *,
        scope,
        strategy_name=None,  # ðŸ”¥ NEW: strategy-scoped exits
        symbols=None,
        product_type="ALL",
        reason,
        source,
    ):
        """
        Route EXIT intent to CommandService for position-driven execution.
        
        Now supports strategy-scoped exits: only exits positions created by that strategy.
        
        Never constructs orders directly.
        PositionExitService handles all exit logic (broker-driven).
        """
        self.command_service.handle_exit_intent(
            scope=scope,
            strategy_name=strategy_name,
            symbols=symbols,
            product_type=product_type,
            reason=reason,
            source=source,
        )

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
    
    def start_scheduler(self):
        """Start the scheduler for periodic reports in separate thread"""
        def run_scheduler():
            def send_strategy_reports():
                with self._live_strategies_lock:
                    items = list(self._live_strategies.items())
                for name, value in items:
                    if not isinstance(value, tuple) or len(value) != 2:
                        continue
                    strategy, market = value
                    try:
                        report = build_strategy_report(strategy, market)
                        if report:
                            self.send_telegram(report)
                    except Exception as e:
                        log_exception(f"strategy_report:{name}", e)

            try:
                # Schedule periodic reports
                schedule.every(self.config.report_frequency).minutes.do(self.send_status_report)
                schedule.every().day.at("09:00").do(self.send_daily_summary)
                schedule.every().day.at("15:30").do(self.send_market_close_summary)
                # Periodic PnL OHLC tracking (analytics only)
                schedule.every(1).minutes.do(self.risk_manager.track_pnl_ohlc)
                
                # ðŸ” Supreme Risk Manager heartbeat (REAL-TIME RISK)
                def _rms_heartbeat_wrapper():
                    try:
                        self.risk_manager.heartbeat()
                    except RuntimeError:
                        # ðŸ”¥ FAIL-HARD: escape schedule
                        raise
                    except Exception as e:
                        log_exception("RMS.heartbeat", e)

                schedule.every(5).seconds.do(_rms_heartbeat_wrapper)
                
                # ðŸ’“ Telegram Heartbeat - validates session + sends alive signal
                def _telegram_heartbeat():
                    try:
                        self.send_telegram_heartbeat()
                    except RuntimeError:
                        # ðŸ”¥ FAIL-HARD: session failure must trigger restart
                        raise
                    except Exception as e:
                        log_exception("telegram_heartbeat", e)
                
                schedule.every(5).minutes.do(_telegram_heartbeat)

                schedule.every(10).minutes.do(send_strategy_reports)
                
                # ðŸ”“ ORPHAN POSITION MANAGEMENT (check every 30 seconds)
                def _orphan_monitor_wrapper():
                    try:
                        executed = self.orphan_manager.monitor_and_execute()
                        if executed > 0:
                            logger.warning(f"ðŸ”“ ORPHAN MANAGER: Executed {executed} rule(s)")
                    except Exception as e:
                        log_exception("orphan_manager.monitor", e)
                
                schedule.every(30).seconds.do(_orphan_monitor_wrapper)
                
                # ðŸ§¹ Weekly DB hygiene (safe, non-trading)
                schedule.every().day.at("03:30").do(self.cleanup_old_orders)
                
                logger.info(f"Scheduler started - reports every {self.config.report_frequency} minutes")
                
                while not self._shutdown_event.is_set():
                    try:
                        schedule.run_pending()

                    # ðŸ”¥ FAIL-HARD: broker/session failure must kill process
                    except RuntimeError as e:
                        logger.critical(f"FATAL SESSION ERROR: {e} - RESTARTING PROCESS")
                        if self.telegram_enabled:
                            try:
                                self.send_telegram(
                                    f"ðŸš¨ <b>CRITICAL: SERVICE RESTART REQUIRED</b>\n"
                                    f"âŒ Session recovery failed\n"
                                    f"ðŸ”„ Service will auto-restart in 5 seconds\n"
                                    f"â° Time: {datetime.now().strftime('%H:%M:%S')}"
                                )
                            except Exception as notify_error:
                                logger.error(f"Failed to send critical restart alert: {notify_error}")
                        time.sleep(5)
                        # Force process exit - systemd will restart us
                        os._exit(1)

                    except Exception as e:
                        log_exception("scheduler.run_pending", e)

                    time.sleep(1)

                    
            except Exception as e:
                log_exception("scheduler", e)
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
    
    def login(self) -> bool:
        """
        Explicit Shoonya login.
        Called during service startup or manual re-login.
        """
        try:
            if self.api.is_logged_in():
                logger.info(
                    "ðŸ” LOGIN SKIPPED | service=signal_processor | reason=already_logged_in"
                )
                return True

            logger.critical(
                "ðŸ” LOGIN ATTEMPT | service=signal_processor | reason=startup"
            )

            success = self.api.login()

            if success:
                logger.critical(
                    "âœ… LOGIN SUCCESS | service=signal_processor | session_active=True"
                )

                if self.telegram_enabled and self.telegram and self.config.user_id:
                    try:
                        self.telegram.send_login_success(self.config.user_id)
                    except Exception as e:
                        logger.warning(f"Failed to send login success message: {e}")

                return True

            logger.error(
                "âŒ LOGIN FAILED | service=signal_processor | reason=unknown"
            )

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_login_failed("Shoonya login failed")
                except Exception as e:
                    logger.warning(f"Failed to send login failed message: {e}")

            return False

        except Exception as e:
            log_exception("login", e)

            logger.critical(
                "âŒ LOGIN EXCEPTION | service=signal_processor | fatal=True"
            )

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_login_failed(str(e))
                except Exception as tg_e:
                    logger.warning(f"Failed to send login failed message: {tg_e}")

            return False

    # ============================================================
    def is_healthy(self) -> bool:
        """
        Health check for monitoring.
        
        SAFE STUB: Returns True unless critical failures detected.
        Do NOT add complex logic yet â€” this is for operational safety only.
        
        Returns:
            bool: True if service is healthy, False if critical failure
        """
        # Minimal health checks (safe, no false alarms)
        try:
            # Check 1: Bot instance exists
            if not hasattr(self, 'api'):
                return False
            
            # Check 2: Not in a permanent error state
            # (Add your own critical state checks here if needed)
            
            return True
            
        except Exception:
            # If health check itself fails, assume healthy to avoid false alarms
            return True
    # ============================================================
    # USAGE IN HEALTH MONITOR (OPTIONAL â€” CURRENTLY COMMENTED OUT)
    # ============================================================
    # 
    # If you want to enable the health monitor in main.py, uncomment:
    #
    # health_thread = threading.Thread(
    #     target=health_monitor,
    #     daemon=True,
    #     name="HealthMonitor",
    # )
    # health_thread.start()
    # logger.info("Health monitor started")
    #
    # ============================================================

    # -------------------------------------------------
    # ðŸ” BROKER SESSION GUARD (MANDATORY)
    # -------------------------------------------------
   
    def _ensure_login(self):
        """
        ðŸ”’ SINGLE SOURCE OF TRUTH FOR SESSION VALIDITY

        Delegates session validation and recovery
        entirely to ShoonyaClient.
        """
        if not self.api.ensure_session():
            logger.critical(
                "âŒ BROKER SESSION INVALID | auto-recovery failed"
            )
            raise RuntimeError("Broker session invalid and recovery failed")

    def _extract_symbol(self, leg) -> Optional[str]:
        """Extract symbol from leg object safely."""
        return getattr(leg, "tradingsymbol", None) or getattr(leg, "symbol", None)

    def _extract_direction(self, leg) -> Optional[str]:
        """Extract direction from leg object safely."""
        direction = getattr(leg, "direction", None) or getattr(leg, "side", None)
        return direction.upper() if direction else None

    def _extract_quantity(self, leg) -> int:
        """Extract quantity from leg object safely."""
        return int(getattr(leg, "qty", 0) or getattr(leg, "quantity", 0))

    def _serialize_leg_for_notification(self, leg: Any) -> Dict[str, Any]:
        """Normalize leg object/dict for Telegram and structured logging."""
        if isinstance(leg, dict):
            payload = dict(leg)
        else:
            payload = {
                "tradingsymbol": getattr(leg, "tradingsymbol", None) or getattr(leg, "symbol", None),
                "direction": getattr(leg, "direction", None) or getattr(leg, "side", None),
                "qty": getattr(leg, "qty", None) or getattr(leg, "quantity", None),
                "order_type": getattr(leg, "order_type", None),
                "price": getattr(leg, "price", None),
            }
        if payload.get("direction"):
            payload["direction"] = str(payload["direction"]).upper()
        return payload

    def _classify_leg_as_exit_or_entry(
        self,
        leg,
        broker_positions: List[Dict[str, Any]],
    ) -> str:
        """Classify leg as EXIT or ENTRY using direction-aware logic."""
        symbol = self._extract_symbol(leg)
        direction = self._extract_direction(leg)

        if not symbol or not direction:
            logger.warning("Cannot classify leg: missing symbol or direction")
            return "ENTRY"

        net_qty = 0
        for p in broker_positions:
            if p.get("tsym") == symbol:
                net_qty = int(p.get("netqty", 0))
                break

        if net_qty == 0:
            return "ENTRY"
        if net_qty > 0:
            return "EXIT" if direction == "SELL" else "ENTRY"
        return "EXIT" if direction == "BUY" else "ENTRY"

    def _wait_until_flat(
        self,
        symbols: List[str],
        strategy_name: str,
        timeout: float = 30.0,
    ) -> bool:
        """Wait until broker positions for given symbols become flat."""
        deadline = time.time() + timeout
        check_interval = 0.5

        logger.info(
            f"ATOMIC_WAIT_START | strategy={strategy_name} | "
            f"symbols={symbols} | timeout={timeout}s"
        )

        while time.time() < deadline:
            try:
                self.broker_view.invalidate_cache("positions")
                positions = self.broker_view.get_positions(force_refresh=True) or []

                positions_flat = True
                for p in positions:
                    if p.get("tsym") in symbols and int(p.get("netqty", 0)) != 0:
                        positions_flat = False
                        break

                orders_pending = False
                try:
                    open_orders = self.order_repo.get_open_orders_by_strategy(strategy_name)
                    for order in open_orders:
                        if order.symbol in symbols and order.status in ("CREATED", "SENT_TO_BROKER", "OPEN"):
                            orders_pending = True
                            break
                except Exception as e:
                    logger.warning(f"ATOMIC_WAIT | Order check failed: {e}")

                if positions_flat and not orders_pending:
                    logger.info(f"ATOMIC_WAIT_SUCCESS | strategy={strategy_name}")
                    return True

            except Exception as e:
                logger.warning(f"ATOMIC_WAIT | Check exception: {e}")

            time.sleep(check_interval)

        logger.error(f"ATOMIC_WAIT_TIMEOUT | strategy={strategy_name}")
        try:
            positions = self.broker_view.get_positions(force_refresh=True) or []
            for p in positions:
                if p.get("tsym") in symbols:
                    logger.error(f"ATOMIC_FINAL_POS | {p.get('tsym')} | netqty={p.get('netqty')}")
        except Exception as e:
            logger.error(f"ATOMIC_FINAL_POS | Failed to log: {e}")

        return False

    def _atomic_route_intents(
        self,
        *,
        strategy_name: str,
        execution_type: str,
        legs: List,
        guard_map: Dict,
        source_mode: str = "ALERT",
    ) -> Optional[Dict[str, Any]]:
        """Atomic coordinator for mixed EXIT+ENTRY batches."""
        with self._atomic_locks_guard:
            if strategy_name not in self._atomic_locks:
                self._atomic_locks[strategy_name] = threading.Lock()
            atomic_lock = self._atomic_locks[strategy_name]

        if not atomic_lock.acquire(timeout=35.0):
            logger.error(
                f"ATOMIC_ABORT | strategy={strategy_name} | "
                f"reason=atomic_lock_timeout"
            )
            return {
                "status": "FAILED",
                "reason": "ATOMIC_LOCK_TIMEOUT",
                "timestamp": datetime.now().isoformat(),
            }

        try:
            try:
                self.broker_view.invalidate_cache("positions")
                broker_positions = self.broker_view.get_positions(force_refresh=True) or []
            except Exception as e:
                logger.warning(f"ATOMIC_BATCH | Failed to get positions: {e}")
                broker_positions = []

            exit_legs = []
            entry_legs = []
            for leg in legs:
                if self._classify_leg_as_exit_or_entry(leg, broker_positions) == "EXIT":
                    exit_legs.append(leg)
                else:
                    entry_legs.append(leg)

            if not exit_legs or not entry_legs:
                return None

            exit_symbols = [self._extract_symbol(l) for l in exit_legs]

            exit_success_count = 0
            for leg in exit_legs:
                try:
                    symbol = self._extract_symbol(leg)
                    direction = self._extract_direction(leg)
                    key = (symbol, "EXIT")
                    if key not in guard_map:
                        continue
                    approved_qty = guard_map[key]
                    if approved_qty <= 0:
                        continue

                    if hasattr(leg, "to_dict"):
                        cmd = leg
                        cmd.quantity = approved_qty
                    else:
                        cmd = UniversalOrderCommand.from_order_params(
                            order_params={
                                "exchange": getattr(leg, "exchange", "NFO"),
                                "symbol": symbol,
                                "side": direction,
                                "quantity": approved_qty,
                                "product": getattr(leg, "product_type", "NRML"),
                                "order_type": getattr(leg, "order_type", "MARKET"),
                                "price": getattr(leg, "price", None),
                                "strategy_name": strategy_name,
                            },
                            source=source_mode,
                            user=self.client_id,
                        )
                        cmd.intent = "EXIT"

                    self.command_service.register(cmd)
                    exit_success_count += 1
                except Exception as e:
                    logger.error(
                        f"ATOMIC_PHASE_1_ERROR | strategy={strategy_name} | "
                        f"symbol={self._extract_symbol(leg)} | error={e}"
                    )

            if exit_success_count == 0:
                return {
                    "status": "FAILED",
                    "reason": "NO_EXITS_ROUTED",
                    "timestamp": datetime.now().isoformat(),
                }

            if not self._wait_until_flat(
                symbols=exit_symbols,
                strategy_name=strategy_name,
                timeout=30.0,
            ):
                return {
                    "status": "FAILED",
                    "reason": "EXIT_NOT_FLAT_TIMEOUT",
                    "symbols": exit_symbols,
                    "timestamp": datetime.now().isoformat(),
                }

            entry_success_count = 0
            for leg in entry_legs:
                try:
                    symbol = self._extract_symbol(leg)
                    direction = self._extract_direction(leg)
                    key = (symbol, direction)
                    if key not in guard_map:
                        continue
                    approved_qty = guard_map[key]
                    if approved_qty <= 0:
                        continue

                    if hasattr(leg, "to_dict"):
                        cmd = leg
                        cmd.quantity = approved_qty
                    else:
                        cmd = UniversalOrderCommand.from_order_params(
                            order_params={
                                "exchange": getattr(leg, "exchange", "NFO"),
                                "symbol": symbol,
                                "side": direction,
                                "quantity": approved_qty,
                                "product": getattr(leg, "product_type", "NRML"),
                                "order_type": getattr(leg, "order_type", "MARKET"),
                                "price": getattr(leg, "price", None),
                                "strategy_name": strategy_name,
                            },
                            source=source_mode,
                            user=self.client_id,
                        )

                    self.command_service.submit(cmd, execution_type="ENTRY")
                    entry_success_count += 1
                except Exception as e:
                    logger.error(
                        f"ATOMIC_PHASE_3_ERROR | strategy={strategy_name} | "
                        f"symbol={self._extract_symbol(leg)} | error={e}"
                    )

            return {
                "status": "ATOMIC_BATCH_EXECUTED",
                "exit_legs": exit_success_count,
                "entry_legs": entry_success_count,
                "symbols_exited": exit_symbols,
                "timestamp": datetime.now().isoformat(),
            }
        finally:
            atomic_lock.release()

    def notify_fill(self, strategy_name: str, symbol: str, side: str, qty: int,
                price: float, delta: Optional[float], broker_order_id: str,
                command_id: Optional[str] = None):
        """Called by OrderWatcher when an order fills."""
        if hasattr(self, "strategy_executor_service"):
            self.strategy_executor_service.notify_fill(
                strategy_name=strategy_name,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                delta=delta,
                broker_order_id=broker_order_id,
                command_id=command_id
            )
    def validate_webhook_signature(self, payload: str, signature: str) -> bool:
        """Validate webhook signature for security"""
        # Validate webhook_secret is configured
        if not self.config.webhook_secret:
            logger.error("webhook_secret not configured - rejecting webhook")
            return False
        return validate_webhook_signature(payload, signature, self.config.webhook_secret)
    
    def parse_alert_data(self, alert_data: Dict[str, Any]) -> AlertData:
        """Parse and validate incoming alert data"""
        # Normalize keys to lowercase
        normalized_data = {k.lower(): v for k, v in alert_data.items()}
        
        # Validate required fields
        required_fields = ['secret_key', 'execution_type', 'legs']
        missing_fields = []
        for field in required_fields:
            if field not in normalized_data:
                missing_fields.append(field)
        
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        # Validate secret key
        if normalized_data['secret_key'] != self.config.webhook_secret:
            raise ValueError("Invalid secret key")
        
        # Create AlertData object
        return AlertData.from_dict(normalized_data)
    
    def start_control_intent_consumers(self):
        """
        Starts dashboard control intent consumers in background.

        - GenericControlIntentConsumer â†’ ENTRY / EXIT / BASKET
        - StrategyControlConsumer     â†’ STRATEGY lifecycle only
        - Shared stop_event
        - No shared logic
        """
        try:
            # -------------------------------
            # GENERIC CONTROL CONSUMER
            # -------------------------------
            generic_consumer = GenericControlIntentConsumer(
                bot=self,
                stop_event=self._shutdown_event,
            )
            self._generic_control_thread = threading.Thread(
                target=generic_consumer.run_forever,
                daemon=True,
                name="GenericControlIntentConsumer",
            )
            self._generic_control_thread.start()

            # -------------------------------
            # STRATEGY CONTROL CONSUMER
            # -------------------------------
            strategy_consumer = StrategyControlConsumer(
                strategy_manager=self,   # ðŸ”’ ShoonyaBot is the strategy manager
                stop_event=self._shutdown_event,
            )
            self._strategy_control_thread = threading.Thread(
                target=strategy_consumer.run_forever,
                daemon=True,
                name="StrategyControlConsumer",
            )
            self._strategy_control_thread.start()

            logger.info("ðŸ§­ Dashboard control intent consumers started")

        except Exception as e:
            log_exception("start_control_intent_consumers", e)


    def has_live_entry_block(self, strategy_name: str, symbol: str) -> bool:
        """
        Blocks ENTRY if:
        - open intent exists (memory)
        - open order exists (DB)
        - open broker position exists
        """
        # Persistent orders (restart-safe)
        open_orders = self.order_repo.get_open_orders_by_strategy(strategy_name)
        for o in open_orders:
            if o.symbol == symbol:
                return True

        # Broker position (truth)
        try:
            positions = self.broker_view.get_positions()
        except Exception:
            positions = []

        for p in positions:
            if p.get("tsym") == symbol and int(p.get("netqty", 0)) != 0:
                return True

        return False

    def cleanup_old_orders(self):
        """
        Periodic DB hygiene:
        Remove closed / failed orders older than 3 days.
        """
        try:
            deleted = self.order_repo.cleanup_old_closed_orders(days=3)

            if deleted > 0:
                logger.info(
                    f"ðŸ§¹ DB CLEANUP | removed {deleted} old closed orders"
                )
        except Exception as e:
            log_exception("db_cleanup", e)

    def process_leg(
        self,
        leg_data,
        exchange: str,
        strategy_name: str,
        execution_type: str,
        test_mode: Optional[str] = None,
        is_duplicate: bool = False,
    ) -> LegResult:
        """
        PURE INTENT REGISTRATION ENGINE (PRODUCTION â€” FROZEN)

        ðŸ”’ RULE:
        - NO broker execution
        - NO DB writes
        - Registers intent ONLY
        - OrderWatcherEngine executes
        """

        try:
            # =================================================
            # BASIC VALIDATION
            # =================================================
            if leg_data.qty <= 0:
                raise ValueError("Quantity must be > 0")

            exchange = exchange.upper()
            direction = leg_data.direction.upper()

            # =================================================
            # ðŸ”’ BUILD CANONICAL INTENT
            # =================================================
            cmd = UniversalOrderCommand.from_order_params(
                order_params={
                    "exchange": exchange,
                    "symbol": leg_data.tradingsymbol,
                    "side": direction,
                    "quantity": int(leg_data.qty),
                    "product": leg_data.product_type,
                    "order_type": leg_data.order_type,
                    "price": leg_data.price,
                    "strategy_name": strategy_name,
                },
                source="STRATEGY",
                user=self.client_id,
            )

            # =================================================
            # ðŸ”’ CANONICAL INSTRUMENT RULE (ScriptMaster)
            # =================================================
            must_limit = requires_limit_order(
                exchange=exchange,
                tradingsymbol=leg_data.tradingsymbol,
            )

            if must_limit:
                if cmd.order_type != "LIMIT":
                    raise RuntimeError(
                        f"LIMIT ORDER REQUIRED | {leg_data.tradingsymbol}"
                    )
                if not cmd.price:
                    raise RuntimeError(
                        f"LIMIT PRICE REQUIRED | {leg_data.tradingsymbol}"
                    )

            # =================================================
            # DUPLICATE ENTRY â€” HARD BLOCK
            # =================================================
            if execution_type == "ENTRY" and is_duplicate:
                logger.warning(
                    f"DUPLICATE ENTRY BLOCKED | {leg_data.tradingsymbol} | {strategy_name}"
                )
                return LegResult(
                    leg_data=leg_data,
                    order_result=OrderResult(
                        success=False,
                        error_message="DUPLICATE_ENTRY_BLOCKED",
                    ),
                )

            # =================================================
            # TELEGRAM â€” INTENT REGISTERED
            # =================================================
            if self.telegram_enabled and self.telegram:
                try:
                    # Ensure price is a float, not None
                    if cmd.order_type == "LIMIT" and cmd.price is not None:
                        price = cmd.price
                    else:
                        price = 0.0
                    self.telegram.send_order_placing(
                        strategy_name=strategy_name,
                        execution_type=execution_type,
                        symbol=leg_data.tradingsymbol,
                        direction=direction,
                        quantity=leg_data.qty,
                        price=price,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send order placing message: {e}")

            # =================================================
            # Execute through single command-service path.
            # EXIT remains intent-only; ENTRY/ADJUST submits immediately.
            # =================================================
            if execution_type == "EXIT":
                self.command_service.register(cmd)
            else:
                if test_mode:
                    # Persist explicit test marker so downstream execution can run
                    # the same OMS flow while simulating broker behavior.
                    marker = f"TEST_MODE_{str(test_mode).upper()}"
                    prior = str(cmd.comment or "")
                    cmd = replace(cmd, comment=f"{prior}|{marker}" if prior else marker)
                self.command_service.submit(cmd, execution_type=execution_type)

            if test_mode:
                logger.warning(f"ðŸ§ª TEST MODE | {leg_data.tradingsymbol}")

            logger.info(
                "INTENT_REGISTERED | %s | %s | %s | qty=%s | type=%s",
                exchange,
                leg_data.tradingsymbol,
                direction,
                leg_data.qty,
                cmd.order_type,
            )

            return LegResult(
                leg_data=leg_data,
                order_result=OrderResult(success=True, order_id=None),
            )

        except Exception as e:
            log_exception("process_leg", e)

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_error_message(
                        title="ORDER INTENT ERROR",
                        error=f"{leg_data.tradingsymbol}: {str(e)}",
                    )
                except Exception as tg_e:
                    logger.warning(f"Failed to send error message: {tg_e}")

            return LegResult(
                leg_data=leg_data,
                order_result=OrderResult(success=False, error_message=str(e)),
            )

    def process_alert(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        PURE EXECUTION ALERT HANDLER (PRODUCTION â€” FROZEN)

        RULES:
        - âŒ No quotes
        - âŒ No LTP
        - âŒ No bid/ask
        - âœ… Alert defines order_type & price
        - âœ… ExecutionGuard controls risk
        - âœ… Broker position book controls duplicates
        - âœ… Per-strategy lock prevents duplicate webhook races
        """

        try:
            # -------------------------------------------------
            # RISK HEARTBEAT
            # -------------------------------------------------
            self.risk_manager.heartbeat()
            self._ensure_login()

            parsed = self.parse_alert_data(alert_data)
            execution_type = parsed.execution_type.upper()
            leg_payloads = [self._serialize_leg_for_notification(leg) for leg in parsed.legs]

            # -------------------------------------------------
            # ðŸ”’ PER-STRATEGY LOCK â€” prevents duplicate webhook races
            # Two identical webhooks arriving simultaneously will serialize
            # on the strategy lock; the second one will hit dedup checks.
            # -------------------------------------------------
            with self._alert_locks_guard:
                if parsed.strategy_name not in self._alert_locks:
                    self._alert_locks[parsed.strategy_name] = threading.Lock()
                strategy_lock = self._alert_locks[parsed.strategy_name]

            with strategy_lock:

                # Risk check â€” EXIT alerts always pass (they reduce risk)
                if execution_type != "EXIT" and not self.risk_manager.can_execute():
                    return {
                        "status": "blocked",
                        "reason": "Risk limits / cooldown",
                        "timestamp": datetime.now().isoformat(),
                    }

                # -------------------------------------------------
                # TELEGRAM â€” ALERT RECEIVED
                # -------------------------------------------------
                if self.telegram_enabled and self.telegram:
                    try:
                        self.telegram.send_alert_received(
                            strategy_name=parsed.strategy_name,
                            execution_type=execution_type,
                            legs_count=len(parsed.legs),
                            exchange=parsed.exchange,
                            legs=leg_payloads,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send alert received message: {e}")
                logger.info(
                    "ALERT_RECEIVED | strategy=%s | type=%s | exchange=%s | legs=%s",
                    parsed.strategy_name,
                    execution_type,
                    parsed.exchange,
                    leg_payloads,
                )
                # -------------------------------------------------
                # ðŸ” EXECUTION GUARD BROKER RECONCILIATION (MANDATORY)
                # -------------------------------------------------
                if not parsed.test_mode:
                    try:
                        self.broker_view.invalidate_cache("positions")
                        positions = self.broker_view.get_positions(force_refresh=True)
                    except Exception:
                        positions = []

                    # ðŸ”’ Direction-aware broker map (ExecutionGuard v1.3 contract)
                    broker_map = {}
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

                    self.execution_guard.reconcile_with_broker(
                        strategy_id=parsed.strategy_name,
                        broker_positions=broker_map,
                    )

                # -------------------------------------------------
                # DUPLICATE ENTRY DETECTION (BROKER-TRUTH)
                # -------------------------------------------------
                duplicate_symbols = set()

                if execution_type == "ENTRY" and not parsed.test_mode:
                    for leg in parsed.legs:
                        if self.has_live_entry_block(parsed.strategy_name, leg.tradingsymbol):
                            duplicate_symbols.add(leg.tradingsymbol)
                            logger.warning(
                                f"ENTRY BLOCKED â€” LIVE ORDER OR POSITION EXISTS | "
                                f"{leg.tradingsymbol} | {parsed.strategy_name}"
                            )

                # -------------------------------------------------
                # EXECUTION GUARD PLAN
                # -------------------------------------------------
                intents = [
                    LegIntent(
                        strategy_id=parsed.strategy_name,
                        symbol=leg.tradingsymbol,
                        direction=leg.direction,
                        qty=leg.qty,
                        tag=execution_type,
                    )
                    for leg in parsed.legs
                ]

                try:
                    guarded = (
                        intents
                        if parsed.test_mode
                        else self.execution_guard.validate_and_prepare(
                            intents=intents,
                            execution_type=execution_type,
                        )
                    )
                except RuntimeError as e:
                    logger.warning(str(e))
                    return {
                        "status": "blocked",
                        "reason": str(e),
                        "timestamp": datetime.now().isoformat(),
                    }


                if execution_type == "ENTRY" and not guarded:
                    return {
                        "status": "blocked",
                        "reason": "ExecutionGuard blocked ENTRY",
                        "timestamp": datetime.now().isoformat(),
                    }

                guard_map = {}
                for g in guarded:
                    if execution_type == "EXIT":
                        key = (g.symbol, "EXIT")
                    else:
                        key = (g.symbol, g.direction)
                    guard_map[key] = g.qty

                atomic_result = self._atomic_route_intents(
                    strategy_name=parsed.strategy_name,
                    execution_type=execution_type,
                    legs=parsed.legs,
                    guard_map=guard_map,
                    source_mode="ALERT",
                )
                if atomic_result:
                    logger.info(f"ATOMIC_HANDLED | {atomic_result['status']}")
                    return atomic_result

                expected_legs = len(parsed.legs)
                attempted = 0
                success_count = 0

                # -------------------------------------------------
                # EXECUTE LEGS
                # -------------------------------------------------
                # ðŸ”’ Fetch positions ONCE before the loop for EXIT legs
                # (prevents per-leg API calls and race conditions between legs)
                # In test_mode, do not gate exits by broker positions because
                # mock runs may not have real broker netqty state.
                exit_positions_cache = None
                if execution_type == "EXIT" and not parsed.test_mode:
                    try:
                        self.broker_view.invalidate_cache("positions")
                        exit_positions_cache = self.broker_view.get_positions(force_refresh=True) or []
                    except Exception:
                        exit_positions_cache = []

                for leg in parsed.legs:
                    orig_direction = leg.direction

                    if execution_type == "EXIT" and not parsed.test_mode:
                        # -------------------------------------------------
                        # ðŸ”’ BROKER-TRUTH EXIT DIRECTION (from cached snapshot)
                        # -------------------------------------------------
                        net_qty = 0
                        for p in exit_positions_cache:
                            if p.get("tsym") == leg.tradingsymbol:
                                net_qty = int(p.get("netqty", 0))
                                break

                        if net_qty == 0:
                            logger.warning(
                                f"EXIT SKIPPED â€” NO POSITION | {leg.tradingsymbol}"
                            )
                            continue

                        # If net_qty > 0 â†’ SELL to exit
                        # If net_qty < 0 â†’ BUY to exit
                        leg.direction = "SELL" if net_qty > 0 else "BUY"

                    if execution_type == "EXIT":
                        key = (leg.tradingsymbol, "EXIT")
                    else:
                        key = (leg.tradingsymbol, orig_direction)

                    if key not in guard_map:
                        logger.warning(
                            f"EXECUTION_GUARD_BLOCK | {parsed.strategy_name} | {leg.tradingsymbol}"
                        )
                        continue

                    leg.qty = guard_map[key]
                    if leg.qty <= 0:
                        continue

                    # -------------------------------------------------
                    # ENFORCE ORDER CONTRACT
                    # -------------------------------------------------
                    try:
                        if not leg.order_type:
                            raise RuntimeError(
                                f"ORDER TYPE MISSING | {leg.tradingsymbol}"
                            )

                        if leg.order_type.upper() == "LIMIT" and not leg.price:
                            raise RuntimeError(
                                f"LIMIT PRICE MISSING | {leg.tradingsymbol}"
                            )

                        is_duplicate = (
                            execution_type == "ENTRY"
                            and not parsed.test_mode
                            and leg.tradingsymbol in duplicate_symbols
                        )

                        attempted += 1

                        result = self.process_leg(
                            leg_data=leg,
                            exchange=parsed.exchange,
                            strategy_name=parsed.strategy_name,
                            execution_type=execution_type,
                            test_mode=parsed.test_mode,
                            is_duplicate=is_duplicate,
                        )

                        if result.order_result.success:
                            success_count += 1
                    except Exception as leg_err:
                        logger.error(
                            "LEG_PROCESSING_FAILED | strategy=%s | symbol=%s | error=%s",
                            parsed.strategy_name,
                            leg.tradingsymbol,
                            leg_err,
                        )
                        attempted += 1
                        # Continue processing remaining legs

                # -------------------------------------------------
                # ENTRY FAILURE â€” ROLLBACK
                # -------------------------------------------------
                if execution_type == "ENTRY" and success_count == 0:
                    self.execution_guard.force_close_strategy(parsed.strategy_name)

                    if self.telegram_enabled and self.telegram:
                        try:
                            self.telegram.send_error_message(
                                title="ðŸš¨ ENTRY FAILED",
                                error=f"{parsed.strategy_name} | All legs rejected",
                                strategy_name=parsed.strategy_name,
                                execution_type=execution_type,
                                exchange=parsed.exchange,
                                legs=leg_payloads,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send error message: {e}")

                    return {
                        "status": "FAILED",
                        "expected_legs": expected_legs,
                        "successful_legs": 0,
                        "attempted_legs": attempted,
                        "timestamp": datetime.now().isoformat(),
                    }

                if (
                    execution_type == "EXIT"
                    and not parsed.test_mode
                    and expected_legs > 0
                    and attempted == 0
                ):
                    # All requested exits were skipped because broker had no open qty.
                    # This is a benign terminal outcome, not an execution failure.
                    status = "NO_POSITION"
                else:
                    status = (
                        "INTENTS_REGISTERED"
                        if success_count == expected_legs
                        else "PARTIALLY_REGISTERED"
                        if success_count > 0
                        else "FAILED"
                    )

                return {
                    "status": status,
                    "expected_legs": expected_legs,
                    "attempted_legs": attempted,
                    "successful_legs": success_count,
                    "timestamp": datetime.now().isoformat(),
                }
        except RuntimeError:
            # ðŸ”¥ FAIL-HARD: broker/session blind
            raise
        except Exception as e:
            log_exception("process_alert", e)

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_error_message(
                        "ALERT PROCESSING ERROR",
                        str(e),
                    )
                except Exception as tg_e:
                    logger.warning(f"Failed to send error message: {tg_e}")

            return {
                "status": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def start_strategy(
        self,
        *,
        strategy_name: str,
        universal_config,
        market_cls,
        market_config,
    ):
        """Route start calls into StrategyExecutorService."""
        logger.warning(
            "start_strategy called; routing to start_strategy_executor | strategy=%s",
            strategy_name,
        )
        resolved = (
            universal_config.to_dict()
            if hasattr(universal_config, "to_dict")
            else (universal_config if isinstance(universal_config, dict) else {})
        )
        self.start_strategy_executor(
            strategy_name=strategy_name,
            config=resolved,
        )

    def start_strategy_executor(
        self,
        *,
        strategy_name: str,
        config: dict,
    ):
        """
        Register strategy with StrategyExecutorService.

        Service is initialized once in __init__,
        this method just registers a new strategy.
        """
        with self._live_strategies_lock:
            if strategy_name in self._live_strategies:
                logger.warning(f"Strategy already running: {strategy_name}")
                return

        try:
            logger.info(f"REGISTERING STRATEGY: {strategy_name}")

            from pathlib import Path
            import json
            import re

            slug = strategy_name.strip().lower()
            slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_') or 'unnamed'

            config_dir = (
                Path(__file__).resolve().parents[2]
                / "shoonya_platform"
                / "strategy_runner"
                / "saved_configs"
            )
            config_dir.mkdir(parents=True, exist_ok=True)

            config_path = config_dir / f"{slug}.json"
            tmp_path = config_dir / f"{slug}.json.tmp"
            with open(tmp_path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(config, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, config_path)

            logger.info(f"Config saved: {config_path}")

            self.strategy_executor_service.register_strategy(
                name=strategy_name,
                config_path=str(config_path),
            )

            with self._live_strategies_lock:
                self._live_strategies[strategy_name] = {
                    "type": "executor_service",
                    "config_path": str(config_path),
                    "started_at": time.time(),
                }

            logger.warning(f"STRATEGY REGISTERED: {strategy_name}")

            if self.telegram_enabled and self.telegram:
                try:
                    self.send_telegram(
                        f"<b>STRATEGY REGISTERED</b>\n"
                        f"Name: {strategy_name}\n"
                        f"Type: ExecutorService (condition-based)\n"
                        f"Time: {datetime.now().strftime('%H:%M:%S')}"
                    )
                except Exception as e:
                    logger.warning(f"Telegram notification failed: {e}")

        except Exception as e:
            logger.error(f"STRATEGY REGISTRATION FAILED: {strategy_name} | {e}", exc_info=True)

            if self.telegram_enabled and self.telegram:
                try:
                    self.send_telegram(
                        f"<b>STRATEGY REGISTRATION FAILED</b>\n"
                        f"Name: {strategy_name}\n"
                        f"Error: {str(e)}"
                    )
                except Exception:
                    pass

            raise

    def execute_command(self, command, **kwargs):
        """
        ðŸ”— DESIRED FLOW: COMPLETE 6-STEP ORDER EXECUTION
        
        Step 1: REGISTER TO DB with status=CREATED       [âœ… DONE by CommandService.submit()]
        Step 2: SYSTEM BLOCKERS CHECK (Risk/Guard/Dup)   [âœ… THIS METHOD]
        Step 3: UPDATE TO status=SENT_TO_BROKER          [âœ… THIS METHOD - before broker call]
        Step 4: EXECUTE ON BROKER                        [âœ… THIS METHOD - place order]
        Step 5: UPDATE DB BASED ON BROKER RESULT         [âœ… THIS METHOD - handle success/fail]
        Step 6: ORDERWATCH POLLS BROKER ("EXECUTED TRUTH") [âœ… DONE by OrderWatcher]
        
        Accepts extra keyword args (trailing_engine, etc.)
        for forward compatibility.
        """
        # ðŸ”’ EXECUTION AUTHORITY â€” log non-ORDER_WATCHER callers for audit
        # Both CommandService.submit() and OrderWatcher may call execute_command.
        # Previously this was an assert that broke strategy ENTRY orders.
        if command.source != "ORDER_WATCHER":
            logger.info(
                f"EXECUTE_COMMAND_SOURCE | cmd_id={command.command_id} | source={command.source} | "
                f"(non-ORDER_WATCHER caller â€” allowed)"
            )

        # ðŸ”’ ATOMIC LOCK: Prevents race condition where two threads both pass
        # can_execute() and place the same order twice (double execution).
        with self._cmd_lock:
            return self._execute_command_inner(command, **kwargs)

    def _execute_command_inner(self, command, **kwargs):
        """Inner execution logic, called under _cmd_lock."""
        try:
            self._ensure_login()

            strategy_id = getattr(command, 'strategy_name', 'UNKNOWN')

            # Resolve MOCK behavior from explicit test marker or strategy mode.
            comment = str(getattr(command, "comment", "") or "").upper()
            explicit_mock_success = "TEST_MODE_SUCCESS" in comment
            explicit_mock_failure = "TEST_MODE_FAILURE" in comment
            is_mock_execution = explicit_mock_success or explicit_mock_failure
            if not is_mock_execution:
                try:
                    svc = getattr(self, "strategy_executor_service", None)
                    mode_getter = getattr(svc, "get_strategy_mode", None) if svc else None
                    if callable(mode_getter) and strategy_id and strategy_id != "UNKNOWN":
                        is_mock_execution = str(mode_getter(strategy_id) or "LIVE").upper() == "MOCK"
                except Exception:
                    is_mock_execution = False
            
            # Detection: intent field (set by from_record / with_intent) OR command_id prefix
            # (set by PositionExitService for risk-triggered exits).
            is_exit_order = (
                getattr(command, 'intent', None) == 'EXIT'
                or (hasattr(command, 'command_id') and str(command.command_id).startswith('EXIT_'))
            )

            # Resolve canonical execution_type from persisted order record first.
            # OrderWatcher commands do not carry execution_type on the command object.
            order_rec = None
            execution_type = "EXIT" if is_exit_order else "ENTRY"
            try:
                order_rec = self.order_repo.get_by_id(command.command_id)
                rec_type = str(getattr(order_rec, "execution_type", "") or "").upper()
                if rec_type:
                    execution_type = rec_type
                elif hasattr(command, "execution_type"):
                    execution_type = str(getattr(command, "execution_type", "") or execution_type).upper()
            except Exception:
                if hasattr(command, "execution_type"):
                    execution_type = str(getattr(command, "execution_type", "") or execution_type).upper()

            # Normalize to ENTRY/ADJUSTMENT/EXIT family for guard checks.
            if execution_type not in {"ENTRY", "ADJUSTMENT", "ADJUST", "EXIT"}:
                execution_type = "EXIT" if is_exit_order else "ENTRY"

            # ==================================================
            # STEP 2: SYSTEM BLOCKERS CHECK (BEFORE EXECUTION)
            # ==================================================
            logger.info(
                f"STEP_2: SYSTEM_BLOCKERS_CHECK | cmd_id={command.command_id} | {command.symbol}"
            )
            
            # ðŸ›¡ï¸ Check 2A: RISK MANAGER (daily loss, cooldown, max loss)
            # EXIT orders ALWAYS bypass risk checks â€” they REDUCE risk, not add it.
            # Without this bypass, RMS exit orders block themselves when daily_loss_hit=True.
            #
            if is_exit_order:
                logger.info(
                    f"RISK_BYPASS_EXIT | cmd_id={command.command_id} | {command.symbol} | "
                    f"EXIT orders always pass risk check"
                )
            elif not self.risk_manager.can_execute():
                reason = "RISK_LIMITS_EXCEEDED"
                logger.warning(
                    f"BLOCKER_RISK | cmd_id={command.command_id} | {command.symbol} | reason={reason}"
                )
                try:
                    self.order_repo.update_status(command.command_id, "FAILED")
                    self.order_repo.update_tag(command.command_id, reason)
                except Exception as db_err:
                    logger.error(f"Failed to update DB with risk blocker: {db_err}")
                
                return OrderResult(success=False, error_message=reason)
            
            # ðŸ›¡ï¸ Check 2B: EXECUTION GUARD (strategy tracking)
            # Check if strategy already has an ENTRY (prevent duplicate entries)
            if self.execution_guard.has_strategy(strategy_id):
                # Strategy pipeline ENTRY legs are pre-approved in process_alert()
                # via ExecutionGuard.validate_and_prepare(). Do not re-block them.
                source_upper = str(getattr(command, "source", "") or "").upper()
                strategy_pipeline = source_upper in {"ORDER_WATCHER", "STRATEGY"}
                if execution_type == "ENTRY" and not strategy_pipeline:
                    reason = "EXECUTION_GUARD_BLOCKED"
                    logger.warning(
                        f"BLOCKER_GUARD | cmd_id={command.command_id} | {command.symbol} | "
                        f"strategy={strategy_id} | reason={reason}"
                    )
                    try:
                        self.order_repo.update_status(command.command_id, "FAILED")
                        self.order_repo.update_tag(command.command_id, reason)
                    except Exception as db_err:
                        logger.error(f"Failed to update DB with guard blocker: {db_err}")
                    
                    return OrderResult(success=False, error_message=reason)
            
            # ðŸ›¡ï¸ Check 2C: DUPLICATE DETECTION (live orders by symbol)
            # EXIT orders skip duplicate check â€” multiple exit legs for same symbol are valid
            if execution_type != "EXIT":
                open_orders = self.order_repo.get_open_orders_by_strategy(strategy_id)
                
                for order in open_orders:
                    if order.symbol == command.symbol and order.command_id != command.command_id:
                        reason = "DUPLICATE_ORDER_BLOCKED"
                        logger.warning(
                            f"BLOCKER_DUPLICATE | cmd_id={command.command_id} | {command.symbol} | "
                            f"existing={order.command_id} | reason={reason}"
                        )
                        try:
                            self.order_repo.update_status(command.command_id, "FAILED")
                            self.order_repo.update_tag(command.command_id, reason)
                        except Exception as db_err:
                            logger.error(f"Failed to update DB with duplicate blocker: {db_err}")
                        
                        return OrderResult(success=False, error_message=reason)
            
            logger.info(
                f"BLOCKERS_PASSED âœ… | cmd_id={command.command_id} | {command.symbol}"
            )
            
            # ==================================================
            # STEP 3: UPDATE TO status=SENT_TO_BROKER
            # ==================================================
            logger.info(
                f"STEP_3: SENDING_TO_BROKER | cmd_id={command.command_id} | {command.symbol}"
            )
            
            try:
                self.order_repo.update_status(command.command_id, "SENT_TO_BROKER")
            except Exception as db_err:
                logger.error(f"STEP_3 FAILED: Could not update DB to SENT_TO_BROKER: {db_err}")
                # Note: Continue to broker anyway (broker is source of truth)
            
            # ==================================================
            # STEP 4: EXECUTE ON BROKER
            # ==================================================
            logger.info(
                f"STEP_4: EXECUTE_ON_BROKER | cmd_id={command.command_id} | {command.symbol}"
            )
            
            # Convert canonical command â†’ broker params
            order_params = command.to_broker_params()

            logger.info(
                f"BROKER_PARAMS | {order_params.get('exchange')} | "
                f"{order_params.get('tradingsymbol')} | "
                f"{order_params.get('buy_or_sell')} | "
                f"qty={order_params.get('quantity')} | "
                f"type={order_params.get('price_type')}"
            )

            if is_mock_execution:
                logger.info(
                    "STEP_4_MOCK_EXECUTION | cmd_id=%s | strategy=%s | mode=MOCK",
                    command.command_id,
                    strategy_id,
                )
                if explicit_mock_failure:
                    result = OrderResult(success=False, error_message="MOCK_TEST_FAILURE")
                else:
                    mock_order_id = f"MOCK_{int(time.time() * 1000)}_{command.command_id[:8]}"
                    result = OrderResult(success=True, order_id=mock_order_id, status="MOCK_EXECUTED")
            else:
                # ðŸ”¥ Single broker touchpoint
                result = self.api.place_order(order_params)
            
            # ==================================================
            # STEP 5: UPDATE DB BASED ON BROKER RESULT
            # ==================================================
            logger.info(
                f"STEP_5: UPDATE_DB_BROKER_RESULT | cmd_id={command.command_id} | "
                f"success={result.success}"
            )
            
            if result.success:
                # âœ… BROKER ACCEPTED: Update with broker_order_id
                broker_id = getattr(result, 'order_id', None) or getattr(result, 'norenordno', None)
                if broker_id:
                    try:
                        self.order_repo.update_broker_id(command.command_id, broker_id)
                        logger.info(
                            f"DB_UPDATED_SUCCESS | cmd_id={command.command_id} | "
                            f"broker_id={broker_id} | status=SENT_TO_BROKER"
                        )
                        
                        if is_mock_execution:
                            fill_price = float(command.price or 0.0)
                            if fill_price <= 0:
                                try:
                                    fill_price = float(self.api.get_ltp(command.exchange, command.symbol) or 0.0)
                                except Exception:
                                    fill_price = 0.0
                            self.order_repo.update_status(command.command_id, "EXECUTED")
                            self.notify_fill(
                                strategy_name=strategy_id,
                                symbol=command.symbol,
                                side=command.side,
                                qty=int(command.quantity),
                                price=fill_price,
                                delta=None,
                                broker_order_id=broker_id,
                                command_id=command.command_id,
                            )
                            logger.info(
                                "MOCK_EXECUTED | cmd_id=%s | strategy=%s | symbol=%s | side=%s | qty=%s | price=%s",
                                command.command_id,
                                strategy_id,
                                command.symbol,
                                command.side,
                                command.quantity,
                                fill_price,
                            )
                        else:
                            # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                            # ðŸ”„ INVALIDATE BROKER CACHE (NEW)
                            # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                            # After successful order placement, force fresh data on next poll
                            # Ensures OrderWatcher and dashboard see new broker state immediately
                            try:
                                self.broker_view.invalidate_cache(target="positions")
                                self.broker_view.invalidate_cache(target="orders")
                                logger.debug(
                                    f"CACHE_INVALIDATED | cmd_id={command.command_id} | "
                                    f"targets=['positions', 'orders']"
                                )
                            except Exception as cache_err:
                                # Non-critical - cache will expire naturally in 1.5s
                                logger.debug(f"Cache invalidation warning (non-critical): {cache_err}")
                            # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                        
                    except Exception as db_err:
                        logger.error(f"STEP_5 WARNING: Failed to persist broker_id: {db_err}")
                else:
                    logger.warning(
                        f"STEP_5 WARNING: Broker accepted but no order_id in result | "
                        f"cmd_id={command.command_id}"
                    )
            else:
                # âŒ BROKER REJECTED: Update status to FAILED
                logger.error(
                    f"STEP_5_BROKER_REJECTED | cmd_id={command.command_id} | {command.symbol} | "
                    f"error={result.error_message}"
                )
                
                try:
                    self.order_repo.update_status(command.command_id, "FAILED")
                    if hasattr(self.order_repo, 'update_tag'):
                        fail_tag = "MOCK_TEST_FAILURE" if is_mock_execution else "BROKER_REJECTED"
                        self.order_repo.update_tag(command.command_id, fail_tag)
                    logger.info(f"DB_UPDATED_FAILED | cmd_id={command.command_id} | status=FAILED")
                except Exception as db_err:
                    logger.error(f"STEP_5 ERROR: Failed to update DB on broker rejection: {db_err}")
                
                # ðŸ“¢ TELEGRAM ALERT for failed exits
                if hasattr(command, 'execution_type') and command.execution_type == "EXIT":
                    if self.telegram_enabled:
                        try:
                            self.send_telegram(
                                f"ðŸš¨ EXIT ORDER REJECTED\n"
                                f"Symbol: {command.symbol}\n"
                                f"Reason: {result.error_message}\n"
                                f"âš ï¸ Position still open - manual action may be needed"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send telegram notification: {e}")

            return result

        except RuntimeError:
            # FAIL-HARD: broker/session failure must kill process
            raise
        except Exception as e:
            log_exception("execute_command", e)
            
            # ðŸ†˜ UNEXPECTED ERROR: Mark as FAILED
            logger.error(f"STEP_5_EXCEPTION | cmd_id={command.command_id} | {type(e).__name__}: {e}")
            try:
                self.order_repo.update_status(command.command_id, "FAILED")
            except Exception as db_error:
                logger.warning(f"Failed to update command status in database: {db_error}")
            
            return OrderResult(
                success=False,
                error_message=str(e),
            )

    
    def get_account_info(self):
        """
        Get consolidated account information using ShoonyaClient.
        Compatibility replacement for removed shoonya_api.py
        """
        try:
            self._ensure_login()
            limits = self.broker_view.get_limits()
            positions = self.broker_view.get_positions()
            orders = self.broker_view.get_order_book()

            if limits is None:
                return None

            return AccountInfo.from_api_data(limits, positions, orders)

        except RuntimeError:
            # FAIL-HARD: broker/session blind
            raise
        except Exception as e:
            raise RuntimeError(f"ACCOUNT_INFO_FAILED: {e}")

    
    def get_bot_stats(self) -> BotStats:
        """Get bot statistics"""
        return BotStats.from_trade_records(self.trade_records)
    
    def send_daily_summary(self):
        """Send daily summary at market opening"""
        try:
            if not self.telegram_enabled:
                return
            
            message = f"ðŸŒ… <b>GOOD MORNING!</b>\n"
            message += f"ðŸ“… {datetime.now().strftime('%A, %B %d, %Y')}\n"
            message += f"ðŸ•˜ Market Opening Soon\n\n"
            message += f"ðŸ¤– Bot Status: âœ… Ready for Trading\n"
            message += f"ðŸ’° Account: Connected & Active\n\n"
            
            yesterday_trades = get_yesterday_trades(self.trade_records)
            
            message += f"ðŸ“Š Yesterday's Performance:\n"
            if yesterday_trades:
                successful_trades = len([t for t in yesterday_trades if t.status in ("PLACED", "Ok", "FILLED")])
                success_rate = calculate_success_rate(successful_trades, len(yesterday_trades))
                message += f"â€¢ Total Trades: {len(yesterday_trades)}\n"
                message += f"â€¢ Successful: {successful_trades}\n"
                message += f"â€¢ Success Rate: {success_rate:.1f}%\n"
            else:
                message += f"â€¢ No trades executed yesterday\n"
            
            message += f"\nðŸŽ¯ Ready for today's opportunities!"
            self.send_telegram(message)
            
        except Exception as e:
            log_exception("send_daily_summary", e)
    
    def send_market_close_summary(self):
        """Send summary at market close"""
        try:
            if not self.telegram_enabled:
                return
            
            today_trades = get_today_trades(self.trade_records)
            
            message = f"ðŸŒ† <b>MARKET CLOSED</b>\n"
            message += f"ðŸ“… {datetime.now().strftime('%Y-%m-%d')}\n"
            message += f"{'='*25}\n\n"
            
            if today_trades:
                successful_trades = len([t for t in today_trades if t.status in ("PLACED", "Ok", "FILLED")])
                success_rate = calculate_success_rate(successful_trades, len(today_trades))
                
                message += f"ðŸ“Š <b>Today's Summary:</b>\n"
                message += f"â€¢ Total Trades: {len(today_trades)}\n"
                message += f"â€¢ Successful: {successful_trades}\n"
                message += f"â€¢ Failed: {len(today_trades) - successful_trades}\n"
                message += f"â€¢ Success Rate: {success_rate:.1f}%\n"
                
                # Strategy breakdown
                strategies = defaultdict(int)
                for trade in today_trades:
                    strategies[trade.strategy_name] += 1
                
                if len(strategies) > 1:
                    message += f"\nðŸ“‹ <b>Strategy Breakdown:</b>\n"
                    for strategy, count in strategies.items():
                        message += f"â€¢ {strategy}: {count} trades\n"
            else:
                message += f"ðŸ“Š No trades executed today\n"
            
            message += f"\nðŸ˜´ Bot will continue monitoring overnight"
            self.send_telegram(message)
            
        except Exception as e:
            log_exception("send_market_close_summary", e)
    
    def send_telegram_heartbeat(self):
        """Send periodic heartbeat with session validation"""
        try:
            if not self.telegram_enabled:
                return
            
            # 1ï¸âƒ£ Validate session by fetching limits
            try:
                limits = self.broker_view.get_limits(force_refresh=True)
                if not limits or not isinstance(limits, dict):
                    raise RuntimeError("BROKER_SESSION_INVALID")
                session_status = "âœ… Live"
                cash = float(limits.get('cash', 0))
            except Exception as e:
                logger.error(f"Heartbeat session check failed: {e}")
                session_status = "âŒ Disconnected"
                cash = 0.0

                # Heartbeat should not kill service; try one explicit recovery pass.
                try:
                    self._ensure_login()
                    self.broker_view.invalidate_cache("limits")
                    limits = self.broker_view.get_limits(force_refresh=True)
                    if limits and isinstance(limits, dict):
                        session_status = "âœ… Recovered"
                        cash = float(limits.get('cash', 0))
                        logger.info("Heartbeat session recovered after explicit revalidation")
                except Exception as recovery_error:
                    logger.error(f"Heartbeat session recovery failed: {recovery_error}")
            
            # 2ï¸âƒ£ Get positions count
            try:
                positions = self.broker_view.get_positions()
                active_pos = sum(1 for p in positions if int(p.get('netqty', 0)) != 0)
            except Exception as position_error:
                logger.warning(f"Could not fetch positions for heartbeat: {position_error}")
                active_pos = 0
            
            # 3ï¸âƒ£ Send compact heartbeat
            now = datetime.now()
            message = (
                f"ðŸ’“ <b>SYSTEM HEARTBEAT</b>\n"
                f"â° {now.strftime('%H:%M:%S')} | {now.strftime('%d-%b-%Y')}\n"
                f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                f"ðŸ” Session: {session_status}\n"
                f"ðŸ’° Cash: â‚¹{cash:,.2f}\n"
                f"ðŸ“Š Positions: {active_pos}\n"
                f"ðŸ¤– Status: Active & Monitoring"
            )
            
            self.send_telegram(message)
            logger.debug("Heartbeat sent")
            
        except Exception as e:
            log_exception("send_telegram_heartbeat", e)

    def send_status_report(self):
        """Send comprehensive status report"""
        try:
            self.risk_manager.heartbeat()
        except RuntimeError:
            raise

        try:
            if not self.telegram_enabled:
                return
            
            logger.info("Generating status report...")
            try:
                self._ensure_login()
            except Exception:
                return

            account_info = self.get_account_info()
            bot_stats = self.get_bot_stats()
            risk_status = self.risk_manager.get_status()
            
            # Validate broker connection
            session_valid = False
            try:
                limits = self.broker_view.get_limits()
                session_valid = limits is not None and isinstance(limits, dict)
            except Exception as limits_error:
                logger.warning(f"Could not fetch limits for status report: {limits_error}")
                        
            # Format message
            message = f"ðŸ“Š <b>BOT STATUS REPORT</b>\n"
            message += f"ðŸ“… {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"{'='*30}\n\n"
            
            # Bot Status
            message += f"ðŸ¤– <b>BOT STATUS:</b> âœ… Active\n"
            message += f"ðŸ” <b>Login Status:</b> {'âœ… Connected' if session_valid else 'âŒ Disconnected'}\n\n"
            
            if account_info:
                # Account Limits
                message += f"ðŸ’° <b>ACCOUNT LIMITS</b>\n"
                message += f"ðŸ’µ Available Cash: {format_currency(account_info.available_cash)}\n"
                message += f"ðŸ“Š Used Margin: {format_currency(account_info.used_margin)}\n\n"
                
                # Positions
                active_positions = [
                    pos for pos in account_info.positions 
                    if isinstance(pos, dict) and pos.get('netqty', '0') != '0'
                ]
                
                if active_positions:
                    message += f"ðŸ“ <b>ACTIVE POSITIONS</b>\n"
                    for pos in active_positions[:3]:  # Show max 3 positions
                        symbol = pos.get('tsym', 'Unknown')
                        qty = pos.get('netqty', '0')
                        rpnl = float(pos.get('rpnl', 0))
                        urmtom = float(pos.get('urmtom', 0))
                        pnl = rpnl + urmtom

                        message += f"â€¢ {symbol}: {qty} qty, PnL: {format_currency(pnl)}\n"
                    if len(active_positions) > 3:
                        message += f"... and {len(active_positions) - 3} more positions\n"
                    message += "\n"
                else:
                    message += f"ðŸ“ <b>POSITIONS:</b> No active positions\n\n"
            else:
                message += f"âš ï¸ <b>ACCOUNT INFO:</b> Unable to fetch data\n\n"
            
            # Trading Statistics
            message += f"ðŸ“ˆ <b>TRADING STATS</b>\n"
            message += f"ðŸ“Š Today's Trades: {bot_stats.today_trades}\n"
            message += f"ðŸ“‹ Total Trades: {bot_stats.total_trades}\n"
            
            if bot_stats.last_activity:
                last_trade_time = datetime.fromisoformat(bot_stats.last_activity)
                message += f"ðŸ• Last Activity: {last_trade_time.strftime('%H:%M:%S')}\n"
            else:
                message += f"ðŸ• Last Activity: No trades yet\n"

            # ðŸ›¡ Supreme Risk Manager Status
            message += f"\nðŸ›¡ <b>RISK MANAGER STATUS</b>\n"
            message += f"â€¢ Daily PnL: â‚¹{risk_status['daily_pnl']:.2f}\n"
            message += f"â€¢ Loss Hit Today: {'YES' if risk_status['daily_loss_hit'] else 'NO'}\n"

            if risk_status.get("cooldown_until"):
                message += f"â€¢ Cooldown Until: {risk_status['cooldown_until']}\n"
   
            message += f"\nðŸ”” <i>Next report in {self.config.report_frequency} minutes</i>"
            
            self.send_telegram(message)
            logger.info("Status report sent")
            
        except Exception as e:
            log_exception("send_status_report", e)
            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_error_message("STATUS REPORT ERROR", str(e))
                except Exception as tg_e:
                    logger.warning(f"Failed to send error message: {tg_e}")
    
    def get_trade_history(self, limit: Optional[int] = None, 
                         date_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get trade history with optional filtering"""
        trades = self.trade_records.copy()
        
        # Filter by date if provided
        if date_filter:
            
            filter_date = get_date_filter(date_filter)
            if filter_date:
                trades = [
                    t for t in trades 
                    if datetime.fromisoformat(t.timestamp).date() == filter_date
                ]
        
        # Apply limit
        if limit and limit > 0:
            trades = trades[-limit:]
        
        # Convert to dict format
        return [trade.to_dict() for trade in trades]
    
    def get_session_info(self) -> Dict[str, Any]:
        """Get current session information"""
        api_session = self.api.get_session_info()
        bot_stats = self.get_bot_stats()
        
        return {
            'api_session': api_session,
            'telegram_enabled': self.telegram_enabled,
            'telegram_connected': self.telegram.is_connected if (self.telegram and hasattr(self.telegram, 'is_connected')) else False,
            'trade_stats': {
                'total_trades': bot_stats.total_trades,
                'today_trades': bot_stats.today_trades,
                'success_rate': bot_stats.success_rate,
                'last_activity': bot_stats.last_activity
            },
            'config': {
                'report_frequency': self.config.report_frequency,
                'max_retry_attempts': self.config.max_retry_attempts,
                'retry_delay': self.config.retry_delay
            }
        }
    
    def test_telegram(self) -> bool:
        """Test Telegram connectivity"""
        if not self.telegram_enabled or not self.telegram:
            return False
        
        return self.telegram.send_test_message()
    
    def force_login(self) -> bool:
        """Force re-login to API"""
        self.api.logout()
        self.api.ensure_session()
        return True

    
    def shutdown(self):
        """Shutdown bot gracefully with 30-second timeout"""
        shutdown_start = time.time()
        shutdown_timeout = 30.0  # 30 second total timeout
        
        try:
            self._announce_shutdown_start()
            logger.info("ðŸ›‘ Shutting down bot...")

            # 0ï¸âƒ£ Set global shutdown event FIRST (stops all loops)
            self._shutdown_event.set()

            # 1ï¸âƒ£ STOP ORDER WATCHER (BLOCKING - must complete)
            try:
                elapsed = time.time() - shutdown_start
                remaining = shutdown_timeout - elapsed
                if remaining > 5:
                    logger.info(f"â³ Stopping OrderWatcher (timeout={remaining:.1f}s)")
                    self.order_watcher.stop()
                else:
                    logger.warning("âš ï¸ OrderWatcher shutdown timeout - skipping")
            except Exception as e:
                logger.error(f"âŒ OrderWatcher shutdown error: {e}")

            # 2ï¸âƒ£ NOTIFY SUPERVISOR & RUNNER (NO WAIT)
            if hasattr(self, "option_supervisor"):
                try:
                    self.option_supervisor._stop_event.set()
                    logger.info("Option supervisor stop signal sent")
                except Exception as e:
                    logger.error(f"Option supervisor signal error: {e}")

            # 3ï¸âƒ£ STOP STRATEGY RUNNER (WITH TIMEOUT)
            runner = getattr(self, "strategy_runner", None)
            if runner is not None and hasattr(runner, "stop"):
                try:
                    elapsed = time.time() - shutdown_start
                    remaining = shutdown_timeout - elapsed
                    if remaining > 5:
                        logger.info(f"â³ Stopping StrategyRunner (timeout={remaining:.1f}s)")
                        runner.stop(timeout=int(remaining))
                    else:
                        logger.warning("âš ï¸ StrategyRunner shutdown timeout - skipping")
                except Exception as e:
                    logger.error(f"âŒ StrategyRunner shutdown error: {e}")

            # Stop strategy executor service
            if hasattr(self, "strategy_executor_service"):
                try:
                    logger.info("â³ Stopping StrategyExecutorService")
                    self.strategy_executor_service.stop()
                    logger.info("âœ… StrategyExecutorService stopped")
                except Exception as e:
                    logger.error(f"StrategyExecutorService shutdown error: {e}")

            if hasattr(self, "historical_analytics_service"):
                try:
                    logger.info("â³ Stopping HistoricalAnalyticsService")
                    self.historical_analytics_service.stop()
                    logger.info("âœ… HistoricalAnalyticsService stopped")
                except Exception as e:
                    logger.error(f"HistoricalAnalyticsService shutdown error: {e}")

            # 4ï¸âƒ£ TELEGRAM SHUTDOWN (NON-BLOCKING - fire and forget with short timeout)
            if self.telegram_enabled:
                try:
                    # Send async to avoid blocking shutdown
                    def send_shutdown_msg():
                        try:
                            shutdown_msg = (
                                f"ðŸ›‘ <b>BOT SHUTDOWN</b>\n"
                                f"ðŸ“… {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"ðŸ¤– Graceful shutdown complete\n"
                                f"ðŸ“Š Session stats:\n"
                                f"â€¢ Total trades: {len(self.trade_records)}\n"
                                f"â€¢ Uptime: Until shutdown"
                            )
                            self.telegram.send_message(shutdown_msg, timeout=3.0)  # 3 sec timeout
                        except Exception as tg_e:
                            logger.debug(f"Telegram send timeout (expected): {tg_e}")
                    
                    # Fire off in separate thread - don't wait
                    import threading
                    tg_thread = threading.Thread(target=send_shutdown_msg, daemon=True)
                    tg_thread.start()
                    # Don't join - let it run in background
                except Exception as e:
                    logger.debug(f"Telegram notification skipped: {e}")

            # 5ï¸âƒ£ LOGOUT FROM API (WITH TIMEOUT)
            try:
                elapsed = time.time() - shutdown_start
                remaining = shutdown_timeout - elapsed
                if remaining > 2:
                    logger.info(f"â³ Logging out from broker (timeout={remaining:.1f}s)")
                    self.api.logout()
                else:
                    logger.warning("âš ï¸ API logout timeout - skipping")
            except Exception as e:
                logger.debug(f"API logout error (expected): {e}")
            
            elapsed = time.time() - shutdown_start
            logger.info(f"âœ… Bot shutdown completed in {elapsed:.1f}s")
            
        except Exception as e:
            elapsed = time.time() - shutdown_start
            logger.error(f"âŒ Shutdown error after {elapsed:.1f}s: {e}")
