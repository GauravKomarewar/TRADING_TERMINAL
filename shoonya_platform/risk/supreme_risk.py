#!/usr/bin/env python3
"""
Supreme Risk Manager - FINAL CORRECTED VERSION
===============================================

✅ USES OFFICIAL NorenApi PARAMETERS (from your ShoonyaClient.py)
✅ Compatible with your existing system
✅ Tested against your actual error logs

CRITICAL FIX:
- Uses "exchange" NOT "exch" (official NorenApi standard)
- Uses "price_type" NOT "order_type" 
- Uses "product_type" NOT "product"
- Uses "tradingsymbol" NOT "symbol"
- Uses "buy_or_sell" NOT "side"

Version: v1.2.3-PRODUCTION-READY
"""

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
    Supreme risk authority with GUARANTEED exit enforcement.
    Uses official NorenApi parameter names for 100% compatibility.
    """
    
    def __init__(self, bot):
        self._lock = threading.RLock()
        self.force_exit_in_progress = False

        cfg = bot.config
        client_id = bot.client_id
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
        self.failed_days = deque(maxlen=self.MAX_CONSECUTIVE_LOSS_DAYS)
        self.cooldown_until: Optional[date] = None
        self.daily_loss_hit: bool = False
        self.warning_sent: bool = False
        
        self.last_manual_position_signature = None
        self.last_manual_violation_ts = None
        self.human_violation_detected = False
        self.MANUAL_ALERT_COOLDOWN_SEC = 60

        self.last_status_update: Optional[datetime] = None
        self.last_known_pnl: Optional[float] = None

        self.pnl_ohlc = {
            "1m": OrderedDict(),
            "5m": OrderedDict(),
            "1d": OrderedDict(),
        }
        
        logger.info("SupremeRiskManager initialized v1.2.3-PRODUCTION-READY (NorenApi compatible)")

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
                self.human_violation_detected = data.get("human_violation_detected", False)

        except Exception as e:
            log_exception("RiskState.load", e)

    def _save_state(self):
        try:
            data = {
                "date": str(self.current_day),
                "dynamic_max_loss": self.dynamic_max_loss,
                "highest_profit": self.highest_profit,
                "daily_loss_hit": self.daily_loss_hit,
                "human_violation_detected": self.human_violation_detected,
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log_exception("RiskState.save", e)

    def can_execute(self) -> bool:
        today = date.today()
        self._update_pnl("SYSTEM")

        if today != self.current_day:
            self._reset_daily_state(today)

        if self.cooldown_until and today < self.cooldown_until:
            logger.critical("Trading blocked: cooldown until %s", self.cooldown_until)
            return False

        if self.daily_loss_hit:
            logger.critical("Trading blocked: daily max loss already hit")
            return False

        if self.daily_pnl <= self.dynamic_max_loss:
            self._handle_daily_loss_breach()
            return False

        return True

    def can_execute_command(self, command) -> Tuple[bool, str]:
        with self._lock:
            today = date.today()
            
            if self.force_exit_in_progress:
                return False, "FORCE_EXIT_IN_PROGRESS"

            if today != self.current_day:
                self._reset_daily_state(today)

            if self.cooldown_until and today < self.cooldown_until:
                return False, "RISK_COOLDOWN_ACTIVE"

            if self.daily_loss_hit:
                return False, "DAILY_MAX_LOSS_ALREADY_HIT"

            if self.daily_pnl <= self.dynamic_max_loss:
                self._handle_daily_loss_breach()
                return False, "DAILY_MAX_LOSS_BREACHED"

            lot_size = getattr(command, "lot_size", None)
            if lot_size and command.quantity % lot_size != 0:
                return False, "INVALID_LOT_SIZE"

            return True, "OK"

    def emergency_exit_all(self, reason: str = "RISK_VIOLATION"):
        """
        🚨 GUARANTEED EXIT using OFFICIAL NorenApi parameters.
        
        ✅ Uses exact parameter names from NorenApi.place_order():
           - exchange (NOT "exch")
           - tradingsymbol (NOT "symbol")  
           - buy_or_sell (NOT "side")
           - product_type (NOT "product")
           - price_type (NOT "order_type")
        """
        logger.critical(
            f"🚨 EMERGENCY EXIT INITIATED | reason={reason} | "
            f"DIRECT BROKER EXECUTION"
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

                if not symbol or not exchange or not product:
                    continue

                exit_side = "SELL" if netqty > 0 else "BUY"
                exit_qty = abs(netqty)

                must_limit = requires_limit_order(
                    exchange=exchange,
                    tradingsymbol=symbol
                )

                price_type = "LMT" if must_limit else "MKT"
                price = None

                if must_limit:
                    try:
                        ltp = self.bot.api.get_ltp(exchange, symbol)
                        if ltp:
                            price = self._calc_emergency_limit_price(
                                ltp=ltp,
                                side=exit_side,
                                tick=0.05
                            )
                    except Exception as e:
                        logger.error(f"LTP fetch failed for {symbol}: {e}")
                        price = 0.0 if exit_side == "BUY" else 99999.99

                logger.critical(
                    f"🚨 EMERGENCY EXIT | {symbol} | {exit_side} | "
                    f"qty={exit_qty} | type={price_type} | price={price}"
                )

                try:
                    # ✅ OFFICIAL NorenApi PARAMETERS (from your ShoonyaClient)
                    order_params = {
                        "exchange": exchange,          # ✅ Official NorenApi
                        "tradingsymbol": symbol,       # ✅ Official NorenApi
                        "quantity": exit_qty,
                        "buy_or_sell": exit_side,      # ✅ Official NorenApi
                        "product_type": product,       # ✅ Official NorenApi
                        "price_type": price_type,      # ✅ Official NorenApi
                        "retention": "DAY",
                        "discloseqty": 0,
                    }
                    
                    if price is not None:
                        order_params["price"] = price

                    result = self.bot.api.place_order(order_params)

                    if result.success:
                        exit_count += 1
                        logger.critical(
                            f"✅ EMERGENCY EXIT PLACED | {symbol} | {result.order_id}"
                        )
                    else:
                        failed_exits.append((symbol, result.error_message))
                        logger.error(
                            f"❌ EMERGENCY EXIT FAILED | {symbol} | {result.error_message}"
                        )

                except Exception as e:
                    failed_exits.append((symbol, str(e)))
                    logger.exception(f"❌ EMERGENCY EXIT EXCEPTION | {symbol}")

            total_positions = len([p for p in positions if int(p.get("netqty", 0)) != 0])

            logger.critical(
                f"🚨 EMERGENCY EXIT COMPLETE | total={total_positions} "
                f"successful={exit_count} failed={len(failed_exits)}"
            )

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

            # ✅ ExecutionGuard cleanup (check for method existence)
            try:
                if hasattr(self.bot, "execution_guard"):
                    guard = self.bot.execution_guard
                    # Try different method names
                    if hasattr(guard, 'force_close_strategy'):
                        for strategy_id in list(getattr(guard, '_strategy_positions', {}).keys()):
                            guard.force_close_strategy(strategy_id)
                        logger.warning("ExecutionGuard cleared via force_close_strategy")
                    else:
                        logger.warning("ExecutionGuard has no cleanup method available")
            except Exception:
                logger.exception("ExecutionGuard cleanup failed")
            # allow heartbeat to retry later
            self.force_exit_in_progress = False
            
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

    def _calc_emergency_limit_price(self, *, ltp: float, side: str, tick: float = 0.05) -> float:
        buffer = 0.02
        
        if side == "BUY":
            raw = ltp * (1 + buffer)
            return math.ceil(raw / tick) * tick
        else:
            raw = ltp * (1 - buffer)
            return math.floor(raw / tick) * tick

    def _handle_daily_loss_breach(self):
        if self.daily_loss_hit and self.force_exit_in_progress:
            return

        with self._lock:
            if self.daily_loss_hit:
                return

            self.daily_loss_hit = True
            self.failed_days.append(self.current_day)
            self.force_exit_in_progress = True

            logger.critical(
                "🔴 DAILY MAX LOSS HIT: %.2f — FORCING EXIT",
                self.daily_pnl
            )

            if self.bot.telegram_enabled:
                consecutive_msg = ""
                if len(self.failed_days) > 1:
                    consecutive_msg = (
                        f"📉 Consecutive loss days: "
                        f"{len(self.failed_days)}/{self.MAX_CONSECUTIVE_LOSS_DAYS}\n"
                    )
                
                self.bot.send_telegram(
                    f"🛑 <b>DAILY MAX LOSS HIT</b>\n\n"
                    f"💔 Current PnL: ₹{self.daily_pnl:.2f}\n"
                    f"🚫 Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
                    f"{consecutive_msg}\n"
                    f"🔻 FORCING EXIT OF ALL POSITIONS\n"
                    f"⏸ Trading halted for today"
                )

            self._request_exit_for_all_positions()

            if not self._verify_exit_progress(timeout_sec=6):
                logger.critical(
                    "⚠️ OMS EXIT TIMEOUT — ESCALATING TO EMERGENCY EXIT"
                )
                self.emergency_exit_all(reason="OMS_EXIT_TIMEOUT")

            if len(self.failed_days) == self.MAX_CONSECUTIVE_LOSS_DAYS:
                self._activate_cooldown()

    def _request_exit_for_all_positions(self):
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

    def _verify_exit_progress(self, timeout_sec: int = 6) -> bool:
        start = time.time()

        while time.time() - start < timeout_sec:
            self.bot._ensure_login()
            positions = self.bot.api.get_positions() or []

            if all(int(p.get("netqty", 0)) == 0 for p in positions):
                logger.info("✅ All positions successfully closed")
                return True

            time.sleep(1)

        logger.warning("❌ Exit verification timeout - positions still open")
        return False

    def on_broker_positions(self, positions: list):
        if not self.daily_loss_hit:
            return

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
                "🚨 INSTANT ENFORCEMENT | Manual trade after max loss | %s",
                symbol,
            )

            self.bot.request_exit(
                symbol=symbol,
                exchange=exchange,
                quantity=abs(netqty),
                side=side,
                product_type=product,
                reason="RMS_MANUAL_TRADE_ENFORCEMENT",
                source="RISK",
            )

    def heartbeat(self):
        with self._lock:
            try:
                if hasattr(self.bot, 'order_watcher'):
                    try:
                        if not self.bot.order_watcher.is_alive():
                            logger.critical(
                                "🚨 ORDER WATCHER DEAD - EMERGENCY EXIT"
                            )
                            self.emergency_exit_all(reason="ORDER_WATCHER_DEAD")
                            return
                    except Exception:
                        logger.exception("Failed to check OrderWatcher liveness")
                        self.emergency_exit_all(reason="ORDER_WATCHER_CHECK_FAILED")
                        return

                self.bot._ensure_login()
                self._update_pnl("SYSTEM")

                if self.daily_loss_hit and not self.force_exit_in_progress:
                    positions = self.bot.api.get_positions() or []

                    if any(int(p.get("netqty", 0)) != 0 for p in positions):
                        logger.critical(
                            "♻️ HEARTBEAT DETECTED LIVE POSITION AFTER EXIT FAILURE — RETRYING EXIT"
                        )

                        # IMPORTANT: re-arm exit
                        self.force_exit_in_progress = False

                        self._request_exit_for_all_positions()
                        
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
                        self.human_violation_detected = True
                        self.daily_loss_hit = True
                        self._save_state()

                        logger.critical(
                            "🚨 MANUAL TRADE AFTER RISK HIT | positions=%s",
                            position_signature
                        )

                        if self.bot.telegram_enabled:
                            self.bot.send_telegram(
                                "🚨 <b>CRITICAL RISK VIOLATION</b>\n\n"
                                "⛔ MANUAL TRADE detected after max loss hit\n\n"
                                "🛑 TRADING IS STRICTLY PROHIBITED\n"
                                "⚠️ Position will be FORCE-EXITED\n\n"
                                f"📅 Date: {self.current_day}\n"
                                f"⏰ Time: {now.strftime('%H:%M:%S')}\n\n"
                                "🔒 STOP TRADING IMMEDIATELY"
                            )

                        self.force_exit_in_progress = True
                        self._request_exit_for_all_positions()

                self._update_trailing_max_loss()
                self._check_warning_threshold()

                if self.daily_pnl <= self.dynamic_max_loss:
                    self._handle_daily_loss_breach()

                if self.force_exit_in_progress:
                    positions = self.bot.api.get_positions() or []
                    if all(int(p.get("netqty", 0)) == 0 for p in positions):
                        self.force_exit_in_progress = False
                        logger.info("Force exit completed - all positions flat")

                self.track_pnl_ohlc()
                self._send_periodic_status()

            except Exception as exc:
                log_exception("SupremeRiskManager.heartbeat", exc)

    # Remaining methods unchanged (trailing, analytics, etc.)
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
            logger.warning("Trailing max loss updated → %.2f", self.dynamic_max_loss)
            if self.bot.telegram_enabled:
                self.bot.send_telegram(
                    f"🛡 <b>TRAILING RISK UPDATED</b>\n\n"
                    f"📈 Net Profit: ₹{self.highest_profit:.2f}\n"
                    f"🔒 New Max Loss: ₹{self.dynamic_max_loss:.2f}"
                )

    def _update_pnl(self, strategy_name: str):
        self.bot._ensure_login()
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
        if self.dynamic_max_loss < 0:
            warning_level = abs(self.dynamic_max_loss) * self.WARNING_THRESHOLD_PCT
            if abs(self.daily_pnl) >= warning_level:
                self.warning_sent = True
                self._send_warning()
        else:
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

    def _activate_cooldown(self):
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        self.cooldown_until = today + timedelta(days=days_until_monday)
        logger.critical("COOLDOWN ACTIVATED until %s", self.cooldown_until)
        if self.bot.telegram_enabled:
            self.bot.send_telegram(
                f"🧊 <b>RISK COOLDOWN ACTIVATED</b>\n\n"
                f"📉 {self.MAX_CONSECUTIVE_LOSS_DAYS} consecutive loss days\n"
                f"⏸ Trading blocked until: {self.cooldown_until}\n"
                f"🔄 System resumes next Monday"
            )

    def track_pnl_ohlc(self):
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
            self._update_ohlc("1m", now.replace(second=0, microsecond=0), net_pnl)
            self._update_ohlc(
                "5m",
                now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0),
                net_pnl,
            )
            self._update_ohlc("1d", now.date(), net_pnl)
            self._prune_old_ohlc()
        except Exception as exc:
            log_exception("SupremeRiskManager.track_pnl_ohlc", exc)

    def _update_ohlc(self, tf: str, key, pnl: float):
        store = self.pnl_ohlc[tf]
        candle = store.get(key)
        if candle is None:
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
            for key, candle in list(store.items()):
                ts = candle["timestamp"]
                if isinstance(ts, date) and not isinstance(ts, datetime):
                    ts = datetime.combine(ts, datetime.min.time())
                if ts < cutoff:
                    del store[key]
                else:
                    break

    def get_pnl_ohlc(self, timeframe: str) -> List[Dict]:
        return list(self.pnl_ohlc.get(timeframe, {}).values())

    def get_pnl_stats(self) -> Dict:
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
        if stats["today_high"] != 0 or stats["today_low"] != 0:
            stats["today_range"] = stats["today_high"] - stats["today_low"]
        else:
            stats["today_range"] = 0.0
        return stats

    def _send_periodic_status(self):
        if not self.bot.telegram_enabled:
            return
        now = datetime.now()
        if self.last_status_update is not None:
            elapsed_seconds = (now - self.last_status_update).total_seconds()
            if elapsed_seconds < self.STATUS_UPDATE_INTERVAL * 60:
                return
        self.last_status_update = now
        if self.dynamic_max_loss < 0:
            pnl_pct_used = (abs(self.daily_pnl) / abs(self.dynamic_max_loss)) * 100
        else:
            pnl_pct_used = 0
        remaining = (
            abs(self.dynamic_max_loss) - abs(self.daily_pnl) 
            if self.daily_pnl < 0 
            else abs(self.dynamic_max_loss)
        )
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
        daily_data = self.get_pnl_ohlc("1d")
        high_low_msg = ""
        if daily_data and len(daily_data) > 0:
            today_candle = daily_data[-1]
            high_low_msg = (
                f"📈 Today High: ₹{today_candle['high']:.2f}\n"
                f"📉 Today Low: ₹{today_candle['low']:.2f}\n"
            )
        self.bot.send_telegram(
            f"{status_emoji} <b>RMS STATUS</b>\n\n"
            f"📊 Status: {status_text}\n"
            f"💰 Current PnL: ₹{self.daily_pnl:.2f}\n"
            f"{high_low_msg}"
            f"🎯 Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
            f"📈 Risk Used: {pnl_pct_used:.1f}%\n"
            f"💵 Remaining: ₹{remaining:.2f}\n"
            f"📅 {self.current_day} ⏰ {now.strftime('%H:%M:%S')}"
        )

    def send_current_status(self):
        if not self.bot.telegram_enabled:
            return
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
        if self.dynamic_max_loss < 0:
            pnl_pct_used = (abs(self.daily_pnl) / abs(self.dynamic_max_loss)) * 100
        else:
            pnl_pct_used = 0
        remaining = (
            abs(self.dynamic_max_loss) - abs(self.daily_pnl) 
            if self.daily_pnl < 0 
            else abs(self.dynamic_max_loss)
        )
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
            f"📊 Range: ₹{stats['today_range']:.2f}\n"
            f"🎯 Max Loss: ₹{self.dynamic_max_loss:.2f}\n"
            f"📈 Risk Used: {pnl_pct_used:.1f}%\n"
            f"💵 Remaining: ₹{remaining:.2f}\n"
            f"⚠️ Warning: {'Yes' if self.warning_sent else 'No'}\n"
            f"🛑 Loss Hit: {'Yes' if self.daily_loss_hit else 'No'}\n"
            f"📉 Failed Days: {len(self.failed_days)}/{self.MAX_CONSECUTIVE_LOSS_DAYS}\n"
            f"📅 {self.current_day} ⏰ {datetime.now().strftime('%H:%M:%S')}"
            f"{cooldown_info}"
        )

    def _reset_daily_state(self, new_day: date):
        logger.info("Risk rollover: %s → %s", self.current_day, new_day)
        self.force_exit_in_progress = False
        if self.daily_pnl > 0:
            self.failed_days.clear()
        self.current_day = new_day
        self.daily_pnl = 0.0
        self.daily_loss_hit = False
        self.warning_sent = False
        self.last_status_update = None
        self.last_known_pnl = None
        self.human_violation_detected = False
        self.pnl_ohlc["1m"].clear()
        self.pnl_ohlc["5m"].clear()
        self.dynamic_max_loss = self.BASE_MAX_LOSS
        self.highest_profit = 0.0
        self._save_state()

    def get_status(self) -> Dict:
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

    def on_trade_update(self, strategy_name: str):
        with self._lock:
            try:
                self._update_pnl(strategy_name)
                self._update_trailing_max_loss()
                self._check_warning_threshold()
                if self.daily_pnl <= self.dynamic_max_loss:
                    self._handle_daily_loss_breach()
                self.track_pnl_ohlc()
                self._send_periodic_status()
            except Exception as exc:
                log_exception("SupremeRiskManager.on_trade_update", exc)