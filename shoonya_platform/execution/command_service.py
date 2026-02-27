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

from shoonya_platform.logging.logger_config import get_component_logger
from shoonya_platform.persistence.order_record import OrderRecord

from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.execution.validation import validate_order

from shoonya_platform.execution.trailing import (
    PointsTrailing,
    PercentTrailing,
    AbsoluteTrailing,
)

from shoonya_platform.execution.position_exit_service import PositionExitService


logger = get_component_logger('command_service')


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
            order_repo=bot.order_repo,
            client_id=bot.client_id,
        )

    def register(self, cmd: UniversalOrderCommand):
        """
        Register EXIT intent only (NO execution).
        """
        # 🔒 FIX: Make EXIT intent explicit & authoritative
        cmd = cmd.with_intent("EXIT")
            
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

            order_type=cmd.order_type or "MARKET",
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
        
        Called by both strategy alerts (source=STRATEGY) and OrderWatcher (source=ORDER_WATCHER).
        """
        # 🔒 HARD BLOCK EXIT — EXITs must go via PositionExitService → OrderWatcher
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

    def handle_exit_intent(
        self,
        *,
        scope,
        strategy_name=None,  # 🔥 NEW: filter exits by strategy
        symbols,
        product_type,
        reason,
        source,
    ):
        """
        Route EXIT intent to PositionExitService for execution.
        
        This is the single gateway for all EXIT requests (strategy, RMS, manual, API).
        Now supports strategy-scoped exits for safer multi-strategy deployments.
        """
        self.position_exit_service.exit_positions(
            scope=scope,
            strategy_name=strategy_name,
            symbols=symbols,
            product_scope=product_type,
            reason=reason,
            source=source,
        )
