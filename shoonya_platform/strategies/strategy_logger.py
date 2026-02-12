#!/usr/bin/env python3
"""
Strategy Logger System
======================

Purpose:
- Per-strategy logging with file persistence
- Memory buffer for real-time UI streaming
- Rotating file handler to prevent disk bloat
- Thread-safe logging across strategies
- Intelligent logging: only log on initialization, monitoring intervals, and actions

Features:
- Logs to: logs/strategies/{strategy_name}.log
- In-memory buffer: Last 1000 lines
- Rotation: 10MB per file, 5 backups
- Filtering: DEBUG, INFO, WARNING, ERROR
- Smart logging: Prevent spam, only log meaningful events

Logging Levels:
- INFO:    Strategy initialization, actions, user events
- WARNING: Issues, threshold breaches
- ERROR:   Failed operations, exceptions
- DEBUG:   Disabled by default (no spam)

Status: PRODUCTION READY
Date: 2026-02-12
"""

import logging
import logging.handlers
from pathlib import Path
from collections import deque
from typing import List, Optional, Dict
from datetime import datetime
import threading
import time

# Create logs/strategies directory
LOGS_DIR = Path(__file__).resolve().parents[2] / "logs" / "strategies"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class MemoryHandler(logging.Handler):
    """Handler that stores logs in memory for UI streaming"""
    
    def __init__(self):
        super().__init__()
        self.buffer: deque = deque(maxlen=1000)
        self.lock: Optional[threading.Lock] = threading.Lock()
    
    def emit(self, record: logging.LogRecord):
        """Store log record in memory"""
        try:
            msg = self.format(record)
            assert self.lock is not None
            with self.lock:
                self.buffer.append({
                    "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": msg
                })
        except Exception:
            self.handleError(record)
    
    def get_logs(self, lines: int = 100, level: Optional[str] = None) -> List[Dict]:
        """Get logs from buffer, optionally filtered by level.
        
        Args:
            lines: Number of recent lines to return
            level: Optional log level filter (DEBUG, INFO, WARNING, ERROR)
            
        Returns:
            List of log records as dictionaries
        """
        assert self.lock is not None
        with self.lock:
            logs = list(self.buffer)
        
        logs = logs[-lines:] if lines > 0 else logs
        
        if level:
            logs = [log for log in logs if log['level'].upper() == level.upper()]
        
        return logs
    
    def clear(self):
        """Clear memory buffer"""
        assert self.lock is not None
        with self.lock:
            self.buffer.clear()


