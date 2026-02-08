#!/usr/bin/env python3
"""
SERVICE ISOLATION LAYER
=======================

Purpose:
- Isolate different service components (trading_bot, dashboard, risk manager, etc.)
- Prevent cascading failures - error in one service doesn't kill others
- Provide health status monitoring for each service
- Enable independent service restart and recovery

Architecture:
    - Each service runs independently with its own logger
    - Services communicate through well-defined interfaces only
    - Failures are isolated within service boundaries
    - Health checks monitor service status

Services Managed:
    1. ExecutionService - webhook processing (main service)
    2. TradingBot - bot logic and alert handling
    3. RiskManager - risk validation
    4. OrderWatcher - order tracking and recovery
    5. CommandService - broker command execution
    6. Dashboard - API and UI server

Usage:
    from shoonya_platform.services.service_manager import ServiceManager
    
    manager = ServiceManager()
    manager.start()
"""

import logging
import threading
import time
from enum import Enum
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from shoonya_platform.logging.logger_config import get_component_logger


class ServiceStatus(Enum):
    """Service health status"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RECOVERING = "recovering"


@dataclass
class ServiceHealth:
    """Health information for a service"""
    name: str
    status: ServiceStatus = ServiceStatus.STOPPED
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    restart_count: int = 0
    uptime_seconds: float = 0.0
    started_at: Optional[datetime] = None
    
    def __str__(self) -> str:
        status_emoji = {
            ServiceStatus.RUNNING: "✅",
            ServiceStatus.ERROR: "❌",
            ServiceStatus.RECOVERING: "🔄",
            ServiceStatus.STARTING: "⏳",
            ServiceStatus.STOPPED: "⏹️"
        }
        
        emoji = status_emoji.get(self.status, "❓")
        result = f"{emoji} {self.name:20} - {self.status.value:10}"
        
        if self.restart_count > 0:
            result += f" | Restarts: {self.restart_count}"
        
        if self.status in (ServiceStatus.ERROR, ServiceStatus.RECOVERING):
            result += f" | Error: {self.last_error}"
        
        if self.uptime_seconds > 0:
            hours = int(self.uptime_seconds // 3600)
            minutes = int((self.uptime_seconds % 3600) // 60)
            result += f" | Uptime: {hours}h {minutes}m"
        
        return result


class IsolatedService:
    """
    Base class for isolated services.
    
    Each service runs with its own error handling and logging.
    """
    
    def __init__(self, name: str, enable_auto_restart: bool = True):
        self.name = name
        self.logger = get_component_logger(self._get_component_key())
        self.enable_auto_restart = enable_auto_restart
        self.health = ServiceHealth(name=name)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def _get_component_key(self) -> str:
        """Get the logging component key for this service."""
        mapping = {
            'execution_service': 'execution_service',
            'trading_bot': 'trading_bot',
            'risk_manager': 'risk_manager',
            'order_watcher': 'order_watcher',
            'command_service': 'command_service',
            'dashboard': 'dashboard',
            'recovery_service': 'recovery'
        }
        return mapping.get(self.name, self.name.lower().replace(' ', '_'))
    
    def start(self) -> None:
        """Start the service in a separate thread."""
        with self._lock:
            if self.health.status != ServiceStatus.STOPPED:
                self.logger.warning(f"Service already in {self.health.status.value} state")
                return
            
            self.health.status = ServiceStatus.STARTING
            self._stop_event.clear()
            
            self._thread = threading.Thread(
                target=self._run_with_isolation,
                daemon=False,
                name=f"{self.name}Thread"
            )
            self._thread.start()
            self.logger.info(f"🚀 Service started (thread: {self._thread.name})")
    
    def _run_with_isolation(self) -> None:
        """Run service with isolation - errors don't affect other services."""
        try:
            self.health.started_at = datetime.now()
            self.health.status = ServiceStatus.RUNNING
            self.logger.info(f"Service initialization complete")
            
            # Call the service's actual run method
            self.run()
            
        except Exception as e:
            self.health.status = ServiceStatus.ERROR
            self.health.last_error = str(e)
            self.health.last_error_time = datetime.now()
            
            self.logger.error(f"❌ Service error: {e}", exc_info=True)
            
            if self.enable_auto_restart:
                self._attempt_restart()
        
        finally:
            if self.health.status != ServiceStatus.ERROR:
                self.health.status = ServiceStatus.STOPPED
            
            if self.health.started_at:
                self.health.uptime_seconds = (datetime.now() - self.health.started_at).total_seconds()
    
    def _attempt_restart(self) -> None:
        """Attempt to restart the service after an error."""
        self.health.status = ServiceStatus.RECOVERING
        self.health.restart_count += 1
        
        self.logger.warning(f"🔄 Attempting restart ({self.health.restart_count})...")
        
        # Wait before restart to avoid rapid failure loops
        for i in range(3):
            if self._stop_event.is_set():
                self.logger.info("Stop requested, canceling restart")
                return
            time.sleep(1)
        
        self.logger.info(f"Restarting service after restart #{self.health.restart_count}")
        self._run_with_isolation()
    
    def run(self) -> None:
        """Override this method in subclasses with the actual service logic."""
        raise NotImplementedError("Subclasses must implement run()")
    
    def stop(self) -> None:
        """Stop the service gracefully."""
        with self._lock:
            self.logger.info(f"🛑 Stopping service...")
            self._stop_event.set()
            self.health.status = ServiceStatus.STOPPING
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)
        
        self.health.status = ServiceStatus.STOPPED
        self.logger.info(f"Service stopped")
    
    def is_running(self) -> bool:
        """Check if service is running."""
        return self.health.status == ServiceStatus.RUNNING
    
    def is_stopped(self) -> bool:
        """Check if service is stopped."""
        return self.health.status == ServiceStatus.STOPPED
    
    def should_stop(self) -> bool:
        """Check if stop has been requested (safe to use in service loops)."""
        return self._stop_event.is_set()


