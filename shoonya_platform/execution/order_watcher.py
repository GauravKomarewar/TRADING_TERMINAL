#!/usr/bin/env python3
"""
OrderWatcherEngine
==================

PRODUCTION-GRADE EXECUTION ENGINE
Aligned with ScriptMaster v2.0 (PRODUCTION FROZEN)

🎯 DESIRED FLOW - OrderWatcher implements STEP 6: BROKER POLLING + EXIT DISPATCH
=====================================
Step 1: REGISTER TO DB with status=CREATED           [Done by CommandService]
Step 2: SYSTEM BLOCKERS CHECK (Risk/Guard/Dup)       [Done by execute_command]
Step 3: UPDATE TO status=SENT_TO_BROKER              [Done by execute_command]
Step 4: EXECUTE ON BROKER                            [Done by execute_command]
Step 5: UPDATE DB BASED ON BROKER RESULT             [Done by execute_command]
Step 6: ORDERWATCH POLLS BROKER ("EXECUTED TRUTH")  [⭐ THIS MODULE]
   - Check order status on broker
   - If COMPLETE → status=EXECUTED
   - If REJECTED/CANCELLED/EXPIRED → status=FAILED
   - Clear execution guard on failure
Step 7: DISPATCH CREATED EXIT ORDERS TO BROKER       [⭐ THIS MODULE]
   - Poll DB for CREATED EXIT orders
   - Simple market EXITs → dispatch via execute_command()
   - Managed EXITs (with SL/trailing) → monitor and trail
Step 8: MONITOR MANAGED EXITS                        [⭐ THIS MODULE]
   - Track SL/target/trailing for managed exit orders
   - Trail SL upward as price moves in favour
   - Trigger MARKET exit when SL or target hit

Invariants:
- Broker is the ONLY source of EXECUTED truth
- EXIT execution is idempotent and persistent
- Order type rules enforced ONLY via ScriptMaster
- OrderWatcher executes intents, never decides them
- ExecutionGuard is reconciled ONLY from broker truth
"""

import time
import logging
import threading
from datetime import datetime
from typing import Dict, Optional, List

from shoonya_platform.logging.logger_config import get_component_logger
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.persistence.order_record import OrderRecord
from shoonya_platform.execution.intent import UniversalOrderCommand

logger = get_component_logger('order_watcher')


