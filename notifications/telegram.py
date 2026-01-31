#!/usr/bin/env python3
"""
Telegram Notifier Module
Handles all Telegram notifications using HTTP requests
"""

import logging
import requests
from typing import Optional, Literal

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
        
    
    def test_connection(self):
        """Test Telegram bot connection"""
        try:
            url = f"{self.base_url}/getMe"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get('ok'):
                    bot_name = bot_info['result']['first_name']
                    logger.info(f"Telegram bot connected successfully: {bot_name}")
                    self.is_connected = True
                    return True
                else:
                    logger.error(f"Telegram bot test failed: {bot_info}")
                    self.is_connected = False
                    return False
            else:
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
        parse_mode: Literal["HTML", "MarkdownV2"] = "HTML"
    ) -> bool:
        """Send message to Telegram using HTTP request"""
        if not self.is_connected:
            logger.warning("Telegram not connected, attempting to reconnect...")
            if not self.test_connection():
                logger.error("Failed to reconnect to Telegram")
                return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = self.session.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                response_data = response.json()
                if response_data.get('ok'):
                    logger.debug("Telegram message sent successfully")
                    return True
                else:
                    logger.error(f"Telegram API error: {response_data}")
                    return False
            else:
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
    
    def send_startup_message(self, host: str, port: int, report_frequency: int) -> bool:
        """Send bot startup notification"""
        message = (
            f"🚀 <b>BOT STARTING UP</b>\n"
            f"📅 Starting at system boot\n"
            f"🤖 Initializing trading bot...\n"
            f"🔐 Attempting login...\n"
            f"🌐 Server: http://{host}:{port}\n"
            f"🔔 Telegram: ✅ Connected\n"
            f"📊 Reports: Every {report_frequency} minutes"
        )
        return self.send_message(message)
    
    def send_ready_message(self, host: str, port: int, report_frequency: int) -> bool:
        """Send bot ready notification"""
        message = (
            f"✅ <b>BOT READY</b>\n"
            f"🌐 Server: http://{host}:{port}\n"
            f"🔔 Telegram: Connected\n"
            f"📊 Reports: Every {report_frequency} minutes\n"
            f"🎯 Status: Monitoring for alerts...\n\n"
            f"📋 Available endpoints:\n"
            f"• /webhook (POST) - Receive trading alerts\n"
            f"• /health (GET) - Health check\n"
            f"• /status (GET) - Detailed status\n"
            f"• /report (POST) - Manual report\n"
            f"• /test-telegram (POST) - Test notifications"
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
    
    def send_alert_received(self, strategy_name: str, execution_type: str, 
                          legs_count: int, exchange: str) -> bool:
        """Send alert received notification"""
        from datetime import datetime
        
        message = (
            f"🔔 <b>ALERT RECEIVED</b>\n"
            f"🎯 Strategy: {strategy_name}\n"
            f"📊 Type: {execution_type.upper()}\n"
            f"📦 Legs: {legs_count}\n"
            f"🏢 Exchange: {exchange}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send_message(message)
    
    def send_order_placing(self, strategy_name: str, execution_type: str, 
                          symbol: str, direction: str, quantity: int, price: float) -> bool:
        """Send order placing notification"""
        if isinstance(price, (int, float)) and price > 0:
            price_str = f"₹{price:.2f}"
        else:
            price_str = "Market"

        
        message = (
            f"📤 <b>PLACING ORDER</b>\n"
            f"🎯 Strategy: {strategy_name}\n"
            f"📊 Type: {execution_type.upper()}\n"
            f"📈 Symbol: {symbol}\n"
            f"🔄 Action: {direction}\n"
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
    
    def send_alert_summary(self, strategy_name: str, success_count: int, 
                          total_legs: int, status: str) -> bool:
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
    
    def send_error_message(self, title: str, error: str) -> bool:
        """Send generic error notification"""
        from datetime import datetime
        
        message = (
            f"💥 <b>{title}</b>\n"
            f"❌ Error: {error}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
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
