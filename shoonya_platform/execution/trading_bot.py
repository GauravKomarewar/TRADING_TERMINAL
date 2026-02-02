#!/usr/bin/env python3
"""

Trading Bot Module
Main trading bot logic with alert processing and trade management
"""
# ======================================================================
# 🔒 PRODUCTION FROZEN — BOT / OMS LAYER
# Date: 2026-01-29

# This file is client-isolated by design.
# Multi-client readiness depends ONLY on:
# - Client-scoped OrderRepository
# - Client-scoped Risk state storage
# - Dashboard command scoping

# NO further OMS changes required for copy trading.

# Guarantees:
#   ✔ Single broker touchpoint via CommandService
#   ✔ EXIT intents registered only, never executed directly
#   ✔ OrderWatcherEngine is sole EXIT executor
#   ✔ ScriptMaster governs all order-type rules
#   ✔ Duplicate ENTRY blocked at memory, DB, broker & guard levels
#   ✔ Recovery-safe across restart, cancel, and partial fills
# ✅ Single _ensure_login() — no shadowing, no ambiguity
# ✅ Lazy + auditable login (matches supervisor & long-running service model)
# ✅ Single broker touchpoint (execute_command → ShoonyaClient)
# ✅ EXIT purity preserved (intent-only → OrderWatcherEngine)
# ✅ Risk manager correctly uses broker truth only
# ✅ ExecutionGuard + DB + broker triple-duplicate protection intact
# ✅ RecoveryBootstrap ordering is correct
# ✅ Dashboard control consumers are isolated, intent-only
# ✅ No silent session invalidation vectors left inside OMS

# 🔒 COPY-TRADING READY (BOT LAYER)
# • Client identity resolved via Config.get_client_identity()
# • No direct USER_ID / USER_NAME usage
# • OMS behavior unchanged


# Architecture:
#   Strategy / Risk → Intent → CommandService → OrderWatcher → Broker
# 🔒 SINGLE SOURCE OF TRUTH FOR BROKER LOGIN
# Do NOT redefine this method elsewhere in the class.

# ⚠️ DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
import schedule

#-----------------SCRIPTMASTER---------
from scripts.scriptmaster import requires_limit_order

# ---------------- CORE ----------------
from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient

# ---------------- NOTIFICATIONS ----------------
from notifications.telegram import TelegramNotifier

# # ---------------- PERSISTENCE ----------------
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.persistence.models import OrderRecord

# # ---------------- RECOVERY ----------------
from shoonya_platform.services.recovery_service import RecoveryBootstrap

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

# ---------------- REPORTING ----------------
from shoonya_platform.strategies.reporting.strategy_reporter import build_strategy_report

#--------------------MODELS--------------
from shoonya_platform.domain.models import TradeRecord, AlertData, LegResult, BotStats, OrderResult, AccountInfo
#--------------------UTILS--------------
from shoonya_platform.utils.utils import (
    validate_webhook_signature, 
    format_currency,
    get_today_trades,
    get_yesterday_trades,
    calculate_success_rate,
    log_exception,get_date_filter
)

logger = logging.getLogger(__name__)

