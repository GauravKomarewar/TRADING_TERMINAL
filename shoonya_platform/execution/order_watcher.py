#!/usr/bin/env python3
"""
OrderWatcherEngine
==================

PRODUCTION-GRADE EXECUTION ENGINE
Aligned with ScriptMaster v2.0 (PRODUCTION FROZEN)

🎯 DESIRED FLOW - OrderWatcher implements STEP 6: BROKER POLLING
=====================================
Step 1: REGISTER TO DB with status=CREATED           [Done by CommandService]
Step 2: SYSTEM BLOCKERS CHECK (Risk/Guard/Dup)       [Done by execute_command]
Step 3: UPDATE TO status=SENT_TO_BROKER              [Done by execute_command]
Step 4: EXECUTE ON BROKER                            [Done by execute_command]
Step 5: UPDATE DB BASED ON BROKER RESULT             [Done by execute_command]
Step 6: ORDERWATCH POLLS BROKER ("EXECUTED TRUTH")  [⭐ THIS MODULE]
   - Check order status on broker
   - If COMPLETE → status=EXECUTED
   - If REJECTED/CANCELLED/EXPIRED → status=FAILED
   - Clear execution guard on failure

Invariants:
- Broker is the ONLY source of EXECUTED truth
- EXIT execution is idempotent and persistent
- Order type rules enforced ONLY via ScriptMaster
- OrderWatcher executes intents, never decides them
- ExecutionGuard is reconciled ONLY from broker truth
"""

import time
import logging
import threading
from typing import Dict

from shoonya_platform.logging.logger_config import get_component_logger
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.execution.intent import UniversalOrderCommand
from scripts.scriptmaster import requires_limit_order

logger = get_component_logger('order_watcher')


