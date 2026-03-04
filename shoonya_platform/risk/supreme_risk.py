#!/usr/bin/env python3
"""
Supreme Risk Manager
===================

PRODUCTION-GRADE RISK AUTHORITY — EXECUTION-ALIGNED

ROLE (FROZEN):
- Decide WHEN risk is breached
- NEVER decide HOW to exit
- NEVER infer qty / side / symbol
- NEVER submit broker orders

EXIT LAW:
Risk → PositionExitService → OrderWatcherEngine → Broker → Reconcile → Cleanup
"""

import os
import json
import time
import math
import threading
import logging
from datetime import date, datetime, timedelta
from collections import deque, OrderedDict
from typing import Dict, Optional, List, Tuple

from shoonya_platform.logging.logger_config import get_component_logger
from shoonya_platform.utils.utils import log_exception

logger = get_component_logger('risk_manager')


class SupremeRiskManager:
    """
    🔒 SupremeRiskManager (v1.3.0 — PRODUCTION FROZEN)

    Responsibilities:
    - Risk evaluation
    - Daily loss enforcement
    - Trailing max-loss logic
    - Cooldown enforcement
    - Human/manual trade violation detection
    - EXIT decision routing ONLY
    """

    # --------------------------------------------------
    # INIT
    # --------------------------------------------------

    def __init__(self, bot):
        self.bot = bot
        self._lock = threading.RLock()

        cfg = bot.config
        client_id = bot.client_id

        # ---------------- Risk state persistence ----------------
        self.STATE_FILE = f"{cfg.risk_state_file.rstrip('.json')}_{client_id}.json"
        os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)

        # ---------------- Config ----------------
        self.BASE_MAX_LOSS = cfg.risk_base_max_loss
        self.TRAIL_STEP = cfg.risk_trail_step
        self.WARNING_THRESHOLD_PCT = cfg.risk_warning_threshold
        self.MAX_CONSECUTIVE_LOSS_DAYS = cfg.risk_max_consecutive_loss_days
        self.STATUS_UPDATE_INTERVAL = cfg.risk_status_update_min
        self.PNL_RETENTION = cfg.risk_pnl_retention

        # ---------------- Runtime state ----------------
        self.current_day: date = date.today()
        self.daily_pnl: float = 0.0
        self.dynamic_max_loss: float = self.BASE_MAX_LOSS
        self.highest_profit: float = 0.0

        self.failed_days = deque(maxlen=self.MAX_CONSECUTIVE_LOSS_DAYS)
        self.cooldown_until: Optional[date] = None
        self.daily_loss_hit: bool = False
        self.warning_sent: bool = False

        # 🔒 Execution flag (monotonic)
        self.force_exit_in_progress: bool = False

        # Manual trade detection
        self.last_manual_position_signature = None
        self.last_manual_violation_ts = None
        self.human_violation_detected = False
        self.MANUAL_ALERT_COOLDOWN_SEC = 5  # 🔥 Reduced from 60s — fast re-detection

        # Status / analytics
        self.last_status_update: Optional[datetime] = None
        self.last_known_pnl: Optional[float] = None

        self.pnl_ohlc = {
            "1m": OrderedDict(),
            "5m": OrderedDict(),
            "1d": OrderedDict(),
        }

        self._load_state()

        logger.info("SupremeRiskManager initialized v1.3.0 (EXECUTION-ALIGNED)")

    @staticmethod
    def _trading_days_between(d1: date, d2: date) -> int:
        """
        Return number of trading days between d1 and d2 (exclusive).
        Assumes Monday–Friday are trading days.
        """
        if d1 >= d2:
            return 0
        delta = (d2 - d1).days
        # full weeks contribute 5 trading days each
        full_weeks, remainder = divmod(delta, 7)
        trading_days = full_weeks * 5
        # add trading days in the remaining partial week
        for offset in range(1, remainder + 1):
            if (d1 + timedelta(days=offset)).weekday() < 5:  # 0=Monday .. 4=Friday
                trading_days += 1
        return trading_days
    
    # --------------------------------------------------
    # STATE PERSISTENCE
    # --------------------------------------------------

    def _load_state(self):
        if not os.path.exists(self.STATE_FILE):
            logger.info("RMS: No previous state file found, starting fresh")
            return
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)

            if data.get("date") == str(self.current_day):
                self.dynamic_max_loss = data.get("dynamic_max_loss", self.BASE_MAX_LOSS)
                self.highest_profit = data.get("highest_profit", 0.0)
                self.daily_loss_hit = data.get("daily_loss_hit", False)
                self.human_violation_detected = data.get("human_violation_detected", False)

                # Restore failed_days and cooldown_until (crash-safe)
                saved_failed_days = data.get("failed_days", [])
                for d_str in saved_failed_days:
                    try:
                        self.failed_days.append(date.fromisoformat(d_str))
                    except (ValueError, TypeError):
                        pass
                saved_cooldown = data.get("cooldown_until")
                if saved_cooldown:
                    try:
                        self.cooldown_until = date.fromisoformat(saved_cooldown)
                    except (ValueError, TypeError):
                        pass

                logger.info(
                    "RMS: State loaded | date=%s | max_loss=%.2f | profit=%.2f | loss_hit=%s",
                    self.current_day,
                    self.dynamic_max_loss,
                    self.highest_profit,
                    self.daily_loss_hit,
                )
            else:
                logger.info(
                    "RMS: State date mismatch (old=%s, current=%s), starting fresh",
                    data.get("date"),
                    self.current_day,
                )

        except Exception as e:
            log_exception("RiskState.load", e)

    def _save_state(self):
        try:
            state_data = {
                "date": str(self.current_day),
                "daily_pnl": self.daily_pnl,
                "dynamic_max_loss": self.dynamic_max_loss,
                "highest_profit": self.highest_profit,
                "daily_loss_hit": self.daily_loss_hit,
                "human_violation_detected": self.human_violation_detected,
                "force_exit_in_progress": self.force_exit_in_progress,
                "failed_days": [str(d) for d in self.failed_days],
                "cooldown_until": str(self.cooldown_until) if self.cooldown_until else None,
                "base_max_loss": self.BASE_MAX_LOSS,
                "warning_sent": self.warning_sent,
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(state_data, f)
            logger.debug("RMS: State saved | loss_hit=%s | max_loss=%.2f", self.daily_loss_hit, self.dynamic_max_loss)
        except Exception as e:
            log_exception("RiskState.save", e)

    # --------------------------------------------------
    # EXECUTION DECISION (ONLY)
    # --------------------------------------------------

    def _route_global_exit(self, reason: str):
        """
        🔒 CANONICAL EXIT ROUTE

        Risk decides → PositionExitService executes.
        """
        logger.critical("RISK EXIT ROUTED | reason=%s | scope=ALL", reason)

        self.bot.request_exit(
            scope="ALL",
            symbols=None,
            product_type="ALL",
            reason=reason,
            source="RISK",
        )

    # --------------------------------------------------
    # ENTRY GATING
    # --------------------------------------------------

    def can_execute(self) -> bool:
        with self._lock:
            today = date.today()
            try:
                self._update_pnl()
            except RuntimeError:
                # 🔥 FAIL-HARD: broker/session failure must kill process
                raise

            if today != self.current_day:
                logger.info("RMS: New day detected | old=%s | new=%s", self.current_day, today)
                self._reset_daily_state(today)

            if self.cooldown_until and today < self.cooldown_until:
                logger.warning(
                    "RMS: Entry BLOCKED | reason=COOLDOWN | until=%s | current=%s",
                    self.cooldown_until,
                    today,
                )
                return False

            if self.force_exit_in_progress:
                logger.warning(
                    "RMS: Entry BLOCKED | reason=FORCE_EXIT_IN_PROGRESS | pnl=%.2f",
                    self.daily_pnl,
                )
                return False

            if self.daily_loss_hit:
                logger.warning(
                    "RMS: Entry BLOCKED | reason=DAILY_LOSS_HIT | pnl=%.2f | max_loss=%.2f",
                    self.daily_pnl,
                    self.dynamic_max_loss,
                )
                return False

            if self.daily_pnl <= self.dynamic_max_loss:
                logger.critical(
                    "RMS: Max loss breach detected | pnl=%.2f | max_loss=%.2f | triggering exit",
                    self.daily_pnl,
                    self.dynamic_max_loss,
                )
                self._handle_daily_loss_breach()
                return False

            logger.debug(
                "RMS: Entry ALLOWED | pnl=%.2f | max_loss=%.2f | margin=%.2f",
                self.daily_pnl,
                self.dynamic_max_loss,
                self.daily_pnl - self.dynamic_max_loss,
            )
            return True

    def can_execute_command(self, command) -> Tuple[bool, str]:
        with self._lock:
            if self.force_exit_in_progress:
                logger.warning("RMS: Command BLOCKED | reason=FORCE_EXIT_IN_PROGRESS | command=%s", command)
                return False, "FORCE_EXIT_IN_PROGRESS"

            if self.daily_loss_hit:
                logger.warning("RMS: Command BLOCKED | reason=DAILY_MAX_LOSS_HIT | command=%s", command)
                return False, "DAILY_MAX_LOSS_HIT"

            logger.debug("RMS: Command ALLOWED | command=%s", command)
            return True, "OK"

    # --------------------------------------------------
    # LOSS BREACH
    # --------------------------------------------------
    def _handle_daily_loss_breach(self):
        if self.daily_loss_hit:
            logger.debug("RMS: Loss breach already handled, skipping duplicate")
            return

        self.daily_loss_hit = True
        self._save_state()  # 🔒 PERSIST IMMEDIATELY — crash cannot clear this flag
        self.failed_days.append(self.current_day)
        self.force_exit_in_progress = True

        # # ✅ FIX: verify that the loss days are truly consecutive
        # days_list = list(self.failed_days)
        # is_consecutive = True
        # if len(days_list) >= 2:
        #     for i in range(len(days_list)-1):
        #         if (days_list[i+1] - days_list[i]).days != 1:
        #             is_consecutive = False
        #             break

        # consecutive_losses = len(days_list) if is_consecutive else 0
        # 🔥 NEW LOGIC: count trading days between first and last failure — must be <= MAX_CONSECUTIVE_LOSS_DAY
        # ✅ Check that loss days are truly consecutive trading days
        days_list = list(self.failed_days)
        is_consecutive = True
        if len(days_list) >= 2:
            for i in range(len(days_list) - 1):
                # Gap should be exactly 1 trading day
                if self._trading_days_between(days_list[i], days_list[i+1]) != 1:
                    is_consecutive = False
                    break

        consecutive_losses = len(days_list) if is_consecutive else 0

        logger.critical(
            "🔴 DAILY MAX LOSS HIT | pnl=%.2f | max_loss=%.2f | consecutive_days=%d/%d | consecutive=%s",
            self.daily_pnl,
            self.dynamic_max_loss,
            consecutive_losses,
            self.MAX_CONSECUTIVE_LOSS_DAYS,
            is_consecutive,
        )

        if self.bot.telegram_enabled:
            msg = (
                f"🛑 <b>DAILY MAX LOSS BREACH</b>\n\n"
                f"💔 Current PnL: ₹{self.daily_pnl:.2f}\n"
                f"🔒 Max Loss Limit: ₹{self.dynamic_max_loss:.2f}\n"
                f"📉 Breach Amount: ₹{abs(self.daily_pnl - self.dynamic_max_loss):.2f}\n"
                f"📊 Consecutive Loss Days: {consecutive_losses}/{self.MAX_CONSECUTIVE_LOSS_DAYS}\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"⚠️ <b>FORCING EXIT OF ALL POSITIONS</b>"
            )
            self.bot.send_telegram(msg)

        self._route_global_exit("RMS_DAILY_MAX_LOSS")

        # 🔥 Immediately cancel all pending orders (don't wait for next heartbeat)
        self._cancel_pending_broker_orders()
        self._cancel_pending_system_entries()

        # ✅ FIX: only activate cooldown if days are truly consecutive
        if is_consecutive and consecutive_losses == self.MAX_CONSECUTIVE_LOSS_DAYS:
            logger.critical(
                "🚨 MAX CONSECUTIVE LOSS DAYS REACHED | activating cooldown until Monday"
            )
            self._activate_cooldown()

    # --------------------------------------------------
    # HEARTBEAT
    # --------------------------------------------------

    def heartbeat(self):
        with self._lock:
            try:
                # Get fresh positions and update PnL in one call
                positions = self._update_pnl()
                
                has_live_position = any(int(p.get("netqty", 0)) != 0 for p in positions)
                
                logger.debug(
                    "RMS: Heartbeat | pnl=%.2f | max_loss=%.2f | live_pos=%s | loss_hit=%s | positions=%d",
                    self.daily_pnl,
                    self.dynamic_max_loss,
                    has_live_position,
                    self.daily_loss_hit,
                    len(positions),
                )

                # Only check trailing/manual if we have positions
                if positions:
                    # Max loss breach check (BASE or TRAILING)
                    if (
                        has_live_position
                        and not self.daily_loss_hit
                        and self.daily_pnl <= self.dynamic_max_loss
                    ):
                        if self.highest_profit > 0:
                            logger.critical(
                                "🔴 TRAILING LOSS HIT | pnl=%.2f <= trail=%.2f | highest_profit=%.2f",
                                self.daily_pnl,
                                self.dynamic_max_loss,
                                self.highest_profit,
                            )
                        else:
                            logger.critical(
                                "🔴 BASE MAX LOSS HIT | pnl=%.2f <= max_loss=%.2f",
                                self.daily_pnl,
                                self.dynamic_max_loss,
                            )
                        self._handle_daily_loss_breach()

                    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    # POST-BREACH ENFORCEMENT (continuous flatten loop)
                    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    if self.daily_loss_hit:
                        all_flat = all(int(p.get("netqty", 0)) == 0 for p in positions)

                        if all_flat and not self.force_exit_in_progress:
                            # Truly done — cancel any lingering broker orders too
                            self._cancel_pending_broker_orders()
                            self._cancel_pending_system_entries()
                            logger.info("RMS: Post-breach — all positions flat, orders cleaned")
                        elif all_flat and self.force_exit_in_progress:
                            # Exit cycle complete, but stay vigilant
                            self.force_exit_in_progress = False
                            self._cancel_pending_broker_orders()
                            self._cancel_pending_system_entries()
                            logger.info("RMS: Exit cycle completed, all flat — staying in DAILY_LOSS_HIT mode")
                        else:
                            # STILL have live positions after breach → force exit again
                            live_count = sum(1 for p in positions if int(p.get("netqty", 0)) != 0)
                            logger.critical(
                                "🚨 RMS: POSITIONS EXIST AFTER BREACH | live=%d | re-triggering flatten",
                                live_count,
                            )
                            self._cancel_pending_broker_orders()
                            self._cancel_pending_system_entries()
                            if not self.force_exit_in_progress:
                                self.force_exit_in_progress = True
                                self.human_violation_detected = True
                                self._save_state()
                                self._route_global_exit("RMS_POST_BREACH_FLATTEN")
                                if self.bot.telegram_enabled:
                                    live_details = []
                                    for p in positions:
                                        nq = int(p.get("netqty", 0))
                                        if nq != 0:
                                            live_details.append(
                                                f"  • {p.get('exch', '?')}:{p.get('tsym', '?')} qty={nq}"
                                            )
                                    detail_text = "\n".join(live_details)
                                    self.bot.send_telegram(
                                        f"🚨 <b>POST-BREACH FLATTEN</b>\n\n"
                                        f"Positions detected after max loss hit:\n"
                                        f"{detail_text}\n\n"
                                        f"⚠️ Force-exiting ALL positions again"
                                    )
                else:
                    logger.debug("RMS: No positions in broker snapshot")

                # ALWAYS run these regardless of positions
                self._update_trailing_max_loss()
                self._check_warning_threshold()
                self.track_pnl_ohlc()
                self._save_state()  # Keep dashboard risk widget up-to-date
                self._send_periodic_status()
            except RuntimeError:
                # 🔥 FAIL-HARD: broker/session failure must kill process
                raise
            except Exception as exc:
                log_exception("SupremeRiskManager.heartbeat", exc)

    # --------------------------------------------------
    # BROKER ORDER / SYSTEM ENTRY CANCELLATION
    # --------------------------------------------------

    def _cancel_pending_broker_orders(self):
        """
        Cancel all OPEN/PENDING orders on the broker side.
        Called after breach to prevent any pending buy/sell from filling.
        """
        try:
            order_book = self.bot.api.get_order_book()
            if not order_book:
                return

            cancelled = 0
            for o in order_book:
                status = (o.get("status") or "").upper()
                if status in ("OPEN", "PENDING", "TRIGGER_PENDING", "SL-PENDING", "AFTER MARKET ORDER REQ RECEIVED"):
                    orderno = o.get("norenordno", "")
                    if orderno:
                        try:
                            self.bot.api.cancel_order(orderno)
                            cancelled += 1
                            logger.info(
                                "RMS: Cancelled broker order | orderno=%s | sym=%s | status=%s",
                                orderno, o.get("tsym", "?"), status,
                            )
                        except Exception as e:
                            logger.warning("RMS: Failed to cancel order %s: %s", orderno, e)

            if cancelled:
                logger.critical("🚨 RMS: Cancelled %d pending broker orders post-breach", cancelled)
                if self.bot.telegram_enabled:
                    self.bot.send_telegram(
                        f"🚨 <b>RISK: Cancelled {cancelled} pending broker orders</b>\n"
                        f"Daily loss hit — no new orders allowed"
                    )
        except Exception as e:
            logger.error("RMS: Error cancelling broker orders: %s", e)

    def _cancel_pending_system_entries(self):
        """
        Mark all CREATED (non-EXIT) system orders as FAILED in the DB.
        Prevents OrderWatcher from picking them up and executing them.
        """
        try:
            open_orders = self.bot.order_repo.get_open_orders()
            cancelled = 0
            for order in open_orders:
                # Only cancel ENTRY/ADJUST — never cancel EXIT orders
                if getattr(order, "tag", None) == "EXIT":
                    continue
                if getattr(order, "execution_type", "") == "EXIT":
                    continue
                try:
                    self.bot.order_repo.update_status(order.command_id, "FAILED")
                    self.bot.order_repo.update_tag(order.command_id, "RISK_BREACH_CANCELLED")
                    cancelled += 1
                    logger.info(
                        "RMS: Cancelled system order | cmd_id=%s | sym=%s",
                        order.command_id, getattr(order, "symbol", "?"),
                    )
                except Exception as e:
                    logger.warning("RMS: Failed to cancel system order %s: %s", order.command_id, e)

            if cancelled:
                logger.critical("🚨 RMS: Cancelled %d pending system entries post-breach", cancelled)
        except Exception as e:
            logger.error("RMS: Error cancelling system entries: %s", e)

    # --------------------------------------------------
    # TRAILING / PNL / ANALYTICS (UNCHANGED LOGIC)
    # --------------------------------------------------

    def _update_pnl(self):
        """Update PnL from fresh broker positions snapshot.
        
        🔒 CNC positions are EXCLUDED from daily PnL calculation.
        CNC is long-term holding and should NOT trigger intraday risk breaches.
        Only MIS and NRML contribute to daily_pnl.
        
        🛡️ BUG-12 FIX: If get_positions() returns empty but we previously
        had a non-zero PnL, preserve the last known PnL (session-failure guard).
        """
        self.bot._ensure_login()
        
        try:
            positions = self.bot.api.get_positions() or []
        except Exception as e:
            # API call failed entirely — preserve last known PnL
            logger.warning(
                "RMS: get_positions() FAILED (%s) — preserving last_known_pnl=%.2f",
                e,
                self.last_known_pnl if self.last_known_pnl is not None else 0.0,
            )
            return []  # Return empty so heartbeat skips breach checks while blind
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # BUG-12 FIX: Empty positions with prior PnL = suspected session failure.
        # Do NOT reset daily_pnl to 0.0 — that disables risk enforcement and
        # can cause false profit injection / trailing-stop confusion.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if not positions and self.last_known_pnl is not None and self.last_known_pnl != 0.0:
            logger.warning(
                "RMS: get_positions returned EMPTY but last_known_pnl=%.2f "
                "— preserving PnL (possible session/API issue)",
                self.last_known_pnl,
            )
            return []  # Return empty so heartbeat skips breach checks while blind
        
        total_rpnl = 0.0
        total_urmtom = 0.0
        position_count = 0
        live_position_count = 0
        
        for p in positions:
            try:
                # 🔒 Skip CNC positions — they don't affect intraday risk
                product = (p.get("prd") or "").upper()
                if product in ("CNC", "C"):
                    logger.debug(
                        "RMS: Skipping CNC position | symbol=%s | prd=%s",
                        p.get("tsym", "UNKNOWN"),
                        product,
                    )
                    continue

                rpnl = float(p.get("rpnl", 0))
                urmtom = float(p.get("urmtom", 0))
                netqty = int(p.get("netqty", 0))
                
                total_rpnl += rpnl
                total_urmtom += urmtom
                position_count += 1
                
                if netqty != 0:
                    live_position_count += 1
                    logger.debug(
                        "RMS: Live position | symbol=%s | qty=%d | rpnl=%.2f | urmtom=%.2f",
                        p.get("tsym", "UNKNOWN"),
                        netqty,
                        rpnl,
                        urmtom,
                    )
                elif rpnl != 0 or urmtom != 0:
                    logger.debug(
                        "RMS: Closed position | symbol=%s | rpnl=%.2f | urmtom=%.2f",
                        p.get("tsym", "UNKNOWN"),
                        rpnl,
                        urmtom,
                    )
            except Exception as e:
                logger.warning("RMS: Failed to parse position | error=%s", str(e))
                continue
        
        total = total_rpnl + total_urmtom
        pnl_change = total - self.daily_pnl if self.last_known_pnl is not None else 0.0
        
        logger.info(
            "RMS: PnL Update | total=%.2f (rpnl=%.2f + urmtom=%.2f) | change=%+.2f | positions=%d (live=%d)",
            total,
            total_rpnl,
            total_urmtom,
            pnl_change,
            position_count,
            live_position_count,
        )
        
        self.daily_pnl = total
        self.last_known_pnl = total
        
        return positions  # Return for reuse in heartbeat

    def _update_trailing_max_loss(self):
        if self.daily_pnl <= self.highest_profit:
            return
        
        old_profit = self.highest_profit
        old_max_loss = self.dynamic_max_loss
        
        self.highest_profit = self.daily_pnl
        steps = int(self.highest_profit // self.TRAIL_STEP)
        new_loss = self.BASE_MAX_LOSS + steps * self.TRAIL_STEP
        
        if new_loss > self.dynamic_max_loss:
            self.dynamic_max_loss = new_loss
            self.warning_sent = False
            self._save_state()
            
            logger.info(
                "📈 TRAILING STOP UPDATED | profit: %.2f→%.2f | max_loss: %.2f→%.2f | steps=%d",
                old_profit,
                self.highest_profit,
                old_max_loss,
                self.dynamic_max_loss,
                steps,
            )
            
            if self.bot.telegram_enabled:
                msg = (
                    f"📈 <b>Trailing Stop Updated</b>\n\n"
                    f"🎯 New Highest Profit: ₹{self.highest_profit:.2f}\n"
                    f"🔒 New Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
                    f"📊 Trail Steps: {steps}\n"
                    f"💰 Protected Profit: ₹{abs(self.dynamic_max_loss - self.BASE_MAX_LOSS):.2f}"
                )
                self.bot.send_telegram(msg)

    def _check_warning_threshold(self):
        if self.warning_sent or self.daily_loss_hit:
            return
        
        threshold_value = abs(self.dynamic_max_loss) * self.WARNING_THRESHOLD_PCT
        
        # ✅ FIX: Only trigger on losses, not profits
        if self.daily_pnl <= -threshold_value:
            self.warning_sent = True
            
            distance_to_exit = abs(self.daily_pnl - self.dynamic_max_loss)
            
            logger.warning(
                "⚠️ RISK WARNING | pnl=%.2f | threshold=%.2f | distance_to_exit=%.2f",
                self.daily_pnl,
                threshold_value,
                distance_to_exit,
            )
            
            if self.bot.telegram_enabled:
                msg = (
                    f"⚠️ <b>RISK WARNING</b>\n\n"
                    f"💔 Current PnL: ₹{self.daily_pnl:.2f}\n"
                    f"🔒 Max Loss Limit: ₹{self.dynamic_max_loss:.2f}\n"
                    f"📏 Distance to Exit: ₹{distance_to_exit:.2f}\n"
                    f"📊 Warning Threshold: {self.WARNING_THRESHOLD_PCT*100:.0f}%\n\n"
                    f"⚠️ Approaching exit threshold!"
                )
                self.bot.send_telegram(msg)

    def _activate_cooldown(self):
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        self.cooldown_until = today + timedelta(days=days_until_monday)

        logger.critical(
            "🚨 COOLDOWN ACTIVATED | consecutive_losses=%d | until=%s | days=%d",
            self.MAX_CONSECUTIVE_LOSS_DAYS,
            self.cooldown_until,
            days_until_monday,
        )

        if self.bot.telegram_enabled:
            msg = (
                f"🚨 <b>TRADING COOLDOWN ACTIVATED</b>\n\n"
                f"📉 Consecutive Loss Days: {self.MAX_CONSECUTIVE_LOSS_DAYS}\n"
                f"🔒 Trading Locked Until: {self.cooldown_until.strftime('%A, %B %d, %Y')}\n"
                f"📅 Days Until Resume: {days_until_monday}\n\n"
                f"⚠️ All trading blocked until next Monday"
            )
            self.bot.send_telegram(msg)

    # --------------------------------------------------
    # PNL OHLC / REPORTING (UNCHANGED)
    # --------------------------------------------------

    def track_pnl_ohlc(self):
        try:
            now = datetime.now()
            self._update_ohlc("1m", now.replace(second=0, microsecond=0), self.daily_pnl)
            self._update_ohlc(
                "5m",
                now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0),
                self.daily_pnl,
            )
            self._update_ohlc("1d", now.date(), self.daily_pnl)
            self._prune_old_ohlc()
        except Exception as exc:
            log_exception("track_pnl_ohlc", exc)

    def _update_ohlc(self, tf, key, pnl):
        store = self.pnl_ohlc[tf]
        candle = store.get(key)
        if not candle:
            store[key] = {
                "timestamp": key,
                "open": pnl,
                "high": pnl,
                "low": pnl,
                "close": pnl,
            }
        else:
            candle["high"] = max(candle["high"], pnl)
            candle["low"] = min(candle["low"], pnl)
            candle["close"] = pnl

    def _prune_old_ohlc(self):
        now = datetime.now()
        for tf, store in self.pnl_ohlc.items():
            cutoff = now - self.PNL_RETENTION[tf]
            for k in list(store.keys()):
                ts = store[k]["timestamp"]
                if isinstance(ts, date) and not isinstance(ts, datetime):
                    ts = datetime.combine(ts, datetime.min.time())
                if ts < cutoff:
                    del store[k]

    def _send_periodic_status(self):
        if not self.bot.telegram_enabled:
            return
        now = datetime.now()
        if self.last_status_update and (
            now - self.last_status_update
        ).total_seconds() < self.STATUS_UPDATE_INTERVAL * 60:
            return
        
        self.last_status_update = now
        
        distance_to_exit = abs(self.daily_pnl - self.dynamic_max_loss)
        protected_profit = abs(self.dynamic_max_loss - self.BASE_MAX_LOSS)
        
        status_icon = "🟢" if self.daily_pnl > 0 else "🔴" if self.daily_pnl < 0 else "⚪"
        
        msg = (
            f"🛡 <b>RMS STATUS UPDATE</b>\n\n"
            f"{status_icon} Current PnL: ₹{self.daily_pnl:.2f}\n"
            f"🔒 Max Loss Limit: ₹{self.dynamic_max_loss:.2f}\n"
            f"📏 Distance to Exit: ₹{distance_to_exit:.2f}\n"
            f"🎯 Highest Profit: ₹{self.highest_profit:.2f}\n"
            f"💰 Protected Profit: ₹{protected_profit:.2f}\n"
            f"📅 Date: {self.current_day.strftime('%d-%b-%Y')}\n"
            f"⏰ Time: {now.strftime('%H:%M:%S')}"
        )
        
        if self.daily_loss_hit:
            msg += f"\n\n🔴 <b>MAX LOSS HIT - TRADING BLOCKED</b>"
        elif self.cooldown_until:
            msg += f"\n\n⚠️ <b>COOLDOWN ACTIVE UNTIL {self.cooldown_until.strftime('%d-%b')}</b>"
        
        logger.info("RMS: Periodic status sent")
        self.bot.send_telegram(msg)

    def _reset_daily_state(self, new_day: date):
        logger.info(
            "🔄 DAILY RESET | old_date=%s | new_date=%s | final_pnl=%.2f",
            self.current_day,
            new_day,
            self.daily_pnl,
        )
        
        self.current_day = new_day
        self.daily_pnl = 0.0
        self.daily_loss_hit = False
        self.warning_sent = False
        self.force_exit_in_progress = False
        self.dynamic_max_loss = self.BASE_MAX_LOSS
        self.highest_profit = 0.0
        self.last_manual_position_signature = None
        self.last_manual_violation_ts = None
        self.human_violation_detected = False
        self.pnl_ohlc["1m"].clear()
        self.pnl_ohlc["5m"].clear()
        self._save_state()
        
        logger.info("✅ Daily state reset complete | max_loss=%.2f", self.BASE_MAX_LOSS)
        
        if self.bot.telegram_enabled:
            msg = (
                f"🔄 <b>NEW TRADING DAY</b>\n\n"
                f"📅 Date: {new_day.strftime('%A, %B %d, %Y')}\n"
                f"🔒 Base Max Loss: ₹{self.BASE_MAX_LOSS:.2f}\n"
                f"📊 Trail Step: ₹{self.TRAIL_STEP:.2f}\n\n"
                f"✅ RMS Ready"
            )
            self.bot.send_telegram(msg)

    def get_status(self) -> Dict:
        return {
            "date": str(self.current_day),
            "daily_pnl": self.daily_pnl,
            "daily_loss_hit": self.daily_loss_hit,
            "cooldown_until": str(self.cooldown_until) if self.cooldown_until else None,
        }