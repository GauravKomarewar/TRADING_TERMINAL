#!/usr/bin/env python3
"""
COPY TRADING SERVICE
====================

Purpose:
- Fan out master alerts to all registered follower endpoints.
- Validate incoming copy-alerts on follower side (HMAC signature check).
- Support mirrored (same qty) and scaled (qty × factor) execution modes.
- Thread-pool based parallel delivery for low latency.

Architecture:
                       TradingView
                           │ webhook
                           ▼
                    Master Bot (role=master)
                    process_alert() succeeds
                           │
                    CopyTradingService.fan_out()
                    ┌──────┴──────────────────┐
                    ▼                         ▼
            Follower A                  Follower B
            POST /copy-alert            POST /copy-alert
            (HMAC signed)               (HMAC signed)

Follower side:
    POST /copy-alert  →  validate HMAC  →  bot.process_copy_alert()

SECURITY:
- Each request is signed with HMAC-SHA256 using COPY_TRADING_SECRET.
- The secret MUST be identical on master and all followers.
- The follower verifies the signature before executing any trade.

MODES:
- mirror  : copy alert exactly as-is (quantity unchanged)
- scaled  : multiply all qty values by COPY_TRADING_SCALE_FACTOR
"""

import hashlib
import hmac
import json
import logging
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from shoonya_platform.logging.logger_config import get_component_logger