class OrderWatcherEngine(threading.Thread):
    """
    OrderWatcherEngine

    Responsibilities:
    ✅ Step 1-5: Done by CommandService/execute_command
    ✅ Step 6: Poll broker, update DB to EXECUTED/FAILED, reconcile guard
    """

    def __init__(self, bot, poll_interval: float = 1.0):
        super().__init__(daemon=True)
        self.bot = bot
        self.poll_interval = poll_interval
        self._running = True
        self.repo = OrderRepository(bot.client_id)
        self._last_failure_log = {}
        self._failure_log_ttl_sec = 60.0

    def _should_log_failure(self, broker_id: str, status: str) -> bool:
        now = time.time()
        key = (broker_id, status)
        last = self._last_failure_log.get(key)
        if last and now - last < self._failure_log_ttl_sec:
            return False
        self._last_failure_log[key] = now
        if len(self._last_failure_log) > 1000:
            cutoff = now - self._failure_log_ttl_sec
            self._last_failure_log = {
                k: ts for k, ts in self._last_failure_log.items() if ts >= cutoff
            }
        return True

    # --------------------------------------------------
    # Thread lifecycle
    # --------------------------------------------------

    def stop(self):
        self._running = False

    def run(self):
        logger.info(
            "🧠 OrderWatcherEngine STEP 6: BROKER POLLING (ScriptMaster v2.0 compliant)"
        )

        while self._running:
            self.bot._ensure_login()
            self._reconcile_broker_orders()  # STEP 6: Poll broker & update to EXECUTED/FAILED
            self._process_open_intents()     # Legacy support for pre-submitted intents
            time.sleep(self.poll_interval)

    # ==================================================
    # STEP 6: RECONCILE WITH BROKER (DEFINITIVE TRUTH)
    # ==================================================

    def _reconcile_broker_orders(self):
        """
        STEP 6: Poll broker for EXECUTED truth.
        
        Updates DB status from SENT_TO_BROKER → EXECUTED/FAILED based on broker reality.
        This is the ONLY source of definitive execution status.
        """
        try:
            broker_orders = self.bot.api.get_order_book() or []
        except Exception:
            logger.exception("OrderWatcher: get_order_book() failed — broker polling skipped this cycle")
            return

        for bo in broker_orders:
            broker_id = bo.get("norenordno")
            status = (bo.get("status") or "").upper()

            if not broker_id or not status:
                continue

            record = self.repo.get_by_broker_id(broker_id)
            if not record:
                continue
            
            # 🔒 Skip already reconciled orders (idempotency)
            if record.status in ("EXECUTED", "FAILED"):
                continue
            
            # ==================================================
            # 📍 BROKER FAILURE (STEP 6A)
            # ==================================================
            if status in ("REJECTED", "CANCELLED", "EXPIRED"):
                logger.warning(
                    f"STEP_6A_BROKER_FAILED | cmd_id={record.command_id} | "
                    f"broker_id={broker_id} | status={status}"
                )
                
                self.repo.update_status(record.command_id, "FAILED")
                if hasattr(self.repo, 'update_tag'):
                    self.repo.update_tag(record.command_id, f"BROKER_{status}")

                # 🔒 FIX: Clear guard state for failed leg
                try:
                    self.bot.execution_guard.force_clear_symbol(
                        strategy_id=record.strategy_name,
                        symbol=record.symbol,
                    )
                    logger.info(
                        f"GUARD_CLEARED | strategy={record.strategy_name} | symbol={record.symbol}"
                    )
                except Exception:
                    logger.exception(
                        "OrderWatcher: failed to clear guard state | strategy=%s symbol=%s",
                        record.strategy_name,
                        record.symbol,
                    )

                if self._should_log_failure(broker_id, status):
                    logger.error(
                        "OrderWatcher: STEP_6A_BROKER_FAILURE | "
                        "cmd_id=%s broker_id=%s status=%s",
                        record.command_id,
                        broker_id,
                        status,
                    )
                continue

            # ==================================================
            # ✅ BROKER EXECUTED (STEP 6B - FINAL TRUTH)
            # ==================================================
            if status == "COMPLETE":
                logger.info(
                    f"STEP_6B_BROKER_EXECUTED | cmd_id={record.command_id} | broker_id={broker_id}"
                )
                
                self.repo.update_status(record.command_id, "EXECUTED")

                logger.info(
                    "OrderWatcher: EXECUTED_CONFIRMED | cmd_id=%s broker_id=%s",
                    record.command_id,
                    broker_id,
                )

                # � NEW: Notify strategy of fill via on_fill() callback
                try:
                    self._notify_strategy_fill(record, bo)
                except Exception:
                    logger.exception(
                        "OrderWatcher: on_fill callback failed | cmd_id=%s",
                        record.command_id,
                    )

                # �🔒 BROKER-TRUTH CONVERGENCE POINT
                self._reconcile_execution_guard(record.strategy_name)

    # --------------------------------------------------
    # ExecutionGuard reconciliation (BROKER-DRIVEN ONLY)
    # --------------------------------------------------

    def _reconcile_execution_guard(self, strategy_name: str) -> None:
        """
        Reconcile ExecutionGuard AFTER broker EXECUTED confirmation.

        This is the ONLY legal place where:
        - Guard reconciliation occurs
        - Strategy cleanup is allowed
        """
        try:
            broker_map = self._build_broker_map()

            self.bot.execution_guard.reconcile_with_broker(
                strategy_id=strategy_name,
                broker_positions=broker_map,
            )

            # If strategy is fully flat after reconciliation,
            # cleanup is now LEGALLY allowed.
            # if strategy_name not in self.bot.execution_guard._strategy_positions:
            if not self.bot.execution_guard.has_strategy(strategy_name):
                self.bot.execution_guard.force_close_strategy(strategy_name)

                logger.info(
                    "OrderWatcher: strategy fully closed | strategy=%s",
                    strategy_name,
                )

        except Exception as e:
            logger.exception(
                "OrderWatcher: guard reconciliation failed | strategy=%s | %s",
                strategy_name,
                e,
            )

    # --------------------------------------------------
    # 🔥 ON_FILL CALLBACK — Wire strategy fill notifications
    # --------------------------------------------------

    def _notify_strategy_fill(self, record, broker_order):
        """
        Extract fill details from broker order and notify strategy via on_fill().

        Broker order format:
        {
          "norenordno": "string",
          "status": "COMPLETE",
          "tsym": "SYMBOL",
          "side": "BUY" / "SELL",
          "fillshares": qty,
          "avgprc": price,
          "prcflag": "LTP" / etc,
          ... (delta may or may not be present)
        }

        Route returned intents through CommandService.
        """
        try:
            symbol = broker_order.get("tsym", record.symbol)
            side = (broker_order.get("side") or "").upper()
            qty = int(broker_order.get("fillshares", 0))
            price = float(broker_order.get("avgprc", 0))
            delta = broker_order.get("delta")  # May be None or string

            if not symbol or not side or qty == 0:
                logger.warning(
                    f"Fill callback: incomplete fill data | cmd_id={record.command_id}"
                )
                return

            # Try to parse delta
            try:
                delta = float(delta) if delta else None
            except (ValueError, TypeError):
                delta = None

            logger.info(
                f"FILL_CALLBACK | cmd_id={record.command_id} | "
                f"{symbol} {side} {qty} @ {price} | delta={delta}"
            )

            # Get all live strategies and call on_fill on each
            # (they'll ignore fills that aren't theirs)
            intents = self._collect_fill_callbacks(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                delta=delta,
                strategy_name=record.strategy_name,
            )

            # Route collected intents through CommandService
            for intent in intents:
                try:
                    self.bot.command_service.submit(intent, execution_type="ADJUSTMENT")
                    logger.info(
                        f"FILL_INTENT_ROUTED | cmd_id={record.command_id} | "
                        f"intent={intent.side} {intent.symbol}"
                    )
                except Exception:
                    logger.exception(
                        "OrderWatcher: failed to route fill intent | cmd_id=%s",
                        record.command_id,
                    )

        except Exception:
            logger.exception(
                "OrderWatcher: _notify_strategy_fill failed | cmd_id=%s",
                record.command_id,
            )

    def _collect_fill_callbacks(
        self, symbol: str, side: str, qty: int, price: float, delta: float, strategy_name: str
    ) -> list:
        """
        Call on_fill() on all live strategies matching the filled symbol/strategy.

        Returns list of UniversalOrderCommand intents for adjustments/exit.
        """
        intents = []

        with self.bot._live_strategies_lock:
            strategies = list(self.bot._live_strategies.items())

        for strat_name, (strategy, market) in strategies:
            # Only notify the strategy that placed the order
            # (or all strategies if strategy_name is unknown)
            if strategy_name and strat_name != strategy_name:
                continue

            if not hasattr(strategy, "on_fill"):
                continue

            try:
                result = strategy.on_fill(
                    symbol=symbol,
                    side=side,
                    price=price,
                    qty=qty,
                    delta=delta,
                )

                if result:
                    intents.extend(result)
                    logger.info(
                        f"Strategy on_fill returned {len(result)} intents | {strat_name}"
                    )

            except Exception:
                logger.exception(
                    "OrderWatcher: strategy.on_fill() failed | strategy=%s | symbol=%s",
                    strat_name,
                    symbol,
                )

        return intents

    # --------------------------------------------------
    # Direction-aware broker map (ExecutionGuard v1.3)
    # --------------------------------------------------

    def _build_broker_map(self) -> Dict[str, Dict[str, int]]:
        """
        Build direction-aware broker map.

        Contract:
            {
              "SYMBOL": {
                "BUY": qty,
                "SELL": qty
              }
            }
        """
        positions = self.bot.api.get_positions() or []
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

        return broker_map

    # ==================================================
    # LEGACY SUPPORT: Intent execution (RARELY USED)
    # ==================================================

    def _process_open_intents(self):
        """
        ⚠️ LEGACY: This is for rare cases where CREATED orders exist.
        Normal flow: CommandService.submit() → execute_command() handles Steps 1-5
        
        This only executes orders that:
        1. Have status=CREATED (not yet sent to broker)
        2. Don't have broker_order_id yet
        """
        intents = self.repo.get_open_orders()
        if not intents:
            return

        for record in intents:
            # Handle CREATED orders that were never submitted
            if record.status == "CREATED" and not record.broker_order_id:
                logger.info(
                    f"LEGACY_INTENT_EXECUTION | cmd_id={record.command_id} | {record.symbol}"
                )
                
                # This should be rare - normally execute_command would have handled this
                # But for compatibility, submit it now
                try:
                    self._execute_legacy_intent(record)
                except Exception:
                    logger.exception(
                        "OrderWatcher: legacy intent execution failed | cmd_id=%s",
                        record.command_id,
                    )

    def _execute_legacy_intent(self, record):
        """
        Execute a legacy intent (rare case where CREATED order wasn't submitted).
        Follows the 6-step flow within this call.
        """
        # --------------------------------------------------
        # ScriptMaster — order type LAW
        # --------------------------------------------------
        must_use_limit = requires_limit_order(
            exchange=record.exchange,
            tradingsymbol=record.symbol,
        )

        order_type = "LIMIT" if must_use_limit else "MARKET"
        price = 0.0

        if must_use_limit:
            ltp = self.bot.api.get_ltp(record.exchange, record.symbol)
            if not ltp:
                return

            # Aggressive but legal (LMT-as-MKT)
            price = float(ltp)

        # --------------------------------------------------
        # Build canonical execution command
        # --------------------------------------------------
        cmd = UniversalOrderCommand.from_record(
            record,
            order_type=order_type,
            price=price,
            source="ORDER_WATCHER",
        )

        # --------------------------------------------------
        # Submit via execute_command (which does Steps 2-5)
        # --------------------------------------------------
        try:
            result = self.bot.execute_command(cmd)
        except Exception:
            logger.exception(
                "OrderWatcher: execution crash | cmd_id=%s",
                record.command_id,
            )
            return

        # Normalize result object/dict for backwards compatibility
        if isinstance(result, dict):
            _R = type("ExecutionResult", (), {})()
            _R.success = result.get("success", result.get("ok", False))
            _R.error_message = (
                result.get("error_message")
                or result.get("error")
                or result.get("emsg")
            )
            _R.order_id = (
                result.get("order_id")
                or result.get("norenordno")
                or result.get("broker_id")
            )
            result = _R

        if not getattr(result, "success", False):
            logger.error(
                "OrderWatcher: legacy submission failed | cmd_id=%s error=%s",
                record.command_id,
                getattr(result, "error_message", None),
            )
            return

        logger.info(
            "OrderWatcher: legacy intent submitted | cmd_id=%s broker_id=%s type=%s",
            record.command_id,
            result.order_id,
            order_type,
        )

    # -----------------------------------------------------------------
    # Compatibility shims for older tests / callers
    # -----------------------------------------------------------------
    def _process_orders(self):
        """
        Backwards-compatible alias for older code/tests that called
        `_process_orders`. Delegates to `_process_open_intents`.
        """
        return self._process_open_intents()

    def _fire_exit(self, order):
        """
        Backwards-compatible exit trigger. Builds a minimal exit command
        and delegates to the `CommandService` for submission.
        """
        try:
            # Build minimal params if Mock/struct-like
            sym = getattr(order, 'symbol', None) or (order.get('symbol') if isinstance(order, dict) else None)
            qty = getattr(order, 'quantity', None) or (order.get('quantity') if isinstance(order, dict) else None)
            exch = getattr(order, 'exchange', None) or (order.get('exchange') if isinstance(order, dict) else None) or "NFO"
            side = getattr(order, 'side', None) or (order.get('side') if isinstance(order, dict) else None)
            product = getattr(order, 'product', None) or (order.get('product') if isinstance(order, dict) else None) or "M"

            # Determine correct exit direction (opposite of position side)
            if side and side.upper() == "BUY":
                exit_direction = "SELL"
            elif side and side.upper() == "SELL":
                exit_direction = "BUY"
            else:
                exit_direction = "SELL"  # Default fallback

            params = {
                "exchange": exch,
                "tradingsymbol": sym,
                "quantity": qty or 0,
                "direction": exit_direction,
                "product": product,
                "order_type": "MARKET",
                "price": None,
            }

            cmd = UniversalOrderCommand.from_order_params(order_params=params, source="ORDER_WATCHER", user=self.bot.client_id)

            # Submit via command service (OrderWatcher expects CommandService to exist on bot)
            try:
                self.bot.command_service.register(cmd, execution_type="EXIT")
            except Exception:
                # best-effort: fall back to direct execute_command
                try:
                    self.bot.execute_command(cmd)
                except Exception:
                    logger.exception("OrderWatcher: failed to fire exit for %s", sym)

        except Exception:
            logger.exception("OrderWatcher: _fire_exit failed")

    def register(self, record):
        """Register an intent/order with OrderWatcher (compat shim).

        Older callers used `order_watcher.register(...)`; provide a thin
        wrapper that persists the record to repository.
        """
        try:
            self.repo.create(record)
        except Exception:
            logger.exception("OrderWatcher: register failed")