# ======================================================================
# ExecutionMixin — extracted from trading_bot.py
#
# Contains: process_alert (full alert handler), execute_command
#           (6-step broker execution), start_strategy / start_strategy_executor.
# ======================================================================
import json
import logging
import os
import re
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from shoonya_platform.execution.execution_guard import LegIntent
from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.domain.business_models import OrderResult
from shoonya_platform.utils.utils import log_exception
from shoonya_platform.logging.logger_config import get_component_logger

logger = get_component_logger('trading_bot')


class ExecutionMixin:
    """Methods for alert execution, command dispatch, and strategy startup."""

    def process_alert(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        PURE EXECUTION ALERT HANDLER (PRODUCTION — FROZEN)

        RULES:
        - No quotes, No LTP, No bid/ask
        - Alert defines order_type & price
        - ExecutionGuard controls risk
        - Broker position book controls duplicates
        - Per-strategy lock prevents duplicate webhook races
        """

        try:
            # RISK HEARTBEAT
            self.risk_manager.heartbeat()
            self._ensure_login()

            parsed = self.parse_alert_data(alert_data)
            execution_type = parsed.execution_type.upper()
            leg_payloads = [self._serialize_leg_for_notification(leg) for leg in parsed.legs]

            # PER-STRATEGY LOCK — prevents duplicate webhook races
            with self._alert_locks_guard:
                if parsed.strategy_name not in self._alert_locks:
                    self._alert_locks[parsed.strategy_name] = threading.Lock()
                strategy_lock = self._alert_locks[parsed.strategy_name]

            with strategy_lock:

                # Risk check — EXIT alerts always pass (they reduce risk)
                if execution_type != "EXIT" and not self.risk_manager.can_execute():
                    return {
                        "status": "blocked",
                        "reason": "Risk limits / cooldown",
                        "timestamp": datetime.now().isoformat(),
                    }

                # TELEGRAM — ALERT RECEIVED
                if self.telegram_enabled and self.telegram:
                    try:
                        self.telegram.send_alert_received(
                            strategy_name=parsed.strategy_name,
                            execution_type=execution_type,
                            legs_count=len(parsed.legs),
                            exchange=parsed.exchange,
                            legs=leg_payloads,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send alert received message: {e}")
                logger.info(
                    "ALERT_RECEIVED | strategy=%s | type=%s | exchange=%s | legs=%s",
                    parsed.strategy_name,
                    execution_type,
                    parsed.exchange,
                    leg_payloads,
                )

                # EXECUTION GUARD BROKER RECONCILIATION (MANDATORY)
                # LIVE: reconcile from broker positions
                # MOCK: reconcile from executor's tracked legs (no broker call)
                if not parsed.test_mode:
                    try:
                        self.broker_view.invalidate_cache("positions")
                        positions = self.broker_view.get_positions(force_refresh=True)
                    except Exception as pos_err:
                        logger.warning("Failed to fetch positions for guard reconciliation: %s", pos_err)
                        positions = []

                    broker_map = {}
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

                    self.execution_guard.reconcile_with_broker(
                        strategy_id=parsed.strategy_name,
                        broker_positions=broker_map,
                    )
                else:
                    # MOCK: build virtual position map from executor state
                    mock_broker_map = self._build_mock_position_map(parsed.strategy_name)
                    self.execution_guard.reconcile_with_broker(
                        strategy_id=parsed.strategy_name,
                        broker_positions=mock_broker_map,
                    )

                # DUPLICATE ENTRY DETECTION
                # LIVE: check broker positions + DB
                # MOCK: check DB + executor state
                duplicate_symbols = set()

                if execution_type == "ENTRY":
                    if not parsed.test_mode:
                        for leg in parsed.legs:
                            if self.has_live_entry_block(parsed.strategy_name, leg.tradingsymbol):
                                duplicate_symbols.add(leg.tradingsymbol)
                                logger.warning(
                                    f"ENTRY BLOCKED — LIVE ORDER OR POSITION EXISTS | "
                                    f"{leg.tradingsymbol} | {parsed.strategy_name}"
                                )
                    else:
                        for leg in parsed.legs:
                            if self._has_mock_entry_block(parsed.strategy_name, leg.tradingsymbol):
                                duplicate_symbols.add(leg.tradingsymbol)
                                logger.warning(
                                    f"MOCK ENTRY BLOCKED — VIRTUAL POSITION EXISTS | "
                                    f"{leg.tradingsymbol} | {parsed.strategy_name}"
                                )

                # EXECUTION GUARD PLAN
                intents = [
                    LegIntent(
                        strategy_id=parsed.strategy_name,
                        symbol=leg.tradingsymbol,
                        direction=leg.direction,
                        qty=leg.qty,
                        tag=execution_type,
                    )
                    for leg in parsed.legs
                ]

                try:
                    guarded = self.execution_guard.validate_and_prepare(
                        intents=intents,
                        execution_type=execution_type,
                    )
                except RuntimeError as e:
                    logger.warning(str(e))
                    return {
                        "status": "blocked",
                        "reason": str(e),
                        "timestamp": datetime.now().isoformat(),
                    }

                if execution_type == "ENTRY" and not guarded:
                    return {
                        "status": "blocked",
                        "reason": "ExecutionGuard blocked ENTRY",
                        "timestamp": datetime.now().isoformat(),
                    }

                guard_map = {}
                for g in guarded:
                    if execution_type == "EXIT":
                        key = (g.symbol, "EXIT")
                    else:
                        key = (g.symbol, g.direction)
                    guard_map[key] = g.qty

                atomic_result = self._atomic_route_intents(
                    strategy_name=parsed.strategy_name,
                    execution_type=execution_type,
                    legs=parsed.legs,
                    guard_map=guard_map,
                    source_mode="ALERT",
                )
                if atomic_result:
                    logger.info(f"ATOMIC_HANDLED | {atomic_result['status']}")
                    return atomic_result

                expected_legs = len(parsed.legs)
                attempted = 0
                success_count = 0

                # EXECUTE LEGS
                exit_positions_cache = None
                if execution_type == "EXIT":
                    if not parsed.test_mode:
                        try:
                            self.broker_view.invalidate_cache("positions")
                            exit_positions_cache = self.broker_view.get_positions(force_refresh=True) or []
                        except Exception:
                            exit_positions_cache = []
                    else:
                        # MOCK: build virtual positions from executor state
                        exit_positions_cache = self._build_mock_exit_positions(parsed.strategy_name)

                for leg in parsed.legs:
                    orig_direction = leg.direction

                    if execution_type == "EXIT" and exit_positions_cache is not None:
                        net_qty = 0
                        for p in exit_positions_cache:
                            if p.get("tsym") == leg.tradingsymbol:
                                net_qty = int(p.get("netqty", 0))
                                break

                        if net_qty == 0:
                            logger.warning(
                                f"EXIT SKIPPED — NO POSITION | {leg.tradingsymbol}"
                            )
                            continue

                        leg = replace(leg, direction="SELL" if net_qty > 0 else "BUY")

                    if execution_type == "EXIT":
                        key = (leg.tradingsymbol, "EXIT")
                    else:
                        key = (leg.tradingsymbol, orig_direction)

                    if key not in guard_map:
                        logger.warning(
                            f"EXECUTION_GUARD_BLOCK | {parsed.strategy_name} | {leg.tradingsymbol}"
                        )
                        continue

                    leg.qty = guard_map[key]
                    if leg.qty <= 0:
                        continue

                    # ENFORCE ORDER CONTRACT
                    try:
                        if not leg.order_type:
                            raise RuntimeError(
                                f"ORDER TYPE MISSING | {leg.tradingsymbol}"
                            )

                        if leg.order_type.upper() == "LIMIT" and not leg.price:
                            raise RuntimeError(
                                f"LIMIT PRICE MISSING | {leg.tradingsymbol}"
                            )

                        is_duplicate = (
                            execution_type == "ENTRY"
                            and leg.tradingsymbol in duplicate_symbols
                        )

                        attempted += 1

                        result = self.process_leg(
                            leg_data=leg,
                            exchange=parsed.exchange,
                            strategy_name=parsed.strategy_name,
                            execution_type=execution_type,
                            test_mode=parsed.test_mode,
                            is_duplicate=is_duplicate,
                        )

                        if result.order_result.success:
                            success_count += 1
                    except Exception as leg_err:
                        logger.error(
                            "LEG_PROCESSING_FAILED | strategy=%s | symbol=%s | error=%s",
                            parsed.strategy_name,
                            leg.tradingsymbol,
                            leg_err,
                        )
                        attempted += 1

                # ENTRY FAILURE — ROLLBACK
                if execution_type == "ENTRY" and success_count == 0:
                    self.execution_guard.force_close_strategy(parsed.strategy_name)

                    if self.telegram_enabled and self.telegram:
                        try:
                            self.telegram.send_error_message(
                                title="\U0001f6a8 ENTRY FAILED",
                                error=f"{parsed.strategy_name} | All legs rejected",
                                strategy_name=parsed.strategy_name,
                                execution_type=execution_type,
                                exchange=parsed.exchange,
                                legs=leg_payloads,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send error message: {e}")

                    return {
                        "status": "FAILED",
                        "expected_legs": expected_legs,
                        "successful_legs": 0,
                        "attempted_legs": attempted,
                        "timestamp": datetime.now().isoformat(),
                    }

                if (
                    execution_type == "EXIT"
                    and expected_legs > 0
                    and attempted == 0
                ):
                    status = "NO_POSITION"
                else:
                    status = (
                        "INTENTS_REGISTERED"
                        if success_count == expected_legs
                        else "PARTIALLY_REGISTERED"
                        if success_count > 0
                        else "FAILED"
                    )

                return {
                    "status": status,
                    "expected_legs": expected_legs,
                    "attempted_legs": attempted,
                    "successful_legs": success_count,
                    "timestamp": datetime.now().isoformat(),
                }
        except RuntimeError:
            # FAIL-HARD: broker/session blind
            raise
        except Exception as e:
            log_exception("process_alert", e)

            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_error_message(
                        "ALERT PROCESSING ERROR",
                        str(e),
                    )
                except Exception as tg_e:
                    logger.warning(f"Failed to send error message: {tg_e}")

            return {
                "status": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def start_strategy(
        self,
        *,
        strategy_name: str,
        universal_config,
        market_cls,
        market_config,
    ):
        """Route start calls into StrategyExecutorService."""
        logger.warning(
            "start_strategy called; routing to start_strategy_executor | strategy=%s",
            strategy_name,
        )
        resolved = (
            universal_config.to_dict()
            if hasattr(universal_config, "to_dict")
            else (universal_config if isinstance(universal_config, dict) else {})
        )
        self.start_strategy_executor(
            strategy_name=strategy_name,
            config=resolved,
        )

    def start_strategy_executor(
        self,
        *,
        strategy_name: str,
        config: dict,
    ):
        """
        Register strategy with StrategyExecutorService.

        Service is initialized once in __init__,
        this method just registers a new strategy.
        """
        with self._live_strategies_lock:
            if strategy_name in self._live_strategies:
                logger.warning(f"Strategy already running: {strategy_name}")
                return

        try:
            logger.info(f"REGISTERING STRATEGY: {strategy_name}")

            slug = strategy_name.strip().lower()
            slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_') or 'unnamed'

            config_dir = (
                Path(__file__).resolve().parents[1]
                / "strategy_runner"
                / "saved_configs"
            )
            config_dir.mkdir(parents=True, exist_ok=True)

            config_path = config_dir / f"{slug}.json"
            tmp_path = config_dir / f"{slug}.json.tmp"
            with open(tmp_path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(config, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, config_path)

            logger.info(f"Config saved: {config_path}")

            self.strategy_executor_service.register_strategy(
                name=strategy_name,
                config_path=str(config_path),
            )

            with self._live_strategies_lock:
                if strategy_name in self._live_strategies:
                    logger.warning("Strategy registered by concurrent thread: %s", strategy_name)
                    return
                self._live_strategies[strategy_name] = {
                    "type": "executor_service",
                    "config_path": str(config_path),
                    "started_at": time.time(),
                }

            logger.warning(f"STRATEGY REGISTERED: {strategy_name}")

            if self.telegram_enabled and self.telegram:
                try:
                    self.send_telegram(
                        f"<b>STRATEGY REGISTERED</b>\n"
                        f"Name: {strategy_name}\n"
                        f"Type: ExecutorService (condition-based)\n"
                        f"Time: {datetime.now().strftime('%H:%M:%S')}",
                        category="strategy"
                    )
                except Exception as e:
                    logger.warning(f"Telegram notification failed: {e}")

        except Exception as e:
            logger.error(f"STRATEGY REGISTRATION FAILED: {strategy_name} | {e}", exc_info=True)

            if self.telegram_enabled and self.telegram:
                try:
                    self.send_telegram(
                        f"<b>STRATEGY REGISTRATION FAILED</b>\n"
                        f"Name: {strategy_name}\n"
                        f"Error: {str(e)}",
                        category="strategy"
                    )
                except Exception:
                    pass

            raise

    def execute_command(self, command, **kwargs):
        """
        DESIRED FLOW: COMPLETE 6-STEP ORDER EXECUTION

        Step 1: REGISTER TO DB with status=CREATED       [DONE by CommandService.submit()]
        Step 2: SYSTEM BLOCKERS CHECK (Risk/Guard/Dup)   [THIS METHOD]
        Step 3: UPDATE TO status=SENT_TO_BROKER          [THIS METHOD]
        Step 4: EXECUTE ON BROKER                        [THIS METHOD]
        Step 5: UPDATE DB BASED ON BROKER RESULT         [THIS METHOD]
        Step 6: ORDERWATCH POLLS BROKER                  [DONE by OrderWatcher]

        Accepts extra keyword args (trailing_engine, etc.)
        for forward compatibility.
        """
        if command.source != "ORDER_WATCHER":
            logger.info(
                f"EXECUTE_COMMAND_SOURCE | cmd_id={command.command_id} | source={command.source} | "
                f"(non-ORDER_WATCHER caller — allowed)"
            )

        with self._cmd_lock:
            return self._execute_command_inner(command, **kwargs)

    def _execute_command_inner(self, command, **kwargs):
        """Inner execution logic, called under _cmd_lock."""
        try:
            self._ensure_login()

            strategy_id = getattr(command, 'strategy_name', 'UNKNOWN')

            # Resolve MOCK behavior from explicit test marker or strategy mode.
            comment = str(getattr(command, "comment", "") or "").upper()
            explicit_mock_success = "TEST_MODE_SUCCESS" in comment
            explicit_mock_failure = "TEST_MODE_FAILURE" in comment
            is_mock_execution = explicit_mock_success or explicit_mock_failure
            if not is_mock_execution:
                try:
                    svc = getattr(self, "strategy_executor_service", None)
                    mode_getter = getattr(svc, "get_strategy_mode", None) if svc else None
                    if callable(mode_getter) and strategy_id and strategy_id != "UNKNOWN":
                        is_mock_execution = str(mode_getter(strategy_id) or "LIVE").upper() == "MOCK"
                except Exception:
                    is_mock_execution = False

            _intent_is_exit = getattr(command, 'intent', None) == 'EXIT'
            _prefix_is_exit = hasattr(command, 'command_id') and str(command.command_id).startswith('EXIT_')
            if _prefix_is_exit and not _intent_is_exit:
                logger.warning(
                    "EXIT detected by command_id prefix, not by intent field | cmd_id=%s",
                    command.command_id,
                )
            is_exit_order = _intent_is_exit or _prefix_is_exit

            order_rec = None
            execution_type = "EXIT" if is_exit_order else "ENTRY"
            try:
                order_rec = self.order_repo.get_by_id(command.command_id)
                rec_type = str(getattr(order_rec, "execution_type", "") or "").upper()
                if rec_type:
                    execution_type = rec_type
                elif hasattr(command, "execution_type"):
                    execution_type = str(getattr(command, "execution_type", "") or execution_type).upper()
            except Exception:
                if hasattr(command, "execution_type"):
                    execution_type = str(getattr(command, "execution_type", "") or execution_type).upper()

            if execution_type not in {"ENTRY", "ADJUSTMENT", "ADJUST", "EXIT"}:
                execution_type = "EXIT" if is_exit_order else "ENTRY"

            # ==================================================
            # STEP 2: SYSTEM BLOCKERS CHECK
            # ==================================================
            logger.info(
                f"STEP_2: SYSTEM_BLOCKERS_CHECK | cmd_id={command.command_id} | {command.symbol}"
            )

            # Check 2A: RISK MANAGER
            if is_exit_order:
                logger.info(
                    f"RISK_BYPASS_EXIT | cmd_id={command.command_id} | {command.symbol} | "
                    f"EXIT orders always pass risk check"
                )
            elif not self.risk_manager.can_execute():
                reason = "RISK_LIMITS_EXCEEDED"
                logger.warning(
                    f"BLOCKER_RISK | cmd_id={command.command_id} | {command.symbol} | reason={reason}"
                )
                try:
                    self.order_repo.update_status(command.command_id, "FAILED")
                    self.order_repo.update_tag(command.command_id, reason)
                except Exception as db_err:
                    logger.error(f"Failed to update DB with risk blocker: {db_err}")

                return OrderResult(success=False, error_message=reason)

            # Check 2B: EXECUTION GUARD
            if self.execution_guard.has_strategy(strategy_id):
                source_upper = str(getattr(command, "source", "") or "").upper()
                strategy_pipeline = source_upper in {"ORDER_WATCHER", "STRATEGY"}
                if execution_type == "ENTRY" and not strategy_pipeline:
                    reason = "EXECUTION_GUARD_BLOCKED"
                    logger.warning(
                        f"BLOCKER_GUARD | cmd_id={command.command_id} | {command.symbol} | "
                        f"strategy={strategy_id} | reason={reason}"
                    )
                    try:
                        self.order_repo.update_status(command.command_id, "FAILED")
                        self.order_repo.update_tag(command.command_id, reason)
                    except Exception as db_err:
                        logger.error(f"Failed to update DB with guard blocker: {db_err}")

                    return OrderResult(success=False, error_message=reason)

            # Check 2C: DUPLICATE DETECTION
            if execution_type != "EXIT":
                open_orders = self.order_repo.get_open_orders_by_strategy(strategy_id)

                for order in open_orders:
                    if order.symbol == command.symbol and order.command_id != command.command_id:
                        reason = "DUPLICATE_ORDER_BLOCKED"
                        logger.warning(
                            f"BLOCKER_DUPLICATE | cmd_id={command.command_id} | {command.symbol} | "
                            f"existing={order.command_id} | reason={reason}"
                        )
                        try:
                            self.order_repo.update_status(command.command_id, "FAILED")
                            self.order_repo.update_tag(command.command_id, reason)
                        except Exception as db_err:
                            logger.error(f"Failed to update DB with duplicate blocker: {db_err}")

                        return OrderResult(success=False, error_message=reason)

            logger.info(
                f"BLOCKERS_PASSED \u2705 | cmd_id={command.command_id} | {command.symbol}"
            )

            # ==================================================
            # STEP 3: UPDATE TO status=SENT_TO_BROKER
            # ==================================================
            logger.info(
                f"STEP_3: SENDING_TO_BROKER | cmd_id={command.command_id} | {command.symbol}"
            )

            try:
                self.order_repo.update_status(command.command_id, "SENT_TO_BROKER")
            except Exception as db_err:
                logger.error(f"STEP_3 FAILED: Could not update DB to SENT_TO_BROKER: {db_err}")

            # ==================================================
            # STEP 4: EXECUTE ON BROKER
            # ==================================================
            logger.info(
                f"STEP_4: EXECUTE_ON_BROKER | cmd_id={command.command_id} | {command.symbol}"
            )

            order_params = command.to_broker_params()

            logger.info(
                f"BROKER_PARAMS | {order_params.get('exchange')} | "
                f"{order_params.get('tradingsymbol')} | "
                f"{order_params.get('buy_or_sell')} | "
                f"qty={order_params.get('quantity')} | "
                f"type={order_params.get('price_type')}"
            )

            # GLOBAL PAPER TRADING GUARD — blocks ALL real broker submissions
            _trading_mode = os.environ.get("TRADING_MODE", "LIVE").upper()
            _force_paper = _trading_mode == "PAPER"

            if is_mock_execution or _force_paper:
                if _force_paper and not is_mock_execution:
                    logger.info(
                        "STEP_4_PAPER_MODE | cmd_id=%s | strategy=%s | TRADING_MODE=PAPER — broker call blocked",
                        command.command_id,
                        strategy_id,
                    )
                else:
                    logger.info(
                        "STEP_4_MOCK_EXECUTION | cmd_id=%s | strategy=%s | mode=MOCK",
                        command.command_id,
                        strategy_id,
                    )
                if explicit_mock_failure:
                    result = OrderResult(success=False, error_message="MOCK_TEST_FAILURE")
                else:
                    _cmd_suffix = (command.command_id or "NOCMD")[:8]
                    mock_order_id = f"MOCK_{int(time.time() * 1000)}_{_cmd_suffix}"
                    _paper_status = "PAPER_EXECUTED" if _force_paper else "MOCK_EXECUTED"
                    result = OrderResult(success=True, order_id=mock_order_id, status=_paper_status)
            else:
                result = self.api.place_order(order_params)

            # ==================================================
            # STEP 5: UPDATE DB BASED ON BROKER RESULT
            # ==================================================
            logger.info(
                f"STEP_5: UPDATE_DB_BROKER_RESULT | cmd_id={command.command_id} | "
                f"success={result.success}"
            )

            if result.success:
                broker_id = getattr(result, 'order_id', None) or getattr(result, 'norenordno', None)
                if broker_id:
                    try:
                        self.order_repo.update_broker_id(command.command_id, broker_id)
                        logger.info(
                            f"DB_UPDATED_SUCCESS | cmd_id={command.command_id} | "
                            f"broker_id={broker_id} | status=SENT_TO_BROKER"
                        )

                        if is_mock_execution:
                            try:
                                fill_price = float(command.price) if command.price else 0.0
                            except (ValueError, TypeError):
                                fill_price = 0.0
                            if fill_price <= 0:
                                fill_price = self._get_ltp_from_tick_store(
                                    command.exchange, command.symbol
                                )
                            if fill_price <= 0:
                                logger.warning(
                                    "MOCK_FILL_PRICE_ZERO | cmd_id=%s | symbol=%s | "
                                    "no price from tick store, using 0.0",
                                    command.command_id, command.symbol,
                                )
                            self.order_repo.update_status(command.command_id, "EXECUTED")
                            try:
                                _qty = int(float(command.quantity or 0))
                            except (ValueError, TypeError):
                                _qty = 0
                            self.notify_fill(
                                strategy_name=strategy_id,
                                symbol=command.symbol,
                                side=command.side,
                                qty=_qty,
                                price=fill_price,
                                delta=None,
                                broker_order_id=broker_id,
                                command_id=command.command_id,
                            )
                            logger.info(
                                "MOCK_EXECUTED | cmd_id=%s | strategy=%s | symbol=%s | side=%s | qty=%s | price=%s",
                                command.command_id,
                                strategy_id,
                                command.symbol,
                                command.side,
                                command.quantity,
                                fill_price,
                            )
                        else:
                            try:
                                self.broker_view.invalidate_cache(target="positions")
                                self.broker_view.invalidate_cache(target="orders")
                                logger.debug(
                                    f"CACHE_INVALIDATED | cmd_id={command.command_id} | "
                                    f"targets=['positions', 'orders']"
                                )
                            except Exception as cache_err:
                                logger.debug(f"Cache invalidation warning (non-critical): {cache_err}")

                    except Exception as db_err:
                        logger.error(f"STEP_5 WARNING: Failed to persist broker_id: {db_err}")
                else:
                    logger.warning(
                        f"STEP_5 WARNING: Broker accepted but no order_id in result | "
                        f"cmd_id={command.command_id}"
                    )
            else:
                logger.error(
                    f"STEP_5_BROKER_REJECTED | cmd_id={command.command_id} | {command.symbol} | "
                    f"error={result.error_message}"
                )

                try:
                    self.order_repo.update_status(command.command_id, "FAILED")
                    if hasattr(self.order_repo, 'update_tag'):
                        fail_tag = "MOCK_TEST_FAILURE" if is_mock_execution else "BROKER_REJECTED"
                        self.order_repo.update_tag(command.command_id, fail_tag)
                    logger.info(f"DB_UPDATED_FAILED | cmd_id={command.command_id} | status=FAILED")
                except Exception as db_err:
                    logger.error(f"STEP_5 ERROR: Failed to update DB on broker rejection: {db_err}")

                if execution_type == "EXIT":
                    if self.telegram_enabled:
                        try:
                            self.send_telegram(
                                f"\U0001f6a8 EXIT ORDER REJECTED\n"
                                f"Symbol: {command.symbol}\n"
                                f"Reason: {result.error_message}\n"
                                f"\u26a0\ufe0f Position still open - manual action may be needed",
                                category="strategy"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send telegram notification: {e}")

            return result

        except RuntimeError:
            raise
        except Exception as e:
            log_exception("execute_command", e)

            logger.error(f"STEP_5_EXCEPTION | cmd_id={command.command_id} | {type(e).__name__}: {e}")
            try:
                self.order_repo.update_status(command.command_id, "FAILED")
            except Exception as db_error:
                logger.warning(f"Failed to update command status in database: {db_error}")

            return OrderResult(
                success=False,
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # MOCK PIPELINE HELPERS — virtual position tracking for test parity
    # ------------------------------------------------------------------

    def _build_mock_position_map(self, strategy_name: str) -> Dict[str, Dict[str, int]]:
        """Build a broker-compatible position map from executor state legs."""
        broker_map: Dict[str, Dict[str, int]] = {}
        try:
            svc = getattr(self, "strategy_executor_service", None)
            if svc is None:
                return broker_map
            executor = svc._executors.get(strategy_name)
            if executor is None:
                return broker_map
            for leg in executor.state.legs.values():
                if not leg.is_active:
                    continue
                sym = leg.trading_symbol or leg.symbol
                if not sym:
                    continue
                qty = int(leg.qty * max(1, getattr(leg, "lot_size", 1)))
                broker_map.setdefault(sym, {"BUY": 0, "SELL": 0})
                if leg.side.value == "SELL":
                    broker_map[sym]["SELL"] += qty
                else:
                    broker_map[sym]["BUY"] += qty
        except Exception as e:
            logger.warning("_build_mock_position_map failed: %s", e)
        return broker_map

    def _has_mock_entry_block(self, strategy_name: str, symbol: str) -> bool:
        """Check for duplicate entry using DB + executor state (no broker call)."""
        # DB check (same as live)
        open_orders = self.order_repo.get_open_orders_by_strategy(strategy_name)
        for o in open_orders:
            if o.symbol == symbol:
                return True
        # Executor state check (virtual position)
        try:
            svc = getattr(self, "strategy_executor_service", None)
            if svc:
                executor = svc._executors.get(strategy_name)
                if executor:
                    for leg in executor.state.legs.values():
                        if not leg.is_active:
                            continue
                        tsym = leg.trading_symbol or leg.symbol
                        if tsym == symbol:
                            return True
        except Exception as e:
            logger.warning("_has_mock_entry_block executor check failed: %s", e)
        return False

    def _build_mock_exit_positions(self, strategy_name: str) -> List[Dict[str, Any]]:
        """Build virtual broker positions list from executor state for EXIT verification."""
        positions: List[Dict[str, Any]] = []
        try:
            svc = getattr(self, "strategy_executor_service", None)
            if svc is None:
                return positions
            executor = svc._executors.get(strategy_name)
            if executor is None:
                return positions
            for leg in executor.state.legs.values():
                if not leg.is_active:
                    continue
                sym = leg.trading_symbol or leg.symbol
                qty = int(leg.qty * max(1, getattr(leg, "lot_size", 1)))
                # Convention: SELL position = negative netqty
                net = -qty if leg.side.value == "SELL" else qty
                positions.append({"tsym": sym, "netqty": net})
        except Exception as e:
            logger.warning("_build_mock_exit_positions failed: %s", e)
        return positions

    def _get_ltp_from_tick_store(self, exchange: str, symbol: str) -> float:
        """
        Get LTP from tick store (no broker REST API call).
        Falls back to option chain DB if tick store has no data.
        """
        try:
            from scripts.scriptmaster import get_tokens
            tokens = get_tokens(exchange=exchange, tradingsymbol=symbol)
            if tokens:
                from shoonya_platform.market_data.feeds.live_feed import get_tick_data
                tick = get_tick_data(tokens[0])
                if tick:
                    ltp = float(tick.get("ltp") or tick.get("lp") or 0.0)
                    if ltp > 0:
                        return ltp
        except Exception as e:
            logger.debug("Tick store LTP lookup failed for %s: %s", symbol, e)
        return 0.0
