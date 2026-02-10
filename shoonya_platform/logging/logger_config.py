#!/usr/bin/env python3
"""
CENTRALIZED LOGGING CONFIGURATION
==================================

Purpose:
- Setup per-component loggers with rotating file handlers
- Isolate logs by service: dashboard, trading_bot, risk_manager, order_watcher, command_service, execution_guard
- Each logger has its own rotating log file (50MB, 10 backups)
- All logs also go to console with clean formatting
- Safe for multi-process setups (no race conditions)

USAGE:
    from shoonya_platform.logging.logger_config import setup_application_logging, get_component_logger
    
    # Setup once in main
    setup_application_logging(log_dir="logs", level="INFO")
    
    # Get logger in each module
    logger = get_component_logger("trading_bot")
    
Component Loggers:
    - EXECUTION_SERVICE (main.py)
    - TRADING_BOT (ShoonyaBot)
    - RISK_MANAGER (SupremeRiskManager)
    - ORDER_WATCHER (OrderWatcherEngine)
    - COMMAND_SERVICE (CommandService)
    - EXECUTION_GUARD (ExecutionGuard)
    - DASHBOARD (Dashboard API)
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Dict

# Standard format: [TIMESTAMP] [LEVEL] [COMPONENT] [MESSAGE]
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
LOG_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# Component names - use these consistently
# Key → (logger_name, log_filename)
# Loggers using __name__ (e.g. 'shoonya_platform.execution.broker') are
# children of their parent logger, so we register parent loggers as well.
COMPONENT_NAMES = {
    # ---- Core execution ----
    'execution_service': 'EXECUTION_SERVICE',
    'trading_bot':       'TRADING_BOT',
    'risk_manager':      'RISK_MANAGER',
    'order_watcher':     'ORDER_WATCHER',
    'command_service':   'COMMAND_SERVICE',
    'execution_guard':   'EXECUTION_GUARD',
    'recovery':          'RECOVERY_SERVICE',

    # ---- Dashboard & API ----
    'dashboard':         'DASHBOARD',          # parent of DASHBOARD.APP, DASHBOARD.INTENT, etc.

    # ---- Market Data ----
    'market_data':       'shoonya_platform.market_data',   # catches supervisor, store, option_chain, feeds, instruments

    # ---- Strategies ----
    'strategy':          'STRATEGY_RUNNER',
    'strategy_db':       'STRATEGY_RUNNER_DB',

    # ---- Broker / Engine ----
    'broker':            'shoonya_platform.brokers',       # catches shoonya client logs
    'engine':            'ENGINE',
    'execution_control': 'EXECUTION.CONTROL',

    # ---- Services ----
    'services':          'shoonya_platform.services',      # catches service_manager, recovery_service via __name__

    # ---- Execution sub-modules (use __name__) ----
    'execution':         'shoonya_platform.execution',     # catches position_exit_service, intent_tracker, broker.py, etc.

    # ---- Notifications / Telegram ----
    'notifications':     'notifications',

    # ---- Core / Config ----
    'core':              'shoonya_platform.core',
}

# Global configuration
_log_dir: Optional[Path] = None
_log_level: str = 'INFO'
_console_handler: Optional[logging.StreamHandler] = None
_component_handlers: Dict[str, logging.handlers.RotatingFileHandler] = {}


def setup_application_logging(
    log_dir: str = 'logs',
    level: str = 'INFO',
    max_bytes: int = 50 * 1024 * 1024,  # 50 MB per file
    backup_count: int = 10,  # Keep 10 backups
    quiet_uvicorn: bool = True
) -> None:
    """
    Initialize application-wide logging with per-component rotating handlers.
    
    This MUST be called once at application startup (in main()).
    
    Args:
        log_dir: Directory to store log files
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_bytes: Max size of a log file before rotation (default 50MB)
        backup_count: Number of backup files to keep (default 10)
        quiet_uvicorn: Suppress uvicorn access logs (default True)
    """
    global _log_dir, _log_level, _console_handler
    
    _log_dir = Path(log_dir)
    _log_level = level
    
    # Create logs directory
    _log_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove any existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATETIME_FORMAT)
    
    # Add console handler (shared by all loggers)
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setLevel(getattr(logging, level.upper()))
    _console_handler.setFormatter(formatter)
    root_logger.addHandler(_console_handler)
    
    # Suppress uvicorn access logs if requested
    if quiet_uvicorn:
        logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    
    # Initialize component-specific handlers
    _setup_component_handlers(max_bytes, backup_count, formatter)

    # 🔒 CATCH-ALL: root file handler so NO log message is lost.
    # When running as a systemd service, console output may be truncated.
    # This file catches everything that doesn't match a component handler.
    _root_log_file = _log_dir / "application.log"
    _root_fh = logging.handlers.RotatingFileHandler(
        _root_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
    )
    _root_fh.setLevel(getattr(logging, level.upper()))
    _root_fh.setFormatter(formatter)
    root_logger.addHandler(_root_fh)


def _setup_component_handlers(max_bytes: int, backup_count: int, formatter: logging.Formatter) -> None:
    """
    Setup rotating file handlers for each component and IMMEDIATELY attach them.

    Previously handlers were created here but only attached in get_component_logger().
    This meant any module that used logging.getLogger() instead of get_component_logger()
    would never get a file handler — losing all logs when running as a systemd service.
    """
    global _component_handlers
    
    for key, component_name in COMPONENT_NAMES.items():
        log_file = _log_dir / f"{key}.log"
        
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        handler.setLevel(getattr(logging, _log_level.upper()))
        handler.setFormatter(formatter)
        
        _component_handlers[component_name] = handler

        # 🔧 IMMEDIATELY attach handler to the named logger.
        # This covers both:
        #   - Modules using get_component_logger('trading_bot') → logger name 'TRADING_BOT'
        #   - Modules using logging.getLogger(__name__)         → logger name 'shoonya_platform.execution.xyz'
        #     (these propagate up to parent logger 'shoonya_platform.execution')
        logger = logging.getLogger(component_name)
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(handler)


def get_component_logger(component_key: str) -> logging.Logger:
    """
    Get or create a logger for a specific component.
    
    Args:
        component_key: Key from COMPONENT_NAMES dict
        
    Returns:
        Configured logger for the component
        
    Example:
        logger = get_component_logger('trading_bot')
        logger.info("Starting bot initialization")
    """
    if component_key not in COMPONENT_NAMES:
        raise ValueError(f"Unknown component: {component_key}. Must be one of {list(COMPONENT_NAMES.keys())}")
    
    component_name = COMPONENT_NAMES[component_key]
    logger = logging.getLogger(component_name)
    
    # Add file handler if not already added
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        if component_name in _component_handlers:
            logger.addHandler(_component_handlers[component_name])
    
    return logger


def rotate_logs() -> Dict[str, str]:
    """
    Manually trigger rotation of all log files.
    Useful for scheduled maintenance or before sharing logs.
    
    Returns:
        Dict mapping component names to rotated file paths
    """
    result = {}
    for component_name, handler in _component_handlers.items():
        try:
            handler.doRollover()
            result[component_name] = f"Rotated: {handler.baseFilename}"
        except Exception as e:
            result[component_name] = f"Failed to rotate: {e}"
    
    return result


def get_log_files() -> Dict[str, Path]:
    """
    Get paths to all active log files.
    
    Returns:
        Dict mapping component names to log file paths
    """
    result = {}
    for component_name, handler in _component_handlers.items():
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            result[component_name] = Path(handler.baseFilename)
    
    return result


def export_logs_summary() -> Dict[str, Dict]:
    """
    Get summary of all log files (exists, size, lines).
    Useful for monitoring log disk usage.
    
    Returns:
        Dict with summary statistics for each log file
    """
    summary = {}
    
    for component_name, log_path in get_log_files().items():
        if log_path.exists():
            size_mb = log_path.stat().st_size / (1024 * 1024)
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = len(f.readlines())
            except Exception:
                lines = 0
            
            summary[component_name] = {
                'path': str(log_path),
                'size_mb': round(size_mb, 2),
                'lines': lines,
                'exists': True
            }
        else:
            summary[component_name] = {
                'path': str(log_path),
                'exists': False
            }
    
    return summary


class ServiceLogger:
    """
    Convenience wrapper for component loggers with structured logging.
    
    Example:
        svc_logger = ServiceLogger('trading_bot')
        svc_logger.startup("Bot starting initialization")
        svc_logger.event("order", "BUY", symbol="INFY10JAN2026C1450")
        svc_logger.error_with_context("Order failed", order_id=123, error=exc)
    """
    
    def __init__(self, component_key: str):
        self.logger = get_component_logger(component_key)
        self.component = COMPONENT_NAMES[component_key]
    
    def startup(self, message: str):
        """Log component startup"""
        self.logger.info(f"🚀 STARTUP: {message}")
    
    def shutdown(self, message: str):
        """Log component shutdown"""
        self.logger.info(f"🛑 SHUTDOWN: {message}")
    
    def event(self, event_type: str, action: str, **context):
        """Log a business event"""
        ctx_str = " | ".join(f"{k}={v}" for k, v in context.items())
        msg = f"[{event_type.upper()}] {action}"
        if ctx_str:
            msg += f" | {ctx_str}"
        self.logger.info(msg)
    
    def warning(self, message: str, **context):
        """Log warning with context"""
        ctx_str = " | ".join(f"{k}={v}" for k, v in context.items())
        msg = f"⚠️  {message}"
        if ctx_str:
            msg += f" | {ctx_str}"
        self.logger.warning(msg)
    
    def error_with_context(self, message: str, **context):
        """Log error with structured context"""
        ctx_str = " | ".join(f"{k}={v}" for k, v in context.items())
        msg = f"❌ {message}"
        if ctx_str:
            msg += f" | {ctx_str}"
        self.logger.error(msg)
    
    def debug_trace(self, message: str, **context):
        """Log debug trace with context"""
        ctx_str = " | ".join(f"{k}={v}" for k, v in context.items())
        msg = f"[TRACE] {message}"
        if ctx_str:
            msg += f" | {ctx_str}"
        self.logger.debug(msg)


# Backward compatibility: setup_logging returns root logger
def setup_logging(log_file: str = 'webhook_bot.log', log_level: str = 'INFO') -> logging.Logger:
    """
    DEPRECATED: Use setup_application_logging() and get_component_logger() instead.
    
    This function is kept for backward compatibility only.
    """
    from logging.handlers import RotatingFileHandler
    
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATETIME_FORMAT)
    
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=50 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.setFormatter(formatter)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return root_logger
