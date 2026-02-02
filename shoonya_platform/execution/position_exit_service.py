# shoonya_platform/execution/position_exit_service.py

from typing import Literal, List, Optional
from datetime import datetime
import logging
import uuid

from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.execution.execution_guard import ExecutionGuard
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.persistence.models import OrderRecord

logger = logging.getLogger(__name__)


class PositionExitService:
    """
    Position-driven exit service.

    HARD GUARANTEES:
    - Broker position book is the only source of truth
    - No qty / side / product inference from internal state
    - Every exit (strategy / RMS / manual / API / recovery) goes through here
    - Orders registered via OrderRepository (OrderWatcher will execute)
    """

    def __init__(
        self,
        *,
        broker_client: ShoonyaClient,
        order_watcher,  # OrderWatcherEngine (type hint avoided for circular imports)
        execution_guard: ExecutionGuard,
        order_repo: Optional[OrderRepository] = None,
        client_id: Optional[str] = None,
    ):
        self.client = broker_client
        self.order_watcher = order_watcher
        self.execution_guard = execution_guard
        self.order_repo = order_repo
        self.client_id = client_id

    def exit_positions(
        self,
        *,
        scope: Literal["ALL", "SYMBOLS"],
        symbols: Optional[List[str]],
        product_scope: Literal["MIS", "NRML", "ALL"],
        reason: str,
        source: str,
    ) -> None:
        """
        Exit positions using broker position book as source of truth.
        
        Registers EXIT orders via OrderRepository.
        OrderWatcher will execute them with LMT-as-MKT rules and ScriptMaster compliance.
        """

        logger.warning(
            "EXIT REQUEST RECEIVED | scope=%s symbols=%s product_scope=%s reason=%s source=%s",
            scope,
            symbols,
            product_scope,
            reason,
            source,
        )

        positions = self.client.get_positions() or []

        if not positions:
            logger.warning("No broker positions found — nothing to exit")
            return

        exit_legs = []

        for row in positions:
            # ---- Basic sanity ----
            net_qty = int(row.get("netqty", 0))
            if net_qty == 0:
                continue

            tradingsymbol = row.get("tsym")
            exchange = row.get("exch")
            product = row.get("prd")  # MIS / NRML / CNC

            # ---- CNC holdings protection ----
            # Never touch CNC holdings
            if product == "CNC":
                logger.warning("SKIP CNC HOLDING | %s", tradingsymbol)
                continue

            # ---- Product scope enforcement ----
            if product_scope != "ALL" and product != product_scope:
                logger.warning(
                    "SKIP PRODUCT MISMATCH | %s | requested=%s actual=%s",
                    tradingsymbol,
                    product_scope,
                    product,
                )
                continue

            # ---- Symbol scope enforcement ----
            if scope == "SYMBOLS":
                if not symbols or tradingsymbol not in symbols:
                    logger.warning(
                        "SKIP SYMBOL OUT OF SCOPE | %s",
                        tradingsymbol,
                    )
                    continue

            # ---- Resolve exit side & quantity (broker truth) ----
            quantity = abs(net_qty)
            side = "SELL" if net_qty > 0 else "BUY"

            logger.warning(
                "EXIT LEG COLLECTED | %s | %s | qty=%s | product=%s",
                tradingsymbol,
                side,
                quantity,
                product,
            )

            exit_legs.append(
                {
                    "exchange": exchange,
                    "symbol": tradingsymbol,
                    "product": product,
                    "quantity": quantity,
                    "side": side,
                    "reason": reason,
                    "source": source,
                }
            )

        if not exit_legs:
            logger.warning("No eligible positions after filtering — nothing to exit")
            return

        logger.critical("REGISTERING %d EXIT ORDERS (POSITION-DRIVEN)", len(exit_legs))

        # Register all exit orders via OrderRepository
        # OrderWatcher will execute them
        for leg in exit_legs:
            self._register_exit_order(leg)

    def _register_exit_order(self, leg: dict) -> None:
        """
        Register a single exit order in the repository.
        OrderWatcher monitors and executes these orders.
        """
        try:
            # Create unique command ID for this exit
            command_id = f"EXIT_{leg['source']}_{leg['symbol']}_{int(datetime.utcnow().timestamp()*1000)}"

            # Create OrderRecord for exit
            record = OrderRecord(
                command_id=command_id,
                broker_order_id=None,
                execution_type="EXIT",

                source=leg["source"],
                user="SYSTEM",
                strategy_name="__SYSTEM__",  # Canonical system strategy

                exchange=leg["exchange"],
                symbol=leg["symbol"],
                side=leg["side"],
                quantity=leg["quantity"],
                product=leg["product"],

                order_type="MARKET",
                price=0.0,  # MARKET orders don't use price

                stop_loss=None,
                target=None,
                trailing_type=None,
                trailing_value=None,

                status="CREATED",
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                tag="EXIT",
            )

            # Persist to repository
            if self.order_repo:
                self.order_repo.create(record)
                logger.warning(
                    "EXIT ORDER REGISTERED | %s | %s %s qty=%s | reason=%s",
                    leg["exchange"],
                    leg["symbol"],
                    leg["side"],
                    leg["quantity"],
                    leg["reason"],
                )
            else:
                logger.error("ORDER REPOSITORY NOT AVAILABLE — exit order NOT registered")

        except Exception as e:
            logger.exception(f"FAILED TO REGISTER EXIT ORDER | {leg['symbol']} | {e}")