class OrderWatcherEngine(threading.Thread):
    """
    OrderWatcherEngine

    Responsibilities:
    ✅ Step 1-5: Done by CommandService/execute_command
    ✅ Step 6: Poll broker, update DB to EXECUTED/FAILED, reconcile guard
    """

    def __init__(self, bot, poll_interval: float = 1.0):
        super().__init__(daemon=True)
        self.bot = bot
        self.poll_interval = poll_interval
        self._running = True
        self.repo = OrderRepository(bot.client_id)
        self._last_failure_log = {}
        self._failure_log_ttl_sec = 60.0

        # Managed EXIT state: command_id → { current_sl, entry_price, highest_price }
        self._managed_exits: Dict[str, dict] = {}
        self._managed_exits_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._dispatched_exits: set = set()  # Prevent re-dispatch within same session

    def _should_log_failure(self, broker_id: str, status: str) -> bool:
        now = time.time()
        key = (broker_id, status)
        last = self._last_failure_log.get(key)
        if last and now - last < self._failure_log_ttl_sec:
            return False
        self._last_failure_log[key] = now
        if len(self._last_failure_log) > 1000:
            cutoff = now - self._failure_log_ttl_sec
            self._last_failure_log = {
                k: ts for k, ts in self._last_failure_log.items() if ts >= cutoff
            }
        return True

    # --------------------------------------------------
    # Thread lifecycle
    # --------------------------------------------------

    def stop(self):
        self._running = False

    def run(self):
        logger.info(
            "🧠 OrderWatcherEngine STEP 6+7+8: BROKER POLLING + EXIT DISPATCH + MANAGED EXITS"
        )

        while self._running:
            try:
                self.bot._ensure_login()
                self._reconcile_broker_orders()    # STEP 6: Poll broker & update to EXECUTED/FAILED
                self._dispatch_pending_exits()     # STEP 7: Dispatch CREATED EXIT orders
                self._monitor_managed_exits()      # STEP 8: Trail SL, check target/SL levels
            except RuntimeError:
                raise
            except Exception:
                logger.exception("OrderWatcher loop error")
            time.sleep(self.poll_interval)

    # ==================================================
    # STEP 6: RECONCILE WITH BROKER (DEFINITIVE TRUTH)
    # ==================================================

    def _reconcile_broker_orders(self):
        """
        STEP 6: Poll broker for EXECUTED truth.
        
        Updates DB status from SENT_TO_BROKER → EXECUTED/FAILED based on broker reality.
        This is the ONLY source of definitive execution status.
        """
        try:
            broker_orders = self.bot.api.get_order_book() or []
        except Exception as _ob_err:
            self._ob_fail_count = getattr(self, '_ob_fail_count', 0) + 1
            if self._ob_fail_count <= 3 or self._ob_fail_count % 20 == 0:
                logger.error(
                    "OrderWatcher: get_order_book() failed (count=%d) — broker polling skipped: %s",
                    self._ob_fail_count, _ob_err,
                )
            return

        self._ob_fail_count = 0  # Reset on success
        for bo in broker_orders:
            broker_id = bo.get("norenordno")
            status = (bo.get("status") or "").upper()

            if not broker_id or not status:
                continue

            record = self.repo.get_by_broker_id(broker_id)
            if not record:
                continue
            
            # 🔒 Skip already reconciled orders (idempotency)
            if record.status in ("EXECUTED", "FAILED"):
                continue
            
            # ==================================================
            # 📍 BROKER FAILURE (STEP 6A)
            # ==================================================
            if status in ("REJECTED", "CANCELLED", "EXPIRED"):
                logger.warning(
                    f"STEP_6A_BROKER_FAILED | cmd_id={record.command_id} | "
                    f"broker_id={broker_id} | status={status}"
                )
                
                self.repo.update_status(record.command_id, "FAILED")
                if hasattr(self.repo, 'update_tag'):
                    self.repo.update_tag(record.command_id, f"BROKER_{status}")

                # 🔒 FIX: Clear guard state for failed leg
                try:
                    self.bot.execution_guard.force_clear_symbol(
                        strategy_id=record.strategy_name,
                        symbol=record.symbol,
                    )
                    logger.info(
                        f"GUARD_CLEARED | strategy={record.strategy_name} | symbol={record.symbol}"
                    )
                except Exception:
                    logger.exception(
                        "OrderWatcher: failed to clear guard state | strategy=%s symbol=%s",
                        record.strategy_name,
                        record.symbol,
                    )

                if self._should_log_failure(broker_id, status):
                    logger.error(
                        "OrderWatcher: STEP_6A_BROKER_FAILURE | "
                        "cmd_id=%s broker_id=%s status=%s",
                        record.command_id,
                        broker_id,
                        status,
                    )
                continue

            # ==================================================
            # ✅ BROKER EXECUTED (STEP 6B - FINAL TRUTH)
            # ==================================================
            if status == "COMPLETE":
                logger.info(
                    f"STEP_6B_BROKER_EXECUTED | cmd_id={record.command_id} | broker_id={broker_id}"
                )
                
                self.repo.update_status(record.command_id, "EXECUTED")

                logger.info(
                    "OrderWatcher: EXECUTED_CONFIRMED | cmd_id=%s broker_id=%s",
                    record.command_id,
                    broker_id,
                )

                # 🔔 Notify strategy of fill via on_fill() callback
                try:
                    self._notify_strategy_fill(record, bo)
                except Exception:
                    logger.exception(
                        "OrderWatcher: on_fill callback failed | cmd_id=%s",
                        record.command_id,
                    )

                # 🔒 BROKER-TRUTH CONVERGENCE POINT
                self._reconcile_execution_guard(
                    strategy_name=record.strategy_name,
                    executed_symbol=record.symbol,
                )

    # ==================================================
    # STEP 7: DISPATCH CREATED EXIT ORDERS
    # ==================================================

    def _dispatch_pending_exits(self):
        """
        Poll DB for CREATED EXIT orders and dispatch them.

        - Simple MARKET EXITs (no SL/target/trailing): execute immediately via execute_command()
        - Managed EXITs (with SL/target/trailing): register as managed and monitor
        - Only dispatches orders created TODAY to prevent stale orders from
          previous days being sent to the broker (e.g. MIS auto-squared).
        """
        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y-%m-%d")

        with self._dispatch_lock:
            try:
                open_orders = self.repo.get_open_orders()
            except Exception as e:
                logger.warning("OrderWatcher: get_open_orders failed: %s", e)
                return

            for record in open_orders:
                if record.status != "CREATED":
                    continue
                if (record.execution_type or "").upper() != "EXIT":
                    continue

                # Skip stale orders from previous days — they will be expired
                # by the daily reset in PerStrategyExecutor.
                created_date = str(getattr(record, "created_at", "") or "")[:10]
                if created_date < today_str:
                    logger.warning(
                        "OrderWatcher: SKIPPING stale EXIT order from %s | cmd_id=%s | symbol=%s | strategy=%s",
                        created_date, record.command_id, record.symbol, record.strategy_name,
                    )
                    continue

                has_sl = record.stop_loss is not None and record.stop_loss > 0
                has_target = record.target is not None and record.target > 0
                has_trailing = (
                    record.trailing_type is not None
                    and record.trailing_type != "NONE"
                    and record.trailing_value is not None
                    and record.trailing_value > 0
                )

                if has_sl or has_target or has_trailing:
                    with self._managed_exits_lock:
                        if record.command_id not in self._managed_exits:
                            self._register_managed_exit(record)
                else:
                    if record.command_id not in self._dispatched_exits:
                        success = self._dispatch_simple_exit(record)
                        if success:
                            self._dispatched_exits.add(record.command_id)

    def _dispatch_simple_exit(self, record: OrderRecord) -> bool:
        """Dispatch a simple MARKET EXIT order to broker via execute_command(). Returns True on success."""
        try:
            # Mark as dispatching to prevent re-dispatch on next cycle.
            # Preserve any TEST_MODE marker so retries loaded from DB still
            # detect mock-mode even after the strategy is unregistered.
            _orig_tag = str(record.tag or "")
            _has_mock = "TEST_MODE_SUCCESS" in _orig_tag or "TEST_MODE_FAILURE" in _orig_tag
            _dispatch_tag = "DISPATCHING|TEST_MODE_SUCCESS" if _has_mock else "DISPATCHING"
            try:
                self.repo.update_tag(record.command_id, _dispatch_tag)
            except Exception:
                pass

            cmd = UniversalOrderCommand.from_record(
                record,
                order_type=record.order_type or "MARKET",
                price=record.price or 0.0,
                source="ORDER_WATCHER",
            )

            logger.info(
                "STEP_7_DISPATCH_EXIT | cmd_id=%s | %s %s %s qty=%s",
                record.command_id,
                record.exchange,
                record.symbol,
                record.side,
                record.quantity,
            )

            result = self.bot.execute_command(command=cmd)

            if result and result.success:
                return True

            err = getattr(result, "error_message", "unknown") if result else "no result"
            logger.error(
                "STEP_7_EXIT_FAILED | cmd_id=%s | symbol=%s | error=%s",
                record.command_id,
                record.symbol,
                err,
            )
            return False
        except Exception:
            logger.exception(
                "STEP_7_EXIT_EXCEPTION | cmd_id=%s | symbol=%s",
                record.command_id,
                record.symbol,
            )
            return False

    def _register_managed_exit(self, record: OrderRecord):
        """Register an EXIT order for managed monitoring (SL/target/trailing)."""
        try:
            self.repo.update_tag(record.command_id, "MANAGED_EXIT")
        except Exception:
            pass

        initial_ltp = record.managed_anchor_ltp
        if initial_ltp is None:
            try:
                positions = self.bot.api.get_positions() or []
                for pos in positions:
                    if pos.get("tsym") != record.symbol:
                        continue
                    pos_product = pos.get("prd") or pos.get("product")
                    if record.product and pos_product and pos_product != record.product:
                        continue
                    live_price = pos.get("ltp", pos.get("lp", 0))
                    if live_price is not None:
                        initial_ltp = float(live_price or 0) or None
                    break
            except Exception:
                logger.warning(
                    "MANAGED_EXIT_REGISTER_LTP_LOOKUP_FAILED | cmd_id=%s | %s",
                    record.command_id,
                    record.symbol,
                    exc_info=True,
                )

        base_stop_loss = record.managed_base_stop_loss if record.managed_base_stop_loss is not None else record.stop_loss

        self._managed_exits[record.command_id] = {
            "record": record,
            "stop_loss": record.stop_loss,
            "base_stop_loss": base_stop_loss,
            "target": record.target,
            "trailing_type": record.trailing_type,
            "trailing_value": record.trailing_value,
            "trail_when": record.trail_when,
            "initial_ltp": initial_ltp,
            "activation_price": None,
            "trailing_activated": False,
            "highest_price": None,
            "lowest_price": None,
            "registered_at": time.time(),
        }

        if initial_ltp is not None or base_stop_loss is not None:
            try:
                self._update_order_risk_fields(record.command_id, {
                    "managed_anchor_ltp": initial_ltp,
                    "managed_base_stop_loss": base_stop_loss,
                })
            except Exception:
                logger.exception(
                    "MANAGED_EXIT_STATE_PERSIST_FAILED | cmd_id=%s | %s",
                    record.command_id,
                    record.symbol,
                )

        logger.warning(
            "MANAGED_EXIT_REGISTERED | cmd_id=%s | %s | side=%s | qty=%s | SL=%s | target=%s | trail=%s/%s | trail_when=%s | initial_ltp=%s",
            record.command_id,
            record.symbol,
            record.side,
            record.quantity,
            record.stop_loss,
            record.target,
            record.trailing_type,
            record.trailing_value,
            record.trail_when,
            initial_ltp,
        )

    # ==================================================
    # STEP 8: MONITOR MANAGED EXITS (SL / TARGET / TRAIL)
    # ==================================================

    def _monitor_managed_exits(self):
        """
        For each managed exit order, check current LTP against SL/target levels.
        Trail the SL as price moves in the position's favour.
        Trigger MARKET exit when conditions are met.
        """
        with self._managed_exits_lock:
            if not self._managed_exits:
                return
            # Shallow-copy each state dict so workers operate on local copies
            # and don't race with other threads mutating the originals.
            snapshot = [(cmd_id, dict(state)) for cmd_id, state in self._managed_exits.items()]

        try:
            positions = self.bot.api.get_positions() or []
        except Exception as e:
            logger.warning("OrderWatcher: positions fetch for managed exits failed: %s", e)
            return

        pos_map: Dict[str, dict] = {}
        for p in positions:
            sym = p.get("tsym")
            if sym:
                pos_map[sym] = p

        to_remove: List[str] = []
        updated_states: Dict[str, dict] = {}

        for cmd_id, state in snapshot:
            record = state["record"]
            symbol = record.symbol

            # Verify order still CREATED
            try:
                current_record = self.repo.get_by_id(cmd_id)
                if not current_record or current_record.status not in ("CREATED",):
                    to_remove.append(cmd_id)
                    continue
            except Exception:
                logger.warning("OrderWatcher: repo.get_by_id failed for cmd_id=%s", cmd_id, exc_info=True)
                continue

            pos = pos_map.get(symbol)
            net_qty = int(pos.get("netqty", 0)) if pos else 0

            if net_qty == 0:
                logger.info(
                    "MANAGED_EXIT_POSITION_FLAT | cmd_id=%s | %s",
                    cmd_id, symbol,
                )
                try:
                    self.repo.update_status(cmd_id, "FAILED")
                    self.repo.update_tag(cmd_id, "POSITION_ALREADY_FLAT")
                except Exception:
                    pass
                to_remove.append(cmd_id)
                continue

            # Broker payloads may expose live price as either `ltp` or `lp`.
            # Fall back to `lp` so managed exits keep working across brokers.
            ltp = float(pos.get("ltp", pos.get("lp", 0)) or 0)
            if ltp <= 0:
                continue

            is_long = net_qty > 0
            sl = state.get("stop_loss")
            target = state.get("target")
            trailing_type = state.get("trailing_type")
            trailing_value = state.get("trailing_value")
            trigger_exit = False
            trigger_reason = ""

            # ── TRAILING SL LOGIC ──
            if trailing_type and trailing_value and trailing_value > 0:
                if state.get("initial_ltp") is None:
                    state["initial_ltp"] = ltp

                # Check trail_when activation
                trail_when = state.get("trail_when")
                trailing_activated = state.get("trailing_activated", False)
                if not trailing_activated and trail_when and trail_when > 0:
                    initial_ltp = float(state.get("initial_ltp") or 0)
                    activation_price = initial_ltp + float(trail_when) if is_long else initial_ltp - float(trail_when)
                    state["activation_price"] = activation_price

                    # LONG: activate after favorable move above anchor by trail_when steps.
                    # SHORT: activate after favorable move below anchor by trail_when steps.
                    if is_long and ltp >= activation_price:
                        state["trailing_activated"] = True
                        trailing_activated = True
                        logger.info(
                            "TRAILING_ACTIVATED | %s | ltp=%s >= activation=%s | anchor=%s | trail_when=%s",
                            symbol, ltp, activation_price, initial_ltp, trail_when,
                        )
                    elif not is_long and ltp <= activation_price:
                        state["trailing_activated"] = True
                        trailing_activated = True
                        logger.info(
                            "TRAILING_ACTIVATED | %s | ltp=%s <= activation=%s | anchor=%s | trail_when=%s",
                            symbol, ltp, activation_price, initial_ltp, trail_when,
                        )
                elif not trail_when or trail_when <= 0:
                    # No trail_when set — trailing is immediately active
                    trailing_activated = True
                    state["trailing_activated"] = True
                    state["activation_price"] = state.get("initial_ltp")

                if trailing_activated:
                    # POINTS trailing (dashboard PM): move SL in fixed steps
                    # from the original configured stop-loss, not as ltp +/- trail.
                    if trailing_type == "POINTS":
                        base_sl = state.get("base_stop_loss")
                        if base_sl is None and sl is not None:
                            base_sl = float(sl)
                            state["base_stop_loss"] = base_sl

                        initial_ltp = float(state.get("initial_ltp") or 0)
                        step_trigger = float(trail_when) if trail_when and trail_when > 0 else float(trailing_value)
                        step_move = float(trailing_value)

                        if base_sl is not None and initial_ltp > 0 and step_trigger > 0 and step_move > 0:
                            favorable_move = (ltp - initial_ltp) if is_long else (initial_ltp - ltp)
                            favorable_move = max(0.0, favorable_move)
                            steps = int(favorable_move // step_trigger)

                            if steps > 0:
                                if is_long:
                                    new_sl = float(base_sl) + (steps * step_move)
                                    if sl is None or new_sl > sl:
                                        old_sl = sl
                                        state["stop_loss"] = new_sl
                                        sl = new_sl
                                        logger.info(
                                            "TRAILING_SL_UPDATED | %s | old_sl=%s | new_sl=%s | base_sl=%s | anchor=%s | ltp=%s | steps=%s",
                                            symbol,
                                            old_sl,
                                            new_sl,
                                            base_sl,
                                            initial_ltp,
                                            ltp,
                                            steps,
                                        )
                                        try:
                                            self._update_order_risk_fields(record.command_id, {
                                                "stop_loss": new_sl,
                                                "managed_anchor_ltp": initial_ltp,
                                                "managed_base_stop_loss": base_sl,
                                            })
                                        except Exception:
                                            logger.exception("Failed to persist trailed stop loss for %s", symbol)
                                else:
                                    new_sl = float(base_sl) - (steps * step_move)
                                    if sl is None or new_sl < sl:
                                        old_sl = sl
                                        state["stop_loss"] = new_sl
                                        sl = new_sl
                                        logger.info(
                                            "TRAILING_SL_UPDATED | %s | old_sl=%s | new_sl=%s | base_sl=%s | anchor=%s | ltp=%s | steps=%s",
                                            symbol,
                                            old_sl,
                                            new_sl,
                                            base_sl,
                                            initial_ltp,
                                            ltp,
                                            steps,
                                        )
                                        try:
                                            self._update_order_risk_fields(record.command_id, {
                                                "stop_loss": new_sl,
                                                "managed_anchor_ltp": initial_ltp,
                                                "managed_base_stop_loss": base_sl,
                                            })
                                        except Exception:
                                            logger.exception("Failed to persist trailed stop loss for %s", symbol)
                    else:
                        # Keep legacy behaviour for non-POINTS modes.
                        if is_long:
                            if state["highest_price"] is None or ltp > state["highest_price"]:
                                state["highest_price"] = ltp
                            if trailing_type == "PERCENT":
                                new_sl = state["highest_price"] * (1 - trailing_value / 100)
                            else:
                                new_sl = state["highest_price"] - trailing_value
                            if sl is None or new_sl > sl:
                                state["stop_loss"] = new_sl
                                sl = new_sl
                        else:
                            if state["lowest_price"] is None or ltp < state["lowest_price"]:
                                state["lowest_price"] = ltp
                            if trailing_type == "PERCENT":
                                new_sl = state["lowest_price"] * (1 + trailing_value / 100)
                            else:
                                new_sl = state["lowest_price"] + trailing_value
                            if sl is None or new_sl < sl:
                                state["stop_loss"] = new_sl
                                sl = new_sl

            # ── CHECK SL HIT ──
            if sl is not None:
                if is_long and ltp <= sl:
                    trigger_exit = True
                    trigger_reason = f"SL_HIT ltp={ltp} <= sl={sl}"
                elif not is_long and ltp >= sl:
                    trigger_exit = True
                    trigger_reason = f"SL_HIT ltp={ltp} >= sl={sl}"

            # ── CHECK TARGET HIT ──
            if target is not None and not trigger_exit:
                if is_long and ltp >= target:
                    trigger_exit = True
                    trigger_reason = f"TARGET_HIT ltp={ltp} >= target={target}"
                elif not is_long and ltp <= target:
                    trigger_exit = True
                    trigger_reason = f"TARGET_HIT ltp={ltp} <= target={target}"

            if trigger_exit:
                logger.warning(
                    "MANAGED_EXIT_TRIGGERED | cmd_id=%s | %s | %s | net_qty=%d",
                    cmd_id, symbol, trigger_reason, net_qty,
                )
                self._execute_managed_exit(record, abs(net_qty))
                to_remove.append(cmd_id)
            else:
                # Track locally-modified states to merge back
                updated_states[cmd_id] = state

        with self._managed_exits_lock:
            # Merge updated trailing state back into shared dict
            for cmd_id, local_state in updated_states.items():
                if cmd_id in self._managed_exits:
                    orig = self._managed_exits[cmd_id]
                    orig["trailing_activated"] = local_state["trailing_activated"]
                    orig["highest_price"] = local_state["highest_price"]
                    orig["lowest_price"] = local_state["lowest_price"]
                    orig["stop_loss"] = local_state["stop_loss"]
                    orig["base_stop_loss"] = local_state.get("base_stop_loss")
                    orig["initial_ltp"] = local_state.get("initial_ltp")
                    orig["activation_price"] = local_state.get("activation_price")
            for cmd_id in to_remove:
                self._managed_exits.pop(cmd_id, None)

    def _execute_managed_exit(self, record: OrderRecord, broker_qty: int):
        """Execute a managed exit by placing a MARKET order."""
        try:
            from uuid import uuid4
            exit_cmd_id = f"EXIT_MANAGED_{record.symbol}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"

            exit_record = OrderRecord(
                command_id=exit_cmd_id,
                broker_order_id=None,
                execution_type="EXIT",
                source=record.source,
                user=record.user,
                strategy_name=record.strategy_name,
                exchange=record.exchange,
                symbol=record.symbol,
                side=record.side,
                quantity=broker_qty,
                product=record.product,
                order_type="MARKET",
                price=0.0,
                stop_loss=None,
                target=None,
                trailing_type=None,
                trailing_value=None,
                status="CREATED",
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                tag="MANAGED_EXIT_MARKET",
            )
            self.repo.create(exit_record)

            cmd = UniversalOrderCommand.from_record(
                exit_record,
                order_type="MARKET",
                price=0.0,
                source="ORDER_WATCHER",
            )

            result = self.bot.execute_command(command=cmd)
            if result and result.success:
                logger.info(
                    "MANAGED_EXIT_DISPATCHED | cmd_id=%s | %s %s qty=%d",
                    exit_cmd_id, record.symbol, record.side, broker_qty,
                )
                # Only mark original record after successful dispatch
                self.repo.update_status(record.command_id, "FAILED")
                self.repo.update_tag(record.command_id, "MANAGED_EXIT_TRIGGERED")
            else:
                err = getattr(result, "error_message", "unknown") if result else "no result"
                logger.error(
                    "MANAGED_EXIT_DISPATCH_FAILED | cmd_id=%s | %s | error=%s — original record left active",
                    exit_cmd_id, record.symbol, err,
                )
        except Exception:
            logger.exception(
                "MANAGED_EXIT_EXCEPTION | cmd_id=%s | %s — original record left active",
                record.command_id, record.symbol,
            )

    # --------------------------------------------------
    # ExecutionGuard reconciliation (BROKER-DRIVEN ONLY)
    # --------------------------------------------------
    def _reconcile_execution_guard(self, strategy_name: str, executed_symbol: str) -> None:
        try:
            symbols = self._get_strategy_symbols(strategy_name)
            if executed_symbol:
                symbols.add(executed_symbol)
            broker_map = self._build_broker_map(symbol_filter=symbols or None)

            self.bot.execution_guard.reconcile_with_broker(
                strategy_id=strategy_name,
                broker_positions=broker_map,
            )

            # Closed means reconciliation removed all tracked legs for this strategy.
            if not self.bot.execution_guard.has_strategy(strategy_name):
                logger.info(
                    "OrderWatcher: strategy fully closed | strategy=%s",
                    strategy_name,
                )

        except Exception as e:
            logger.exception(
                "OrderWatcher: guard reconciliation failed | strategy=%s | %s",
                strategy_name,
                e,
            )

    # --------------------------------------------------
    # 🔥 ON_FILL CALLBACK — Wire strategy fill notifications
    # --------------------------------------------------
    def _notify_strategy_fill(self, record, broker_order):
        """
        Extract fill details from broker order and notify strategy via on_fill().

        Broker order format:
        {
        "norenordno": "string",
        "status": "COMPLETE",
        "tsym": "SYMBOL",
        "side": "BUY" / "SELL",
        "fillshares": qty,
        "avgprc": price,
        "prcflag": "LTP" / etc,
        ... (delta may or may not be present)
        }

        Route returned intents through CommandService.
        """
        try:
            symbol = broker_order.get("tsym", record.symbol)
            # Shoonya API returns trantype as "B"/"S", not "BUY"/"SELL"
            raw_side = (
                broker_order.get("side")
                or broker_order.get("trantype")
                or record.side
                or ""
            ).upper()
            # Normalize: B → BUY, S → SELL
            side_map = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}
            side = side_map.get(raw_side, raw_side)
            
            qty = int(broker_order.get("fillshares") or broker_order.get("qty") or 0)
            price = float(broker_order.get("avgprc") or broker_order.get("flprc") or 0)
            delta = broker_order.get("delta")  # Shoonya doesn't provide this  # May be None or string

            if not symbol or not side or qty == 0:
                logger.warning(
                    f"Fill callback: incomplete fill data | cmd_id={record.command_id}"
                )
                return

            # Try to parse delta
            try:
                delta = float(delta) if delta else None
            except (ValueError, TypeError):
                delta = None

            logger.info(
                f"FILL_CALLBACK | cmd_id={record.command_id} | "
                f"{symbol} {side} {qty} @ {price} | delta={delta}"
            )

            # Keep StrategyExecutorService state in sync immediately on broker fill.
            # This avoids pending-timeout drift between OMS and monitor view.
            try:
                self.bot.notify_fill(
                    strategy_name=record.strategy_name,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=price,
                    delta=delta,
                    broker_order_id=record.broker_order_id,
                    command_id=record.command_id,
                )
            except Exception:
                logger.exception(
                    "OrderWatcher: bot.notify_fill failed | cmd_id=%s",
                    record.command_id,
                )

        except Exception:
            logger.exception(
                "OrderWatcher: _notify_strategy_fill failed | cmd_id=%s",
                record.command_id,
            )

    # --------------------------------------------------
    # Direction-aware broker map (ExecutionGuard v1.3)
    # --------------------------------------------------

    def _build_broker_map(self, symbol_filter: Optional[set] = None) -> Dict[str, Dict[str, int]]:
        """
        Build direction-aware broker map.

        Contract:
            {
              "SYMBOL": {
                "BUY": qty,
                "SELL": qty
              }
            }
        """
        positions = self.bot.api.get_positions() or []
        broker_map: Dict[str, Dict[str, int]] = {}

        for p in positions:
            sym = p.get("tsym")
            net = int(p.get("netqty", 0))

            if not sym or net == 0:
                continue
            if symbol_filter is not None and sym not in symbol_filter:
                continue

            broker_map.setdefault(sym, {"BUY": 0, "SELL": 0})

            if net > 0:
                broker_map[sym]["BUY"] = net
            else:
                broker_map[sym]["SELL"] = abs(net)

        return broker_map

    def _get_strategy_symbols(self, strategy_name: str) -> set:
        """
        Best-effort fetch of currently tracked symbols for a strategy.
        Used to scope reconciliation to strategy-relevant broker positions only.
        """
        guard = getattr(self.bot, "execution_guard", None)
        if guard is None:
            return set()

        lock = getattr(guard, "_lock", None)
        positions = getattr(guard, "_strategy_positions", None)
        if lock is None or not isinstance(positions, dict):
            return set()

        with lock:
            tracked = positions.get(strategy_name) or {}
            return set(tracked.keys())

    # ==================================================
    # PUBLIC API: Managed Exit State (for Dashboard)
    # ==================================================

    def get_managed_exits_snapshot(self) -> List[dict]:
        """Return a snapshot of all currently managed exit orders for dashboard display."""
        result = []
        with self._managed_exits_lock:
            for cmd_id, state in list(self._managed_exits.items()):
                record = state["record"]
                next_trail_price = None
                initial_ltp = state.get("initial_ltp")
                trail_when = state.get("trail_when")
                trailing_value = state.get("trailing_value")
                trailing_type = state.get("trailing_type")
                stop_loss = state.get("stop_loss")
                base_stop_loss = state.get("base_stop_loss")

                if (
                    trailing_type == "POINTS"
                    and initial_ltp is not None
                    and trailing_value is not None
                    and trail_when is not None
                ):
                    try:
                        step_trigger = float(trail_when)
                        step_move = float(trailing_value)
                        anchor = float(initial_ltp)
                        if step_trigger > 0 and step_move > 0:
                            steps_done = 0
                            if stop_loss is not None and base_stop_loss is not None:
                                if record.side == "SELL":
                                    sl_delta = float(stop_loss) - float(base_stop_loss)
                                else:
                                    sl_delta = float(base_stop_loss) - float(stop_loss)
                                if sl_delta > 0:
                                    steps_done = int(sl_delta // step_move)
                            direction = 1.0 if record.side == "SELL" else -1.0
                            next_trail_price = anchor + (direction * ((steps_done + 1) * step_trigger))
                    except Exception:
                        next_trail_price = None

                result.append({
                    "command_id": cmd_id,
                    "symbol": record.symbol,
                    "exchange": record.exchange,
                    "side": record.side,
                    "quantity": record.quantity,
                    "product": record.product,
                    "strategy_name": record.strategy_name,
                    "stop_loss": state.get("stop_loss"),
                    "base_stop_loss": state.get("base_stop_loss"),
                    "target": state.get("target"),
                    "trailing_type": state.get("trailing_type"),
                    "trailing_value": state.get("trailing_value"),
                    "trail_when": state.get("trail_when"),
                    "initial_ltp": state.get("initial_ltp"),
                    "activation_price": state.get("activation_price"),
                    "next_trail_price": next_trail_price,
                    "trailing_activated": state.get("trailing_activated", False),
                    "highest_price": state.get("highest_price"),
                    "lowest_price": state.get("lowest_price"),
                    "registered_at": state.get("registered_at"),
                })
        return result

    def update_managed_exit(self, symbol: str, updates: dict, product: str = None) -> bool:
        """
        Update SL/target/trailing for a managed exit identified by symbol.
        Returns True if found and updated, False otherwise.
        Explicitly null/None values are honoured to allow the caller to clear a field.
        """
        with self._managed_exits_lock:
            for cmd_id, state in list(self._managed_exits.items()):
                record = state["record"]
                if record.symbol == symbol and (product is None or record.product == product):
                    if "stop_loss" in updates:
                        val = updates["stop_loss"]
                        state["stop_loss"] = float(val) if val is not None else None
                        state["base_stop_loss"] = float(val) if val is not None else state.get("base_stop_loss")
                    if "target" in updates:
                        val = updates["target"]
                        state["target"] = float(val) if val is not None else None
                    if "trailing_value" in updates:
                        val = updates["trailing_value"]
                        state["trailing_value"] = float(val) if val is not None else None
                    if "trailing_type" in updates:
                        state["trailing_type"] = updates["trailing_type"]  # may be None to clear
                    if "trail_when" in updates:
                        val = updates["trail_when"]
                        state["trail_when"] = float(val) if val is not None else None
                    if any(field in updates for field in ("trailing_type", "trailing_value", "trail_when")):
                        # Clear trailing progression so new config starts fresh.
                        state["trailing_activated"] = False
                        state["activation_price"] = None
                        state["highest_price"] = None
                        state["lowest_price"] = None

                    # Also update the DB record for persistence across restarts
                    try:
                        db_updates = dict(updates)
                        db_updates["managed_anchor_ltp"] = state.get("initial_ltp")
                        db_updates["managed_base_stop_loss"] = state.get("base_stop_loss")
                        self._update_order_risk_fields(record.command_id, db_updates)
                    except Exception:
                        logger.exception("Failed to update DB risk fields for %s", symbol)

                    logger.warning(
                        "MANAGED_EXIT_UPDATED | cmd_id=%s | %s | product=%s | SL=%s | target=%s | trail=%s/%s | trail_when=%s | anchor=%s",
                        cmd_id, symbol,
                        record.product,
                        state.get("stop_loss"), state.get("target"),
                        state.get("trailing_type"), state.get("trailing_value"), state.get("trail_when"), state.get("initial_ltp"),
                    )
                    return True
        return False

    def remove_managed_exit(self, symbol: str, product: str = None) -> bool:
        """Remove a managed exit by symbol (disables SL/target monitoring)."""
        with self._managed_exits_lock:
            for cmd_id, state in list(self._managed_exits.items()):
                record = state["record"]
                if record.symbol == symbol and (product is None or record.product == product):
                    self._managed_exits.pop(cmd_id, None)
                    try:
                        self.repo.update_status(cmd_id, "FAILED")
                        self.repo.update_tag(cmd_id, "MANAGER_DISABLED")
                    except Exception:
                        pass
                    logger.warning(
                        "MANAGED_EXIT_REMOVED | cmd_id=%s | %s | product=%s | cleared_anchor=%s",
                        cmd_id,
                        symbol,
                        record.product,
                        state.get("initial_ltp"),
                    )
                    return True
        return False

    def _update_order_risk_fields(self, command_id: str, updates: dict):
        """Update risk fields on the DB order record."""
        from shoonya_platform.persistence.database import get_connection
        conn = get_connection()
        try:
            sets = []
            params = []
            for field in ("stop_loss", "target", "trailing_type", "trailing_value", "trail_when"):
                if field in updates:
                    sets.append(f"{field} = ?")
                    params.append(updates[field])
            for field in ("managed_anchor_ltp", "managed_base_stop_loss"):
                if field in updates:
                    sets.append(f"{field} = ?")
                    params.append(updates[field])
            if not sets:
                return
            params.append(datetime.utcnow().isoformat())
            params.append(command_id)
            conn.execute(
                f"UPDATE orders SET {', '.join(sets)}, updated_at = ? WHERE command_id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

    def enable_managed_exit(self, symbol: str, exchange: str, side: str,
                            quantity: int, product: str, stop_loss: float = None,
                            target: float = None, trailing_type: str = None,
                            trailing_value: float = None, trail_when: float = None) -> bool:
        """
        Create and register a new managed exit for an existing broker position.
        Called from dashboard when user enables position manager for a position.
        """
        from uuid import uuid4

        # Check if already managed
        with self._managed_exits_lock:
            for state in self._managed_exits.values():
                if state["record"].symbol == symbol and state["record"].product == product:
                    # Already managed — update instead (release lock, update_managed_exit takes it)
                    break
            else:
                state = None
        if state and state["record"].symbol == symbol and state["record"].product == product:
            return self.update_managed_exit(symbol, {
                "stop_loss": stop_loss,
                "target": target,
                "trailing_type": trailing_type,
                "trailing_value": trailing_value,
                "trail_when": trail_when,
            }, product=product)

        cmd_id = f"MANAGED_{symbol}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"
        strategy_name = f"__BASKET__:DASH-MGR-{uuid4().hex[:10]}:LEG_0"

        record = OrderRecord(
            command_id=cmd_id,
            broker_order_id=None,
            execution_type="EXIT",
            source="STRATEGY",
            user=self.bot.client_id,
            strategy_name=strategy_name,
            exchange=exchange,
            symbol=symbol,
            side=side,
            quantity=quantity,
            product=product,
            order_type="MARKET",
            price=0.0,
            stop_loss=stop_loss,
            target=target,
            trailing_type=trailing_type or "NONE",
            trailing_value=trailing_value,
            trail_when=trail_when,
            status="CREATED",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
            tag="MANAGED_EXIT",
        )
        self.repo.create(record)
        with self._managed_exits_lock:
            self._register_managed_exit(record)
        return True
