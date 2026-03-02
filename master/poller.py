#!/usr/bin/env python3
"""
MASTER HEALTH POLLER
====================
Background thread that periodically polls the /health endpoint of each
registered client and updates the registry with the result.
Auto-blocks clients that miss too many consecutive polls.
"""

import logging
import threading
import time
from typing import Dict

import httpx

logger = logging.getLogger("master.poller")


class HealthPoller:
    """
    Polls each client's /health endpoint on a configurable interval.

    Args:
        registry:          MasterRegistry instance
        poll_interval_s:   Seconds between poll cycles (default 30)
        timeout_s:         Per-request timeout in seconds
        auto_block_misses: Auto-block after this many consecutive failures
    """

    def __init__(
        self,
        registry,
        poll_interval_s: int = 30,
        timeout_s: float = 5.0,
        auto_block_misses: int = 3,
    ) -> None:
        self._registry = registry
        self._interval = poll_interval_s
        self._timeout = timeout_s
        self._auto_block_misses = auto_block_misses
        self._miss_counter: Dict[str, int] = {}
        self._http_client = httpx.Client(timeout=self._timeout)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="MasterHealthPoller",
            daemon=True,
        )

    def start(self) -> None:
        if self._thread.is_alive():
            logger.warning("HealthPoller.start() called while already running — ignored")
            return
        logger.info(
            "HealthPoller started | interval=%ds | auto_block_after=%d misses",
            self._interval,
            self._auto_block_misses,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)
        self._http_client.close()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_all()
            except Exception as exc:
                logger.error("Poller cycle error: %s", exc)
            self._stop_event.wait(self._interval)

    def _poll_all(self) -> None:
        clients = self._registry.list_all()
        if not clients:
            return

        for client in clients:
            if not client.get("service_enabled", True):
                continue

            client_id = client["client_id"]
            webhook_url = client.get("webhook_url", "").rstrip("/")
            if not webhook_url:
                continue

            health_url = webhook_url + "/health"
            health_status = "unknown"

            try:
                resp = self._http_client.get(health_url)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        health_status = data.get("status", "healthy") if isinstance(data, dict) else "healthy"
                    except Exception:
                        health_status = "healthy"
                    self._miss_counter[client_id] = 0
                else:
                    health_status = f"http_{resp.status_code}"
                    self._miss_counter[client_id] = (
                        self._miss_counter.get(client_id, 0) + 1
                    )
            except Exception as exc:
                health_status = "unreachable"
                self._miss_counter[client_id] = (
                    self._miss_counter.get(client_id, 0) + 1
                )
                logger.warning("Health check failed for %s: %s", client_id, exc)

            # Record heartbeat (client may have been deleted mid-cycle)
            try:
                self._registry.record_heartbeat(client_id, health_status)
            except KeyError:
                logger.debug("Skipping heartbeat for removed client: %s", client_id)
                continue

            # Auto-block if too many consecutive misses
            misses = self._miss_counter.get(client_id, 0)
            if (
                self._auto_block_misses > 0
                and misses >= self._auto_block_misses
                and not client.get("trading_blocked", False)
            ):
                logger.warning(
                    "AUTO-BLOCK: %s missed %d consecutive health checks",
                    client_id,
                    misses,
                )
                try:
                    self._registry.block_trading(
                        client_id,
                        reason=f"Auto-blocked: {misses} missed health checks",
                    )
                except Exception as block_err:
                    logger.error("Auto-block failed for %s: %s", client_id, block_err)