class ServiceManager:
    """
    Manages multiple isolated services.
    
    Ensures:
    - Each service has independent error handling
    - Services don't cascade failures
    - Health monitoring for all services
    - Coordinated shutdown
    """
    
    def __init__(self):
        self.logger = get_component_logger('execution_service')
        self.services: Dict[str, IsolatedService] = {}
        self._health_check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def register_service(self, service: IsolatedService) -> None:
        """Register a service to be managed."""
        self.services[service.name] = service
        self.logger.info(f"Registered service: {service.name}")
    
    def start_all(self, start_health_check: bool = True) -> None:
        """Start all registered services."""
        self.logger.info("=" * 70)
        self.logger.info("🚀 STARTING ALL SERVICES")
        self.logger.info("=" * 70)
        
        for service in self.services.values():
            try:
                service.start()
            except Exception as e:
                self.logger.error(f"Failed to start {service.name}: {e}")
        
        if start_health_check:
            self._start_health_check()
        
        self.logger.info("✅ All services started")
    
    def stop_all(self) -> None:
        """Stop all services gracefully."""
        self.logger.info("=" * 70)
        self.logger.info("🛑 STOPPING ALL SERVICES")
        self.logger.info("=" * 70)
        
        self._stop_event.set()
        
        # Stop in reverse order
        for service in reversed(list(self.services.values())):
            try:
                service.stop()
            except Exception as e:
                self.logger.error(f"Error stopping {service.name}: {e}")
        
        self.logger.info("✅ All services stopped")
    
    def _start_health_check(self) -> None:
        """Start periodic health check monitor."""
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True,
            name="HealthCheckThread"
        )
        self._health_check_thread.start()
    
    def _health_check_loop(self) -> None:
        """Periodic health check (every 60 seconds)."""
        while not self._stop_event.is_set():
            try:
                time.sleep(60)
                self._log_health_status()
            except Exception as e:
                self.logger.error(f"Health check error: {e}")
    
    def _log_health_status(self) -> None:
        """Log health status of all services."""
        self.logger.info("=" * 70)
        self.logger.info("📋 SERVICE HEALTH STATUS")
        self.logger.info("=" * 70)
        
        for service in self.services.values():
            self.logger.info(str(service.health))
        
        # Calculate uptime for long-running services
        total_uptime = sum(s.health.uptime_seconds for s in self.services.values() if s.is_running())
        self.logger.info(f"Total service uptime: {total_uptime / 3600:.1f} hours")
    
    def get_health(self) -> Dict[str, ServiceHealth]:
        """Get health status of all services."""
        return {name: service.health for name, service in self.services.items()}
    
    def get_status_summary(self) -> Dict[str, str]:
        """Get simple status summary for monitoring."""
        return {
            name: {
                'status': service.health.status.value,
                'restarts': service.health.restart_count,
                'error': service.health.last_error
            }
            for name, service in self.services.items()
        }
