#!/usr/bin/env python3
"""
PositionExitService
===================

PRODUCTION-GRADE POSITION-DRIVEN EXIT SERVICE

Invariants:
- Broker position book is the ONLY source of truth
- NO qty / side inference from internal state
- NO ExecutionGuard mutation
- NO broker execution
- EXIT = intent registration ONLY
- OrderWatcherEngine is the sole executor & cleanup authority
"""

import logging
from typing import Literal, List, Optional
from datetime import datetime, timedelta

from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.persistence.models import OrderRecord

logger = logging.getLogger(__name__)


class PositionExitService:
    """
    Position-driven EXIT intent service.

    Responsibilities:
    - Read broker position book
    - Determine EXIT side + qty (broker truth)
    - Register EXIT intents in OrderRepository
    - Prevent duplicate EXIT spam
    """

    def __init__(
        self,
        *,
        broker_client: ShoonyaClient,
        order_repo: OrderRepository,
        client_id: str,
    ):
        self.client = broker_client
        self.repo = order_repo
        self.client_id = client_id

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def exit_positions(
        self,
        *,
        scope: Literal["ALL", "SYMBOLS"],
        symbols: Optional[List[str]],
        product_scope: Literal["MIS", "NRML", "ALL"],
        reason: str,
        source: str,
        strategy_name: Optional[str] = None,
    ) -> None:
        """
        Register EXIT intents using broker position book as truth.

        NO execution happens here.
        """
        logger.critical(
            "EXIT REQUEST | scope=%s symbols=%s product=%s reason=%s source=%s",
            scope,
            symbols,
            product_scope,
            reason,
            source,
        )

        positions = self.client.get_positions()
        if not positions:
            logger.warning("EXIT: no broker positions (confirmed flat)")
            return

        exit_legs = []

        for row in positions:
            net_qty = int(row.get("netqty", 0))
            if net_qty == 0:
                continue

            tradingsymbol = row.get("tsym")
            exchange = row.get("exch")
            product = row.get("prd")  # MIS / NRML / CNC

            # -------------------------------
            # CNC protection
            # -------------------------------
            if product == "CNC":
                logger.warning("EXIT SKIPPED (CNC) | %s", tradingsymbol)
                continue

            # -------------------------------
            # Product scope filter
            # -------------------------------
            if product_scope != "ALL" and product != product_scope:
                continue

            # -------------------------------
            # Symbol scope filter
            # -------------------------------
            if scope == "SYMBOLS":
                if not symbols or tradingsymbol not in symbols:
                    continue

            side = "SELL" if net_qty > 0 else "BUY"
            qty = abs(net_qty)

            exit_legs.append(
                {
                    "exchange": exchange,
                    "symbol": tradingsymbol,
                    "product": product,
                    "side": side,
                    "quantity": qty,
                }
            )

        if not exit_legs:
            logger.warning("EXIT: no eligible positions after filtering")
            return

        logger.critical(
            "EXIT INTENTS REGISTERING | count=%d",
            len(exit_legs),
        )

        for leg in exit_legs:
            self._register_exit_intent(
                leg=leg,
                reason=reason,
                source=source,
                strategy_name=strategy_name,
            )

    # --------------------------------------------------
    # Internal helpers
    # --------------------------------------------------

    def _register_exit_intent(
        self,
        *,
        leg: dict,
        reason: str,
        source: str,
        strategy_name: Optional[str],
    ) -> None:
        """
        Register a single EXIT intent (idempotent).
        """
        try:
            if self._recent_exit_exists(leg["symbol"]):
                logger.warning(
                    "EXIT DUPLICATE SKIPPED | %s",
                    leg["symbol"],
                )
                return

            command_id = (
                f"EXIT_{source}_{leg['symbol']}_"
                f"{int(datetime.utcnow().timestamp() * 1000)}"
            )

            record = OrderRecord(
                command_id=command_id,
                broker_order_id=None,
                execution_type="EXIT",

                source=source,
                user="SYSTEM",
                strategy_name=strategy_name or "__SYSTEM__",

                exchange=leg["exchange"],
                symbol=leg["symbol"],
                side=leg["side"],
                quantity=leg["quantity"],
                product=leg["product"],

                order_type="MARKET",   # ScriptMaster may override
                price=0.0,

                stop_loss=None,
                target=None,
                trailing_type=None,
                trailing_value=None,

                status="CREATED",
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                tag="EXIT",
            )

            self.repo.create(record)

            logger.warning(
                "EXIT INTENT REGISTERED | %s | %s qty=%s | reason=%s",
                leg["symbol"],
                leg["side"],
                leg["quantity"],
                reason,
            )

        except Exception:
            logger.exception(
                "FAILED TO REGISTER EXIT INTENT | %s",
                leg.get("symbol"),
            )

    def _recent_exit_exists(self, symbol: str) -> bool:
        """
        Prevent duplicate EXIT intents for the same symbol.

        Uses ONLY OrderRepository public API (PRODUCTION FROZEN).
        """
        open_orders = self.repo.get_open_orders()

        for order in open_orders:
            if (
                order.execution_type == "EXIT"
                and order.symbol == symbol
            ):
                return True

        return False