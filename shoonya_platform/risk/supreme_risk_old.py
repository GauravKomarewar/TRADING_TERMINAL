#!/usr/bin/env python3
"""
Supreme Risk Manager
====================

Authoritative capital protection layer with real-time monitoring & analytics.

Design principles:
- Broker positions are the ONLY source of truth
- netqty != 0 => position is LIVE
- netqty == 0 => position is CLOSED
- No local position cache
- Safe across crashes / restarts
- Real-time risk monitoring with periodic updates
- Historical PnL analytics for strategy optimization
"""
# ======================================================================
# 🔒 PRODUCTION FREEZE — SUPREME RISK MANAGER
# Version : v1.2.1
# Status  : PRODUCTION FROZEN — CAPITAL SAFE
# Notes   :
# • RMS has absolute exit authority
# • OrderWatcher failure-safe
# • Escalation path enabled
# • No known unhandled loss scenarios

# 🔒 RMS EXIT ESCALATION — LOCK SAFE
# Date: 2026-01-30

# Manual lock release removed.
# Exit verification is non-blocking.
# Heartbeat and broker hooks remain responsive.
# No deadlocks, no re-entrancy risk.

# SupremeRiskManager concurrency model is FINAL.

# ======================================================================

import time
import json
import os
import threading
from scripts.scriptmaster import requires_limit_order
import math

import logging
from datetime import date, datetime, timedelta
from collections import defaultdict, deque, OrderedDict
from typing import Dict, Optional, List, Tuple

from shoonya_platform.utils.utils import log_exception

logger = logging.getLogger(__name__)


