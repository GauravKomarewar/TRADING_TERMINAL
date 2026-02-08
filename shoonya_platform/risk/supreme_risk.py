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
        self.MANUAL_ALERT_COOLDOWN_SEC = 60

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
                "dynamic_max_loss": self.dynamic_max_loss,
                "highest_profit": self.highest_profit,
                "daily_loss_hit": self.daily_loss_hit,
                "human_violation_detected": self.human_violation_detected,
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
        self.failed_days.append(self.current_day)
        self.force_exit_in_progress = True
        consecutive_losses = len(self.failed_days)

        logger.critical(
            "🔴 DAILY MAX LOSS HIT | pnl=%.2f | max_loss=%.2f | consecutive_days=%d/%d",
            self.daily_pnl,
            self.dynamic_max_loss,
            consecutive_losses,
            self.MAX_CONSECUTIVE_LOSS_DAYS,
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

        if consecutive_losses == self.MAX_CONSECUTIVE_LOSS_DAYS:
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
                    # Trailing loss check
                    if (
                        has_live_position
                        and not self.daily_loss_hit
                        and self.highest_profit > 0
                        and self.daily_pnl < self.dynamic_max_loss
                    ):
                        logger.critical(
                            "🔴 TRAILING LOSS HIT | pnl=%.2f < trail=%.2f | highest_profit=%.2f",
                            self.daily_pnl,
                            self.dynamic_max_loss,
                            self.highest_profit,
                        )
                        self._handle_daily_loss_breach()

                    # Manual trade detection
                    self.on_broker_positions(positions)

                    # Exit completion check
                    if self.daily_loss_hit:
                        all_flat = all(int(p.get("netqty", 0)) == 0 for p in positions)

                        if all_flat:
                            self.force_exit_in_progress = False
                            logger.info("RMS: Exit cycle fully completed, all positions flat")
                        else:
                            live_count = sum(1 for p in positions if int(p.get("netqty", 0)) != 0)
                            logger.warning(
                                "RMS: Exit in progress, waiting for positions to flatten | live_positions=%d",
                                live_count,
                            )
                else:
                    logger.debug("RMS: No positions in broker snapshot")

                # ALWAYS run these regardless of positions
                self._update_trailing_max_loss()
                self._check_warning_threshold()
                self.track_pnl_ohlc()
                self._send_periodic_status()
            except RuntimeError:
                # 🔥 FAIL-HARD: broker/session failure must kill process
                raise
            except Exception as exc:
                log_exception("SupremeRiskManager.heartbeat", exc)

    # --------------------------------------------------
    # MANUAL TRADE DETECTION
    # --------------------------------------------------

    def on_broker_positions(self, positions: list):
        if not self.daily_loss_hit:
            return

        # 🔒 CRITICAL FIX: prevent re-trigger during exit execution
        if self.force_exit_in_progress:
            logger.debug("RMS: Manual detection skipped (exit in progress)")
            return
            
        live_positions = tuple(
            (p.get("exch"), p.get("tsym"), int(p.get("netqty", 0)))
            for p in positions
            if int(p.get("netqty", 0)) != 0
        )

        if not live_positions:
            logger.debug("RMS: No live positions detected")
            return

        now = datetime.now()
        if (
            live_positions != self.last_manual_position_signature
            and (
                self.last_manual_violation_ts is None
                or (now - self.last_manual_violation_ts).total_seconds()
                >= self.MANUAL_ALERT_COOLDOWN_SEC
            )
        ):
            self.last_manual_position_signature = live_positions
            self.last_manual_violation_ts = now
            self.human_violation_detected = True
            self._save_state()

            position_details = "\n".join(
                [f"  • {exch}:{sym} qty={qty}" for exch, sym, qty in live_positions]
            )

            logger.critical(
                "🚨 MANUAL TRADE AFTER RISK HIT | positions=%d\n%s",
                len(live_positions),
                position_details,
            )

            if self.bot.telegram_enabled:
                msg = (
                    f"🚨 <b>CRITICAL RISK VIOLATION</b>\n\n"
                    f"⚠️ Manual trade detected AFTER max loss hit\n"
                    f"📊 Live Positions: {len(live_positions)}\n\n"
                    f"<b>Positions:</b>\n{position_details}\n\n"
                    f"⏰ Time: {now.strftime('%H:%M:%S')}\n"
                    f"💔 Current PnL: ₹{self.daily_pnl:.2f}\n\n"
                    f"🔒 <b>FORCING EXIT AGAIN</b>"
                )
                self.bot.send_telegram(msg)

            self.force_exit_in_progress = True
            self._route_global_exit("RMS_MANUAL_TRADE")

    # --------------------------------------------------
    # TRAILING / PNL / ANALYTICS (UNCHANGED LOGIC)
    # --------------------------------------------------

    def _update_pnl(self):
        """Update PnL from fresh broker positions snapshot"""
        self.bot._ensure_login()
        positions = self.bot.api.get_positions() or []
        
        total_rpnl = 0.0
        total_urmtom = 0.0
        position_count = 0
        live_position_count = 0
        
        for p in positions:
            try:
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
        
        if abs(self.daily_pnl) >= threshold_value:
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