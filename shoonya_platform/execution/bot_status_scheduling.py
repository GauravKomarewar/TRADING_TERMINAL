# ======================================================================
# StatusSchedulingMixin — extracted from trading_bot.py
#
# Contains: scheduler, control-intent consumers, account info,
#           bot stats, daily/market-close/heartbeat/status reports,
#           trade history, session info, test telegram, cleanup.
# ======================================================================
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Optional

import schedule

from shoonya_platform.domain.business_models import AccountInfo, BotStats
from shoonya_platform.execution.generic_control_consumer import GenericControlIntentConsumer
from shoonya_platform.execution.strategy_control_consumer import StrategyControlConsumer
from shoonya_platform.utils.utils import (
    format_currency,
    get_today_trades,
    get_yesterday_trades,
    calculate_success_rate,
    log_exception,
    get_date_filter,
)
from shoonya_platform.logging.logger_config import get_component_logger

logger = get_component_logger('trading_bot')


class StatusSchedulingMixin:
    """Methods for scheduling, periodic reporting, control consumers, and account queries."""

    def start_scheduler(self):
        """Start the scheduler for periodic reports in separate thread"""
        def run_scheduler():
            def send_strategy_reports():
                with self._live_strategies_lock:
                    items = list(self._live_strategies.items())
                for name, value in items:
                    if not isinstance(value, tuple) or len(value) != 2:
                        continue
                    strategy, market = value
                    try:
                        from shoonya_platform.strategy_runner.universal_settings.universal_strategy_reporter import build_strategy_report
                        report = build_strategy_report(strategy, market)
                        if report:
                            self.send_telegram(report, category="reports")
                    except Exception as e:
                        log_exception(f"strategy_report:{name}", e)

            try:
                # send_status_report disabled — 💓 SYSTEM HEARTBEAT is the only periodic status
                # schedule.every(self.config.report_frequency).minutes.do(self.send_status_report)
                schedule.every().day.at("09:00").do(self.send_daily_summary)
                schedule.every().day.at("15:30").do(self.send_market_close_summary)
                schedule.every(1).minutes.do(self.risk_manager.track_pnl_ohlc)

                def _rms_heartbeat_wrapper():
                    try:
                        self.risk_manager.heartbeat()
                    except RuntimeError:
                        raise
                    except Exception as e:
                        log_exception("RMS.heartbeat", e)

                schedule.every(5).seconds.do(_rms_heartbeat_wrapper)

                def _telegram_heartbeat():
                    try:
                        self.send_telegram_heartbeat()
                    except RuntimeError:
                        raise
                    except Exception as e:
                        log_exception("telegram_heartbeat", e)

                schedule.every(5).minutes.do(_telegram_heartbeat)

                schedule.every(10).minutes.do(send_strategy_reports)

                def _orphan_monitor_wrapper():
                    try:
                        executed = self.orphan_manager.monitor_and_execute()
                        if executed > 0:
                            logger.warning(f"\U0001f514 ORPHAN MANAGER: Executed {executed} rule(s)")
                    except Exception as e:
                        log_exception("orphan_manager.monitor", e)

                schedule.every(30).seconds.do(_orphan_monitor_wrapper)

                schedule.every().day.at("03:30").do(self.cleanup_old_orders)

                logger.info(f"Scheduler started - reports every {self.config.report_frequency} minutes")

                while not self._shutdown_event.is_set():
                    try:
                        schedule.run_pending()

                    except RuntimeError as e:
                        logger.critical(f"FATAL SESSION ERROR: {e} - RESTARTING PROCESS")
                        if self.telegram_enabled:
                            try:
                                self.send_telegram(
                                    f"\U0001f6a8 <b>CRITICAL: SERVICE RESTART REQUIRED</b>\n"
                                    f"\u274c Session recovery failed\n"
                                    f"\U0001f504 Service will auto-restart in 5 seconds\n"
                                    f"\u23f0 Time: {datetime.now().strftime('%H:%M:%S')}",
                                    category="system"
                                )
                            except Exception as notify_error:
                                logger.error(f"Failed to send critical restart alert: {notify_error}")
                        time.sleep(5)
                        os._exit(1)

                    except Exception as e:
                        log_exception("scheduler.run_pending", e)

                    time.sleep(1)

            except Exception as e:
                log_exception("scheduler", e)

        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

    def start_control_intent_consumers(self):
        """
        Starts dashboard control intent consumers in background.

        - GenericControlIntentConsumer → ENTRY / EXIT / BASKET
        - StrategyControlConsumer     → STRATEGY lifecycle only
        """
        try:
            generic_consumer = GenericControlIntentConsumer(
                bot=self,
                stop_event=self._shutdown_event,
            )
            self._generic_control_thread = threading.Thread(
                target=generic_consumer.run_forever,
                daemon=True,
                name="GenericControlIntentConsumer",
            )
            self._generic_control_thread.start()

            strategy_consumer = StrategyControlConsumer(
                strategy_manager=self,
                stop_event=self._shutdown_event,
            )
            self._strategy_control_thread = threading.Thread(
                target=strategy_consumer.run_forever,
                daemon=True,
                name="StrategyControlConsumer",
            )
            self._strategy_control_thread.start()

            logger.info("\U0001f9ed Dashboard control intent consumers started")

        except Exception as e:
            log_exception("start_control_intent_consumers", e)

    def cleanup_old_orders(self):
        """Periodic DB hygiene: remove closed / failed orders older than 3 days."""
        try:
            deleted = self.order_repo.cleanup_old_closed_orders(days=3)
            if deleted > 0:
                logger.info(f"\U0001f9f9 DB CLEANUP | removed {deleted} old closed orders")
        except Exception as e:
            log_exception("db_cleanup", e)

    def get_account_info(self):
        """
        Get consolidated account information using ShoonyaClient.
        Compatibility replacement for removed shoonya_api.py
        """
        try:
            self._ensure_login()
            limits = self.broker_view.get_limits()
            positions = self.broker_view.get_positions()
            orders = self.broker_view.get_order_book()

            if limits is None:
                return None

            return AccountInfo.from_api_data(limits, positions, orders)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"ACCOUNT_INFO_FAILED: {e}")

    def get_bot_stats(self) -> BotStats:
        """Get bot statistics"""
        return BotStats.from_trade_records(self.trade_records)

    def send_daily_summary(self):
        """Send daily summary at market opening"""
        try:
            if not self.telegram_enabled:
                return

            message = f"\U0001f305 <b>GOOD MORNING!</b>\n"
            message += f"\U0001f4c5 {datetime.now().strftime('%A, %B %d, %Y')}\n"
            message += f"\U0001f558 Market Opening Soon\n\n"
            message += f"\U0001f916 Bot Status: \u2705 Ready for Trading\n"
            message += f"\U0001f4b0 Account: Connected & Active\n\n"

            yesterday_trades = get_yesterday_trades(self.trade_records)

            message += f"\U0001f4ca Yesterday's Performance:\n"
            if yesterday_trades:
                successful_trades = len([t for t in yesterday_trades if t.status in ("PLACED", "Ok", "FILLED")])
                success_rate = calculate_success_rate(successful_trades, len(yesterday_trades))
                message += f"\u2022 Total Trades: {len(yesterday_trades)}\n"
                message += f"\u2022 Successful: {successful_trades}\n"
                message += f"\u2022 Success Rate: {success_rate:.1f}%\n"
            else:
                message += f"\u2022 No trades executed yesterday\n"

            message += f"\n\U0001f3af Ready for today's opportunities!"
            self.send_telegram(message, category="reports")

        except Exception as e:
            log_exception("send_daily_summary", e)

    def send_market_close_summary(self):
        """Send summary at market close"""
        try:
            if not self.telegram_enabled:
                return

            today_trades = get_today_trades(self.trade_records)

            message = f"\U0001f306 <b>MARKET CLOSED</b>\n"
            message += f"\U0001f4c5 {datetime.now().strftime('%Y-%m-%d')}\n"
            message += f"{'='*25}\n\n"

            if today_trades:
                successful_trades = len([t for t in today_trades if t.status in ("PLACED", "Ok", "FILLED")])
                success_rate = calculate_success_rate(successful_trades, len(today_trades))

                message += f"\U0001f4ca <b>Today's Summary:</b>\n"
                message += f"\u2022 Total Trades: {len(today_trades)}\n"
                message += f"\u2022 Successful: {successful_trades}\n"
                message += f"\u2022 Failed: {len(today_trades) - successful_trades}\n"
                message += f"\u2022 Success Rate: {success_rate:.1f}%\n"

                strategies = defaultdict(int)
                for trade in today_trades:
                    strategies[trade.strategy_name] += 1

                if len(strategies) > 1:
                    message += f"\n\U0001f4cb <b>Strategy Breakdown:</b>\n"
                    for strategy, count in strategies.items():
                        message += f"\u2022 {strategy}: {count} trades\n"
            else:
                message += f"\U0001f4ca No trades executed today\n"

            message += f"\n\U0001f634 Bot will continue monitoring overnight"
            self.send_telegram(message, category="reports")

        except Exception as e:
            log_exception("send_market_close_summary", e)

    def send_telegram_heartbeat(self):
        """Send periodic heartbeat with session validation"""
        try:
            if not self.telegram_enabled:
                return

            # 1. Validate session by fetching limits
            try:
                limits = self.broker_view.get_limits(force_refresh=True)
                if not limits or not isinstance(limits, dict):
                    raise RuntimeError("BROKER_SESSION_INVALID")
                session_status = "\u2705 Live"
                cash = float(limits.get('cash', 0))
            except Exception as e:
                logger.error(f"Heartbeat session check failed: {e}")
                session_status = "\u274c Disconnected"
                cash = 0.0

                try:
                    self._ensure_login()
                    self.broker_view.invalidate_cache("limits")
                    limits = self.broker_view.get_limits(force_refresh=True)
                    if limits and isinstance(limits, dict):
                        session_status = "\u2705 Recovered"
                        cash = float(limits.get('cash', 0))
                        logger.info("Heartbeat session recovered after explicit revalidation")
                except Exception as recovery_error:
                    logger.error(f"Heartbeat session recovery failed: {recovery_error}")

            # 2. Get positions count
            try:
                positions = self.broker_view.get_positions()
                active_pos = sum(1 for p in positions if int(p.get('netqty', 0)) != 0)
            except Exception as position_error:
                logger.warning(f"Could not fetch positions for heartbeat: {position_error}")
                active_pos = 0

            # 3. Send compact heartbeat
            now = datetime.now()
            message = (
                f"\U0001f493 <b>SYSTEM HEARTBEAT</b>\n"
                f"\u23f0 {now.strftime('%H:%M:%S')} | {now.strftime('%d-%b-%Y')}\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\U0001f510 Session: {session_status}\n"
                f"\U0001f4b0 Cash: \u20b9{cash:,.2f}\n"
                f"\U0001f4ca Positions: {active_pos}\n"
                f"\U0001f916 Status: Active & Monitoring"
            )

            self.send_telegram(message, category="reports")
            logger.debug("Heartbeat sent")

        except Exception as e:
            log_exception("send_telegram_heartbeat", e)

    def send_status_report(self):
        """Send comprehensive status report"""
        try:
            self.risk_manager.heartbeat()
        except RuntimeError:
            raise

        try:
            if not self.telegram_enabled:
                return

            logger.info("Generating status report...")
            try:
                self._ensure_login()
            except Exception:
                return

            account_info = self.get_account_info()
            bot_stats = self.get_bot_stats()
            risk_status = self.risk_manager.get_status()

            session_valid = False
            try:
                limits = self.broker_view.get_limits()
                session_valid = limits is not None and isinstance(limits, dict)
            except Exception as limits_error:
                logger.warning(f"Could not fetch limits for status report: {limits_error}")

            message = f"\U0001f4ca <b>BOT STATUS REPORT</b>\n"
            message += f"\U0001f4c5 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"{'='*30}\n\n"

            message += f"\U0001f916 <b>BOT STATUS:</b> \u2705 Active\n"
            message += f"\U0001f510 <b>Login Status:</b> {'\u2705 Connected' if session_valid else '\u274c Disconnected'}\n\n"

            if account_info:
                message += f"\U0001f4b0 <b>ACCOUNT LIMITS</b>\n"
                message += f"\U0001f4b5 Available Cash: {format_currency(account_info.available_cash)}\n"
                message += f"\U0001f4ca Used Margin: {format_currency(account_info.used_margin)}\n\n"

                active_positions = [
                    pos for pos in account_info.positions
                    if isinstance(pos, dict) and pos.get('netqty', '0') != '0'
                ]

                if active_positions:
                    message += f"\U0001f50d <b>ACTIVE POSITIONS</b>\n"
                    for pos in active_positions[:3]:
                        symbol = pos.get('tsym', 'Unknown')
                        qty = pos.get('netqty', '0')
                        try:
                            rpnl = float(pos.get('rpnl', 0) or 0)
                        except (ValueError, TypeError):
                            rpnl = 0.0
                        try:
                            urmtom = float(pos.get('urmtom', 0) or 0)
                        except (ValueError, TypeError):
                            urmtom = 0.0
                        pnl = rpnl + urmtom

                        message += f"\u2022 {symbol}: {qty} qty, PnL: {format_currency(pnl)}\n"
                    if len(active_positions) > 3:
                        message += f"... and {len(active_positions) - 3} more positions\n"
                    message += "\n"
                else:
                    message += f"\U0001f50d <b>POSITIONS:</b> No active positions\n\n"
            else:
                message += f"\u26a0\ufe0f <b>ACCOUNT INFO:</b> Unable to fetch data\n\n"

            message += f"\U0001f4c8 <b>TRADING STATS</b>\n"
            message += f"\U0001f4ca Today's Trades: {bot_stats.today_trades}\n"
            message += f"\U0001f4cb Total Trades: {bot_stats.total_trades}\n"

            if bot_stats.last_activity:
                last_trade_time = datetime.fromisoformat(bot_stats.last_activity)
                message += f"\U0001f555 Last Activity: {last_trade_time.strftime('%H:%M:%S')}\n"
            else:
                message += f"\U0001f555 Last Activity: No trades yet\n"

            message += f"\n\U0001f6e1 <b>RISK MANAGER STATUS</b>\n"
            message += f"\u2022 Daily PnL: \u20b9{risk_status['daily_pnl']:.2f}\n"
            message += f"\u2022 Loss Hit Today: {'YES' if risk_status['daily_loss_hit'] else 'NO'}\n"

            if risk_status.get("cooldown_until"):
                message += f"\u2022 Cooldown Until: {risk_status['cooldown_until']}\n"

            message += f"\n\U0001f514 <i>Next report in {self.config.report_frequency} minutes</i>"

            self.send_telegram(message, category="reports")
            logger.info("Status report sent")

        except Exception as e:
            log_exception("send_status_report", e)
            if self.telegram_enabled and self.telegram:
                try:
                    self.telegram.send_error_message("STATUS REPORT ERROR", str(e))
                except Exception as tg_e:
                    logger.warning(f"Failed to send error message: {tg_e}")

    def get_trade_history(self, limit: Optional[int] = None,
                         date_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get trade history with optional filtering"""
        trades = self.trade_records.copy()

        if date_filter:
            filter_date = get_date_filter(date_filter)
            if filter_date:
                trades = [
                    t for t in trades
                    if datetime.fromisoformat(t.timestamp).date() == filter_date
                ]

        if limit and limit > 0:
            trades = trades[-limit:]

        return [trade.to_dict() for trade in trades]

    def get_session_info(self) -> Dict[str, Any]:
        """Get current session information"""
        api_session = self.api.get_session_info()
        bot_stats = self.get_bot_stats()

        return {
            'api_session': api_session,
            'telegram_enabled': self.telegram_enabled,
            'telegram_connected': self.telegram.is_connected if (self.telegram and hasattr(self.telegram, 'is_connected')) else False,
            'trade_stats': {
                'total_trades': bot_stats.total_trades,
                'today_trades': bot_stats.today_trades,
                'success_rate': bot_stats.success_rate,
                'last_activity': bot_stats.last_activity
            },
            'config': {
                'report_frequency': self.config.report_frequency,
                'max_retry_attempts': self.config.max_retry_attempts,
                'retry_delay': self.config.retry_delay
            }
        }

    def test_telegram(self) -> bool:
        """Test Telegram connectivity"""
        if not self.telegram_enabled or not self.telegram:
            return False

        return self.telegram.send_test_message()
