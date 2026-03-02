# ======================================================================
# AlertProcessingMixin — extracted from trading_bot.py
#
# Contains: strategy intent routing, webhook parsing, leg processing,
#           atomic batching, fill notification, duplicate detection.
# ======================================================================
import threading
import time
import logging
from dataclasses import replace
from datetime import datetime
from typing import Dict, Any, List, Optional

from scripts.scriptmaster import requires_limit_order

from shoonya_platform.execution.execution_guard import LegIntent
from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.domain.business_models import AlertData, LegResult, OrderResult
from shoonya_platform.utils.utils import (
    validate_webhook_signature as _validate_sig,
    log_exception,
)
from shoonya_platform.logging.logger_config import get_component_logger

logger = get_component_logger('trading_bot')


class AlertProcessingMixin:
    """Methods for webhook/alert processing, intent routing, and leg execution."""

    # ==================================================
    # STRATEGY LIFECYCLE WRAPPERS (called by consumers)
    # ==================================================
    def _process_strategy_intents(
        self,
        strategy_name: str,
        strategy,
        market,
        intents,
        *,
        force_exit: bool = False,
    ):
        """
        Route strategy UniversalOrderCommand objects with guard compliance and atomic batching.
        """
        if not intents:
            return

        try:
            guard_intents = []
            for intent in intents:
                symbol = getattr(intent, "symbol", None)
                side = getattr(intent, "side", None)
                qty = getattr(intent, "quantity", 0)

                if not symbol or not side:
                    continue

                guard_intents.append(
                    LegIntent(
                        strategy_id=strategy_name,
                        symbol=symbol,
                        direction=side,
                        qty=qty,
                        tag="ENTRY" if not force_exit else "EXIT",
                    )
                )

            try:
                guarded = self.execution_guard.validate_and_prepare(
                    intents=guard_intents,
                    execution_type="EXIT" if force_exit else "ENTRY",
                )
            except RuntimeError as e:
                logger.warning(f"Guard blocked strategy intents: {e}")
                return

            guard_map = {}
            for g in guarded:
                if force_exit:
                    key = (g.symbol, "EXIT")
                else:
                    key = (g.symbol, g.direction)
                guard_map[key] = g.qty

            atomic_result = self._atomic_route_intents(
                strategy_name=strategy_name,
                execution_type="EXIT" if force_exit else "ENTRY",
                legs=intents,
                guard_map=guard_map,
                source_mode="STRATEGY",
            )
            if atomic_result:
                logger.info(
                    f"ATOMIC_STRATEGY | {strategy_name} | {atomic_result['status']}"
                )
                return

            for intent in intents:
                symbol = None
                try:
                    symbol = getattr(intent, "symbol", None)
                    side = getattr(intent, "side", None)

                    if not symbol or not side:
                        continue

                    if force_exit:
                        key = (symbol, "EXIT")
                    else:
                        key = (symbol, side)

                    if key not in guard_map:
                        logger.warning(f"GUARD_BLOCK | {strategy_name} | {symbol}")
                        continue

                    approved_qty = guard_map[key]
                    if approved_qty <= 0:
                        continue

                    intent.quantity = approved_qty
                    is_exit_like = force_exit or (side == "BUY")

                    if is_exit_like:
                        self.command_service.register(intent)
                        logger.info(f"EXIT intent: {strategy_name} -> {side} {symbol}")
                    else:
                        self.command_service.submit(intent, execution_type="ENTRY")
                        logger.info(f"ENTRY intent: {strategy_name} -> {side} {symbol}")

                except Exception:
                    logger.exception(
                        f"Strategy intent routing failed | {strategy_name} | {symbol}"
                    )

        except Exception:
            logger.exception("Error in _process_strategy_intents")

    def request_entry(self, strategy_name: str):
        with self._live_strategies_lock:
            try:
                value = self._live_strategies[strategy_name]
            except KeyError:
                logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
                raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")
        logger.info("Request ENTRY handled by StrategyExecutorService | %s", strategy_name)
        return

    def request_adjust(self, strategy_name: str):
        with self._live_strategies_lock:
            try:
                value = self._live_strategies[strategy_name]
            except KeyError:
                logger.error("Request ADJUST failed: strategy not registered: %s", strategy_name)
                raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")
        logger.info("Request ADJUST handled by StrategyExecutorService | %s", strategy_name)
        return

    def request_exit(
        self,
        *,
        scope,
        strategy_name=None,
        symbols=None,
        product_type="ALL",
        reason,
        source,
    ):
        """
        Route EXIT intent to CommandService for position-driven execution.

        Now supports strategy-scoped exits: only exits positions created by that strategy.

        Never constructs orders directly.
        PositionExitService handles all exit logic (broker-driven).
        """
        self.command_service.handle_exit_intent(
            scope=scope,
            strategy_name=strategy_name,
            symbols=symbols,
            product_type=product_type,
            reason=reason,
            source=source,
        )

    # --------------------------------------------------
    # Helper extractors
    # --------------------------------------------------
    def _extract_symbol(self, leg) -> Optional[str]:
        """Extract symbol from leg object safely."""
        return getattr(leg, "tradingsymbol", None) or getattr(leg, "symbol", None)

    def _extract_direction(self, leg) -> Optional[str]:
        """Extract direction from leg object safely."""
        direction = getattr(leg, "direction", None) or getattr(leg, "side", None)
        return direction.upper() if direction else None

    def _extract_quantity(self, leg) -> int:
        """Extract quantity from leg object safely."""
        raw = getattr(leg, "qty", None)
        if raw is None:
            raw = getattr(leg, "quantity", None)
        try:
            return int(raw) if raw is not None else 0
        except (ValueError, TypeError):
            return 0

    def _serialize_leg_for_notification(self, leg: Any) -> Dict[str, Any]:
        """Normalize leg object/dict for Telegram and structured logging."""
        if isinstance(leg, dict):
            payload = dict(leg)
        else:
            payload = {
                "tradingsymbol": getattr(leg, "tradingsymbol", None) or getattr(leg, "symbol", None),
                "direction": getattr(leg, "direction", None) or getattr(leg, "side", None),
                "qty": getattr(leg, "qty", None) or getattr(leg, "quantity", None),
                "order_type": getattr(leg, "order_type", None),
                "price": getattr(leg, "price", None),
            }
        if payload.get("direction"):
            payload["direction"] = str(payload["direction"]).upper()
        return payload

    def _classify_leg_as_exit_or_entry(
        self,
        leg,
        broker_positions: List[Dict[str, Any]],
    ) -> str:
        """Classify leg as EXIT or ENTRY using direction-aware logic."""
        symbol = self._extract_symbol(leg)
        direction = self._extract_direction(leg)

        if not symbol or not direction:
            logger.warning("Cannot classify leg: missing symbol or direction")
            return "ENTRY"

        net_qty = 0
        for p in broker_positions:
            if p.get("tsym") == symbol:
                net_qty = int(p.get("netqty", 0))
                break

        if net_qty == 0:
            return "ENTRY"
        if net_qty > 0:
            return "EXIT" if direction == "SELL" else "ENTRY"
        return "EXIT" if direction == "BUY" else "ENTRY"

    def _wait_until_flat(
        self,
        symbols: List[str],
        strategy_name: str,
        timeout: float = 30.0,
    ) -> bool:
        """Wait until broker positions for given symbols become flat."""
        deadline = time.time() + timeout
        check_interval = 0.5

        logger.info(
            f"ATOMIC_WAIT_START | strategy={strategy_name} | "
            f"symbols={symbols} | timeout={timeout}s"
        )

        while time.time() < deadline:
            try:
                self.broker_view.invalidate_cache("positions")
                positions = self.broker_view.get_positions(force_refresh=True) or []

                positions_flat = True
                for p in positions:
                    if p.get("tsym") in symbols and int(p.get("netqty", 0)) != 0:
                        positions_flat = False
                        break

                orders_pending = False
                try:
                    open_orders = self.order_repo.get_open_orders_by_strategy(strategy_name)
                    for order in open_orders:
                        if order.symbol in symbols and order.status in ("CREATED", "SENT_TO_BROKER", "OPEN"):
                            orders_pending = True
                            break
                except Exception as e:
                    logger.warning(f"ATOMIC_WAIT | Order check failed: {e}")

                if positions_flat and not orders_pending:
                    logger.info(f"ATOMIC_WAIT_SUCCESS | strategy={strategy_name}")
                    return True

            except Exception as e:
                logger.warning(f"ATOMIC_WAIT | Check exception: {e}")

            time.sleep(check_interval)

        logger.error(f"ATOMIC_WAIT_TIMEOUT | strategy={strategy_name}")
        try:
            positions = self.broker_view.get_positions(force_refresh=True) or []
            for p in positions:
                if p.get("tsym") in symbols:
                    logger.error(f"ATOMIC_FINAL_POS | {p.get('tsym')} | netqty={p.get('netqty')}")
        except Exception as e:
            logger.error(f"ATOMIC_FINAL_POS | Failed to log: {e}")

        return False

    def _atomic_route_intents(
        self,
        *,
        strategy_name: str,
        execution_type: str,
        legs: List,
        guard_map: Dict,
        source_mode: str = "ALERT",
    ) -> Optional[Dict[str, Any]]:
        """Atomic coordinator for mixed EXIT+ENTRY batches."""
        with self._atomic_locks_guard:
            if strategy_name not in self._atomic_locks:
                self._atomic_locks[strategy_name] = threading.Lock()
            atomic_lock = self._atomic_locks[strategy_name]

        if not atomic_lock.acquire(timeout=35.0):
            logger.error(
                f"ATOMIC_ABORT | strategy={strategy_name} | "
                f"reason=atomic_lock_timeout"
            )
            return {
                "status": "FAILED",
                "reason": "ATOMIC_LOCK_TIMEOUT",
                "timestamp": datetime.now().isoformat(),
            }

        try:
            try:
                self.broker_view.invalidate_cache("positions")
                broker_positions = self.broker_view.get_positions(force_refresh=True) or []
            except Exception as e:
                logger.warning(f"ATOMIC_BATCH | Failed to get positions: {e}")
                broker_positions = []

            exit_legs = []
            entry_legs = []
            for leg in legs:
                if self._classify_leg_as_exit_or_entry(leg, broker_positions) == "EXIT":
                    exit_legs.append(leg)
                else:
                    entry_legs.append(leg)

            if not exit_legs or not entry_legs:
                return None

            exit_symbols = [s for s in (self._extract_symbol(l) for l in exit_legs) if s]

            exit_success_count = 0
            for leg in exit_legs:
                try:
                    symbol = self._extract_symbol(leg)
                    direction = self._extract_direction(leg)
                    key = (symbol, "EXIT")
                    if key not in guard_map:
                        continue
                    approved_qty = guard_map[key]
                    if approved_qty <= 0:
                        continue

                    if hasattr(leg, "to_dict"):
                        cmd = leg
                        cmd.quantity = approved_qty
                    else:
                        cmd = UniversalOrderCommand.from_order_params(
                            order_params={
                                "exchange": getattr(leg, "exchange", "NFO"),
                                "symbol": symbol,
                                "side": direction,
                                "quantity": approved_qty,
                                "product": getattr(leg, "product_type", "NRML"),
                                "order_type": getattr(leg, "order_type", "MARKET"),
                                "price": getattr(leg, "price", None),
                                "strategy_name": strategy_name,
                            },
                            source=source_mode,
                            user=self.client_id,
                        )
                        cmd.intent = "EXIT"

                    self.command_service.register(cmd)
                    exit_success_count += 1
                except Exception as e:
                    logger.error(
                        f"ATOMIC_PHASE_1_ERROR | strategy={strategy_name} | "
                        f"symbol={self._extract_symbol(leg)} | error={e}"
                    )

            if exit_success_count == 0:
                return {
                    "status": "FAILED",
                    "reason": "NO_EXITS_ROUTED",
                    "timestamp": datetime.now().isoformat(),
                }

            if not self._wait_until_flat(
                symbols=exit_symbols,
                strategy_name=strategy_name,
                timeout=30.0,
            ):
                return {
                    "status": "FAILED",
                    "reason": "EXIT_NOT_FLAT_TIMEOUT",
                    "symbols": exit_symbols,
                    "timestamp": datetime.now().isoformat(),
                }

            entry_success_count = 0
            for leg in entry_legs:
                try:
                    symbol = self._extract_symbol(leg)
                    direction = self._extract_direction(leg)
                    key = (symbol, direction)
                    if key not in guard_map:
                        continue
                    approved_qty = guard_map[key]
                    if approved_qty <= 0:
                        continue

                    if hasattr(leg, "to_dict"):
                        cmd = leg
                        cmd.quantity = approved_qty
                    else:
                        cmd = UniversalOrderCommand.from_order_params(
                            order_params={
                                "exchange": getattr(leg, "exchange", "NFO"),
                                "symbol": symbol,
                                "side": direction,
                                "quantity": approved_qty,
                                "product": getattr(leg, "product_type", "NRML"),
                                "order_type": getattr(leg, "order_type", "MARKET"),
                                "price": getattr(leg, "price", None),
                                "strategy_name": strategy_name,
                            },
                            source=source_mode,
                            user=self.client_id,
                        )

                    self.command_service.submit(cmd, execution_type="ENTRY")
                    entry_success_count += 1
                except Exception as e:
                    logger.error(
                        f"ATOMIC_PHASE_3_ERROR | strategy={strategy_name} | "
                        f"symbol={self._extract_symbol(leg)} | error={e}"
                    )

            return {
                "status": "ATOMIC_BATCH_EXECUTED",
                "exit_legs": exit_success_count,
                "entry_legs": entry_success_count,
                "symbols_exited": exit_symbols,
                "timestamp": datetime.now().isoformat(),
            }
        finally:
            atomic_lock.release()

    def notify_fill(self, strategy_name: str, symbol: str, side: str, qty: int,
                price: float, delta: Optional[float], broker_order_id: str,
                command_id: Optional[str] = None):
        """Called by OrderWatcher when an order fills."""
        if hasattr(self, "strategy_executor_service"):
            self.strategy_executor_service.notify_fill(
                strategy_name=strategy_name,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                delta=delta,
                broker_order_id=broker_order_id,
                command_id=command_id
            )

    def validate_webhook_signature(self, payload: str, signature: str) -> bool:
        """Validate webhook signature for security"""
        if not self.config.webhook_secret:
            logger.error("webhook_secret not configured - rejecting webhook")
            return False
        return _validate_sig(payload, signature, self.config.webhook_secret)

    def parse_alert_data(self, alert_data: Dict[str, Any]) -> AlertData:
        """Parse and validate incoming alert data"""
        normalized_data = {k.lower(): v for k, v in alert_data.items()}

        required_fields = ['secret_key', 'execution_type', 'legs']
        missing_fields = []
        for field in required_fields:
            if field not in normalized_data:
                missing_fields.append(field)

        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")

        if normalized_data['secret_key'] != self.config.webhook_secret:
            raise ValueError("Invalid secret key")

        return AlertData.from_dict(normalized_data)

    def has_live_entry_block(self, strategy_name: str, symbol: str) -> bool:
        """
        Blocks ENTRY if:
        - open intent exists (memory)
        - open order exists (DB)
        - open broker position exists
        """
        open_orders = self.order_repo.get_open_orders_by_strategy(strategy_name)
        for o in open_orders:
            if o.symbol == symbol:
                return True

        try:
            positions = self.broker_view.get_positions()
        except Exception as pos_err:
            logger.warning("has_live_entry_block: positions fetch failed, blocking entry: %s", pos_err)
            return True

        for p in positions:
            if p.get("tsym") == symbol and int(p.get("netqty", 0)) != 0:
                return True

        return False

    def process_leg(
        self,
        leg_data,
        exchange: str,
        strategy_name: str,
        execution_type: str,
        test_mode: Optional[str] = None,
        is_duplicate: bool = False,
    ) -> LegResult:
        """
        PURE INTENT REGISTRATION ENGINE (PRODUCTION — FROZEN)

        RULE:
        - NO broker execution
        - NO DB writes
        - Registers intent ONLY
        - OrderWatcherEngine executes
        """

        try:
            # BASIC VALIDATION
            if leg_data.qty <= 0:
                raise ValueError("Quantity must be > 0")

            exchange = exchange.upper()
            if not leg_data.direction:
                raise ValueError(f"Direction is required for {getattr(leg_data, 'tradingsymbol', 'UNKNOWN')}")
            direction = leg_data.direction.upper()

            # BUILD CANONICAL INTENT
            cmd = UniversalOrderCommand.from_order_params(
                order_params={
                    "exchange": exchange,
                    "symbol": leg_data.tradingsymbol,
                    "side": direction,
                    "quantity": int(leg_data.qty),
                    "product": leg_data.product_type,
                    "order_type": leg_data.order_type,
                    "price": leg_data.price,
                    "strategy_name": strategy_name,
                },
                source="STRATEGY",
                user=self.client_id,
            )

            # CANONICAL INSTRUMENT RULE (ScriptMaster)
            must_limit = requires_limit_order(
                exchange=exchange,
                tradingsymbol=leg_data.tradingsymbol,
            )

            if must_limit:
                if cmd.order_type != "LIMIT":
                    raise RuntimeError(
                        f"LIMIT ORDER REQUIRED | {leg_data.tradingsymbol}"
                    )
                if cmd.price is None:
                    raise RuntimeError(
                        f"LIMIT PRICE REQUIRED | {leg_data.tradingsymbol}"
                    )

            # DUPLICATE ENTRY — HARD BLOCK
            if execution_type == "ENTRY" and is_duplicate:
                logger.warning(
                    f"DUPLICATE ENTRY BLOCKED | {leg_data.tradingsymbol} | {strategy_name}"
                )
                return LegResult(
                    leg_data=leg_data,
                    order_result=OrderResult(
                        success=False,
                        error_message="DUPLICATE_ENTRY_BLOCKED",
                    ),
                )

            # TELEGRAM — INTENT REGISTERED
            if self.telegram_enabled and self.telegram:
                try:
                    if cmd.order_type == "LIMIT" and cmd.price is not None:
                        price = cmd.price
                    else:
                        price = 0.0
                    self.telegram.send_order_placing(
                        strategy_name=strategy_name,
                        execution_type=execution_type,
                        symbol=leg_data.tradingsymbol,
                        direction=direction,
                        quantity=leg_data.qty,
                        price=price,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send order placing message: {e}")

            # Execute through single command-service path.
            if execution_type == "EXIT":
                self.command_service.register(cmd)
            else:
                if test_mode:
                    marker = f"TEST_MODE_{str(test_mode).upper()}"
                    prior = str(cmd.comment or "")
                    cmd = replace(cmd, comment=f"{prior}|{marker}" if prior else marker)
                self.command_service.submit(cmd, execution_type=execution_type)

            if test_mode:
                logger.warning(f"\U0001f9ea TEST MODE | {leg_data.tradingsymbol}")

            logger.info(
                "INTENT_REGISTERED | %s | %s | %s | qty=%s | type=%s",
                exchange,
                leg_data.tradingsymbol,
                direction,
                leg_data.qty,
                cmd.order_type,
            )

            return LegResult(
                leg_data=leg_data,
                order_result=OrderResult(success=True, order_id=None),
            )

        except Exception as e:
            log_exception("process_leg", e)

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_error_message(
                        title="ORDER INTENT ERROR",
                        error=f"{leg_data.tradingsymbol}: {str(e)}",
                    )
                except Exception as tg_e:
                    logger.warning(f"Failed to send error message: {tg_e}")

            return LegResult(
                leg_data=leg_data,
                order_result=OrderResult(success=False, error_message=str(e)),
            )
