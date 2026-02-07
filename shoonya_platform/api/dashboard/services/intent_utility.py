#!/usr/bin/env python3
"""
DASHBOARD CONTROL INTENT SERVICE (PRODUCTION)
=============================================

Responsibilities:
- Validate dashboard control requests
- Persist canonical control intents into DB
- NEVER talk to execution layer
- NEVER import execution modules
- SINGLE source of truth for dashboard → OMS boundary
"""
# ======================================================================
# 🔒 CODE FREEZE — PRODUCTION APPROVED
#
# Component : DashboardIntentService
# Version   : v1.1.0
# Status    : PRODUCTION FROZEN
# Date      : 2026-01-30
#
# Guarantees:
# - Pure intent persistence
# - Client-scoped (multi-client / copy trading)
# - No execution coupling
# - TradingView-parity intent format
#
# DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import json
import logging
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Optional

from shoonya_platform.api.dashboard.api.schemas import (
    GenericIntentRequest,
    StrategyIntentRequest,
    IntentResponse,
    BasketIntentRequest,
)

logger = logging.getLogger("DASHBOARD.INTENT")

# 🔒 SINGLE SOURCE OF TRUTH
DB_PATH = "/home/ec2-user/shoonya_platform/shoonya_platform/persistence/data/orders.db"


class DashboardIntentService:
    """
    Dashboard → Control Queue writer.

    Architectural guarantees:
    - No broker calls
    - No execution imports
    - Pure persistence + validation
    """
    def __init__(
        self,
        *,
        client_id: str,
        parent_client_id: Optional[str] = None,
    ):
        """
        Args:
            client_id: Actual trading client
            parent_client_id: Master client (for copy trading)
        """
        self.client_id = client_id
        self.parent_client_id = parent_client_id
    # ==================================================
    # GENERIC ORDER INTENT (BUY / SELL)
    # ==================================================
    def submit_generic_intent(
        self, req: GenericIntentRequest
    ) -> IntentResponse:

        intent_id = f"DASH-GEN-{uuid4().hex[:10]}"

        # --------------------------------------------------
        # 🔒 CANONICAL PAYLOAD (DO NOT DOWNGRADE)
        # --------------------------------------------------
        payload = {
            # ---- Instrument ----
            "exchange": req.exchange,
            "symbol": req.symbol,

            # ---- Execution ----
            "execution_type": req.execution_type,
            "test_mode": req.test_mode,

            # ---- Order ----
            "side": req.side.value,
            "qty": int(req.qty),
            "product": req.product,
            "order_type": req.order_type,
            "price": float(req.price) if req.price is not None else None,

            # ---- Triggered execution ----
            "triggered_order": req.triggered_order,
            "trigger_value": (
                float(req.trigger_value)
                if req.trigger_value is not None
                else None
            ),

            # ---- Risk Management ----
            "target": float(req.target) if req.target is not None else None,
            "stoploss": float(req.stoploss) if req.stoploss is not None else None,
            "trail_sl": float(req.trail_sl) if req.trail_sl is not None else None,
            "trail_when": float(req.trail_when) if req.trail_when is not None else None,

            # ---- Meta ----
            "tag": req.reason or "WEB_MANUAL",
        }


        self._insert_intent(
            intent_id=intent_id,
            intent_type="GENERIC",
            payload=payload,
        )

        logger.info(
            "📥 DASHBOARD INTENT QUEUED | %s %s %s x%d @ %s",
            payload["exchange"],
            payload["side"],
            payload["symbol"],
            payload["qty"],
            payload["price"] if payload["order_type"] != "MARKET" else "MKT",
        )

        return IntentResponse(
            accepted=True,
            message="Generic intent queued",
            intent_id=intent_id,
        )

    # ==================================================
    # STRATEGY CONTROL INTENT
    # ==================================================
    def submit_strategy_intent(
        self, req: StrategyIntentRequest
    ) -> IntentResponse:

        intent_id = f"DASH-STR-{uuid4().hex[:10]}"

        payload = {
            "strategy_name": req.strategy_name,
            "action": req.action.value,   # ENTRY / EXIT / ADJUST / FORCE_EXIT
            "tag": req.reason or "DASHBOARD",
        }

        self._insert_intent(
            intent_id=intent_id,
            intent_type="STRATEGY",
            payload=payload,
        )

        logger.warning(
            "📥 DASHBOARD STRATEGY INTENT | %s → %s",
            req.strategy_name,
            req.action.value,
        )

        return IntentResponse(
            accepted=True,
            message="Strategy intent queued",
            intent_id=intent_id,
        )

    # ==================================================
    # INTERNAL: DB INSERT (ATOMIC & SAFE)
    # ==================================================
    def _insert_intent(
        self,
        *,
        intent_id: str,
        intent_type: str,
        payload: dict,
    ) -> None:
        """
        Persist intent into control queue.

        Guarantees:
        - Atomic
        - Concurrent safe
        - Restart safe
        - Client-scoped
        """

        try:
            conn = sqlite3.connect(
                DB_PATH,
                timeout=5,
                isolation_level=None,
            )
            cur = conn.cursor()

            # --------------------------------------------------
            # 🔒 ENSURE TABLE EXISTS (IDEMPOTENT)
            # --------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS control_intents (
                    id TEXT PRIMARY KEY,

                    client_id TEXT NOT NULL,
                    parent_client_id TEXT,

                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            # --------------------------------------------------
            # 🧾 INSERT CONTROL INTENT (CLIENT-SCOPED)
            # --------------------------------------------------
            cur.execute(
                """
                INSERT INTO control_intents
                (
                    id,
                    client_id,
                    parent_client_id,
                    type,
                    payload,
                    source,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent_id,
                    self.client_id,
                    self.parent_client_id,
                    intent_type,
                    json.dumps(payload, separators=(",", ":")),
                    "DASHBOARD",
                    "PENDING",
                    datetime.utcnow().isoformat(),
                ),
            )

            conn.commit()
            conn.close()

        except Exception:
            logger.exception("❌ DASHBOARD INTENT INSERT FAILED")
            raise RuntimeError("Unable to queue dashboard intent")

    def submit_raw_intent(
        self,
        *,
        intent_id: str,
        intent_type: str,
        payload: dict,
    ):
        """
        PUBLIC, STABLE INTENT INSERT API

        Dashboard-safe wrapper over internal insert logic.
        Consumer behavior MUST remain unchanged.
        """
        return self._insert_intent(
            intent_id=intent_id,
            intent_type=intent_type,
            payload=payload,
        )
    # ==================================================
    # BASKET CONTROL INTENT
    # ==================================================
    def submit_basket_intent(
        self, req: BasketIntentRequest
    ) -> IntentResponse:

        intent_id = f"DASH-BASKET-{uuid4().hex[:10]}"

        payload = {
            "orders": [order.dict() for order in req.orders],
            "tag": req.reason or "WEB_BASKET",
        }

        self._insert_intent(
            intent_id=intent_id,
            intent_type="BASKET",
            payload=payload,
        )

        logger.info(
            "📥 DASHBOARD BASKET INTENT | %d orders queued",
            len(req.orders),
        )

        return IntentResponse(
            accepted=True,
            message="Basket intent queued",
            intent_id=intent_id,
        )
