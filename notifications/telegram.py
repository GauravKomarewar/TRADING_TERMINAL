#!/usr/bin/env python3
"""
Telegram Notifier Module
Handles all Telegram notifications using HTTP requests
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, Literal, Any, Dict, List

import requests

from shoonya_platform.utils.text_sanitize import sanitize_text

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Handle all Telegram notifications using simple HTTP requests"""

    def __init__(self, bot_token: str, chat_id: str):
        """Initialize Telegram notifier with bot token and chat ID"""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.session = requests.Session()
        self.is_connected = False
        self._log_path = self._resolve_log_path()

    def test_connection(self):
        """Test Telegram bot connection"""
        try:
            url = f"{self.base_url}/getMe"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get("ok"):
                    bot_name = bot_info["result"]["first_name"]
                    logger.info(f"Telegram bot connected successfully: {bot_name}")
                    self.is_connected = True
                    return True
                logger.error(f"Telegram bot test failed: {bot_info}")
                self.is_connected = False
                return False

            logger.error(f"Telegram bot test failed: HTTP {response.status_code}")
            logger.error(f"Response: {response.text}")
            self.is_connected = False
            return False

        except Exception as e:
            logger.error(f"Failed to test Telegram connection: {e}")
            self.is_connected = False
            return False

    def send_message(
        self,
        message: str,
        parse_mode: Literal["HTML", "MarkdownV2"] = "HTML",
    ) -> bool:
        """Send message to Telegram using HTTP request"""
        if not self.is_connected:
            logger.warning("Telegram not connected, attempting to reconnect...")
            if not self.test_connection():
                logger.error("Failed to reconnect to Telegram")
                return False

        try:
            safe_message = sanitize_text(message, ascii_only=False)
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": safe_message,
                "parse_mode": parse_mode,
            }

            response = self.session.post(url, json=data, timeout=10)

            if response.status_code == 200:
                response_data = response.json()
                if response_data.get("ok"):
                    logger.debug("Telegram message sent successfully")
                    self._append_message_log(safe_message)
                    return True
                logger.error(f"Telegram API error: {response_data}")
                return False

            logger.error(f"Failed to send Telegram message: HTTP {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False

        except requests.exceptions.Timeout:
            logger.error("Telegram message timeout")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram request error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    def _resolve_log_path(self) -> Path:
        project_root = Path(__file__).resolve().parents[1]
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "telegram_messages.jsonl"

    def _append_message_log(self, message: str) -> None:
        try:
            payload = {
                "ts": time.time(),
                "message": sanitize_text(message, ascii_only=False),
            }
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception as e:
            logger.warning(f"Failed to log telegram message: {e}")

    @staticmethod
    def _format_price(order_type: str, price: Any) -> str:
        if str(order_type or "").upper() in ("LIMIT", "LMT"):
            try:
                return f"₹{float(price):.2f}"
            except Exception:
                return "Limit"
        return "Market"

    def _format_leg_lines(self, legs: Optional[List[Dict[str, Any]]]) -> str:
        if not legs:
            return ""

        lines: List[str] = []
        for idx, leg in enumerate(legs, start=1):
            symbol = str(leg.get("tradingsymbol") or leg.get("symbol") or "-")
            direction = str(leg.get("direction") or leg.get("side") or "-").upper()
            qty = leg.get("qty") if leg.get("qty") is not None else leg.get("quantity")
            order_type = str(leg.get("order_type") or "MARKET").upper()
            price_str = self._format_price(order_type, leg.get("price"))

            # ── Extended leg info (tag, strike, expiry, delta, iv) ──
            tag = leg.get("tag") or ""
            option_type = leg.get("option_type") or ""
            strike = leg.get("strike")
            expiry = leg.get("expiry") or ""
            delta = leg.get("delta")
            iv = leg.get("iv")
            lots = leg.get("lots")

            strike_str = f"₹{strike:.0f}" if strike is not None else ""
            delta_str = f"Δ {delta:.4f}" if delta is not None else ""
            iv_str = f"IV {iv:.1f}%" if iv is not None else ""
            lots_str = f"{lots}L" if lots is not None else ""

            # Line 1: core order info
            main_line = f"   {idx}. {direction} {symbol} | Qty {qty} | {order_type} {price_str}"
            # Line 2: strike / greeks detail (only if available)
            detail_parts = [p for p in [tag, option_type, strike_str, expiry, lots_str, delta_str, iv_str] if p]
            if detail_parts:
                main_line += f"\n      ↳ {' | '.join(detail_parts)}"

            lines.append(main_line)
        return "\n".join(lines)

    def send_startup_message(self, host: str, port: int, report_frequency: int) -> bool:
        """Send bot startup notification"""
        from datetime import datetime

        message = (
            f"🚀 <b>TRADING SYSTEM STARTING</b>\n"
            f"📅 {datetime.now().strftime('%A, %d %B %Y')}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🤖 Initializing trading bot...\n"
            f"🔐 Attempting broker login...\n"
            f"🌐 Server: http://{host}:{port}\n"
            f"🔔 Telegram: ✅ Connected\n"
            f"� Heartbeat: Every 5 minutes\n\n"
            f"⏳ Please wait for READY confirmation..."
        )
        return self.send_message(message)

    def send_ready_message(self, host: str, port: int, report_frequency: int) -> bool:
        """Send bot ready notification"""
        from datetime import datetime

        message = (
            f"✅ <b>SYSTEM READY - TRADING ACTIVE</b>\n"
            f"📅 {datetime.now().strftime('%A, %d %B %Y')}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔐 Login: ✅ Successful\n"
            f"📊 Market Data: ✅ Live\n"
            f"🌐 Dashboard: http://{host}:{port}\n"
            f"💓 Heartbeat: Every 5 minutes\n\n"
            f"🎯 <b>Status: Monitoring for trading signals...</b>\n\n"
            f"📖 <i>Available: Webhook | Dashboard | Live Feed</i>"
        )
        return self.send_message(message)

    def send_login_success(self, user_id: str) -> bool:
        """Send login success notification"""
        from datetime import datetime

        message = (
            f"✅ <b>LOGIN SUCCESSFUL</b>\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"👤 User: {user_id}\n"
            f"🤖 Bot Status: Active & Ready"
        )
        return self.send_message(message)

    def send_login_failed(self, error: str) -> bool:
        """Send login failed notification"""
        from datetime import datetime

        message = (
            f"🚫 <b>LOGIN FAILED</b>\n"
            f"❌ Error: {error}\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message)

    def send_alert_received(
        self,
        strategy_name: str,
        execution_type: str,
        legs_count: int,
        exchange: str,
        legs: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Send alert received notification"""
        from datetime import datetime

        leg_block = self._format_leg_lines(legs)
        leg_details = f"🧩 Leg Details:\n{leg_block}\n" if leg_block else ""
        message = (
            f"🔔 <b>ALERT RECEIVED</b>\n"
            f"🎯 Strategy: {strategy_name}\n"
            f"📊 Type: {execution_type.upper()}\n"
            f"🏢 Exchange: {exchange}\n"
            f"📦 Legs: {legs_count}\n"
            f"{leg_details}"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    def send_order_placing(
        self,
        strategy_name: str,
        execution_type: str,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
    ) -> bool:
        """Send order placing notification"""
        price_str = f"₹{price:.2f}" if isinstance(price, (int, float)) and price > 0 else "Market"

        message = (
            f"📤 <b>PLACING ORDER</b>\n"
            f"🎯 Strategy: {strategy_name}\n"
            f"📊 Type: {execution_type.upper()}\n"
            f"📈 Symbol: {symbol}\n"
            f"🔁 Action: {direction}\n"
            f"📦 Qty: {quantity}\n"
            f"💰 Price: {price_str}"
        )
        return self.send_message(message)

    def send_order_success(self, order_id: str, symbol: str, direction: str, quantity: int) -> bool:
        """Send order success notification"""
        from datetime import datetime

        message = (
            f"✅ <b>ORDER SUCCESSFUL</b>\n"
            f"🆔 Order ID: {order_id}\n"
            f"📈 {symbol} - {direction} {quantity}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    def send_order_failed(self, symbol: str, direction: str, quantity: int, error: str) -> bool:
        """Send order failed notification"""
        from datetime import datetime

        message = (
            f"❌ <b>ORDER FAILED</b>\n"
            f"📈 {symbol} - {direction} {quantity}\n"
            f"🚫 Error: {error}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    def send_alert_summary(
        self,
        strategy_name: str,
        success_count: int,
        total_legs: int,
        status: str,
    ) -> bool:
        """Send alert processing summary"""
        from datetime import datetime

        success_rate = (success_count / total_legs) * 100 if total_legs > 0 else 0
        if success_rate == 100:
            icon = "🎉"
        elif success_rate > 0:
            icon = "⚠️"
        else:
            icon = "❌"

        message = (
            f"{icon} <b>{status}</b>\n"
            f"🎯 Strategy: {strategy_name}\n"
            f"✅ Success: {success_count}/{total_legs}\n"
            f"📊 Rate: {success_rate:.1f}%\n"
            f"⏰ Completed: {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    def send_error_message(
        self,
        title: str,
        error: str,
        *,
        strategy_name: Optional[str] = None,
        execution_type: Optional[str] = None,
        exchange: Optional[str] = None,
        legs: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Send generic error notification"""
        from datetime import datetime

        leg_block = self._format_leg_lines(legs)
        strategy_line = f"\n🎯 Strategy: {strategy_name}" if strategy_name else ""
        type_line = f"\n📊 Type: {execution_type.upper()}" if execution_type else ""
        exchange_line = f"\n🏢 Exchange: {exchange}" if exchange else ""
        legs_line = f"\n📦 Legs: {len(legs)}" if legs else ""
        details_block = f"\n🧩 Leg Details:\n{leg_block}" if leg_block else ""

        message = (
            f"💥 <b>{title}</b>"
            f"{strategy_line}"
            f"{type_line}"
            f"{exchange_line}"
            f"{legs_line}"
            f"\n❌ Error: {error}"
            f"{details_block}"
            f"\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

    def send_test_message(self) -> bool:
        """Send test message"""
        from datetime import datetime

        message = (
            f"🧪 <b>TELEGRAM TEST</b>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"✅ Connection working!"
        )
        return self.send_message(message)
