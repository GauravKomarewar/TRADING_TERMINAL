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
import argparse
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
_dashboard_port: int = 8000  # Set by main() before dashboard thread starts


# ---------------------------------------------------------------------
# GRACEFUL SHUTDOWN HANDLER (SYSTEMD SAFE)
# ---------------------------------------------------------------------
def signal_handler(signum, frame):
    global bot_instance, logger, dashboard_server, shutdown_event
    
    shutdown_start = time.time()

    if logger:
        logger.warning(f"🛑 Received shutdown signal: {signum}")
        logger.info("Initiating graceful shutdown sequence (30s timeout)...")

    # 1️⃣ Global shutdown flag (stops all loops immediately)
    shutdown_event.set()

    # 2️⃣ Shutdown bot FIRST (owns feed, supervisor, watcher) — 25s timeout
    if bot_instance:
        try:
            if logger:
                logger.info("🤖 Shutting down trading bot...")
            bot_instance.shutdown()
        except Exception as e:
            if logger:
                logger.error(f"❌ Error shutting down bot: {e}")

    # 3️⃣ Stop dashboard server (non-blocking)
    if dashboard_server:
        try:
            if logger:
                logger.info("📊 Stopping dashboard server...")
            dashboard_server.should_exit = True
        except Exception as e:
            if logger:
                logger.error(f"❌ Error stopping dashboard: {e}")

    # 4️⃣ Wait for dashboard thread (5s timeout)
    elapsed = time.time() - shutdown_start
    remaining = max(5, 30 - elapsed)  # At least 5s for dashboard
    
    if dashboard_thread and dashboard_thread.is_alive():
        if logger:
            logger.info(f"⏳ Waiting for dashboard thread (timeout={remaining:.1f}s)...")
        dashboard_thread.join(timeout=remaining)
        if dashboard_thread.is_alive():
            if logger:
                logger.warning("⚠️ Dashboard thread did not exit gracefully - force exiting")

    elapsed = time.time() - shutdown_start
    if logger:
        logger.info(f"✅ Graceful shutdown complete in {elapsed:.1f}s")
    
    # Force exit (systemd will restart if configured)
    sys.exit(0)

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
            dashboard_port = _dashboard_port
            config_uv = uvicorn.Config(
                app=app,
                host="0.0.0.0",
                port=dashboard_port,
                log_level="info",
                loop="asyncio",
                lifespan="on",
                access_log=True,
            )

            dashboard_server = uvicorn.Server(config_uv)

            if logger:
                logger.info(
                    f"📊 Dashboard starting on port {dashboard_port} | PID={os.getpid()} | Thread={threading.current_thread().name}"
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

    # -------------------------------------------------
    # CLI ARGUMENT PARSING (MULTI-CLIENT SUPPORT)
    # -------------------------------------------------
    parser = argparse.ArgumentParser(description="Shoonya Trading Platform")
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to client .env file (e.g. config_env/yeleshwar_a_komarewar.env)"
    )
    args = parser.parse_args()

    # Resolve env path
    env_path = None
    if args.env:
        env_path = Path(args.env)
        if not env_path.is_absolute():
            env_path = Path(__file__).resolve().parent / env_path

    try:
        # -------------------------------------------------
        # CONFIG LOADING (FIRST — needed for client_id in logs)
        # -------------------------------------------------
        config = Config(env_path=env_path)
        client_identity = config.get_client_identity()
        client_id = client_identity["client_id"]
        # Extract short name for file paths (e.g. "FA14667" from "GAURAV_Y_KOMAREWAR:FA14667")
        client_short = config.user_id

        # -------------------------------------------------
        # LOGGING SETUP (PER-CLIENT LOG DIRECTORY)
        # -------------------------------------------------
        # Each client gets its own log subdirectory to avoid file conflicts
        base_dir = Path(__file__).resolve().parent
        logs_dir = base_dir / "logs" / client_short
        
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
        # SERVER CONFIG
        # -------------------------------------------------
        logger.info("Configuration loaded for client: %s", client_id)
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
        _dashboard_port = config.dashboard_port
        
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
        
        logger.info(f"✅ Dashboard started on port {config.dashboard_port} (shared session)")

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
            ident="Trading-Service/2.0",
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