#!/usr/bin/env python3
"""
EXECUTION SERVICE ENTRY POINT (PRODUCTION — FREEZE-READY)
==========================================================

Purpose:
- Run TradingView webhook execution service
- Enforce SupremeRiskManager + ExecutionGuard
- Handle Telegram commands (read-only / safety)
- Expose health & status endpoints
- Co-host dashboard in same process (shared session)

STRICT RULES:
- NO separate broker login for dashboard
- NO manual trading endpoints
- NO strategy logic here
- SINGLE ShoonyaBot instance (shared memory)

ARCHITECTURAL NOTE:
- Execution service (Waitress) has PRIORITY
- Dashboard responsiveness may degrade under heavy webhook load
- This is ACCEPTABLE and INTENTIONAL for execution safety

PRODUCTION HARDENING:
- Graceful shutdown coordination
- Thread-safe uvicorn server
- Proper signal handling
- Dashboard auto-restart
- Fail-fast on startup errors
"""

import sys
import os
import signal
import logging
import threading
import time
from pathlib import Path
from typing import Optional

# CRITICAL: Fix Windows console encoding for Unicode support BEFORE any imports
if sys.platform == "win32":
    import io
    import logging
    
    # Wrap both stdout and stderr with UTF-8 encoding (handles emoji gracefully)
    # Do this EXTRA early to catch all logging initialization
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    
    # Suppress logging module's exception handling for Unicode errors
    logging.raiseExceptions = False

from waitress import serve
import uvicorn

from shoonya_platform.core.config import Config
from shoonya_platform.execution.trading_bot import ShoonyaBot, set_global_bot
from shoonya_platform.api.http.execution_app import ExecutionApp
from shoonya_platform.api.dashboard.dashboard_app import create_dashboard_app
from shoonya_platform.logging.logger_config import setup_application_logging, get_component_logger
from shoonya_platform.utils.utils import log_exception

# ---------------------------------------------------------------------
# GLOBALS (FOR SIGNAL HANDLING & THREAD COORDINATION)
# ---------------------------------------------------------------------
bot_instance: Optional[ShoonyaBot] = None
logger: Optional[logging.Logger] = None
dashboard_server: Optional[uvicorn.Server] = None
dashboard_thread: Optional[threading.Thread] = None
shutdown_event = threading.Event()


# ---------------------------------------------------------------------
# GRACEFUL SHUTDOWN HANDLER (SYSTEMD SAFE)
# ---------------------------------------------------------------------
def signal_handler(signum, frame):
    global bot_instance, logger, dashboard_server, shutdown_event

    if logger:
        logger.warning(f"🛑 Received shutdown signal: {signum}")
        logger.info("Initiating graceful shutdown sequence...")

    # 1️⃣ Global shutdown flag
    shutdown_event.set()

    # 2️⃣ Shutdown bot FIRST (owns feed, supervisor, watcher)
    if bot_instance:
        try:
            if logger:
                logger.info("Shutting down trading bot...")
            bot_instance.shutdown()
        except Exception as e:
            if logger:
                logger.error(f"Error shutting down bot: {e}")

    # 3️⃣ Stop dashboard server
    if dashboard_server:
        try:
            if logger:
                logger.info("Stopping dashboard server...")
            dashboard_server.should_exit = True
        except Exception as e:
            if logger:
                logger.error(f"Error stopping dashboard: {e}")

    # 4️⃣ Wait for dashboard thread
    if dashboard_thread and dashboard_thread.is_alive():
        if logger:
            logger.info("Waiting for dashboard thread to terminate...")
        dashboard_thread.join(timeout=5.0)

    if logger:
        logger.info("✅ Shutdown complete")

# ---------------------------------------------------------------------
# DASHBOARD RUNNER (THREAD-SAFE UVICORN WITH AUTO-RESTART)
# ---------------------------------------------------------------------
def run_dashboard():
    """
    Run dashboard using uvicorn.Server (NOT uvicorn.run).
    This is thread-safe and doesn't hijack signal handlers.
    
    CRITICAL FIX: Auto-restart on crash (dashboard crashes don't kill execution)
    """
    global dashboard_server, logger, shutdown_event

    while not shutdown_event.is_set():
        try:
            app = create_dashboard_app()

            # Create Server instance (not run() helper)
            config = uvicorn.Config(
                app=app,
                host="0.0.0.0",
                port=8000,
                log_level="info",
                loop="asyncio",
                lifespan="on",
                access_log=True,
            )

            dashboard_server = uvicorn.Server(config)

            if logger:
                logger.info(
                    f"📊 Dashboard starting | PID={os.getpid()} | Thread={threading.current_thread().name}"
                )

            # This will block until server.should_exit is set
            dashboard_server.run()

            if logger:
                logger.info("Dashboard server stopped")
            
            # If we exit cleanly (shutdown_event set), don't restart
            if shutdown_event.is_set():
                break

        except Exception as exc:
            if logger:
                log_exception("dashboard_thread", exc)
                logger.error(f"Dashboard crashed: {exc}")
            
            # Don't restart if shutting down
            if shutdown_event.is_set():
                break
            
            # Wait before restart to avoid rapid crash loops
            if logger:
                logger.warning("Dashboard will restart in 5 seconds...")
            time.sleep(5)


