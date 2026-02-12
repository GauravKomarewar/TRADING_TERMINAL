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
from uuid import uuid4

from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.persistence.order_record import OrderRecord

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
        
        If strategy_name is provided, only exits positions created by that strategy.
        This prevents cross-strategy position exits in multi-strategy deployments.

        NO execution happens here.
        """
        logger.critical(
            "EXIT REQUEST | scope=%s strategy=%s symbols=%s product=%s reason=%s source=%s",
            scope,
            strategy_name,
            symbols,
            product_scope,
            reason,
            source,
        )

        # 🔥 NEW: If strategy-scoped, find symbols created by that strategy
        if strategy_name:
            symbols = self._get_strategy_symbols(strategy_name)
            if not symbols:
                logger.info("EXIT: no positions for strategy: %s", strategy_name)
                return
            scope = "SYMBOLS"  # Override to filter by our symbols

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
            "EXIT INTENTS REGISTERING | count=%d | strategy=%s",
            len(exit_legs),
            strategy_name,
        )

        for leg in exit_legs:
            self._register_exit_intent(
                leg=leg,
                reason=reason,
                source=source,
                strategy_name=strategy_name,
            )

    # --------------------------------------------------
    # 🔥 NEW: Get symbols created by strategy
    # --------------------------------------------------

    def _get_strategy_symbols(self, strategy_name: str) -> List[str]:
        """
        Query OrderRepository to find all symbols created by this strategy.
        
        Returns list of unique symbols that this strategy has open orders for.
        """
        try:
            # Get all orders for this strategy
            all_orders = self.repo.get_orders() or []
            
            # Filter to orders created by this strategy that are still active
            strategy_orders = [
                o for o in all_orders
                if o.strategy_name == strategy_name and o.status in ("CREATED", "SENT_TO_BROKER", "EXECUTED")
            ]
            
            # Extract unique symbols
            symbols = list(set(o.symbol for o in strategy_orders))
            logger.info(
                "STRATEGY_SYMBOLS | strategy=%s | symbols=%s",
                strategy_name,
                symbols,
            )
            
            return symbols
            
        except Exception:
            logger.exception("Failed to get strategy symbols: %s", strategy_name)
            return []

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
            if self._recent_exit_exists(leg["symbol"], strategy_name=strategy_name):
                logger.warning(
                    "EXIT DUPLICATE SKIPPED | %s",
                    leg["symbol"],
                )
                return

            command_id = (
                f"EXIT_{source}_{leg['symbol']}_"
                f"{int(datetime.utcnow().timestamp() * 1000)}_"
                f"{uuid4().hex[:8]}"
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

    def _recent_exit_exists(self, symbol: str, strategy_name: Optional[str] = None) -> bool:
        """
        Prevent duplicate EXIT intents for the same symbol + strategy.

        Uses ONLY OrderRepository public API (PRODUCTION FROZEN).
        Scoped by strategy_name to avoid cross-strategy dedup collision
        (e.g., Strategy A's EXIT should not block Strategy B's EXIT for same symbol).
        """
        open_orders = self.repo.get_open_orders()

        for order in open_orders:
            if (
                order.execution_type == "EXIT"
                and order.symbol == symbol
                and (strategy_name is None or order.strategy_name == strategy_name)
            ):
                return True

        return False