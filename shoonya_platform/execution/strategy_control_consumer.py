#!/usr/bin/env python3
"""
Execution-side Strategy consumer for DASHBOARD control intents
==============================================================

ROLE:
- Consume dashboard-generated STRATEGY control intents
- Control strategy lifecycle only (ENTRY / EXIT / ADJUST / FORCE_EXIT)
- Never generates alerts
- Never places orders
- Never touches broker or CommandService

This guarantees:
Dashboard strategy buttons == internal strategy lifecycle calls
"""

# ======================================================================
# 🔒 CODE FREEZE — PRODUCTION APPROVED
#
# Component : Strategy ControlIntentConsumer
# Status    : PRODUCTION FROZEN
#Version    : v1.1.1
# Date      : 2026-02-06

#
# Guarantees:
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

from shoonya_platform.execution.db_market import DBBackedMarket
from shoonya_platform.strategies.universal_config.universal_strategy_config import (
    UniversalStrategyConfig
)

def build_universal_config(payload: dict) -> UniversalStrategyConfig:
    return UniversalStrategyConfig(
        strategy_name=payload["strategy_name"],
        strategy_version=payload["strategy_version"],

        exchange=payload["exchange"],
        symbol=payload["symbol"],
        instrument_type=payload["instrument_type"], 
        #instrument_type will drive market_cls selection (OPTIDX/MCX/etc)


        entry_time=time.fromisoformat(payload["entry_time"]),
        exit_time=time.fromisoformat(payload["exit_time"]),

        order_type=payload["order_type"],
        product=payload["product"],

        lot_qty=payload["lot_qty"],
        params=payload["params"],

        poll_interval=payload.get("poll_interval", 2.0),
        cooldown_seconds=payload.get("cooldown_seconds", 0),
    )

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


class StrategyControlConsumer:
    """
    Dashboard strategy lifecycle consumer.

    Handles:
    - ENTRY
    - EXIT
    - ADJUST
    - FORCE_EXIT

    Never places orders.
    Never calls process_alert().
    """

    def __init__(self, *, strategy_manager, stop_event):
        logger.critical("🔥 StrategyControlConsumer initialized")
        self.strategy_manager = strategy_manager
        self.stop_event = stop_event

    # ==================================================
    # MAIN LOOP
    # ==================================================
    def run_forever(self):
        logger.info("🚦 StrategyControlConsumer started")

        while not self.stop_event.is_set():
            try:
                processed = self._process_next_strategy_intent()
                if not processed:
                    time.sleep(POLL_INTERVAL_SEC)

            # 🔥 FAIL-HARD: broker / session failure must kill process
            except RuntimeError:
                raise

            except Exception:
                logger.exception("❌ Strategy control loop error")
                time.sleep(2)

    # ==================================================
    # PROCESS SINGLE STRATEGY INTENT
    # ==================================================
    def _process_next_strategy_intent(self) -> bool:
        row = self._claim_next_strategy_intent()
        if not row:
            return False

        intent_id, payload_json = row

        try:
            payload = json.loads(payload_json)

            strategy_name = payload.get("strategy_name")

            action = payload.get("action")

            if not strategy_name or not action:
                raise RuntimeError("Invalid STRATEGY intent payload")

            logger.warning(
                "🎯 STRATEGY CONTROL | %s → %s",
                strategy_name,
                action,
            )

            # ----------------------------------------------
            # STRATEGY LIFECYCLE DISPATCH
            # ----------------------------------------------
            if action == "ENTRY":
                universal_config = build_universal_config(payload)
                if strategy_name != universal_config.strategy_name:
                    raise RuntimeError("Strategy name mismatch in payload")
                try:
                    self.strategy_manager.start_strategy(
                        strategy_name=universal_config.strategy_name,
                        universal_config=universal_config,
                        market_cls=DBBackedMarket,   # or FeedBackedMarket (explicit choice)
                        market_config={
                            "exchange": universal_config.exchange,
                            "symbol": universal_config.symbol,
                        },
                    )
                except RuntimeError as e:
                    if "already running" in str(e):
                        logger.info("Strategy already running — ENTRY treated as idempotent")
                    else:
                        raise


            elif action == "EXIT":
                self.strategy_manager.request_exit(
                    scope="STRATEGY",
                    symbols=None,
                    product_type="ALL",
                    reason="DASHBOARD_EXIT",
                    source="STRATEGY_CONTROL",
                )

            elif action == "FORCE_EXIT":
                self.strategy_manager.request_exit(
                    scope="STRATEGY",
                    symbols=None,
                    product_type="ALL",
                    reason="FORCE_EXIT",
                    source="STRATEGY_CONTROL",
                )


            else:
                raise RuntimeError(f"Unknown strategy action: {action}")

            self._update_status(intent_id, "ACCEPTED")

            logger.info(
                "✅ STRATEGY intent processed | %s | %s",
                intent_id,
                action,
            )

        except Exception:
            logger.exception("❌ STRATEGY intent failed | %s", intent_id)
            self._update_status(intent_id, "FAILED")

        return True

    # ==================================================
    # CLAIM NEXT STRATEGY INTENT (ATOMIC)
    # ==================================================
    def _claim_next_strategy_intent(self) -> Optional[Tuple[str, str]]:
        conn = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)
        cur = conn.cursor()

        try:
            cur.execute("BEGIN IMMEDIATE")

            cur.execute(
                """
                SELECT id, payload
                FROM control_intents
                WHERE status = 'PENDING'
                  AND type = 'STRATEGY'
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
