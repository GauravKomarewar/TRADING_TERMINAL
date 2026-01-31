#!/usr/bin/env python3
"""
EXECUTION SERVICE ENTRY POINT (PRODUCTION — FROZEN)
===================================================

Purpose:
- Run TradingView webhook execution service
- Enforce SupremeRiskManager + ExecutionGuard
- Handle Telegram commands (read-only / safety)
- Expose health & status endpoints

STRICT RULES:
- NO dashboard
- NO templates
- NO dev server
- NO manual trading endpoints
- NO UI logic
- NO strategy logic here

This file is SYSTEMD-MANAGED and MUST NOT be modified.
"""

import sys
import signal
import logging
from pathlib import Path


from waitress import serve

from shoonya_platform.core.config import Config
from shoonya_platform.execution.trading_bot import ShoonyaBot
from shoonya_platform.api.http.execution_app import ExecutionApp
from shoonya_platform.utils.utils import setup_logging, log_exception

# ---------------------------------------------------------------------
# GLOBALS (FOR SIGNAL HANDLING)
# ---------------------------------------------------------------------
bot_instance = None
logger = None


# ---------------------------------------------------------------------
# SIGNAL HANDLER (SYSTEMD SAFE)
# ---------------------------------------------------------------------
def signal_handler(signum, frame):
    global bot_instance, logger

    if logger:
        logger.warning(f"Received shutdown signal: {signum}")

    if bot_instance:
        try:
            bot_instance.shutdown()
        except Exception:
            pass

    sys.exit(0)


# ---------------------------------------------------------------------
# MAIN (PRODUCTION ONLY)
# ---------------------------------------------------------------------
def main():
    global bot_instance, logger

    try:
        # -------------------------------------------------
        # LOGGING
        # -------------------------------------------------
        base_dir = Path(__file__).resolve().parent
        logs_dir = base_dir / "logs"

        logs_dir.mkdir(exist_ok=True)

        log_file = logs_dir / "execution_service.log"
        logger = setup_logging(str(log_file), "INFO")

        logger.info("=" * 70)
        logger.info("🚀 STARTING EXECUTION SERVICE (PRODUCTION)")
        logger.info("=" * 70)

        # -------------------------------------------------
        # CONFIG
        # -------------------------------------------------
        config = Config()

        # -------------------------------------------------
        # BOT INITIALIZATION
        # -------------------------------------------------
        logger.info("Initializing TradingService")
        bot_instance = ShoonyaBot(config)

        # -------------------------------------------------
        # SIGNALS
        # -------------------------------------------------
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # -------------------------------------------------
        # TELEGRAM STARTUP MESSAGE
        # -------------------------------------------------
        if bot_instance.telegram_enabled:
            server_cfg = config.get_server_config()
            bot_instance.telegram.send_startup_message(
                host=server_cfg["host"],
                port=server_cfg["port"],
                report_frequency=config.report_frequency,
            )

        # -------------------------------------------------
        # INITIAL LOGIN (NON-BLOCKING)
        # -------------------------------------------------
        logger.info("Attempting initial broker login")
        if bot_instance.login():
            logger.info("Broker login successful")
        else:
            logger.warning("Initial login failed — will retry on first execution")

        # -------------------------------------------------
        # EXECUTION-ONLY FLASK APP
        # -------------------------------------------------
        logger.info("Initializing execution HTTP service")
        exec_app = ExecutionApp(bot_instance)
        flask_app = exec_app.get_app()

        server_cfg = config.get_server_config()

        logger.info("Execution service configuration:")
        logger.info(f"  Host       : {server_cfg['host']}")
        logger.info(f"  Port       : {server_cfg['port']}")
        logger.info(f"  Threads    : {server_cfg['threads']}")
        logger.info(f"  Telegram   : {'ENABLED' if bot_instance.telegram_enabled else 'DISABLED'}")

        if bot_instance.telegram_enabled:
            bot_instance.telegram.send_ready_message(
                host=server_cfg["host"],
                port=server_cfg["port"],
                report_frequency=config.report_frequency,
            )

        # -------------------------------------------------
        # START WAITRESS (BLOCKING)
        # -------------------------------------------------
        logger.info("✅ Execution service READY — accepting webhooks")

        serve(
            flask_app,
            host=server_cfg["host"],
            port=server_cfg["port"],
            threads=server_cfg["threads"],
            connection_limit=1000,
            cleanup_interval=30,
            channel_timeout=120,
            max_request_header_size=8192,
            max_request_body_size=1048576,  # 1 MB
            expose_tracebacks=False,
            ident="Shoonya-Execution-Service",
        )

    except Exception as exc:
        if logger:
            log_exception("execution_service.main", exc)
        else:
            print(f"CRITICAL ERROR: {exc}")

        if bot_instance and bot_instance.telegram_enabled:
            bot_instance.telegram.send_error_message(
                "EXECUTION SERVICE CRASHED",
                str(exc),
            )

        sys.exit(1)

    finally:
        if logger:
            logger.info("Execution service stopped")


# ---------------------------------------------------------------------
# ENTRY
# ---------------------------------------------------------------------
if __name__ == "__main__":
    main()
