#!/usr/bin/env python3
"""
MASTER CLIENT REGISTRY
=======================

Manages the JSON-backed registry of all client accounts.
Provides atomic read/write operations and all state transitions
(block, unblock, enable/disable service, copy-trading control).

Thread-safe via a single file-level RLock.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("master.registry")


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class ClientRecord:
    """
    In-memory representation of one registered client.
    All field names mirror the JSON schema in master_clients.json.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        self.client_id: str = data["client_id"]
        self.client_alias: str = data.get("client_alias", self.client_id)
        self.display_name: str = data.get("display_name", self.client_id)
        self.webhook_url: str = data.get("webhook_url", "")
        self.dashboard_url: str = data.get("dashboard_url", "")
        self.env_file: str = data.get("env_file", "")

        # Service state
        self.service_enabled: bool = data.get("service_enabled", True)
        self.trading_blocked: bool = data.get("trading_blocked", False)
        self.block_reason: Optional[str] = data.get("block_reason")

        # Copy trading state
        self.copy_trading_role: str = data.get("copy_trading_role", "standalone")
        self.copy_trading_enabled: bool = data.get("copy_trading_enabled", False)
        self.copy_trading_master_id: Optional[str] = data.get("copy_trading_master_id")
        self.copy_trading_followers: List[str] = data.get("copy_trading_followers", [])

        # Bookkeeping
        self.registered_at: str = data.get("registered_at", _now_iso())
        self.last_heartbeat: Optional[str] = data.get("last_heartbeat")
        self.last_health_status: Optional[str] = data.get("last_health_status")
        self.notes: str = data.get("notes", "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_alias": self.client_alias,
            "display_name": self.display_name,
            "webhook_url": self.webhook_url,
            "dashboard_url": self.dashboard_url,
            "env_file": self.env_file,
            "service_enabled": self.service_enabled,
            "trading_blocked": self.trading_blocked,
            "block_reason": self.block_reason,
            "copy_trading_role": self.copy_trading_role,
            "copy_trading_enabled": self.copy_trading_enabled,
            "copy_trading_master_id": self.copy_trading_master_id,
            "copy_trading_followers": self.copy_trading_followers,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "last_health_status": self.last_health_status,
            "notes": self.notes,
        }


class MasterRegistry:
    """
    Thread-safe JSON-backed client registry.

    Usage:
        registry = MasterRegistry("config_env/master_clients.json")

        # Read
        client = registry.get("FA14667")

        # Write
        registry.block_trading("FA14667", reason="Manual block by admin")
        registry.enable_copy_trading("FA14667")
    """

    def __init__(self, registry_file: str) -> None:
        self._file = Path(registry_file)
        self._lock = threading.RLock()
        self._clients: Dict[str, ClientRecord] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load registry from JSON file. Creates empty file if missing."""
        with self._lock:
            if not self._file.exists():
                self._clients = {}
                self._save_locked()
                logger.info("Registry file created: %s", self._file)
                return

            try:
                with self._file.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                self._clients = {
                    entry["client_id"]: ClientRecord(entry)
                    for entry in data.get("clients", [])
                    if "client_id" in entry
                }
                logger.info("Registry loaded: %d clients", len(self._clients))
            except Exception as exc:
                logger.error("Failed to load registry: %s", exc)
                raise

    def _save_locked(self) -> None:
        """Write current state to JSON file. MUST be called while _lock is held."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": "Master client registry — managed by master_manager.py",
            "updated_at": _now_iso(),
            "clients": [c.to_dict() for c in self._clients.values()],
        }
        tmp_path = self._file.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        tmp_path.replace(self._file)  # Atomic replace

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def reload(self) -> None:
        with self._lock:
            self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [c.to_dict() for c in self._clients.values()]

    def get(self, client_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._clients.get(client_id)
            return record.to_dict() if record else None

    def register(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add or update a client record."""
        client_id = data.get("client_id", "").strip()
        if not client_id:
            raise ValueError("client_id is required")

        with self._lock:
            if client_id in self._clients:
                # Update existing — preserve controlled fields
                existing = self._clients[client_id]
                data.setdefault("service_enabled", existing.service_enabled)
                data.setdefault("trading_blocked", existing.trading_blocked)
                data.setdefault("registered_at", existing.registered_at)

            data["registered_at"] = data.get("registered_at", _now_iso())
            record = ClientRecord(data)
            self._clients[client_id] = record
            self._save_locked()
            logger.info("Client registered/updated: %s", client_id)
            return record.to_dict()

    def delete(self, client_id: str) -> bool:
        with self._lock:
            if client_id not in self._clients:
                return False
            del self._clients[client_id]
            self._save_locked()
            logger.info("Client removed: %s", client_id)
            return True

    # ------------------------------------------------------------------
    # Service Control
    # ------------------------------------------------------------------

    def enable_service(self, client_id: str) -> Dict[str, Any]:
        return self._update_field(client_id, service_enabled=True)

    def disable_service(self, client_id: str) -> Dict[str, Any]:
        return self._update_field(client_id, service_enabled=False)

    def block_trading(self, client_id: str, reason: str = "") -> Dict[str, Any]:
        return self._update_field(client_id, trading_blocked=True, block_reason=reason)

    def unblock_trading(self, client_id: str) -> Dict[str, Any]:
        return self._update_field(client_id, trading_blocked=False, block_reason=None)

    # ------------------------------------------------------------------
    # Copy Trading Control
    # ------------------------------------------------------------------

    def enable_copy_trading(
        self,
        client_id: str,
        role: str = "follower",
        master_id: Optional[str] = None,
        followers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if role not in {"master", "follower"}:
            raise ValueError(f"Invalid copy trading role '{role}'; must be 'master' or 'follower'")
        updates: Dict[str, Any] = {"copy_trading_enabled": True, "copy_trading_role": role}
        if master_id:
            updates["copy_trading_master_id"] = master_id
        if followers is not None:
            updates["copy_trading_followers"] = followers
        return self._update_field(client_id, **updates)

    def disable_copy_trading(self, client_id: str) -> Dict[str, Any]:
        return self._update_field(
            client_id,
            copy_trading_enabled=False,
            copy_trading_role="standalone",
            copy_trading_master_id=None,
            copy_trading_followers=[],
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def record_heartbeat(self, client_id: str, health_status: str = "unknown") -> None:
        with self._lock:
            if client_id not in self._clients:
                raise KeyError(f"Unknown client_id: {client_id}")
            self._clients[client_id].last_heartbeat = _now_iso()
            self._clients[client_id].last_health_status = health_status
            self._save_locked()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_field(self, client_id: str, **kwargs: Any) -> Dict[str, Any]:
        with self._lock:
            if client_id not in self._clients:
                raise KeyError(f"Client not found: {client_id}")
            record = self._clients[client_id]
            for field, value in kwargs.items():
                if not hasattr(record, field):
                    raise ValueError(f"Unknown field '{field}' for ClientRecord")
                setattr(record, field, value)
            self._save_locked()
            logger.info("Client updated: %s | %s", client_id, kwargs)
            return record.to_dict()
