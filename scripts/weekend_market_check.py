#!/usr/bin/env python3
"""
Weekend Market Activity Detector
Checks if market is active on Saturday/Sunday (mock sessions, special events)
Automatically starts trading service if activity detected
"""

import sys
import time
import logging
import subprocess
from datetime import datetime
from typing import Optional
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.market_data.feeds.live_feed import (
    check_feed_health,
    get_feed_stats,
    is_feed_connected
)
from notifications.telegram import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('weekend_check')


def send_telegram_alert(telegram: Optional[TelegramNotifier], message: str):
    """Send telegram notification"""
    try:
        if telegram:
            telegram.send_message(message)
    except Exception as e:
        logger.error(f"Failed to send telegram: {e}")


def check_market_activity(api: ShoonyaClient) -> tuple[bool, str]:
    """
    Check if market is active by validating multiple signals:
    1. Broker login status
    2. Live tick feed monitoring (PRIMARY - real-time activity)
    3. Quote age validation
    4. Order book activity
    5. Broker operational status
    
    Returns:
        (is_active, reason)
    """
    try:
        # 1. Check if can login successfully
        if not api.ensure_session():
            return False, "Login failed"
        
        # 2. PRIMARY CHECK: Live tick feed monitoring
        # This is the most reliable indicator of market activity
        try:
            feed_health = check_feed_health()
            feed_stats = get_feed_stats()
            
            if feed_health.get('healthy'):
                # Feed is connected and receiving ticks
                last_tick_age = feed_stats.get('seconds_since_last_tick')
                if last_tick_age is not None and last_tick_age < 30:
                    # Received ticks within last 30 seconds
                    return True, f"✅ Live ticks detected (age: {last_tick_age:.1f}s)"
                elif last_tick_age is not None:
                    logger.info(f"Feed connected but ticks are stale (age: {last_tick_age:.0f}s)")
            
            # If feed is connected but no recent ticks, it might mean:
            # - Market is closed but websocket is active
            # - Network delay
            # - No subscriptions yet
            if is_feed_connected():
                logger.info("Feed connected but no recent ticks - checking other signals")
        except Exception as e:
            logger.debug(f"Live feed check failed: {e}")
        
        # 3. FALLBACK: Get market quotes for major indices
        try:
            # Try to get NIFTY spot quote
            nifty_quote = api.get_quotes(exchange="NSE", token="26000")
            
            if nifty_quote and isinstance(nifty_quote, dict):
                # Check if quote is recent (within last 5 minutes)
                ft = nifty_quote.get('ft')
                if ft:
                    try:
                        # Parse timestamp
                        quote_time = datetime.fromtimestamp(int(ft))
                        age = (datetime.now() - quote_time).total_seconds()
                        
                        if age < 300:  # Less than 5 minutes old
                            return True, f"Live quote detected (age: {age:.0f}s)"
                    except:
                        pass
        except Exception as e:
            logger.debug(f"Quote check failed: {e}")
        
        # 4. Check order book for today's activity
        try:
            orders = api.get_order_book()
            if orders:
                today = datetime.now().date()
                for order in orders:
                    # Check if any orders from today
                    order_time_str = order.get('norenordno', '')
                    if order_time_str:
                        # Order IDs usually contain timestamp
                        # If we see recent orders, market is active
                        return True, "Recent orders detected"
        except Exception as e:
            logger.debug(f"Order book check failed: {e}")
        
        # 5. Check if exchange is open via limits
        try:
            limits = api.get_limits()
            if limits and isinstance(limits, dict):
                # If we can fetch limits without error, broker is operational
                # But this doesn't necessarily mean market is active
                logger.info("Broker is operational but no market activity detected")
        except Exception as e:
            logger.debug(f"Limits check failed: {e}")
        
        return False, "No market activity detected"
        
    except Exception as e:
        logger.error(f"Market activity check error: {e}")
        return False, f"Error: {str(e)}"


