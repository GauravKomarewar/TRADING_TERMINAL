#!/usr/bin/env python3
"""
Execution-side Generic consumer for DASHBOARD control intents
====================================================

ROLE:
- Consume dashboard-generated control intents
- Execute OMS-level system order mutations
- Convert generic intents into TradingView-style alerts
- Route execution intents via process_alert() ONLY
- Never place broker orders directly

This guarantees:
Dashboard == TradingView == Strategy alerts
"""
# ======================================================================
# 🔒 CODE FREEZE — PRODUCTION APPROVED
#
# Component : Generic ControlIntentConsumer
# Version   : v1.1.2
# Status    : PRODUCTION FROZEN
# Date      : 2026-01-30
#
# Guarantees preserved:
# - Single login authority
# - Intent-only dashboard
# - Watcher-only execution
# - Full risk enforcement
# - Full audit trail
# - Zero session races
# - Dashboard intents follow TradingView execution path
# - No broker access
# - No execution bypass
# - Recovery-safe, idempotent
# - Full risk management support (target, stoploss, trailing)
#
# DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import json
import time
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("EXECUTION.CONTROL")

# Cross-platform database path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(
    _PROJECT_ROOT
    / "shoonya_platform"
    / "persistence"
    / "data"
    / "orders.db"
)
POLL_INTERVAL_SEC = 1.0


