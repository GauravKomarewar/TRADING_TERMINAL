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
from typing import Dict, Optional

from shoonya_platform.logging.logger_config import get_component_logger
from shoonya_platform.persistence.repository import OrderRepository

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

                # 🔔 Notify strategy of fill via on_fill() callback
                try:
                    self._notify_strategy_fill(record, bo)
                except Exception:
                    logger.exception(
                        "OrderWatcher: on_fill callback failed | cmd_id=%s",
                        record.command_id,
                    )

                # 🔒 BROKER-TRUTH CONVERGENCE POINT
                self._reconcile_execution_guard(
                    strategy_name=record.strategy_name,
                    executed_symbol=record.symbol,
                )

    # --------------------------------------------------
    # ExecutionGuard reconciliation (BROKER-DRIVEN ONLY)
    # --------------------------------------------------
    def _reconcile_execution_guard(self, strategy_name: str, executed_symbol: str) -> None:
        """
        Reconcile ExecutionGuard AFTER broker EXECUTED confirmation.

        This is the ONLY legal place where:
        - Guard reconciliation occurs
        - Strategy cleanup is allowed
        """
        try:
            symbols = self._get_strategy_symbols(strategy_name)
            if executed_symbol:
                symbols.add(executed_symbol)
            broker_map = self._build_broker_map(symbol_filter=symbols or None)

            self.bot.execution_guard.reconcile_with_broker(
                strategy_id=strategy_name,
                broker_positions=broker_map,
            )

            # Closed means reconciliation removed all tracked legs for this strategy.
            if not self.bot.execution_guard.has_strategy(strategy_name):
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
            # Shoonya API returns trantype as "B"/"S", not "BUY"/"SELL"
            raw_side = (
                broker_order.get("side")
                or broker_order.get("trantype")
                or record.side
                or ""
            ).upper()
            # Normalize: B → BUY, S → SELL
            side_map = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}
            side = side_map.get(raw_side, raw_side)
            
            qty = int(broker_order.get("fillshares") or broker_order.get("qty") or 0)
            price = float(broker_order.get("avgprc") or broker_order.get("flprc") or 0)
            delta = broker_order.get("delta")  # Shoonya doesn't provide this  # May be None or string

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

            # Keep StrategyExecutorService state in sync immediately on broker fill.
            # This avoids pending-timeout drift between OMS and monitor view.
            try:
                self.bot.notify_fill(
                    strategy_name=record.strategy_name,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=price,
                    delta=delta,
                    broker_order_id=record.broker_order_id,
                    command_id=record.command_id,
                )
            except Exception:
                logger.exception(
                    "OrderWatcher: bot.notify_fill failed | cmd_id=%s",
                    record.command_id,
                )

        except Exception:
            logger.exception(
                "OrderWatcher: _notify_strategy_fill failed | cmd_id=%s",
                record.command_id,
            )

    # --------------------------------------------------
    # Direction-aware broker map (ExecutionGuard v1.3)
    # --------------------------------------------------

    def _build_broker_map(self, symbol_filter: Optional[set] = None) -> Dict[str, Dict[str, int]]:
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
            if symbol_filter is not None and sym not in symbol_filter:
                continue

            broker_map.setdefault(sym, {"BUY": 0, "SELL": 0})

            if net > 0:
                broker_map[sym]["BUY"] = net
            else:
                broker_map[sym]["SELL"] = abs(net)

        return broker_map

    def _get_strategy_symbols(self, strategy_name: str) -> set:
        """
        Best-effort fetch of currently tracked symbols for a strategy.
        Used to scope reconciliation to strategy-relevant broker positions only.
        """
        guard = getattr(self.bot, "execution_guard", None)
        if guard is None:
            return set()

        lock = getattr(guard, "_lock", None)
        positions = getattr(guard, "_strategy_positions", None)
        if lock is None or not isinstance(positions, dict):
            return set()

        with lock:
            tracked = positions.get(strategy_name) or {}
            return set(tracked.keys())