# ---------------------------------------------------------------------
# MAIN (PRODUCTION ONLY)
# ---------------------------------------------------------------------
def main():
    global bot_instance, logger, dashboard_thread

    try:
        # -------------------------------------------------
        # LOGGING SETUP (CENTRALIZED WITH LOG ROTATION)
        # -------------------------------------------------
        # Setup application-wide logging with per-component rotating handlers
        # Each service gets its own log file with 50MB rotation and 10 backups
        base_dir = Path(__file__).resolve().parent
        logs_dir = base_dir / "logs"
        
        setup_application_logging(
            log_dir=str(logs_dir),
            level="INFO",
            max_bytes=50 * 1024 * 1024,  # 50 MB per file
            backup_count=10,  # Keep 10 backups
            quiet_uvicorn=True
        )
        
        # Get the execution service logger
        logger = get_component_logger('execution_service')

        logger.info("=" * 70)
        logger.info("🚀 STARTING EXECUTION SERVICE (PRODUCTION — FREEZE-READY)")
        logger.info("=" * 70)
        logger.info(f"PID: {os.getpid()}")
        logger.info(f"Python: {sys.version}")
        logger.info(f"CWD: {os.getcwd()}")
        logger.info("📋 Log files (rotating, 50MB max, 10 backups):")
        logger.info("   - execution_service.log (main service)")
        logger.info("   - trading_bot.log (bot logic)")
        logger.info("   - command_service.log (command execution)")
        logger.info("   - order_watcher.log (order tracking)")
        logger.info("   - risk_manager.log (risk management)")
        logger.info("   - execution_guard.log (trade guard)")
        logger.info("   - dashboard.log (dashboard API)")

        # -------------------------------------------------
        # CONFIG LOADING
        # -------------------------------------------------
        logger.info("Loading configuration...")
        config = Config()
        server_cfg = config.get_server_config()

        # -------------------------------------------------
        # BOT INITIALIZATION (SINGLE INSTANCE)
        # -------------------------------------------------
        logger.info("Initializing ShoonyaBot (SINGLE INSTANCE)")
        bot_instance = ShoonyaBot(config)
        
        # CRITICAL: Set global bot for dashboard access
        set_global_bot(bot_instance)
        logger.info("✅ Global bot instance registered")

        # -------------------------------------------------
        # SIGNAL HANDLERS (MUST BE IN MAIN THREAD)
        # -------------------------------------------------
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        logger.info("Signal handlers installed")

        # -------------------------------------------------
        # TELEGRAM STARTUP NOTIFICATION
        # -------------------------------------------------
        if bot_instance.telegram_enabled and bot_instance.telegram:
            bot_instance.telegram.send_startup_message(
                host=server_cfg["host"],
                port=server_cfg["port"],
                report_frequency=config.report_frequency,
            )

        # -------------------------------------------------
        # EXECUTION HTTP SERVICE (FLASK + WAITRESS)
        # -------------------------------------------------
        logger.info("Initializing execution HTTP service...")
        exec_app = ExecutionApp(bot_instance)
        flask_app = exec_app.get_app()

        logger.info("Execution service configuration:")
        logger.info(f"  Host       : {server_cfg['host']}")
        logger.info(f"  Port       : {server_cfg['port']}")
        logger.info(f"  Threads    : {server_cfg['threads']}")
        logger.info(f"  Telegram   : {'ENABLED' if bot_instance.telegram_enabled else 'DISABLED'}")

        # -------------------------------------------------
        # DASHBOARD SERVER (CO-HOSTED — SAME PROCESS)
        # NOTE: Execution service has priority.
        # Dashboard responsiveness may degrade under heavy webhook load.
        # This is ACCEPTABLE and intentional.
        # -------------------------------------------------
        logger.info("Starting dashboard server...")
        
        # NON-DAEMON thread (allows graceful shutdown)
        dashboard_thread = threading.Thread(
            target=run_dashboard,
            daemon=False,  # CRITICAL: Non-daemon for clean shutdown
            name="DashboardThread",
        )
        dashboard_thread.start()

        # Wait briefly to ensure dashboard started
        time.sleep(2)

        # CRITICAL FIX: Fail fast if dashboard dies immediately
        if not dashboard_thread.is_alive():
            logger.critical("❌ Dashboard thread died immediately — EXITING")
            sys.exit(1)
        
        logger.info("✅ Dashboard started on port 8000 (shared session)")

        # -------------------------------------------------
        # TELEGRAM READY NOTIFICATION
        # -------------------------------------------------
        if bot_instance.telegram_enabled and bot_instance.telegram:
            bot_instance.telegram.send_ready_message(
                host=server_cfg["host"],
                port=server_cfg["port"],
                report_frequency=config.report_frequency,
            )

        # -------------------------------------------------
        # START WAITRESS (BLOCKING — MAIN THREAD)
        # -------------------------------------------------
        logger.info("=" * 70)
        logger.info("✅ EXECUTION SERVICE READY — ACCEPTING WEBHOOKS")
        logger.info("=" * 70)

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
            ident="Shoonya-Execution-Service/2.0",
        )

    except KeyboardInterrupt:
        if logger:
            logger.info("Received keyboard interrupt")
        shutdown_event.set()

    except Exception as exc:
        if logger:
            log_exception("execution_service.main", exc)
            logger.critical(f"FATAL ERROR: {exc}", exc_info=True)
        else:
            print(f"CRITICAL ERROR: {exc}")
            import traceback
            traceback.print_exc()

        if bot_instance and bot_instance.telegram_enabled and bot_instance.telegram:
            try:
                bot_instance.telegram.send_error_message(
                    "🚨 EXECUTION SERVICE CRASHED",
                    str(exc),
                )
            except Exception as notify_error:
                logger.error(f"Failed to send crash notification via telegram: {notify_error}")

        sys.exit(1)

    finally:
        if logger:
            logger.info("🏁 Execution service stopped")


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------
if __name__ == "__main__":
    main()