class GenericControlIntentConsumer:
    """
    Dashboard control intent consumer.

    FLOW:
    Dashboard UI
      → DashboardIntentService
      → control_intents table
      → ControlIntentConsumer
      → process_alert()
      → OMS execution pipeline
    """

    def __init__(self, *, bot, stop_event):
        logger.critical("🔥 ControlIntentConsumer initialized")
        self.bot = bot
        self.stop_event = stop_event

    # ==================================================
    # MAIN LOOP
    # ==================================================
    def run_forever(self):
        logger.info("🚦 ControlIntentConsumer started")

        while not self.stop_event.is_set():
            try:
                processed = self._process_next_intent()
                if not processed:
                    time.sleep(POLL_INTERVAL_SEC)

            # 🔥 FAIL-HARD: broker / session failure must kill process
            except RuntimeError:
                raise

            except Exception:
                logger.exception("❌ Control intent loop error")
                time.sleep(2)

    def _execute_generic_payload(self, payload: dict, intent_id: str) -> str:
        """
        Execute ONE GenericIntent payload via process_alert().
        Returns final status: ACCEPTED / REJECTED / FAILED
        """

        leg = {
            "tradingsymbol": payload["symbol"],
            "direction": payload["side"],
            "qty": int(payload["qty"]),
            "product_type": payload.get("product", "MIS"),
            "order_type": payload.get("order_type", "MARKET"),
        }

        if leg["order_type"] == "LIMIT":
            if payload.get("price") is None:
                raise RuntimeError("LIMIT order without price")
            leg["price"] = float(payload["price"])

        if payload.get("target") is not None:
            leg["target"] = float(payload["target"])

        if payload.get("stoploss") is not None:
            leg["stop_loss"] = float(payload["stoploss"])

        if payload.get("trail_sl") is not None:
            leg["trailing_type"] = "POINTS"
            leg["trailing_value"] = float(payload["trail_sl"])
            if payload.get("trail_when") is not None:
                leg["trailing_activation_price"] = float(payload["trail_when"])

        alert_payload = {
            "secret_key": self.bot.config.webhook_secret,
            "execution_type": payload.get("execution_type", "ENTRY"),
            "exchange": payload.get("exchange", "NFO"),
            "strategy_name": f"__DASHBOARD__:{intent_id}",
            "test_mode": payload.get("test_mode"),
            "legs": [leg],
        }

        result = self.bot.process_alert(alert_payload)
        status = result.get("status", "")

        if status in ("COMPLETED SUCCESSFULLY", "PARTIALLY COMPLETED"):
            return "ACCEPTED"
        elif status in ("blocked", "FAILED", "error"):
            return "REJECTED"
        return "FAILED"

    def _handle_broker_control_intent(self, intent_type: str, payload: dict, intent_id: str) -> str:
        """
        Handle broker-level control intents emitted by dashboard.
        Converts them into OMS-safe EXIT / MODIFY flows.
        """

        # ----------------------------
        # CANCEL BROKER ORDER
        # ----------------------------
        if intent_type == "CANCEL_BROKER_ORDER":
            broker_order_id = payload.get("broker_order_id")
            if not broker_order_id:
                raise RuntimeError("Missing broker_order_id")

            logger.critical(
                "🛑 DASHBOARD BROKER CANCEL | order_id=%s | intent=%s",
                broker_order_id,
                intent_id,
            )

            # 🔒 REGISTER EXIT VIA OMS (OrderWatcher will execute)
            self.bot.command_service.register_exit_intent(
                broker_order_id=broker_order_id,
                reason="DASHBOARD_CANCEL",
                source="DASHBOARD",
            )

            return "ACCEPTED"

        # ----------------------------
        # MODIFY BROKER ORDER
        # ----------------------------
        if intent_type == "MODIFY_BROKER_ORDER":
            logger.critical(
                "✏️ DASHBOARD BROKER MODIFY | intent=%s | payload=%s",
                intent_id,
                payload,
            )

            # 🔒 Register MODIFY intent only (watcher handles execution)
            self.bot.command_service.register_modify_intent(
                broker_order_id=payload["broker_order_id"],
                order_type=payload.get("order_type"),
                price=payload.get("price"),
                quantity=payload.get("quantity"),
                source="DASHBOARD",
                intent_id=intent_id,
            )

            return "ACCEPTED"

        return "REJECTED"

    # ==================================================
    # PROCESS SINGLE INTENT
    # ==================================================
    def _process_next_intent(self) -> bool:
        
        row = self._claim_next_intent()
        if not row:
            return False

        intent_id, intent_type, payload_json = row

        try:
            payload = json.loads(payload_json)

            if not isinstance(payload, dict):
                logger.error("❌ Invalid payload type | %s", intent_id)
                self._update_status(intent_id, "FAILED")
                return True

            # ==================================================
            # STRATEGY INTENTS — CONTROL PLANE ONLY
            # ==================================================
            if intent_type == "STRATEGY":
                logger.warning(
                    "⚠️ STRATEGY intent ignored by ControlIntentConsumer | %s",
                    intent_id,
                )
                self._update_status(intent_id, "IGNORED")
                return True

            # ==================================================
            # BASKET INTENT — ORDERED EXECUTION
            # ==================================================
            if intent_type == "BASKET":
                orders = payload.get("orders", [])

                # EXIT first, ENTRY later (risk-safe ordering)
                exits = [o for o in orders if o.get("execution_type") == "EXIT"]
                entries = [o for o in orders if o.get("execution_type") != "EXIT"]
                execution_plan = exits + entries

                logger.info(
                    "🧺 Executing BASKET | %s | %d orders",
                    intent_id,
                    len(execution_plan),
                )

                for step, order_payload in enumerate(execution_plan, start=1):
                    try:
                        result = self._execute_generic_payload(order_payload, intent_id)

                        if result != "ACCEPTED":
                            logger.error(
                                "❌ BASKET FAILED | %s | step %d",
                                intent_id,
                                step,
                            )
                            self._update_status(intent_id, "FAILED")
                            return True

                    except Exception:
                        logger.exception(
                            "❌ BASKET ERROR | %s | step %d",
                            intent_id,
                            step,
                        )
                        self._update_status(intent_id, "FAILED")
                        return True

                self._update_status(intent_id, "ACCEPTED")
                logger.info("✅ BASKET COMPLETED | %s", intent_id)
                return True

            # ==================================================
            # SYSTEM ORDER CONTROL (OMS-LEVEL)
            # ==================================================
            if intent_type == "CANCEL_SYSTEM_ORDER":
                command_id = payload.get("command_id")
                if not command_id:
                    raise RuntimeError("Missing command_id")

                logger.critical(
                    "🛑 SYSTEM ORDER CANCEL | command_id=%s | intent=%s",
                    command_id,
                    intent_id,
                )

                self._cancel_system_order(command_id)
                result = "ACCEPTED"

            elif intent_type == "MODIFY_SYSTEM_ORDER":
                logger.critical(
                    "✏️ SYSTEM ORDER MODIFY | intent=%s | payload=%s",
                    intent_id,
                    payload,
                )

                self._modify_system_order(payload)
                result = "ACCEPTED"

            elif intent_type == "CANCEL_ALL_SYSTEM_ORDERS":
                logger.critical(
                    "🛑 SYSTEM ORDER CANCEL ALL | intent=%s",
                    intent_id,
                )

                self._cancel_all_system_orders()
                result = "ACCEPTED"

            # ==================================================
            # BROKER CONTROL (WATCHER-ONLY)
            # ==================================================
            elif intent_type in ("CANCEL_BROKER_ORDER", "MODIFY_BROKER_ORDER"):
                result = self._handle_broker_control_intent(
                    intent_type, payload, intent_id
                )

            # ==================================================
            # GENERIC ORDER (TradingView-style)
            # ==================================================
            else:
                result = self._execute_generic_payload(payload, intent_id)



            if result == "ACCEPTED":
                final_status = "ACCEPTED"
            elif result == "REJECTED":
                final_status = "REJECTED"
            else:
                final_status = "FAILED"

            self._update_status(intent_id, final_status)

            logger.info(
                "✅ Control intent %s processed | %s",
                intent_id,
                final_status,
            )

        except Exception:
            logger.exception("❌ Control intent failed | %s", intent_id)
            self._update_status(intent_id, "FAILED")

        return True

    def _cancel_system_order(self, command_id: str):
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE orders
            SET status = 'FAILED',
                updated_at = CURRENT_TIMESTAMP
            WHERE command_id = ?
            AND client_id = ?
            AND status = 'CREATED'
            AND source = 'MANUAL'
            """,
            (command_id, self.bot.config.client_id),
        )

        if cur.rowcount == 0:
            logger.warning(
                "⚠️ SYSTEM CANCEL NO-OP | command_id=%s",
                command_id,
            )

        conn.commit()
        conn.close()

    def _modify_system_order(self, payload: dict):
        command_id = payload["command_id"]

        fields = []
        values = []

        if payload.get("price") is not None:
            fields.append("price = ?")
            values.append(payload["price"])

        if payload.get("quantity") is not None:
            fields.append("quantity = ?")
            values.append(payload["quantity"])

        if payload.get("order_type") is not None:
            fields.append("order_type = ?")
            values.append(payload["order_type"])

        if not fields:
            logger.warning("⚠️ SYSTEM MODIFY EMPTY | %s", command_id)
            return

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.extend([command_id, self.bot.config.client_id])

        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur = conn.cursor()

        cur.execute(
            f"""
            UPDATE orders
            SET {", ".join(fields)}
            WHERE command_id = ?
            AND client_id = ?
            AND status = 'CREATED'
            AND source = 'MANUAL'
            """,
            values,
        )

        if cur.rowcount == 0:
            logger.warning(
                "⚠️ SYSTEM MODIFY NO-OP | command_id=%s",
                command_id,
            )

        conn.commit()
        conn.close()

    def _cancel_all_system_orders(self):
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE orders
            SET status = 'FAILED',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'CREATED'
            AND source = 'MANUAL'
            AND client_id = ?
            """,
            (self.bot.config.client_id,),
        )

        logger.critical(
            "🛑 SYSTEM CANCEL ALL | affected=%d",
            cur.rowcount,
        )

        conn.commit()
        conn.close()

    # ==================================================
    # CLAIM NEXT INTENT (ATOMIC)
    # ==================================================
    def _claim_next_intent(self) -> Optional[Tuple[str, str, str]]:
        conn = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)
        cur = conn.cursor()

        try:
            cur.execute("BEGIN IMMEDIATE")

            cur.execute(
                """
                SELECT id, type, payload
                FROM control_intents
                WHERE status = 'PENDING'
                ORDER BY created_at
                LIMIT 1
                """
            )

            row = cur.fetchone()
            if not row:
                conn.commit()
                return None

            cur.execute(
                """
                UPDATE control_intents
                SET status = 'PROCESSING'
                WHERE id = ?
                """,
                (row[0],),
            )

            conn.commit()
            return row

        finally:
            conn.close()

    # ==================================================
    # UPDATE STATUS
    # ==================================================
    def _update_status(self, intent_id: str, status: str):
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE control_intents SET status = ? WHERE id = ?",
                (status, intent_id),
            )
            conn.commit()
        finally:
            conn.close()