logger = get_component_logger("copy_trading_service")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest of payload using secret."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def _scale_alert_qty(alert_data: Dict[str, Any], factor: float) -> Dict[str, Any]:
    """
    Return a copy of alert_data with all numeric 'qty'/'quantity' fields
    multiplied by *factor*. The original dict is NOT mutated.
    """
    scaled = json.loads(json.dumps(alert_data))  # deep clone via JSON round-trip

    def _scale_node(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k.lower() in ("qty", "quantity", "lot_qty") and isinstance(v, (int, float)):
                    out[k] = max(1, int(v * factor))
                else:
                    out[k] = _scale_node(v)
            return out
        elif isinstance(node, list):
            return [_scale_node(item) for item in node]
        return node

    return _scale_node(scaled)


# ---------------------------------------------------------------------------
# CopyTradingService
# ---------------------------------------------------------------------------

class CopyTradingService:
    """
    Thread-safe service for copy-trading fanout and validation.

    Instantiate once in ShoonyaBot and call:
        fan_out_alert(original_alert, master_result)   — on master
        validate_copy_signature(payload_bytes, sig)     — on follower
        build_copy_payload(alert, master_result)        — on master before POST
    """

    TIMEOUT_SECONDS: int = 5   # Per-follower HTTP timeout
    MAX_WORKERS: int = 10       # Thread pool size for parallel delivery

    def __init__(self, config) -> None:
        """
        Args:
            config: shoonya_platform.core.config.Config instance
        """
        self._role: str = config.copy_trading_role          # standalone|master|follower
        self._secret: Optional[str] = config.copy_trading_secret
        self._followers: List[str] = config.copy_trading_followers
        self._mode: str = config.copy_trading_mode          # mirror|scaled
        self._scale_factor: float = config.copy_trading_scale_factor
        self._client_id: str = config.get_client_identity()["client_id"]

        self._enabled: bool = self._role in ("master", "follower")

        if self._role == "master":
            logger.info(
                "CopyTradingService initialized | role=MASTER | followers=%d | mode=%s",
                len(self._followers),
                self._mode,
            )
        elif self._role == "follower":
            logger.info(
                "CopyTradingService initialized | role=FOLLOWER | mode=%s",
                self._mode,
            )
        else:
            logger.debug("CopyTradingService initialized | role=STANDALONE (copy trading off)")

    # ------------------------------------------------------------------
    # PUBLIC — MASTER SIDE
    # ------------------------------------------------------------------

    def fan_out_alert(
        self,
        alert_data: Dict[str, Any],
        master_result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Fan out a successfully executed alert to all registered followers.

        Called by the master bot AFTER its own process_alert() succeeds.

        Args:
            alert_data:    Original alert dict received at /webhook
            master_result: Result returned by master's process_alert()

        Returns:
            List of per-follower delivery results, e.g.:
            [
              {"follower": "http://...", "status": "delivered", "http_code": 200},
              {"follower": "http://...", "status": "error", "error": "..."},
            ]
        """
        if self._role != "master" or not self._followers or not self._secret:
            return []

        # Build outbound alert (apply scaling if needed)
        if self._mode == "scaled" and self._scale_factor != 1.0:
            outbound_alert = _scale_alert_qty(alert_data, self._scale_factor)
            logger.debug(
                "CopyTrading: applied scale factor %.2f to alert qty", self._scale_factor
            )
        else:
            outbound_alert = alert_data

        # Build the full copy payload
        copy_payload = self._build_copy_payload(outbound_alert, master_result)
        payload_bytes = json.dumps(copy_payload, ensure_ascii=False).encode("utf-8")
        signature = _build_signature(payload_bytes, self._secret)

        logger.info(
            "CopyTrading: fanning out alert | strategy=%s | followers=%d",
            alert_data.get("strategy_name", "unknown"),
            len(self._followers),
        )

        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(self.MAX_WORKERS, len(self._followers))) as pool:
            future_map = {
                pool.submit(
                    self._deliver_to_follower,
                    follower_url,
                    payload_bytes,
                    signature,
                ): follower_url
                for follower_url in self._followers
            }
            for future in as_completed(future_map):
                follower_url = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "follower": follower_url,
                        "status": "error",
                        "error": str(exc),
                    }
                results.append(result)

        ok_count = sum(1 for r in results if r.get("status") == "delivered")
        logger.info(
            "CopyTrading: fanout complete | delivered=%d/%d",
            ok_count,
            len(self._followers),
        )
        return results

    def _build_copy_payload(
        self,
        alert_data: Dict[str, Any],
        master_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Wrap alert in a copy-trading envelope with metadata."""
        return {
            "copy_trading": True,
            "master_client_id": self._client_id,
            "master_result_status": master_result.get("status"),
            "copy_mode": self._mode,
            "scale_factor": self._scale_factor if self._mode == "scaled" else 1.0,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "alert": alert_data,
        }

    def _deliver_to_follower(
        self,
        follower_base_url: str,
        payload_bytes: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        HTTP POST the copy-alert payload to one follower.
        Returns a dict describing the delivery outcome.
        """
        url = follower_base_url.rstrip("/") + "/copy-alert"
        start = time.monotonic()

        headers = {
            "Content-Type": "application/json",
            "X-Copy-Signature": signature,
            "X-Copy-Master": self._client_id,
        }

        try:
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_SECONDS) as resp:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                body = resp.read().decode("utf-8", errors="replace")
                logger.info(
                    "CopyTrading: delivered to %s | http=%d | ms=%d",
                    url,
                    resp.status,
                    elapsed_ms,
                )
                return {
                    "follower": follower_base_url,
                    "status": "delivered",
                    "http_code": resp.status,
                    "elapsed_ms": elapsed_ms,
                    "body": body[:200],
                }

        except urllib.error.HTTPError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning(
                "CopyTrading: HTTP error for %s | http=%d | body=%s",
                url,
                exc.code,
                body[:200],
            )
            return {
                "follower": follower_base_url,
                "status": "http_error",
                "http_code": exc.code,
                "elapsed_ms": elapsed_ms,
                "error": body[:200],
            }

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning("CopyTrading: delivery failed for %s | error=%s", url, exc)
            return {
                "follower": follower_base_url,
                "status": "error",
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # PUBLIC — FOLLOWER SIDE
    # ------------------------------------------------------------------

    def validate_copy_signature(
        self,
        payload_bytes: bytes,
        provided_signature: str,
    ) -> bool:
        """
        Verify the HMAC-SHA256 signature on an incoming /copy-alert request.

        Args:
            payload_bytes:      Raw request body bytes
            provided_signature: Value of the X-Copy-Signature header

        Returns:
            True if valid, False if tampered / wrong secret.
        """
        if not self._secret:
            logger.error("CopyTrading: cannot validate — COPY_TRADING_SECRET not set")
            return False
        expected = _build_signature(payload_bytes, self._secret)
        valid = hmac.compare_digest(expected, provided_signature or "")
        if not valid:
            logger.warning("CopyTrading: INVALID signature on /copy-alert — rejected")
        return valid

    def extract_alert_from_copy_payload(
        self,
        copy_payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Extract the original alert dict and envelope metadata from the
        copy-trading payload received at /copy-alert.

        Returns:
            (alert_data, metadata)
        """
        alert = copy_payload.get("alert", copy_payload)
        metadata = {k: v for k, v in copy_payload.items() if k != "alert"}
        return alert, metadata

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------

    @property
    def is_master(self) -> bool:
        return self._role == "master"

    @property
    def is_follower(self) -> bool:
        return self._role == "follower"

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def follower_count(self) -> int:
        return len(self._followers)
