#!/usr/bin/env python3
"""
Order Intent Tracking Logger
=============================

Logs complete order processing pipeline:
  Intent Created → DB Write → Broker Send → Broker Confirmation → Watcher Reconciliation

Helps diagnose order failures at each stage.
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class IntentTracker:
    """Track order intent through complete pipeline"""
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.log_file = (
            Path(__file__).resolve().parents[3]
            / "logs"
            / "intent_tracking.log"
        )
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
    def log_intent_created(self, command_id: str, payload: Dict[str, Any]):
        """Log: Intent created in dashboard"""
        msg = {
            "stage": "INTENT_CREATED",
            "command_id": command_id,
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": payload.get("symbol"),
            "side": payload.get("side"),
            "quantity": payload.get("quantity"),
            "order_type": payload.get("order_type"),
        }
        self._write_log(msg)
        logger.info(f"📝 INTENT CREATED | {command_id} | {payload.get('symbol')} {payload.get('side')} {payload.get('quantity')}")
    
    def log_db_write(self, command_id: str, status: str):
        """Log: Order written to order.db"""
        msg = {
            "stage": "DB_WRITE",
            "command_id": command_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log(msg)
        logger.info(f"💾 DB WRITE | {command_id} | status={status}")
    
    def log_sent_to_broker(self, command_id: str, broker_order_id: str):
        """Log: Intent sent to broker"""
        msg = {
            "stage": "SENT_TO_BROKER",
            "command_id": command_id,
            "broker_order_id": broker_order_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log(msg)
        logger.info(f"🚀 SENT_TO_BROKER | {command_id} | broker_id={broker_order_id}")
    
    def log_broker_confirmed(self, command_id: str, broker_order_id: str, filled_qty: int = 0, avg_price: float = 0):
        """Log: Broker confirmed order"""
        msg = {
            "stage": "BROKER_CONFIRMED",
            "command_id": command_id,
            "broker_order_id": broker_order_id,
            "filled_qty": filled_qty,
            "avg_price": avg_price,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log(msg)
        logger.info(f"✅ BROKER_CONFIRMED | {command_id} | filled={filled_qty} @ {avg_price}")
    
    def log_order_executed(self, command_id: str, broker_order_id: str, filled_qty: int, avg_price: float):
        """Log: Order fully executed"""
        msg = {
            "stage": "EXECUTED",
            "command_id": command_id,
            "broker_order_id": broker_order_id,
            "filled_qty": filled_qty,
            "avg_price": avg_price,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log(msg)
        logger.info(f"🎯 EXECUTED | {command_id} | {filled_qty} @ {avg_price}")
    
    def log_order_failed(self, command_id: str, broker_order_id: str = None, reason: str = "unknown"):
        """Log: Order failed/rejected/cancelled"""
        msg = {
            "stage": "FAILED",
            "command_id": command_id,
            "broker_order_id": broker_order_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log(msg)
        logger.error(f"❌ FAILED | {command_id} | reason={reason}")
    
    def log_intent_error(self, command_id: str, step: str, error: str):
        """Log: Error during intent processing"""
        msg = {
            "stage": "ERROR",
            "command_id": command_id,
            "step": step,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log(msg)
        logger.error(f"⚠️ ERROR | {command_id} at {step} | {error}")
    
    def _write_log(self, msg: Dict[str, Any]):
        """Write to intent tracking log file"""
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(msg) + "\n")
        except Exception as e:
            logger.exception(f"Failed to write intent log: {e}")


# Global tracker instances (one per client)
_trackers: Dict[str, IntentTracker] = {}


def get_intent_tracker(client_id: str) -> IntentTracker:
    """Get or create intent tracker for client"""
    if client_id not in _trackers:
        _trackers[client_id] = IntentTracker(client_id)
    return _trackers[client_id]