class StrategyLogger:
    """Logger for individual strategy with intelligent logging control"""
    
    def __init__(self, strategy_name: str):
        """
        Initialize strategy logger.
        
        Args:
            strategy_name: Name of strategy (used for log file)
        """
        self.strategy_name = strategy_name
        self.log_file = LOGS_DIR / f"{strategy_name}.log"
        
        # Create logger - set to INFO level to avoid DEBUG spam
        self.logger = logging.getLogger(f"STRATEGY.{strategy_name}")
        self.logger.setLevel(logging.INFO)  # Only INFO and above by default
        
        # Remove any existing handlers
        self.logger.handlers.clear()
        
        # Add file handler (rotating)
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=10_000_000,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.INFO)  # Only INFO and above
        file_handler.setFormatter(self._get_formatter())
        self.logger.addHandler(file_handler)
        
        # Add memory handler (for UI streaming)
        self.memory_handler = MemoryHandler()
        self.memory_handler.setLevel(logging.INFO)  # Only INFO and above
        self.memory_handler.setFormatter(self._get_formatter())
        self.logger.addHandler(self.memory_handler)
        
        # Prevent propagation to root logger
        self.logger.propagate = False
        
        # Logging state tracking
        self.is_initialized = False
        self.is_monitoring = False
        self.monitoring_interval = 60  # seconds between monitoring logs
        self.last_monitoring_log = 0  # timestamp
        self.last_action_logged = None  # track last action to avoid immediate duplicates
        
        # Log initialization once
        self.info(f"[INIT] Strategy logger initialized: {strategy_name}")
        self.is_initialized = True
    
    @staticmethod
    def _get_formatter() -> logging.Formatter:
        """Get standard formatter for logs"""
        return logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    def set_monitoring_mode(self, enabled: bool, interval: int = 60):
        """
        Enable/disable monitoring mode with interval-based logs.
        
        Args:
            enabled: Whether monitoring is active
            interval: Seconds between monitoring logs (default 60)
        """
        self.is_monitoring = enabled
        self.monitoring_interval = interval
        if enabled:
            self.info(f"[MONITORING] Started monitoring with {interval}s interval")
        else:
            self.info("[MONITORING] Stopped monitoring")
    
    def _should_log_action(self, action: str) -> bool:
        """
        Check if an action should be logged (prevent immediate duplicates).
        
        Args:
            action: Action to log
            
        Returns:
            True if action should be logged
        """
        if self.last_action_logged != action:
            self.last_action_logged = action
            return True
        return False
    
    def _should_log_monitoring(self) -> bool:
        """
        Check if enough time has passed for next monitoring log.
        
        Returns:
            True if monitoring log should be emitted
        """
        if not self.is_monitoring:
            return False
        
        current_time = time.time()
        if current_time - self.last_monitoring_log >= self.monitoring_interval:
            self.last_monitoring_log = current_time
            return True
        return False
    
    def log_action(self, action: str, details: str = ""):
        """
        Log a strategy action (entry, exit, adjustment, etc).
        
        Args:
            action: Action name (ENTRY, EXIT, ADJUST, etc)
            details: Action details
        """
        msg = f"[ACTION] {action}"
        if details:
            msg += f": {details}"
        if self._should_log_action(msg):
            self.logger.info(msg)
    
    def log_monitoring(self, status: str):
        """
        Log monitoring status at configured interval.
        
        Args:
            status: Current monitoring status/summary
        """
        if self._should_log_monitoring():
            self.logger.info(f"[MONITOR] {status}")
    
    def log_user_action(self, action: str, details: str = ""):
        """
        Log a user-initiated action.
        
        Args:
            action: User action (PAUSE, RESUME, STOP, etc)
            details: Action details
        """
        msg = f"[USER] {action}"
        if details:
            msg += f": {details}"
        self.logger.info(msg)
    
    def debug(self, message: str):
        """Log debug message (disabled by default to prevent spam)"""
        # Optionally enable for troubleshooting, but don't log in production
        pass
    
    def info(self, message: str):
        """Log info message"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Log warning message"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """Log error message"""
        self.logger.error(message)
    
    def exception(self, message: str):
        """Log exception"""
        self.logger.exception(message)
    
    def get_recent_logs(self, lines: int = 100, level: Optional[str] = None) -> List[Dict]:
        """Get recent logs from memory buffer.
        
        Args:
            lines: Number of recent lines (0 = all)
            level: Optional filter by level (DEBUG, INFO, WARNING, ERROR)
            
        Returns:
            List of log records as dictionaries
        """
        return self.memory_handler.get_logs(lines, level)
    
    def get_logs_as_text(self, lines: int = 100, level: Optional[str] = None) -> str:
        """Get logs as formatted text string.
        
        Args:
            lines: Number of lines
            level: Optional level filter
            
        Returns:
            Formatted text string for display
        """
        logs = self.get_recent_logs(lines, level)
        if not logs:
            return "No logs available"
        
        text_lines = []
        for log in logs:
            text_lines.append(
                f"[{log['timestamp']}] {log['level']:8s} | {log['message']}"
            )
        
        return "\n".join(text_lines)
    
    def clear_memory_buffer(self):
        """Clear in-memory log buffer"""
        self.memory_handler.clear()


class StrategyLoggerManager:
    """Manage loggers for all strategies"""
    
    def __init__(self):
        self.loggers: Dict[str, StrategyLogger] = {}
        self.lock: Optional[threading.Lock] = threading.Lock()
    
    def get_logger(self, strategy_name: str) -> StrategyLogger:
        """Get or create logger for strategy.
        
        Args:
            strategy_name: Name of strategy
            
        Returns:
            StrategyLogger instance
        """
        assert self.lock is not None
        with self.lock:
            if strategy_name not in self.loggers:
                self.loggers[strategy_name] = StrategyLogger(strategy_name)
            return self.loggers[strategy_name]
    
    def get_all_recent_logs(self, lines: int = 50) -> Dict[str, List[Dict]]:
        """Get recent logs from all strategies.
        
        Args:
            lines: Number of recent lines per strategy
            
        Returns:
            Dict of {strategy_name: logs}
        """
        assert self.lock is not None
        with self.lock:
            return {
                name: logger.get_recent_logs(lines)
                for name, logger in self.loggers.items()
            }
    
    def get_all_logs_combined(self, lines: int = 200) -> List[Dict]:
        """Get combined recent logs from all strategies, sorted by timestamp.
        
        Args:
            lines: Number of most recent lines to return
            
        Returns:
            List of log records sorted by timestamp (newest first where possible)
        """
        all_logs = []
        
        assert self.lock is not None
        with self.lock:
            for logger in self.loggers.values():
                all_logs.extend(logger.get_recent_logs(lines=0))
        
        # Sort by timestamp (newest first best effort)
        try:
            all_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        except Exception:
            pass  # If sorting fails, just use as-is
        
        return all_logs[-lines:] if lines > 0 else all_logs
    
    def clear_strategy_logs(self, strategy_name: str):
        """Clear logs for specific strategy.
        
        Args:
            strategy_name: Name of strategy
        """
        assert self.lock is not None
        with self.lock:
            if strategy_name in self.loggers:
                self.loggers[strategy_name].clear_memory_buffer()


# Global manager instance
_manager: Optional[StrategyLoggerManager] = None


def get_logger_manager() -> StrategyLoggerManager:
    """Get or create global logger manager"""
    global _manager
    if _manager is None:
        _manager = StrategyLoggerManager()
    return _manager


def get_strategy_logger(strategy_name: str) -> StrategyLogger:
    """Get logger for a strategy with intelligent logging.
    
    Logging Features:
    - Initialization: Logged once when strategy starts
    - Monitoring: Logged at configurable intervals (default 60s)
    - Actions: Logged when strategy takes action (entry, exit, adjust)
    - User Actions: Logged when user pauses/resumes/stops
    - Warnings/Errors: Always logged
    - No Debug Spam: DEBUG level disabled by default
    
    Usage:
        logger = get_strategy_logger("MY_STRATEGY")
        
        # Set monitoring interval (logs status every 30 seconds)
        logger.set_monitoring_mode(enabled=True, interval=30)
        
        # Log actions
        logger.log_action("ENTRY", "Long call spread at 100")
        logger.log_action("ADJUST", "Delta drift detected, rehedging")
        logger.log_action("EXIT", "Target hit at 450 profit")
        
        # Log user events
        logger.log_user_action("PAUSE", "User paused strategy")
        logger.log_user_action("RESUME", "User resumed strategy")
        
        # Monitor status (only logs every interval)
        logger.log_monitoring("Delta: 0.5, P&L: +2500, Positions: 4")
        
        # Log warnings/errors always
        logger.warning("Delta exceeded threshold (0.8)")
        logger.error("Failed to place order: Insufficient margin")
    """
    manager = get_logger_manager()
    return manager.get_logger(strategy_name)


def get_all_recent_logs(lines: int = 50) -> Dict[str, List[Dict]]:
    """Get recent logs from all strategies"""
    manager = get_logger_manager()
    return manager.get_all_recent_logs(lines)


def get_combined_logs(lines: int = 200) -> List[Dict]:
    """Get combined logs from all strategies"""
    manager = get_logger_manager()
    return manager.get_all_logs_combined(lines)