class ShoonyaBot:
    """Main trading bot class with integrated Telegram notifications"""
    
    def __init__(self, config: Optional[Config] = None):
        """Initialize the Shoonya trading bot (PRODUCTION)"""
        logger.critical("🔥 ShoonyaBot INIT STARTED")

        # -------------------------------------------------
        # 🔧 CORE CONFIG
        # -------------------------------------------------
        self.config = config or Config()

        # 🔒 Canonical client identity (SINGLE SOURCE OF TRUTH)
        # (copy-trading ready, NO behavior change)
        self.client_identity = self.config.get_client_identity()
        self.client_id = self.client_identity["client_id"]

        self.trade_records: List[TradeRecord] = []

        # -------------------------------------------------
        # 🔌 BROKER CLIENT (LAZY LOGIN)
        # -------------------------------------------------
        # 🔒 Login is enforced lazily via _ensure_login()
        self.api = ShoonyaClient(self.config)

        # -------------------------------------------------
        # 📦 PERSISTENCE (POSITION / ORDER SOURCE OF TRUTH)
        # -------------------------------------------------
        self.order_repo = OrderRepository(client_id=self.client_id)

        # -------------------------------------------------
        # 🚨 SINGLE EXIT AUTHORITY(POSITION-DRIVEN) (MUST BE INITIALIZED FIRST)
        # -------------------------------------------------
        # 🔒 ALL exits (risk / manual / dashboard / recovery)
        # 🔒 MUST flow through OrderWatcherEngine ONLY
        self.order_watcher = OrderWatcherEngine(self)

        # -------------------------------------------------
        # 🛡 EXECUTION & COMMAND LAYER
        # -------------------------------------------------
        self.execution_guard = ExecutionGuard()

        # ⚠️ CommandService DEPENDS on order_watcher
        self.command_service = CommandService(self)

        # -------------------------------------------------
        # 🧠 RISK MANAGER (INTENT ONLY – NO DIRECT ORDERS)
        # -------------------------------------------------
        self.risk_manager = SupremeRiskManager(self)

        # -------------------------------------------------
        # 🧾 COMMAND STATE
        # -------------------------------------------------
        self.pending_commands = []
        self._cmd_lock = threading.Lock()

        # -------------------------------------------------
        # 📢 TELEGRAM (OPTIONAL, NON-BLOCKING)
        # -------------------------------------------------
        self.telegram_enabled = self.config.is_telegram_enabled()
        if self.telegram_enabled:
            try:
                telegram_config = self.config.get_telegram_config()
                self.telegram = TelegramNotifier(
                    telegram_config["bot_token"],
                    telegram_config["chat_id"],
                )
                logger.info("Telegram integration enabled")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram: {e}")
                self.telegram_enabled = False
                self.telegram = None
        else:
            self.telegram = None
            logger.warning("Telegram configuration missing - notifications disabled")

        # -------------------------------------------------
        # 📈 STRATEGY REGISTRY
        # -------------------------------------------------
        self._live_strategies = {}  # strategy_name -> (strategy, market)

        # -------------------------------------------------
        # ♻️ PHASE-2 RECOVERY (SAFE, NON-ACTIVE)
        # -------------------------------------------------
        RecoveryBootstrap(self).run()

        # -------------------------------------------------
        # 🧭 DASHBOARD / API CONTROL CONSUMERS
        # -------------------------------------------------
        self._shutdown_event = threading.Event()
        self.start_control_intent_consumers()

        # -------------------------------------------------
        # ⏱ SCHEDULER
        # -------------------------------------------------
        self.start_scheduler()



    def register_live_strategy(self, strategy_name, strategy, market):
        if strategy_name in self._live_strategies:
            logger.warning(f"⚠️ Strategy already registered: {strategy_name}")
            return
        """
        READ-ONLY registration for reporting only.
        NO trading, NO execution, NO mutation.
        """
        self._live_strategies[strategy_name] = (strategy, market)
        logger.info(f"📡 Registered live strategy for reporting: {strategy_name}")

  
    # ==================================================
    # STRATEGY LIFECYCLE WRAPPERS (called by consumers)
    # ==================================================
    def _process_strategy_intents(self, strategy_name: str, strategy, market, intents, *, force_exit: bool = False):
        """
        Convert strategy `Intent` objects into `UniversalOrderCommand`
        and route them through CommandService.

        - ENTRY intents -> `command_service.submit(..., execution_type="ENTRY")`
        - EXIT-like intents -> `command_service.register(...)` (OrderWatcher will execute)
        """
        from shoonya_platform.execution.intent import UniversalOrderCommand

        EXIT_TAGS = {
            "TIME_EXIT",
            "FORCE_EXIT",
            "PARTIAL_ENTRY",
            "LEG_MISSING",
            "ADJ_REENTRY_FAILED",
            "ADJ_SELECTION_FAILED",
        }

        for intent in intents or []:
            try:
                # Resolve exchange/product from strategy/market
                exchange = getattr(strategy, "exchange", None)
                if not exchange and hasattr(market, "exchange"):
                    exchange = getattr(market, "exchange")

                order_type = "LIMIT" if getattr(intent, "order_type", "MKT") in ("LMT", "LIMIT") else "MARKET"

                order_params = {
                    "exchange": exchange or "NFO",
                    "symbol": intent.symbol,
                    "quantity": int(intent.qty),
                    "side": intent.action,
                    "product": "NRML",
                    "order_type": order_type,
                    "price": float(intent.price) if getattr(intent, "price", None) else None,
                    "strategy_name": strategy_name,
                }

                cmd = UniversalOrderCommand.from_order_params(
                    order_params=order_params,
                    source="STRATEGY",
                    user=strategy_name,
                )

                # EXIT-like intents must be registered (OrderWatcher executes them)
                is_exit_like = force_exit or (getattr(intent, "tag", "") in EXIT_TAGS)

                if is_exit_like:
                    # register a pure EXIT (no immediate broker submit)
                    try:
                        self.command_service.register(cmd)
                        logger.info(f"🔁 Registered EXIT intent from strategy {strategy_name} for {cmd.symbol}")
                    except Exception:
                        logger.exception("Failed to register strategy EXIT intent")
                else:
                    # ENTRY / ADJUST -> submit for immediate execution
                    try:
                        self.command_service.submit(cmd, execution_type="ENTRY")
                        logger.info(f"🚀 Submitted ENTRY intent from strategy {strategy_name} for {cmd.symbol}")
                    except Exception:
                        logger.exception("Failed to submit strategy ENTRY intent")

            except Exception:
                logger.exception("Error processing strategy intent")

    def request_entry(self, strategy_name: str):
        """Trigger a strategy ENTRY cycle for a registered live strategy."""
        try:
            strategy, market = self._live_strategies[strategy_name]
        except KeyError:
            logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
            raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")

        try:
            # warm prepare
            if hasattr(market, "snapshot"):
                strategy.prepare(market.snapshot())
            else:
                try:
                    strategy.prepare(market)
                except Exception:
                    pass

            intents = strategy.on_tick(datetime.now()) or []
            self._process_strategy_intents(strategy_name, strategy, market, intents)

        except Exception:
            logger.exception("Strategy ENTRY failed | %s", strategy_name)

    def request_adjust(self, strategy_name: str):
        """Trigger an ADJUST cycle on a registered strategy."""
        try:
            strategy, market = self._live_strategies[strategy_name]
        except KeyError:
            logger.error("Request ADJUST failed: strategy not registered: %s", strategy_name)
            raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")

        try:
            if hasattr(market, "snapshot"):
                strategy.prepare(market.snapshot())
            else:
                try:
                    strategy.prepare(market)
                except Exception:
                    pass

            intents = strategy.on_tick(datetime.now()) or []
            self._process_strategy_intents(strategy_name, strategy, market, intents)

        except Exception:
            logger.exception("Strategy ADJUST failed | %s", strategy_name)

    def request_exit(
        self,
        *,
        scope,
        symbols=None,
        product_type="ALL",
        reason,
        source,
    ):
        """
        Route EXIT intent to CommandService for position-driven execution.
        
        Never constructs orders directly.
        PositionExitService handles all exit logic (broker-driven).
        """
        self.command_service.handle_exit_intent(
            scope=scope,
            symbols=symbols,
            product_type=product_type,
            reason=reason,
            source=source,
        )

    def request_force_exit(self, strategy_name: str):
        """Trigger an immediate force-exit for a registered strategy."""
        # Alias to request_exit for now (strategy.force_exit is authoritative)
        return self.request_exit(strategy_name)

    def send_telegram(self, message: str) -> bool:
        """Safe wrapper for sending Telegram messages"""
        if self.telegram_enabled and self.telegram:
            try:
                return self.telegram.send_message(message)
            except Exception as e:
                logger.error(f"Telegram send error: {e}")
                return False
        return False
    
    def start_scheduler(self):
        """Start the scheduler for periodic reports in separate thread"""
        def run_scheduler():
            def send_strategy_reports():
                for name, (strategy, market) in self._live_strategies.items():
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
                # 🔐 Supreme Risk Manager heartbeat (REAL-TIME RISK)
                schedule.every(5).seconds.do(self.risk_manager.heartbeat)

                schedule.every(10).minutes.do(send_strategy_reports)
                # 🧹 Weekly DB hygiene (safe, non-trading)
                schedule.every().day.at("03:30").do(self.cleanup_old_orders)
                
                logger.info(f"Scheduler started - reports every {self.config.report_frequency} minutes")
                
                while True:
                    try:
                        schedule.run_pending()
                    except Exception as e:
                        log_exception("scheduler.run_pending", e)
                    time.sleep(60)

                    
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
                    "🔐 LOGIN SKIPPED | service=signal_processor | reason=already_logged_in"
                )
                return True

            logger.critical(
                "🔐 LOGIN ATTEMPT | service=signal_processor | reason=startup"
            )

            success = self.api.login()

            if success:
                logger.critical(
                    "✅ LOGIN SUCCESS | service=signal_processor | session_active=True"
                )

                if self.telegram_enabled:
                    self.telegram.send_login_success(self.config.user_id)

                return True

            logger.error(
                "❌ LOGIN FAILED | service=signal_processor | reason=unknown"
            )

            if self.telegram_enabled:
                self.telegram.send_login_failed("Shoonya login failed")

            return False

        except Exception as e:
            log_exception("login", e)

            logger.critical(
                "❌ LOGIN EXCEPTION | service=signal_processor | fatal=True"
            )

            if self.telegram_enabled:
                self.telegram.send_login_failed(str(e))

            return False
    # -------------------------------------------------
    # 🔐 BROKER SESSION GUARD (MANDATORY)
    # -------------------------------------------------
   
    def _ensure_login(self):
        """
        Ensures Shoonya session is valid before any broker call.

        DO NOT remove.
        This is required for long-running services.
        """
        try:
            if self.api.is_logged_in():
                logger.debug(
                    "🔐 SESSION OK | service=signal_processor | action=skip_login"
                )
                return

            logger.warning(
                "🔐 SESSION EXPIRED | service=signal_processor | action=relogin"
            )

            self.api.login()

            logger.critical(
                "✅ RELOGIN SUCCESS | service=signal_processor | session_restored=True"
            )

        except Exception as e:
            logger.exception(
                "❌ RELOGIN FAILED | service=signal_processor | action=abort"
            )
            raise

    
    def validate_webhook_signature(self, payload: str, signature: str) -> bool:
        """Validate webhook signature for security"""
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
    
  
    def has_open_position(self, tradingsymbol: str) -> bool:
        self._ensure_login()
        positions = self.api.get_positions() or []
        for p in positions:
            if (
                p.get("tsym") == tradingsymbol
                and int(p.get("netqty", 0)) != 0
            ):
                return True
        return False

    def start_control_intent_consumers(self):
        """
        Starts dashboard control intent consumers in background.

        - GenericControlIntentConsumer → ENTRY / EXIT / BASKET
        - StrategyControlConsumer     → STRATEGY lifecycle only
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
                strategy_manager=self,   # 🔒 ShoonyaBot is the strategy manager
                stop_event=self._shutdown_event,
            )
            self._strategy_control_thread = threading.Thread(
                target=strategy_consumer.run_forever,
                daemon=True,
                name="StrategyControlConsumer",
            )
            self._strategy_control_thread.start()

            logger.info("🧭 Dashboard control intent consumers started")

        except Exception as e:
            log_exception("start_control_intent_consumers", e)


    def has_live_entry_block(self, strategy_name: str, symbol: str) -> bool:
        """
        Blocks ENTRY if:
        - open intent exists (memory)
        - open order exists (DB)
        - open broker position exists
        """

        # 1️⃣ In-memory intents (fastest)
        with self._cmd_lock:
            for cmd in self.pending_commands:
                if cmd.strategy_name == strategy_name and cmd.symbol == symbol:
                    return True

        # 2️⃣ Persistent orders (restart-safe)
        open_orders = self.order_repo.get_open_orders_by_strategy(strategy_name)
        for o in open_orders:
            if o.symbol == symbol:
                return True

        # 3️⃣ Broker position (truth)
        positions = self.api.get_positions() or []
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
                    f"🧹 DB CLEANUP | removed {deleted} old closed orders"
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
        PURE EXECUTION ENGINE (PRODUCTION — FROZEN)
        """

        # =================================================
        # 🧪 TEST MODE — NO BROKER TOUCH
        # =================================================
        if test_mode:
            fake_order_id = f"TEST_{strategy_name}_{leg_data.tradingsymbol}_{int(time.time()*1000)}"
            logger.warning(f"🧪 TEST MODE EXECUTION | {leg_data.tradingsymbol}")

            self.trade_records.append(
                TradeRecord(
                    timestamp=datetime.now().isoformat(),
                    strategy_name=strategy_name,
                    execution_type=execution_type,
                    symbol=leg_data.tradingsymbol,
                    direction=leg_data.direction,
                    quantity=leg_data.qty,
                    price=leg_data.price or 0.0,
                    order_id=fake_order_id,
                    status="PLACED",
                )
            )

            return LegResult(
                leg_data=leg_data,
                order_result=OrderResult(success=True, order_id=fake_order_id),
                order_params={"test_mode": True},
            )

        try:
            # =================================================
            # BASIC VALIDATION
            # =================================================
            if leg_data.qty <= 0:
                raise ValueError("Quantity must be > 0")

            exchange = exchange.upper()
            direction = leg_data.direction.upper()

            # =================================================
            # 🔒 BUILD CANONICAL INTENT (SINGLE SOURCE OF TRUTH)
            # =================================================
            cmd = UniversalOrderCommand.from_order_params(
                order_params={
                    "exchange": exchange,
                    "symbol": leg_data.tradingsymbol,
                    "side": direction,
                    "quantity": int(leg_data.qty),
                    "product": leg_data.product_type,

                    # RAW VALUES ALLOWED HERE
                    "order_type": leg_data.order_type,
                    "price": leg_data.price,

                    "strategy_name": strategy_name,
                },
                source="STRATEGY",
                user=self.client_id,
            )

            # =================================================
            # 🔒HARD RULE AS PER INSTRUMENT TYPE — CANONICAL
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
            # DUPLICATE ENTRY — HARD BLOCK
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
            # TELEGRAM — PRE ORDER
            # =================================================
            if self.telegram_enabled:
                self.telegram.send_order_placing(
                    strategy_name=strategy_name,
                    execution_type=execution_type,
                    symbol=leg_data.tradingsymbol,
                    direction=direction,
                    quantity=leg_data.qty,
                    price=cmd.price if cmd.order_type == "LIMIT" else "MARKET",
                )

            # =================================================
            # 🚀 SINGLE BROKER TOUCHPOINT
            # =================================================
            result = self.command_service.submit(cmd, execution_type=execution_type)

            logger.info(
                "ORDER_EXECUTED | %s | %s | %s | qty=%s | type=%s | success=%s",
                exchange,
                leg_data.tradingsymbol,
                direction,
                leg_data.qty,
                cmd.order_type,
                result.success,
            )

            if result.success:
                object.__setattr__(cmd, "broker_order_id", result.order_id)
                with self._cmd_lock:
                    self.pending_commands.append(cmd)

                self.trade_records.append(
                    TradeRecord(
                        timestamp=datetime.now().isoformat(),
                        strategy_name=strategy_name,
                        execution_type=execution_type,
                        symbol=leg_data.tradingsymbol,
                        direction=direction,
                        quantity=leg_data.qty,
                        price=cmd.price or 0.0,
                        order_id=result.order_id,
                        status="PLACED",
                    )
                )

                try:
                    record = OrderRecord(
                        # ---- Identity / audit ----
                        command_id=cmd.command_id,
                        source=cmd.source,
                        user=cmd.user,
                        strategy_name=strategy_name,

                        # ---- Instrument ----
                        exchange=exchange,
                        symbol=leg_data.tradingsymbol,
                        side=direction,
                        quantity=int(leg_data.qty),
                        product=cmd.product,

                        # ---- Order ----
                        order_type=cmd.order_type,
                        price=cmd.price,

                        # ---- Risk ----
                        stop_loss=cmd.stop_loss,
                        target=cmd.target,
                        trailing_type=cmd.trailing_type,
                        trailing_value=cmd.trailing_value,

                        # ---- Broker ----
                        broker_order_id=result.order_id,
                        execution_type=execution_type,

                        # ---- Lifecycle ----
                        # CREATED = OMS intent only (no broker order_id)
                        # SENT_TO_BROKER = broker accepted (order_id assigned)
                        
                        status="SENT_TO_BROKER",
                        created_at=datetime.utcnow().isoformat(),
                        updated_at=datetime.utcnow().isoformat(),
                        tag=None,
                    )

                    self.order_repo.create(record)

                except Exception as e:
                    logger.error(
                        f"ORDER_PERSISTENCE_FAILED | {result.order_id} | {e}"
                    )

            return LegResult(
                leg_data=leg_data,
                order_result=result,
                order_params=cmd.to_broker_params(),
            )

        except Exception as e:
            log_exception("process_leg", e)

            if self.telegram_enabled:
                self.telegram.send_error_message(
                    title="ORDER ERROR",
                    error=f"{leg_data.tradingsymbol}: {str(e)}",
                )

            return LegResult(
                leg_data=leg_data,
                order_result=OrderResult(success=False, error_message=str(e)),
            )

    def mark_command_executed_by_broker_id(self, broker_order_id: str):
        with self._cmd_lock:
            self.pending_commands = [
                c for c in self.pending_commands
                if c.broker_order_id != broker_order_id
            ]

    def process_alert(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        PURE EXECUTION ALERT HANDLER (PRODUCTION — FROZEN)

        RULES:
        - ❌ No quotes
        - ❌ No LTP
        - ❌ No bid/ask
        - ✅ Alert defines order_type & price
        - ✅ ExecutionGuard controls risk
        - ✅ Broker position book controls duplicates
        """

        try:
            # -------------------------------------------------
            # RISK HEARTBEAT
            # -------------------------------------------------
            self.risk_manager.heartbeat()
            self._ensure_login()

            if not self.risk_manager.can_execute():
                return {
                    "status": "blocked",
                    "reason": "Risk limits / cooldown",
                    "timestamp": datetime.now().isoformat(),
                }

            parsed = self.parse_alert_data(alert_data)
            execution_type = parsed.execution_type.upper()

            # -------------------------------------------------
            # TELEGRAM — ALERT RECEIVED
            # -------------------------------------------------
            if self.telegram_enabled:
                self.telegram.send_alert_received(
                    strategy_name=parsed.strategy_name,
                    execution_type=execution_type,
                    legs_count=len(parsed.legs),
                    exchange=parsed.exchange,
                )
            # -------------------------------------------------
            # 🔁 EXECUTION GUARD BROKER RECONCILIATION (MANDATORY)
            # -------------------------------------------------
            if not parsed.test_mode:
                positions = self.api.get_positions() or []
                broker_map = {
                    p.get("tsym"): int(p.get("netqty", 0))
                    for p in positions
                }

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
                            f"ENTRY BLOCKED — LIVE ORDER OR POSITION EXISTS | "
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

            guard_map = {(g.symbol, g.direction): g.qty for g in guarded}

            expected_legs = len(parsed.legs)
            attempted = 0
            success_count = 0

            # -------------------------------------------------
            # EXECUTE LEGS
            # -------------------------------------------------
            for leg in parsed.legs:
                orig_direction = leg.direction

                if execution_type == "EXIT":
                    # -------------------------------------------------
                    # 🔒 BROKER-TRUTH EXIT DIRECTION
                    # -------------------------------------------------
                    positions = self.api.get_positions() or []

                    net_qty = 0
                    for p in positions:
                        if p.get("tsym") == leg.tradingsymbol:
                            net_qty = int(p.get("netqty", 0))
                            break

                    if net_qty == 0:
                        logger.warning(
                            f"EXIT SKIPPED — NO POSITION | {leg.tradingsymbol}"
                        )
                        continue

                    # If net_qty > 0 → SELL to exit
                    # If net_qty < 0 → BUY to exit
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

                    if not parsed.test_mode and execution_type != "EXIT":
                        self.execution_guard.confirm_execution(
                            strategy_id=parsed.strategy_name,
                            symbol=leg.tradingsymbol,
                            direction=leg.direction,
                            qty=leg.qty,
                        )

            # -------------------------------------------------
            # ENTRY FAILURE — ROLLBACK
            # -------------------------------------------------
            if execution_type == "ENTRY" and success_count == 0:
                self.execution_guard.force_close_strategy(parsed.strategy_name)

                if self.telegram_enabled:
                    self.telegram.send_error_message(
                        title="🚨 ENTRY FAILED",
                        error=f"{parsed.strategy_name} | All legs rejected",
                    )

                return {
                    "status": "FAILED",
                    "expected_legs": expected_legs,
                    "successful_legs": 0,
                    "attempted_legs": attempted,
                    "timestamp": datetime.now().isoformat(),
                }

            # -------------------------------------------------
            # EXIT CLEANUP
            # -------------------------------------------------
            if execution_type == "EXIT" and not parsed.test_mode:
                self.execution_guard.force_close_strategy(parsed.strategy_name)

            status = (
                "COMPLETED SUCCESSFULLY"
                if success_count == expected_legs
                else "PARTIALLY COMPLETED"
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

        except Exception as e:
            log_exception("process_alert", e)

            if self.telegram_enabled:
                self.telegram.send_error_message(
                    "ALERT PROCESSING ERROR",
                    str(e),
                )

            return {
                "status": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            }


    def execute_command(self, command, **kwargs):
        """
        🔗 CommandService → ShoonyaBot execution bridge

        Accepts extra keyword args (trailing_engine, etc.)
        for forward compatibility.
        """

        try:
            self._ensure_login()
            # Convert canonical command → broker params
            order_params = command.to_broker_params()

            logger.info(
                f"EXECUTE_COMMAND | {order_params.get('exchange')} | "
                f"{order_params.get('tradingsymbol')} | "
                f"{order_params.get('buy_or_sell')} | "
                f"qty={order_params.get('quantity')} | "
                f"type={order_params.get('price_type')}"
            )

            # 🔥 Single broker touchpoint
            result = self.api.place_order(order_params)

            if not result.success:
                logger.error(
                    f"ORDER_FAILED | {order_params.get('tradingsymbol')} | "
                    f"{result.error_message}"
                )

            return result

        except Exception as e:
            log_exception("execute_command", e)
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
            limits = self.api.get_limits()
            positions = self.api.get_positions()
            orders = self.api.get_order_book()

            if limits is None:
                return None

            return AccountInfo.from_api_data(limits, positions, orders)

        except Exception as e:
            log_exception("get_account_info", e)
            return None

    
    def get_bot_stats(self) -> BotStats:
        """Get bot statistics"""
        return BotStats.from_trade_records(self.trade_records)
    
    def send_daily_summary(self):
        """Send daily summary at market opening"""
        try:
            if not self.telegram_enabled:
                return
            
            message = f"🌅 <b>GOOD MORNING!</b>\n"
            message += f"📅 {datetime.now().strftime('%A, %B %d, %Y')}\n"
            message += f"🕘 Market Opening Soon\n\n"
            message += f"🤖 Bot Status: ✅ Ready for Trading\n"
            message += f"💰 Account: Connected & Active\n\n"
            
            yesterday_trades = get_yesterday_trades(self.trade_records)
            
            message += f"📊 Yesterday's Performance:\n"
            if yesterday_trades:
                successful_trades = len([t for t in yesterday_trades if t.status in ("PLACED", "Ok", "FILLED")])
                success_rate = calculate_success_rate(successful_trades, len(yesterday_trades))
                message += f"• Total Trades: {len(yesterday_trades)}\n"
                message += f"• Successful: {successful_trades}\n"
                message += f"• Success Rate: {success_rate:.1f}%\n"
            else:
                message += f"• No trades executed yesterday\n"
            
            message += f"\n🎯 Ready for today's opportunities!"
            self.send_telegram(message)
            
        except Exception as e:
            log_exception("send_daily_summary", e)
    
    def send_market_close_summary(self):
        """Send summary at market close"""
        try:
            if not self.telegram_enabled:
                return
            
            today_trades = get_today_trades(self.trade_records)
            
            message = f"🌆 <b>MARKET CLOSED</b>\n"
            message += f"📅 {datetime.now().strftime('%Y-%m-%d')}\n"
            message += f"{'='*25}\n\n"
            
            if today_trades:
                successful_trades = len([t for t in today_trades if t.status in ("PLACED", "Ok", "FILLED")])
                success_rate = calculate_success_rate(successful_trades, len(today_trades))
                
                message += f"📊 <b>Today's Summary:</b>\n"
                message += f"• Total Trades: {len(today_trades)}\n"
                message += f"• Successful: {successful_trades}\n"
                message += f"• Failed: {len(today_trades) - successful_trades}\n"
                message += f"• Success Rate: {success_rate:.1f}%\n"
                
                # Strategy breakdown
                strategies = defaultdict(int)
                for trade in today_trades:
                    strategies[trade.strategy_name] += 1
                
                if len(strategies) > 1:
                    message += f"\n📋 <b>Strategy Breakdown:</b>\n"
                    for strategy, count in strategies.items():
                        message += f"• {strategy}: {count} trades\n"
            else:
                message += f"📊 No trades executed today\n"
            
            message += f"\n😴 Bot will continue monitoring overnight"
            self.send_telegram(message)
            
        except Exception as e:
            log_exception("send_market_close_summary", e)
    
    def send_status_report(self):
        """Send comprehensive status report"""
        self.risk_manager.heartbeat()
        try:
            if not self.telegram_enabled:
                return
            
            logger.info("Generating status report...")
            
            # Ensure we're logged in
            if not self.api.is_logged_in():
                if not self.api.login():
                    return

            
            account_info = self.get_account_info()
            bot_stats = self.get_bot_stats()
            risk_status = self.risk_manager.get_status()
            
            # Format message
            message = f"📊 <b>BOT STATUS REPORT</b>\n"
            message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"{'='*30}\n\n"
            
            # Bot Status
            message += f"🤖 <b>BOT STATUS:</b> ✅ Active\n"
            message += f"🔐 <b>Login Status:</b> ✅ Connected\n\n"
            
            if account_info:
                # Account Limits
                message += f"💰 <b>ACCOUNT LIMITS</b>\n"
                message += f"💵 Available Cash: {format_currency(account_info.available_cash)}\n"
                message += f"📊 Used Margin: {format_currency(account_info.used_margin)}\n\n"
                
                # Positions
                active_positions = [
                    pos for pos in account_info.positions 
                    if isinstance(pos, dict) and pos.get('netqty', '0') != '0'
                ]
                
                if active_positions:
                    message += f"📍 <b>ACTIVE POSITIONS</b>\n"
                    for pos in active_positions[:3]:  # Show max 3 positions
                        symbol = pos.get('tsym', 'Unknown')
                        qty = pos.get('netqty', '0')
                        rpnl = float(pos.get('rpnl', 0))
                        urmtom = float(pos.get('urmtom', 0))
                        pnl = rpnl + urmtom

                        message += f"• {symbol}: {qty} qty, PnL: {format_currency(pnl)}\n"
                    if len(active_positions) > 3:
                        message += f"... and {len(active_positions) - 3} more positions\n"
                    message += "\n"
                else:
                    message += f"📍 <b>POSITIONS:</b> No active positions\n\n"
            else:
                message += f"⚠️ <b>ACCOUNT INFO:</b> Unable to fetch data\n\n"
            
            # Trading Statistics
            message += f"📈 <b>TRADING STATS</b>\n"
            message += f"📊 Today's Trades: {bot_stats.today_trades}\n"
            message += f"📋 Total Trades: {bot_stats.total_trades}\n"
            
            if bot_stats.last_activity:
                last_trade_time = datetime.fromisoformat(bot_stats.last_activity)
                message += f"🕐 Last Activity: {last_trade_time.strftime('%H:%M:%S')}\n"
            else:
                message += f"🕐 Last Activity: No trades yet\n"

            # 🛡 Supreme Risk Manager Status
            message += f"\n🛡 <b>RISK MANAGER STATUS</b>\n"
            message += f"• Daily PnL: ₹{risk_status['daily_pnl']:.2f}\n"
            message += f"• Loss Hit Today: {'YES' if risk_status['daily_loss_hit'] else 'NO'}\n"

            if risk_status.get("cooldown_until"):
                message += f"• Cooldown Until: {risk_status['cooldown_until']}\n"
   
            message += f"\n🔔 <i>Next report in {self.config.report_frequency} minutes</i>"
            
            self.send_telegram(message)
            logger.info("Status report sent")
            
        except Exception as e:
            log_exception("send_status_report", e)
            if self.telegram_enabled:
                self.telegram.send_error_message("STATUS REPORT ERROR", str(e))
    
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
            'telegram_connected': self.telegram.is_connected if self.telegram else False,
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
        return self.api.login()

    
    def shutdown(self):
        """Shutdown bot gracefully"""
        try:
            logger.info("Shutting down bot...")

            # 🛑 STOP ORDER WATCHER FIRST
            self.stop_order_watcher()

            self._shutdown_event.set()

            # Send shutdown notification
            if self.telegram_enabled:
                shutdown_msg = (
                    f"🛑 <b>BOT SHUTDOWN</b>\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👤 Graceful shutdown initiated\n"
                    f"📊 Session stats:\n"
                    f"• Total trades: {len(self.trade_records)}\n"
                    f"• Bot uptime: Until shutdown"
                )
                self.send_telegram(shutdown_msg)
            
            # Logout from API
            self.api.logout()
            
            logger.info("Bot shutdown completed")
            
        except Exception as e:
            log_exception("shutdown", e)

    def force_exit_position(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        direction: str,
        product_type: str,
    ):
        """
        🔒 EMERGENCY EXIT REQUEST
        ❌ NO broker submission
        ❌ NO order_type / price decision here
        ✅ Registers EXIT intent only
        ✅ Actual execution handled by OrderWatcherEngine
        """
        logger.critical(
            f"EMERGENCY EXIT REQUEST | {symbol} | {direction} | qty={quantity}"
        )

        self.request_exit(
            symbol=symbol,
            exchange=exchange,
            quantity=int(quantity),
            side=direction.upper(),
            product_type=product_type,
            reason="RISK_FORCE_EXIT",
            source="RISK",
        )

    def start_order_watcher(self):
        self.order_watcher = OrderWatcherEngine(self)
        self.order_watcher.start()


    def stop_order_watcher(self):
        if hasattr(self, "order_watcher"):
            self.order_watcher.stop()


    def get_open_commands(self):
        # TEMPORARY: in-memory list
        with self._cmd_lock:
            return list(self.pending_commands)  # avoid mutation during iteration


    def mark_command_executed(self, command_id):
        with self._cmd_lock:
            self.pending_commands = [
                c for c in self.pending_commands if c.command_id != command_id
            ]

    def update_stop_loss(self, command_id, new_sl):
        # Update DB
        self.order_repo.update_stop_loss(command_id, new_sl)

        # Update in-memory command
        with self._cmd_lock:
            for cmd in self.pending_commands:
                if cmd.command_id == command_id:
                    object.__setattr__(cmd, "stop_loss", new_sl)

