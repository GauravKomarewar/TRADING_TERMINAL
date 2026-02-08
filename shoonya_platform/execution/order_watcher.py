#!/usr/bin/env python3
"""
OrderWatcherEngine
==================

PRODUCTION-GRADE EXECUTION ENGINE
Aligned with ScriptMaster v2.0 (PRODUCTION FROZEN)

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
    - Poll broker order book
    - Persist EXECUTED / FAILED truth
    - Execute OPEN intents mechanically
    - Reconcile ExecutionGuard AFTER broker confirmation
    """

    def __init__(self, bot, poll_interval: float = 1.0):
        super().__init__(daemon=True)
        self.bot = bot
        self.poll_interval = poll_interval
        self._running = True
        self.repo = OrderRepository(bot.client_id)

    # --------------------------------------------------
    # Thread lifecycle
    # --------------------------------------------------

    def stop(self):
        self._running = False

    def run(self):
        logger.info("🧠 OrderWatcherEngine started (ScriptMaster v2.0 compliant)")

        while self._running:
            self.bot._ensure_login()
            self._reconcile_broker_orders()
            self._process_open_intents()
            time.sleep(self.poll_interval)

    # --------------------------------------------------
    # Broker reconciliation (EXECUTED truth ONLY here)
    # --------------------------------------------------

    def _reconcile_broker_orders(self):
        broker_orders = self.bot.api.get_order_book()
        for bo in broker_orders:
            broker_id = bo.get("norenordno")
            status = (bo.get("status") or "").upper()

            if not broker_id or not status:
                continue

            record = self.repo.get_by_broker_id(broker_id)
            if not record:
                continue
            # 🔒 Skip already reconciled orders (idempotency)
            if record.status == "EXECUTED":
                continue
            # -------------------------------
            # Broker FAILURE
            # -------------------------------
            if status in ("REJECTED", "CANCELLED", "EXPIRED"):
                self.repo.update_status(record.command_id, "FAILED")

                # 🔒 FIX: Clear guard state for failed leg
                try:
                    self.bot.execution_guard.force_clear_symbol(
                        strategy_id=record.strategy_name,
                        symbol=record.symbol,
                    )
                except Exception:
                    logger.exception(
                        "OrderWatcher: failed to clear guard state | strategy=%s symbol=%s",
                        record.strategy_name,
                        record.symbol,
                    )

                logger.error(
                    "OrderWatcher: broker failure | cmd_id=%s broker_id=%s status=%s",
                    record.command_id,
                    broker_id,
                    status,
                )
                continue

            # -------------------------------
            # Broker EXECUTED (FINAL TRUTH)
            # -------------------------------
            if status == "COMPLETE":
                self.repo.update_status(record.command_id, "EXECUTED")

                logger.info(
                    "OrderWatcher: EXECUTED | cmd_id=%s broker_id=%s",
                    record.command_id,
                    broker_id,
                )

                # 🔒 BROKER-TRUTH CONVERGENCE POINT
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
        positions = self.bot.api.get_positions()
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

    # --------------------------------------------------
    # Intent execution (MECHANICAL ONLY)
    # --------------------------------------------------

    def _process_open_intents(self):
        intents = self.repo.get_open_orders()
        if not intents:
            return

        for record in intents:
            # 🔒 Idempotency — already submitted
            if record.broker_order_id:
                continue

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
                    continue

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
            # Submit (SINGLE broker path)
            # --------------------------------------------------
            try:
                result = self.bot.execute_command(cmd)
            except Exception:
                logger.exception(
                    "OrderWatcher: execution crash | cmd_id=%s",
                    record.command_id,
                )
                continue

            if not result.success:
                self.repo.update_status(record.command_id, "FAILED")

                logger.error(
                    "OrderWatcher: submission failed | cmd_id=%s error=%s",
                    record.command_id,
                    result.error_message,
                )
                continue

            # --------------------------------------------------
            # Persist submission (NOT executed yet)
            # --------------------------------------------------
            self.repo.update_broker_id(record.command_id, result.order_id)

            logger.info(
                "OrderWatcher: SENT_TO_BROKER | cmd_id=%s broker_id=%s type=%s",
                record.command_id,
                result.order_id,
                order_type,
            )