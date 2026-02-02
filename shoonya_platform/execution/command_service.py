# ======================================================================
# 🔒 PRODUCTION FROZEN — OMS CORE
# Component : CommandService
# Version   : 2026-01-29
# Status    : 🔒 PRODUCTION FROZEN
# Risk      : NONE (within declared OMS model)
# Compatible:
#   ✔ OrderRepository (client-scoped)
#   ✔ OrderWatcherEngine
#   ✔ SupremeRiskManager
#   ✔ Copy trading (N clients)

# ======================================================================

import logging
from datetime import datetime

from shoonya_platform.persistence.models import OrderRecord

from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.execution.validation import validate_order

from shoonya_platform.execution.trailing import (
    PointsTrailing,
    PercentTrailing,
    AbsoluteTrailing,
)

from shoonya_platform.execution.position_exit_service import PositionExitService


logger = logging.getLogger(__name__)


class CommandService:
    """
    SINGLE GATE for all trading actions.

    Guarantees:
    - No direct broker access
    - No UI bypass
    - No strategy bypass
    - Full audit & recovery support
    """

    def __init__(self, bot):
        self.bot = bot
        self.position_exit_service = PositionExitService(
            broker_client=bot.api,
            order_watcher=bot.order_watcher,
            execution_guard=bot.execution_guard,
            order_repo=bot.order_repo,
            client_id=bot.client_id,
        )

    def register(self, cmd: UniversalOrderCommand):
        """
        Register EXIT intent only (NO execution).
        """
        validate_order(cmd)

        record = OrderRecord(
            command_id=cmd.command_id,
            broker_order_id=None,
            execution_type="EXIT",

            source=cmd.source,
            user=cmd.user,
            strategy_name=cmd.strategy_name,

            exchange=cmd.exchange,
            symbol=cmd.symbol,
            side=cmd.side,
            quantity=cmd.quantity,
            product=cmd.product,

            order_type="MARKET",
            price=cmd.price,

            stop_loss=cmd.stop_loss,
            target=cmd.target,
            trailing_type=cmd.trailing_type,
            trailing_value=cmd.trailing_value,

            status="CREATED",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
            tag="EXIT",
        )

        self.bot.order_repo.create(record)

    def submit(self, cmd: UniversalOrderCommand, *, execution_type: str):
        """
        Validate, persist ONCE, and submit ENTRY / ADJUST commands.
        """

        # 🔒 HARD BLOCK EXIT
        if execution_type == "EXIT" or cmd.intent == "EXIT":
            raise RuntimeError(
                "EXIT submission forbidden. "
                "EXITs must go via OrderWatcherEngine."
            )

        # 1️⃣ HARD VALIDATION
        try:
            validate_order(cmd)
        except Exception:
            self.bot.order_repo.create(OrderRecord(
                command_id=cmd.command_id,
                broker_order_id=None,
                execution_type=execution_type,

                source=cmd.source,
                user=cmd.user,
                strategy_name=cmd.strategy_name,

                exchange=cmd.exchange,
                symbol=cmd.symbol,
                side=cmd.side,
                quantity=cmd.quantity,
                product=cmd.product,

                order_type=cmd.order_type,
                price=cmd.price,

                stop_loss=cmd.stop_loss,
                target=cmd.target,
                trailing_type=cmd.trailing_type,
                trailing_value=cmd.trailing_value,

                status="FAILED",
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                tag="VALIDATION_FAILED",
            ))
            raise

        # 2️⃣ TRAILING ENGINE
        trailing_engine = None
        if cmd.trailing_type == "POINTS":
            trailing_engine = PointsTrailing(cmd.trailing_value, cmd.trail_step)
        elif cmd.trailing_type == "PERCENT":
            trailing_engine = PercentTrailing(cmd.trailing_value)
        elif cmd.trailing_type == "ABSOLUTE":
            trailing_engine = AbsoluteTrailing(cmd.trailing_value)

        # 3️⃣ PERSIST (ONCE)
        record = OrderRecord(
            command_id=cmd.command_id,
            broker_order_id=None,
            execution_type=execution_type,
            tag=None,

            source=cmd.source,
            user=cmd.user,
            strategy_name=cmd.strategy_name,

            exchange=cmd.exchange,
            symbol=cmd.symbol,
            side=cmd.side,
            quantity=cmd.quantity,
            product=cmd.product,

            order_type=cmd.order_type,
            price=cmd.price,

            stop_loss=cmd.stop_loss,
            target=cmd.target,
            trailing_type=cmd.trailing_type,
            trailing_value=cmd.trailing_value,

            status="CREATED",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )

        self.bot.order_repo.create(record)

        # 4️⃣ EXECUTION
        return self.bot.execute_command(
            command=cmd,
            trailing_engine=trailing_engine,
        )

    def exit_registered(self, symbol: str) -> bool:
        """
        TEST HELPER: Check if an exit was registered for a symbol.
        """
        try:
            # Query for any exit command matching the symbol
            all_orders = self.bot.order_repo.get_all(limit=1000)
            for order in all_orders:
                if order.symbol == symbol and order.tag == "EXIT":
                    return True
            return False
        except Exception:
            return False

    def handle_exit_intent(
        self,
        *,
        scope,
        symbols,
        product_type,
        reason,
        source,
    ):
        """
        Route EXIT intent to PositionExitService for execution.
        
        This is the single gateway for all EXIT requests (strategy, RMS, manual, API).
        """
        self.position_exit_service.exit_positions(
            scope=scope,
            symbols=symbols,
            product_scope=product_type,
            reason=reason,
            source=source,
        )

    def register_exit_intent(self, *, broker_order_id, reason, source):
        """
        DEPRECATED: Use handle_exit_intent() instead.
        
        This method exists for backward compatibility with generic_control_consumer.
        Broker-level cancellations should be handled by broker API directly.
        """
        logger.warning(
            "register_exit_intent() is deprecated | broker_order_id=%s | reason=%s",
            broker_order_id,
            reason,
        )
        # For now, this is a no-op. Broker order cancellation is handled by dashboard API.
        pass

    def register_modify_intent(
        self, *, broker_order_id, order_type, price, quantity, source, intent_id
    ):
        """
        DEPRECATED: Broker-level modify operations should use broker API directly.
        
        This method exists for backward compatibility.
        """
        logger.warning(
            "register_modify_intent() is deprecated | broker_order_id=%s | intent_id=%s",
            broker_order_id,
            intent_id,
        )
        # For now, this is a no-op. Broker order modifications are handled by broker API.
        pass