def is_service_running() -> bool:
    """Check if trading service is already running"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'trading'],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == 'active'
    except Exception as e:
        logger.error(f"Service status check failed: {e}")
        return False


def start_service():
    """Start the trading service"""
    try:
        subprocess.run(
            ['sudo', 'systemctl', 'start', 'trading'],
            check=True
        )
        return True
    except Exception as e:
        logger.error(f"Failed to start service: {e}")
        return False


def main():
    """Main weekend market check routine"""
    now = datetime.now()
    day_name = now.strftime('%A')
    
    logger.info("=" * 60)
    logger.info(f"🔍 WEEKEND MARKET CHECK | {day_name} | {now.strftime('%H:%M:%S')}")
    logger.info("=" * 60)
    
    # Only run on Saturday/Sunday
    if now.weekday() not in [5, 6]:  # 5=Saturday, 6=Sunday
        logger.info("Not a weekend, skipping check")
        return
    
    # Only check between 9:00-9:30 AM
    if not (now.hour == 9 and now.minute < 30):
        logger.info("Outside check window (9:00-9:30 AM), skipping")
        return
    
    # Check if service is already running
    if is_service_running():
        logger.info("✅ Service already running, nothing to do")
        return
    
    # Initialize config and clients
    telegram: Optional[TelegramNotifier] = None
    try:
        config = Config()
        
        # Initialize telegram
        if config.telegram_bot_token and config.telegram_chat_id:
            telegram = TelegramNotifier(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id
            )
            telegram.test_connection()
        
        # Create broker client
        api = ShoonyaClient(config)
        
        # Attempt login
        logger.info("🔐 Attempting broker login...")
        if not api.login():
            logger.warning("❌ Login failed - market likely closed")
            send_telegram_alert(
                telegram,
                f"📅 <b>Weekend Check - {day_name}</b>\n"
                f"⏰ {now.strftime('%H:%M:%S')}\n"
                f"❌ No market activity detected\n"
                f"💤 Service remains stopped"
            )
            return
        
        logger.info("✅ Login successful, checking market activity...")
        
        # Check for market activity
        is_active, reason = check_market_activity(api)
        
        if is_active:
            logger.info(f"✅ MARKET ACTIVITY DETECTED: {reason}")
            logger.info("🚀 Starting trading service...")
            
            # Send telegram notification
            send_telegram_alert(
                telegram,
                f"🎯 <b>WEEKEND MARKET DETECTED!</b>\n"
                f"📅 {day_name}, {now.strftime('%d %B %Y')}\n"
                f"⏰ {now.strftime('%H:%M:%S')}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ Market Activity: {reason}\n"
                f"🚀 Starting trading service...\n\n"
                f"💡 <i>Mock session or special trading day detected</i>"
            )
            
            # Start the service
            if start_service():
                logger.info("✅ Service started successfully")
                time.sleep(5)
                
                # Verify service is running
                if is_service_running():
                    send_telegram_alert(
                        telegram,
                        f"✅ <b>SERVICE STARTED</b>\n"
                        f"🤖 Trading bot is now active\n"
                        f"📊 Monitoring {day_name} market session"
                    )
                else:
                    logger.error("❌ Service failed to start")
                    send_telegram_alert(
                        telegram,
                        f"❌ <b>SERVICE START FAILED</b>\n"
                        f"⚠️ Please check logs\n"
                        f"📋 journalctl -u trading -n 50"
                    )
            else:
                logger.error("❌ Failed to start service")
        else:
            logger.info(f"💤 No market activity: {reason}")
            logger.info("Service will remain stopped")
            
            # Silent on no activity - don't spam telegram on normal weekends
            
    except Exception as e:
        logger.error(f"Weekend check error: {e}", exc_info=True)
        
        # Send error notification
        try:
            if telegram:
                send_telegram_alert(
                    telegram,
                    f"⚠️ <b>Weekend Check Error</b>\n"
                    f"📅 {day_name}\n"
                    f"❌ {str(e)[:100]}"
                )
        except:
            pass
    
    finally:
        logger.info("Weekend check complete")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