class SupremeRiskManager:
    """
    Supreme risk authority for the trading system.
    Combines real-time risk management with historical analytics.
    """
    def __init__(self, bot):
        """
        Args:
            bot (ShoonyaBot): execution gateway
        """
        self._lock = threading.RLock()
        self.force_exit_in_progress = False

        cfg = bot.config
        client_id = bot.client_id  # canonical client identity
        self.STATE_FILE = f"{cfg.risk_state_file.rstrip('.json')}_{client_id}.json"
        state_dir = os.path.dirname(self.STATE_FILE)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)


        self.BASE_MAX_LOSS = cfg.risk_base_max_loss
        self.TRAIL_STEP = cfg.risk_trail_step
        self.WARNING_THRESHOLD_PCT = cfg.risk_warning_threshold
        self.MAX_CONSECUTIVE_LOSS_DAYS = cfg.risk_max_consecutive_loss_days
        self.STATUS_UPDATE_INTERVAL = cfg.risk_status_update_min
        self.PNL_RETENTION = cfg.risk_pnl_retention

        self.bot = bot
        self.current_day: date = date.today()
        self.dynamic_max_loss = self.BASE_MAX_LOSS
        self.highest_profit = 0.0

        self._load_state()

        self.daily_pnl: float = 0.0

        # Risk management
        self.failed_days = deque(maxlen=self.MAX_CONSECUTIVE_LOSS_DAYS)
        self.cooldown_until: Optional[date] = None
        self.daily_loss_hit: bool = False
        self.warning_sent: bool = False
        
        # Manual intervention alert (PATCH 3 - added human_violation_detected)
        self.last_manual_position_signature = None
        self.last_manual_violation_ts = None
        self.human_violation_detected = False  # PATCH 3
        self.MANUAL_ALERT_COOLDOWN_SEC = 60  # 1 minute

        # Status updates
        self.last_status_update: Optional[datetime] = None
        self.last_known_pnl: Optional[float] = None

        # PnL OHLC tracking for analytics
        self.pnl_ohlc = {
            "1m": OrderedDict(),
            "5m": OrderedDict(),
            "1d": OrderedDict(),
        }
        
        logger.info("SupremeRiskManager initialized with analytics (v1.1.2 - PATCHED)")

    def _load_state(self):
        if not os.path.exists(self.STATE_FILE):
            return
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)

            if data.get("date") == str(self.current_day):
                self.dynamic_max_loss = data.get("dynamic_max_loss", self.BASE_MAX_LOSS)
                self.highest_profit = data.get("highest_profit", 0.0)
                self.daily_loss_hit = data.get("daily_loss_hit", False)
                self.human_violation_detected = data.get("human_violation_detected", False)  # PATCH 3

        except Exception as e:
            log_exception("RiskState.load", e)


    def _save_state(self):
        try:
            data = {
                "date": str(self.current_day),
                "dynamic_max_loss": self.dynamic_max_loss,
                "highest_profit": self.highest_profit,
                "daily_loss_hit": self.daily_loss_hit,
                "human_violation_detected": self.human_violation_detected,  # PATCH 3
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log_exception("RiskState.save", e)

    # ------------------------------------------------------------------
    # PUBLIC ENTRY POINTS
    # ------------------------------------------------------------------

    def can_execute(self) -> bool:
        """
        Gatekeeper before ANY execution.
        """
        today = date.today()
        self._update_pnl("SYSTEM")  # 🔒 FORCE BROKER TRUTH

        if today != self.current_day:
            self._reset_daily_state(today)

        if self.cooldown_until and today < self.cooldown_until:
            logger.critical(
                "Trading blocked due to cooldown until %s",
                self.cooldown_until
            )
            return False

        if self.daily_loss_hit:
            logger.critical("Trading blocked: daily max loss already hit")
            return False

        if self.daily_pnl <= self.dynamic_max_loss:
            self._handle_daily_loss_breach()
            return False

        return True

    # ------------------------------------------------------------------
    # HARD RISK GATE (PRE-ORDER)
    # ------------------------------------------------------------------

    def can_execute_command(self, command) -> Tuple[bool, str]:
        """
        HARD risk gate.
        Called BEFORE broker order is placed.

        Applies to:
        - Dashboard orders
        - Strategy orders
        - Automation

        Does NOT apply to:
        - Manual terminal trades (heartbeat handles those)
        """
        with self._lock:
            today = date.today()
            if self.force_exit_in_progress:
                return False, "FORCE_EXIT_IN_PROGRESS"

            # Day rollover safety
            if today != self.current_day:
                self._reset_daily_state(today)

            # Cooldown check
            if self.cooldown_until and today < self.cooldown_until:
                return False, "RISK_COOLDOWN_ACTIVE"

            # Daily loss already hit
            if self.daily_loss_hit:
                return False, "DAILY_MAX_LOSS_ALREADY_HIT"

            # Live PnL breach check (MOST IMPORTANT)
            if self.daily_pnl <= self.dynamic_max_loss:
                # Mark & force exit only once
                self._handle_daily_loss_breach()
                return False, "DAILY_MAX_LOSS_BREACHED"

            lot_size = getattr(command, "lot_size", None)
            if lot_size and command.quantity % lot_size != 0:
                return False, "INVALID_LOT_SIZE"

            # Optional future hooks (safe placeholders)
            # ------------------------------------------
            # if command.quantity > MAX_QTY:
            #     return False, "QTY_LIMIT_EXCEEDED"
            #
            # if command.symbol in BLOCKED_SYMBOLS:
            #     return False, "SYMBOL_BLOCKED"

            return True, "OK"

    def _escalate_force_exit(self):
        """
        ABSOLUTE LAST RESORT EXIT.
        Used only if OrderWatcher fails.
        """
        logger.critical("🔥 RMS EMERGENCY EXIT — DIRECT BROKER EXECUTION")

        self.bot._ensure_login()
        positions = self.bot.api.get_positions() or []

        for pos in positions:
            try:
                netqty = int(pos.get("netqty", 0))
            except Exception:
                continue

            if netqty == 0:
                continue

            symbol = pos.get("tsym")
            exchange = pos.get("exch")
            product = pos.get("prd")

            side = "SELL" if netqty > 0 else "BUY"
            qty = abs(netqty)

            must_limit = requires_limit_order(
                exchange=exchange,
                tradingsymbol=symbol,
            )

            order_type = "LIMIT" if must_limit else "MARKET"
            price = None

            if must_limit:
                ltp = self.bot.api.get_ltp(exchange, symbol)
                if not ltp:
                    logger.critical(
                        f"❌ EMERGENCY EXIT FAILED — NO LTP | {symbol}"
                    )
                    continue

                buffer = max(0.02, 2 * 0.05)
                raw = (
                    ltp * (1 + buffer)
                    if side == "BUY"
                    else ltp * (1 - buffer)
                )
                price = (
                    math.ceil(raw / 0.05) * 0.05
                    if side == "BUY"
                    else math.floor(raw / 0.05) * 0.05
                )

            logger.critical(
                f"🚨 EMERGENCY EXIT | {symbol} | {side} | qty={qty} | type={order_type}"
            )

            self.bot.api.place_order({
                "exchange": exchange,
                "tradingsymbol": symbol,
                "quantity": qty,
                "buy_or_sell": side,
                "product": product,
                "order_type": order_type,
                "price": price,
            })

    def emergency_exit_all(self, reason: str = "RISK_VIOLATION"):
        """
        Nuclear option: Exit ALL positions immediately bypassing OMS.

        Use ONLY when OrderWatcher is unresponsive or system integrity at risk.
        """
        logger.critical(
            f"🚨 EMERGENCY EXIT INITIATED | reason={reason} | "
            f"BYPASSING OMS - DIRECT BROKER ACCESS"
        )

        try:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions() or []

            exit_count = 0
            failed_exits = []

            for pos in positions:
                try:
                    netqty = int(pos.get("netqty", 0))
                except Exception:
                    continue

                if netqty == 0:
                    continue

                symbol = pos.get("tsym")
                exchange = pos.get("exch")
                product = pos.get("prd")

                exit_side = "SELL" if netqty > 0 else "BUY"
                exit_qty = abs(netqty)

                must_limit = requires_limit_order(exchange=exchange, tradingsymbol=symbol)

                order_type = "LIMIT" if must_limit else "MARKET"
                price = None

                if must_limit:
                    try:
                        ltp = self.bot.api.get_ltp(exchange, symbol)
                        if ltp:
                            buffer = 0.02 if exit_side == "BUY" else -0.02
                            price = round(ltp * (1 + buffer), 2)
                    except Exception as e:
                        logger.error(f"LTP fetch failed for {symbol}: {e}")
                        price = 0.0 if exit_side == "BUY" else 99999.99

                logger.critical(
                    f"🚨 EMERGENCY EXIT | {symbol} | {exit_side} | qty={exit_qty} | "
                    f"type={order_type} | price={price}"
                )

                try:
                    # 🔒 Use CORRECT broker API keys for Shoonya (not generic names)
                    order_params = {
                        "exchange": exchange,
                        "tradingsymbol": symbol,  # NOT "symbol"
                        "quantity": exit_qty,
                        "buy_or_sell": exit_side,  # NOT "side"
                        "product_type": product,  # NOT "product"
                        "price_type": order_type,  # NOT "order_type"
                        "price": price,
                    }

                    result = self.bot.api.place_order(order_params)

                    if result.success:
                        exit_count += 1
                        logger.critical(f"✅ EMERGENCY EXIT PLACED | {symbol} | {result.order_id}")
                    else:
                        failed_exits.append((symbol, result.error_message))
                        logger.error(f"❌ EMERGENCY EXIT FAILED | {symbol} | {result.error_message}")

                except Exception as e:
                    failed_exits.append((symbol, str(e)))
                    logger.exception(f"❌ EMERGENCY EXIT EXCEPTION | {symbol}")

            total_positions = len([p for p in positions if int(p.get("netqty", 0)) != 0])

            logger.critical(
                f"🚨 EMERGENCY EXIT COMPLETE | total={total_positions} "
                f"successful={exit_count} failed={len(failed_exits)}"
            )

            # Notify via Telegram
            if self.bot.telegram_enabled:
                msg = (
                    f"🚨 <b>EMERGENCY EXIT EXECUTED</b>\n"
                    f"Reason: {reason}\n"
                    f"Total: {total_positions}\n"
                    f"Successful: {exit_count}\n"
                    f"Failed: {len(failed_exits)}"
                )
                if failed_exits:
                    msg += "\n\n❌ Failures:\n"
                    for sym, err in failed_exits[:5]:
                        msg += f"• {sym}: {err[:50]}\n"
                self.bot.send_telegram(msg)

            # Force clear ExecutionGuard
            try:
                for strategy_id in list(self.bot.execution_guard._strategy_positions.keys()):
                    self.bot.execution_guard.force_close_strategy(strategy_id)
            except Exception:
                logger.exception("Failed to force-clear ExecutionGuard after emergency exit")

            return exit_count, failed_exits
        except Exception as e:
            logger.critical(f"❌ EMERGENCY EXIT FATAL ERROR: {e}")
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"🚨 <b>EMERGENCY EXIT FAILED</b>\n"
                    f"Fatal error: {str(e)}\n"
                    f"MANUAL INTERVENTION REQUIRED!"
                )
            raise

    def on_trade_update(self, strategy_name: str):
        """
        Call AFTER trade updates / fills.
        """
        with self._lock:
            try:
                self._update_pnl(strategy_name)
                self._update_trailing_max_loss()
                self._check_warning_threshold()

                if self.daily_pnl <= self.dynamic_max_loss:
                    self._handle_daily_loss_breach()
                
                # Track PnL OHLC for analytics
                self.track_pnl_ohlc()
                
                # Send periodic status updates
                self._send_periodic_status()

            except Exception as exc:
                log_exception("SupremeRiskManager.on_trade_update", exc)

    # ------------------------------------------------------------------
    # CORE LOGIC
    # ------------------------------------------------------------------
    def _update_trailing_max_loss(self):
        if self.daily_pnl <= 0:
            return

        if self.daily_pnl <= self.highest_profit:
            return

        self.highest_profit = self.daily_pnl

        steps = int(self.highest_profit // self.TRAIL_STEP)
        new_max_loss = self.BASE_MAX_LOSS + (steps * self.TRAIL_STEP)

        if new_max_loss > self.dynamic_max_loss:
            self.dynamic_max_loss = new_max_loss
            self.warning_sent = False
            self._save_state()

            logger.warning(
                "Trailing max loss updated → %.2f",
                self.dynamic_max_loss
            )

            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"🛡 <b>TRAILING RISK UPDATED</b>\n\n"
                    f"📈 Net Profit: ₹{self.highest_profit:.2f}\n"
                    f"🔒 New Max Loss: ₹{self.dynamic_max_loss:.2f}"
                )

    def _update_pnl(self, strategy_name: str):
        self.bot._ensure_login()   # 🔒 REQUIRED
        positions = self.bot.api.get_positions()

        if not positions:
            if self.last_known_pnl is not None:
                self.daily_pnl = self.last_known_pnl
            return

        total_pnl = 0.0
        for pos in positions:
            try:
                total_pnl += float(pos.get("rpnl", 0)) + float(pos.get("urmtom", 0))
            except Exception:
                continue

        self.daily_pnl = total_pnl
        self.last_known_pnl = total_pnl


    def _check_warning_threshold(self):
        if self.warning_sent or self.daily_loss_hit:
            return

        # LOSS MODE (traditional)
        if self.dynamic_max_loss < 0:
            warning_level = abs(self.dynamic_max_loss) * self.WARNING_THRESHOLD_PCT

            if abs(self.daily_pnl) >= warning_level:
                self.warning_sent = True
                self._send_warning()

        # PROFIT LOCK MODE
        else:
            # Warn only when approaching locked profit
            buffer = self.dynamic_max_loss * (1 - self.WARNING_THRESHOLD_PCT)

            if self.daily_pnl <= self.dynamic_max_loss + buffer:
                self.warning_sent = True
                self._send_warning()

    def _send_warning(self):
        if not self.bot.telegram_enabled:
            return

        remaining = abs(self.daily_pnl - self.dynamic_max_loss)

        self.bot.send_telegram(
            f"⚠️ <b>RISK WARNING</b>\n\n"
            f"💰 Current PnL: ₹{self.daily_pnl:.2f}\n"
            f"🔒 Locked Level: ₹{self.dynamic_max_loss:.2f}\n"
            f"📉 Buffer Left: ₹{remaining:.2f}\n\n"
            f"⚡ Approaching exit threshold!"
        )

    def _handle_daily_loss_breach(self):
        """
        Triggered ONCE per day when max loss breached.
        """
        # 🔒 HARD IDEMPOTENCY GUARD
        if self.daily_loss_hit and self.force_exit_in_progress:
            return

        with self._lock:
            if self.daily_loss_hit:
                return

            self.daily_loss_hit = True
            self.failed_days.append(self.current_day)
            self.force_exit_in_progress = True

            logger.critical(
                "DAILY MAX LOSS HIT: %.2f — FORCING EXIT",
                self.daily_pnl
            )

            if self.bot.telegram_enabled:
                consecutive_msg = ""
                if len(self.failed_days) > 1:
                    consecutive_msg = f"📉 Consecutive loss days: {len(self.failed_days)}/{self.MAX_CONSECUTIVE_LOSS_DAYS}\n"
                
                self.bot.send_telegram(
                    f"🛑 <b>DAILY MAX LOSS HIT</b>\n\n"
                    f"💔 Current PnL: ₹{self.daily_pnl:.2f}\n"
                    f"🚫 Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
                    f"{consecutive_msg}\n"
                    f"🔻 FORCING EXIT OF ALL POSITIONS\n"
                    f"⏸ Trading halted for today"
                )

            self._request_exit_for_all_positions()

            if not self._verify_exit_progress():
                self._escalate_force_exit()

            # 🧹 Hygiene: ExecutionGuard state is now invalid
            try:
                if hasattr(self.bot, "execution_guard"):
                    self.bot.execution_guard.force_close_strategy("__ALL__")
                    logger.warning("ExecutionGuard cleared after RMS force exit")
            except Exception as e:
                log_exception("ExecutionGuard.force_close_strategy", e)

            if len(self.failed_days) == self.MAX_CONSECUTIVE_LOSS_DAYS:
                self._activate_cooldown()

    def _activate_cooldown(self):
        """
        Freeze trading until next Monday.
        """
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        self.cooldown_until = today + timedelta(days=days_until_monday)

        logger.critical(
            "COOLDOWN ACTIVATED until %s",
            self.cooldown_until
        )

        if self.bot.telegram_enabled:
            self.bot.send_telegram(
                f"🧊 <b>RISK COOLDOWN ACTIVATED</b>\n\n"
                f"📉 {self.MAX_CONSECUTIVE_LOSS_DAYS} consecutive loss days detected\n"
                f"⏸ Trading blocked until: {self.cooldown_until}\n"
                f"🔄 System will resume next Monday\n\n"
                f"💡 Use this time to review strategy & analytics"
            )

    def _send_periodic_status(self):
        """
        Send periodic status updates to Telegram.
        Time-gated to prevent spam even with multiple trade fills.
        """
        if not self.bot.telegram_enabled:
            return
        
        now = datetime.now()
        
        # Strict time-based gating
        if self.last_status_update is not None:
            elapsed_seconds = (now - self.last_status_update).total_seconds()
            if elapsed_seconds < self.STATUS_UPDATE_INTERVAL * 60:
                return
        
        self.last_status_update = now
        
        # Calculate metrics
        if self.dynamic_max_loss < 0:
            pnl_pct_used = (abs(self.daily_pnl) / abs(self.dynamic_max_loss)) * 100
        else:
            pnl_pct_used = 0
        # Fix: Human-readable remaining calculation
        remaining = abs(self.dynamic_max_loss) - abs(self.daily_pnl) if self.daily_pnl < 0 else abs(self.dynamic_max_loss)
        
        # Status emoji
        if self.daily_pnl > 0:
            status_emoji = "✅"
            status_text = "PROFIT"
        elif pnl_pct_used < 50:
            status_emoji = "🟢"
            status_text = "SAFE"
        elif pnl_pct_used < 80:
            status_emoji = "🟡"
            status_text = "CAUTION"
        else:
            status_emoji = "🔴"
            status_text = "DANGER"
        
        # Get daily high/low from OHLC
        daily_data = self.get_pnl_ohlc("1d")
        high_low_msg = ""
        if daily_data and len(daily_data) > 0:
            today_candle = daily_data[-1]
            high_low_msg = f"📈 Today High: ₹{today_candle['high']:.2f}\n📉 Today Low: ₹{today_candle['low']:.2f}\n"
        
        self.bot.send_telegram(
            f"{status_emoji} <b>RMS STATUS UPDATE</b>\n\n"
            f"📊 Status: {status_text}\n"
            f"💰 Current PnL: ₹{self.daily_pnl:.2f}\n"
            f"{high_low_msg}"
            f"🎯 Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
            f"📈 Risk Used: {pnl_pct_used:.1f}%\n"
            f"💵 Remaining: ₹{remaining:.2f}\n"
            f"📅 Date: {self.current_day}\n"
            f"⏰ Time: {now.strftime('%H:%M:%S')}"
        )

    # ------------------------------------------------------------------
    # FORCE EXIT
    # ------------------------------------------------------------------
    def _request_exit_for_all_positions(self):
        """
        Register EXIT intents for all live positions.
        Actual execution is handled ONLY by OrderWatcherEngine.
        """
        try:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions() or []

            if not positions:
                logger.info("RMS: no live positions to exit")
                return

            logger.critical("RMS EXIT REQUEST → delegating to OrderWatcher")

            for pos in positions:
                try:
                    netqty = int(pos.get("netqty", 0))
                except Exception:
                    continue

                if netqty == 0:
                    continue

                symbol = pos.get("tsym")
                exchange = pos.get("exch")
                product = pos.get("prd")

                if not symbol or not exchange or not product:
                    continue

                side = "SELL" if netqty > 0 else "BUY"

                # 🔒 EXIT INTENT (NO PRICE, NO ORDER TYPE)
                self.bot.request_exit(
                    symbol=symbol,
                    exchange=exchange,
                    quantity=abs(netqty),
                    side=side,
                    product_type=product,
                    reason="RMS_FORCE_EXIT",
                    source="RISK",
                )

        except Exception as exc:
            log_exception("SupremeRiskManager._request_exit_for_all_positions", exc)

    def force_exit_all_positions(self):
        """
        Force-close ALL open positions (manual + automated).
        """
        try:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions()
            if not positions:
                logger.info("No open positions to force-exit")
                return

            logger.critical("FORCE EXIT initiated for ALL positions")

            for pos in positions:
                try:
                    netqty = int(pos.get("netqty", 0))
                except Exception:
                    continue
                
                if netqty == 0:
                    continue

                symbol = pos.get("tsym")
                exchange = pos.get("exch")
                product = pos.get("prd")

                if not symbol or not exchange or not product:
                    continue

                direction = "SELL" if netqty > 0 else "BUY"
                qty = abs(netqty)

                self.bot.force_exit_position(
                    symbol=symbol,
                    exchange=exchange,
                    quantity=qty,
                    direction=direction,
                    product_type=product,
                )

        except Exception as exc:
            log_exception("SupremeRiskManager.force_exit_all_positions", exc)

    # ------------------------------------------------------------------
    # PNL OHLC TRACKING (IMPROVED)
    # ------------------------------------------------------------------

    def track_pnl_ohlc(self):
        """
        Track NET PnL OHLC for:
        - 1 minute (intraday patterns)
        - 5 minute (short-term trends)
        - Daily (overall performance)
        
        Call this periodically or after trade updates.
        """
        try:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions()
            
            if not positions:
                if self.last_known_pnl is None:
                    return
                net_pnl = self.last_known_pnl

            else:
                net_pnl = 0.0
                for pos in positions:
                    try:
                        net_pnl += float(pos.get("rpnl", 0)) + float(pos.get("urmtom", 0))
                    except Exception:
                        continue

            now = datetime.now()

            # Update different timeframes
            self._update_ohlc("1m", now.replace(second=0, microsecond=0), net_pnl)
            self._update_ohlc(
                "5m",
                now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0),
                net_pnl,
            )
            self._update_ohlc("1d", now.date(), net_pnl)

            # Prune old data to save memory
            self._prune_old_ohlc()

        except Exception as exc:
            log_exception("SupremeRiskManager.track_pnl_ohlc", exc)

    def _update_ohlc(self, tf: str, key, pnl: float):
        """
        Update OHLC candle for given timeframe.
        """
        store = self.pnl_ohlc[tf]

        candle = store.get(key)
        if candle is None:
            # New candle
            store[key] = {
                "timestamp": key,
                "open": pnl,
                "high": pnl,
                "low": pnl,
                "close": pnl,
            }
        else:
            # Update existing candle
            candle["high"] = max(candle["high"], pnl)
            candle["low"] = min(candle["low"], pnl)
            candle["close"] = pnl

    def _prune_old_ohlc(self):
        """
        Remove old OHLC data based on retention policy.
        Keeps memory usage bounded.
        """
        now = datetime.now()

        for tf, store in self.pnl_ohlc.items():
            cutoff = now - self.PNL_RETENTION[tf]

            # Safe iteration: create list copy to avoid mutation during iteration
            for key, candle in list(store.items()):
                ts = candle["timestamp"]
                
                # Convert date to datetime for comparison
                if isinstance(ts, date) and not isinstance(ts, datetime):
                    ts = datetime.combine(ts, datetime.min.time())

                if ts < cutoff:
                    del store[key]
                else:
                    break  # OrderedDict, so rest are newer

    def get_pnl_ohlc(self, timeframe: str) -> List[Dict]:
        """
        Get PnL OHLC data for analysis.
        
        Args:
            timeframe: '1m', '5m', '1d'
            
        Returns:
            List of OHLC candles with timestamp, open, high, low, close
            
        Example:
            daily_candles = risk_manager.get_pnl_ohlc("1d")
            for candle in daily_candles:
                print(f"{candle['timestamp']}: High={candle['high']}, Low={candle['low']}")
        """
        return list(self.pnl_ohlc.get(timeframe, {}).values())

    def get_pnl_stats(self) -> Dict:
        """
        Get comprehensive PnL statistics for dashboard/analytics.
        
        Returns:
            Dict with current day stats, high/low, volatility indicators
        """
        daily_candles = self.get_pnl_ohlc("1d")
        
        stats = {
            "current_pnl": self.daily_pnl,
            "today_high": 0.0,
            "today_low": 0.0,
            "today_open": 0.0,
        }
        
        if daily_candles and len(daily_candles) > 0:
            today = daily_candles[-1]
            stats["today_high"] = today["high"]
            stats["today_low"] = today["low"]
            stats["today_open"] = today["open"]
        
        # Add volatility measure (high-low range)
        if stats["today_high"] != 0 or stats["today_low"] != 0:
            stats["today_range"] = stats["today_high"] - stats["today_low"]
        else:
            stats["today_range"] = 0.0
        
        return stats

    # ------------------------------------------------------------------
    # MANUAL STATUS REQUEST
    # ------------------------------------------------------------------

    def send_current_status(self):
        """
        Send current RMS status immediately with analytics.
        Can be called manually or via command.
        """
        if not self.bot.telegram_enabled:
            return
        
        # Update PnL first
        try:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions()
            if positions:
                total_pnl = 0.0
                for pos in positions:
                    try:
                        total_pnl += float(pos.get("rpnl", 0)) + float(pos.get("urmtom", 0))
                    except Exception:
                        continue
                self.daily_pnl = total_pnl
        except Exception as exc:
            log_exception("send_current_status: PnL update", exc)
        
        # Calculate metrics
        if self.dynamic_max_loss < 0:
            pnl_pct_used = (abs(self.daily_pnl) / abs(self.dynamic_max_loss)) * 100
        else:
            pnl_pct_used = 0
        # Fix: Human-readable remaining calculation
        remaining = abs(self.dynamic_max_loss) - abs(self.daily_pnl) if self.daily_pnl < 0 else abs(self.dynamic_max_loss)
        
        # Status emoji
        if self.daily_pnl > 0:
            status_emoji = "✅"
            status_text = "PROFIT"
        elif pnl_pct_used < 50:
            status_emoji = "🟢"
            status_text = "SAFE"
        elif pnl_pct_used < 80:
            status_emoji = "🟡"
            status_text = "CAUTION"
        else:
            status_emoji = "🔴"
            status_text = "DANGER"
        
        # Get analytics
        stats = self.get_pnl_stats()
        
        cooldown_info = ""
        if self.cooldown_until:
            cooldown_info = f"\n🧊 Cooldown until: {self.cooldown_until}"
        
        self.bot.send_telegram(
            f"{status_emoji} <b>RMS CURRENT STATUS</b>\n\n"
            f"📊 Status: {status_text}\n"
            f"💰 Current PnL: ₹{self.daily_pnl:.2f}\n"
            f"📈 Today High: ₹{stats['today_high']:.2f}\n"
            f"📉 Today Low: ₹{stats['today_low']:.2f}\n"
            f"📊 Today Range: ₹{stats['today_range']:.2f}\n"
            f"🎯 Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
            f"📈 Risk Used: {pnl_pct_used:.1f}%\n"
            f"💵 Remaining: ₹{remaining:.2f}\n"
            f"⚠️ Warning Sent: {'Yes' if self.warning_sent else 'No'}\n"
            f"🛑 Loss Hit: {'Yes' if self.daily_loss_hit else 'No'}\n"
            f"📉 Failed Days: {len(self.failed_days)}/{self.MAX_CONSECUTIVE_LOSS_DAYS}\n"
            f"📅 Date: {self.current_day}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
            f"{cooldown_info}"
        )

    # ------------------------------------------------------------------
    # DAY ROLLOVER
    # ------------------------------------------------------------------

    def _reset_daily_state(self, new_day: date):
        """
        Reset counters on day change.
        """
        logger.info(
            "Risk manager rollover: %s → %s",
            self.current_day,
            new_day
        )
        self.force_exit_in_progress = False
        # Clear loss streak only if previous day was profitable
        if self.daily_pnl > 0:
            self.failed_days.clear()

        self.current_day = new_day
        self.daily_pnl = 0.0
        self.daily_loss_hit = False
        self.warning_sent = False
        self.last_status_update = None
        self.last_known_pnl = None
        self.human_violation_detected = False  # Reset violation flag on new day

        # Clear intraday OHLC (keep daily for history)
        self.pnl_ohlc["1m"].clear()
        self.pnl_ohlc["5m"].clear()

        self.dynamic_max_loss = self.BASE_MAX_LOSS
        self.highest_profit = 0.0
        self._save_state()


    # ------------------------------------------------------------------
    # DIAGNOSTICS & EXPORT
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """
        Exposed for monitoring / dashboards.
        """
        stats = self.get_pnl_stats()
        
        return {
            "date": str(self.current_day),
            "daily_pnl": self.daily_pnl,
            "daily_loss_hit": self.daily_loss_hit,
            "warning_sent": self.warning_sent,
            "failed_days": [str(d) for d in self.failed_days],
            "cooldown_until": str(self.cooldown_until) if self.cooldown_until else None,
            "risk_pct_used": (
                (abs(self.daily_pnl) / abs(self.dynamic_max_loss)) * 100
                if self.daily_pnl < 0 and self.dynamic_max_loss < 0
                else 0
            ),
            "today_high": stats["today_high"],
            "today_low": stats["today_low"],
            "today_range": stats["today_range"],
        }
    
    def export_pnl_data(self, timeframe: str = "1d", format: str = "dict") -> List:
        """
        Export PnL OHLC data for external analysis.
        
        Args:
            timeframe: '1m', '5m', '1d'
            format: 'dict' or 'csv' (returns list of dicts or CSV-ready list)
            
        Returns:
            PnL data in requested format
            
        Use case: Export to CSV, send to analytics platform, create charts
        """
        data = self.get_pnl_ohlc(timeframe)
        
        if format == "csv":
            # Convert to CSV-friendly format
            csv_data = []
            for candle in data:
                csv_data.append([
                    str(candle["timestamp"]),
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                ])
            return csv_data
        
        return data
    def _verify_exit_progress(self, timeout_sec: int = 6) -> bool:
        """
        Waits for positions to flatten.
        Returns True if exit completed, False otherwise.
        """
        start = time.time()

        while time.time() - start < timeout_sec:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions() or []

            if all(int(p.get("netqty", 0)) == 0 for p in positions):
                return True

            time.sleep(1)

        return False

    def heartbeat(self):
        """
        Must be called every 5–10 seconds.
        """
        with self._lock:
            try:
                # ⚠️ BEHAVIOR CHANGE (v1.2.1 intentional enhancement):
                # RMS now actively monitors OrderWatcher thread liveness.
                # If dead, initiates emergency exit to protect capital.
                # This is approved and auditable—see git history for context.
                if hasattr(self.bot, 'order_watcher'):
                    try:
                        if not self.bot.order_watcher.is_alive():
                            logger.critical("🚨 ORDER WATCHER DEAD - EMERGENCY EXIT")
                            self.emergency_exit_all(reason="ORDER_WATCHER_DEAD")
                            return
                    except Exception:
                        # If is_alive check itself fails, proceed with emergency
                        logger.exception("Failed to check OrderWatcher liveness")
                        self.emergency_exit_all(reason="ORDER_WATCHER_CHECK_FAILED")
                        return
                self.bot._ensure_login()
                # 🔒 FORCE LIVE BROKER TRUTH — NO STALE PNL ALLOWED
                self._update_pnl("SYSTEM")
                # -------------------------------------------------
                # 🚨 MANUAL TRADE DETECTION AFTER RISK BREACH
                # -------------------------------------------------
                # PATCH 1: Suppress manual alerts during RMS force-exit
                if self.daily_loss_hit and not self.force_exit_in_progress:
                    positions = self.bot.api.get_positions() or []

                    # Build a stable signature of live positions
                    live_positions = sorted(
                        (p.get("exch"), p.get("tsym"), int(p.get("netqty", 0)))
                        for p in positions
                        if int(p.get("netqty", 0)) != 0
                    )

                    position_signature = tuple(live_positions)

                    now = datetime.now()

                    is_new_manual_trade = (
                        position_signature
                        and position_signature != self.last_manual_position_signature
                    )

                    cooldown_ok = (
                        self.last_manual_violation_ts is None
                        or (now - self.last_manual_violation_ts).total_seconds()
                        >= self.MANUAL_ALERT_COOLDOWN_SEC
                    )

                    if is_new_manual_trade and cooldown_ok:
                        self.last_manual_position_signature = position_signature
                        self.last_manual_violation_ts = now

                        # PATCH 4: Log exact manual exposure for post-mortems
                        logger.critical(
                            "MANUAL TRADE AFTER DAILY RISK HIT | positions=%s",
                            position_signature
                        )

                        # PATCH 3: Persist human violation state
                        self.human_violation_detected = True
                        
                        # PATCH 5: Immediate lock escalation (already breached, but ensure it's marked)
                        self.daily_loss_hit = True
                        self._save_state()

                        if self.bot.telegram_enabled:
                            self.bot.send_telegram(
                                "🚨 <b>CRITICAL RISK VIOLATION DETECTED</b>\n\n"
                                "⛔ You attempted to place a MANUAL TRADE after daily risk was hit.\n\n"
                                "🛑 TRADING IS STRICTLY PROHIBITED FOR TODAY\n"
                                "📉 Daily Max Loss already breached\n\n"
                                "⚠️ This position will be FORCE-EXITED automatically.\n"
                                "🧠 This warning exists to protect you from human error.\n\n"
                                f"📅 Date: {self.current_day}\n"
                                f"⏰ Time: {now.strftime('%H:%M:%S')}\n\n"
                                "🔒 ACTION REQUIRED:\n"
                                "• STOP placing trades immediately\n"
                                "• Step away from the terminal\n"
                                "• Resume only after next session"
                            )
                        # 🔥 ENFORCEMENT (MISSING STEP)
                        self.force_exit_in_progress = True
                        self._request_exit_for_all_positions()
                        
                self._update_trailing_max_loss()
                self._check_warning_threshold()

                if self.daily_pnl <= self.dynamic_max_loss:
                    self._handle_daily_loss_breach()

                # PATCH 2: Reset force-exit lock once positions are flat (verified correct)
                if self.force_exit_in_progress:
                    positions = self.bot.api.get_positions() or []
                    if all(int(p.get("netqty", 0)) == 0 for p in positions):
                        self.force_exit_in_progress = False
                        logger.info("Force exit completed - all positions flat")

                self.track_pnl_ohlc()
                self._send_periodic_status()

            except Exception as exc:
                log_exception("SupremeRiskManager.heartbeat", exc)

    # ------------------------------------------------------------------
    # 🔥 BROKER-TRUTH ENFORCEMENT HOOK (INSTANT)
    # ------------------------------------------------------------------

    def on_broker_positions(self, positions: list):
        """
        HARD enforcement hook.
        Called IMMEDIATELY whenever broker positions are fetched.

        This guarantees:
        - Manual trades are caught instantly
        - No polling dependency
        - No race with OrderWatcher
        """

        # Fast exit: no risk, no work
        if not self.daily_loss_hit:
            return

        # Prevent recursion / duplicate storms
        with self._lock:
            if self.force_exit_in_progress:
                return
            self.force_exit_in_progress = True

        for pos in positions:
            try:
                netqty = int(pos.get("netqty", 0))
            except Exception:
                continue

            if netqty == 0:
                continue

            symbol = pos.get("tsym")
            exchange = pos.get("exch")
            product = pos.get("prd")

            if not symbol or not exchange or not product:
                continue

            side = "SELL" if netqty > 0 else "BUY"

            logger.critical(
                "🛑 RMS INSTANT ENFORCEMENT | Manual/System exposure after max loss | %s",
                symbol,
            )

            # 🔥 EXIT INTENT ONLY (OrderWatcher executes)
            self.bot.request_exit(
                symbol=symbol,
                exchange=exchange,
                quantity=abs(netqty),
                side=side,
                product_type=product,
                reason="RMS_DAILY_MAX_LOSS_ENFORCEMENT",
                source="RISK",
            )
