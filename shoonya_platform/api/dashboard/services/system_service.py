# shoonya_platform/api/dashboard/services/system_service.py

import json
import time
from pathlib import Path
from typing import Optional

from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.core.config import Config
import logging
logger = logging.getLogger(__name__)
# --------------------------------------------------
# SYSTEM-WIDE (NON CLIENT-SCOPED) FILES
# --------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[4]

OPTION_DATA_HEARTBEAT = (
    PROJECT_ROOT / "market_data/option_chain/data/.supervisor_heartbeat"
)
TELEGRAM_LOG = PROJECT_ROOT / "logs/telegram_messages.jsonl"


class SystemTruthService:
    """
    SYSTEM TRUTH — READ ONLY (Dashboard Layer)

    Authorities:
    - OMS DB (via OrderRepository)
    - Risk state file (client-scoped)
    - Market data heartbeat (system-scoped)

    ❌ No execution
    ❌ No broker access
    """

    def __init__(self, client_id: str):
        """
        Args:
            client_id: Dashboard client identifier
        """
        self.client_id = client_id
        self.config = Config()
        self.order_repo = OrderRepository(client_id)

    # ==================================================
    # OMS / DB TRUTH
    # ==================================================
    def get_orders(self, limit: int = 500):
        return self.order_repo.get_all(limit=limit)

    def get_open_orders(self):
        return self.order_repo.get_open_orders()

    # ==================================================
    # CONTROL / SYSTEM INTENTS (OPTIONAL)
    # ==================================================
    def get_control_intents(self, limit: int = 200):
        """
        Control intents are optional and system-dependent.
        If not present, return empty list safely.
        """
        try:
            return self.order_repo.get_control_intents(limit=limit)
        except AttributeError:
            # Backward-compatible fallback
            return []

    # ==================================================
    # RISK STATE (CLIENT-SCOPED)
    # ==================================================
    def get_risk_state(self) -> Optional[dict]:
        # BUG-H1 FIX: str.rstrip(chars) strips individual characters, NOT a
        # suffix string. e.g. "nifty_risk.json".rstrip('.json') would strip
        # 'n','k','s','i','r' etc. from the right — mangling the base path.
        # Use Path.with_suffix('') to strip exactly ".json".
        risk_file = self.config.risk_state_file
        base = str(Path(risk_file).with_suffix(""))
        path = Path(f"{base}_{self.client_id}.json")
        if not path.exists():
            # Fallback to base path for backward compat
            path = Path(risk_file)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    # ==================================================
    # MARKET DATA HEARTBEAT (SYSTEM-SCOPED)
    # ==================================================
    def get_option_data_heartbeat(self) -> Optional[dict]:
        if not OPTION_DATA_HEARTBEAT.exists():
            return None

        # BUG-H3 FIX: Heartbeat file can be empty or partially written if the
        # supervisor crashed mid-write.  raw float()/int() raises ValueError in
        # that case and crashes the entire /home/status snapshot endpoint (polled
        # every 2 s by the dashboard).  Return None on any read/parse failure so
        # the UI shows "heartbeat unavailable" instead of a 500 error.
        try:
            with open(OPTION_DATA_HEARTBEAT) as f:
                ts_raw = f.readline().strip()
                chains_raw = f.readline().strip()
                login = f.readline().strip()

            ts = float(ts_raw)
            chains = int(chains_raw)
        except (OSError, ValueError) as exc:
            logger.warning("Could not read option-data heartbeat: %s", exc)
            return None

        return {
            "timestamp": ts,
            "age_sec": round(time.time() - ts, 1),
            "chains": chains,
            "login": login,
        }

    # ==================================================
    # TELEGRAM MESSAGE LOG (SYSTEM-SCOPED)
    # ==================================================
    def get_telegram_messages(self, limit: int = 200) -> list:
        if not TELEGRAM_LOG.exists():
            return []

        try:
            with open(TELEGRAM_LOG, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            return []

        items = []
        for line in lines[-limit:]:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    def get_telegram_alert_stats(self, limit: int = 500) -> dict:
        messages = self.get_telegram_messages(limit=limit)
        total = len(messages)
        success = 0
        failed = 0
        alerts = 0
        risk = 0
        last_ts = None

        for item in messages:
            text = (item.get("message") or "").lower()
            ts = item.get("ts")
            if ts:
                last_ts = max(last_ts or ts, ts)

            if "alert received" in text:
                alerts += 1
            if "order successful" in text or "login successful" in text:
                success += 1
            if "order failed" in text or "login failed" in text:
                failed += 1
            if "risk" in text or "force exit" in text:
                risk += 1

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "alerts": alerts,
            "risk": risk,
            "last_ts": last_ts,
        }

    # ==================================================
    # DERIVED SYSTEM ANALYTICS
    # ==================================================
    def get_signal_activity(self) -> dict:
        recent = self.order_repo.get_all(limit=1)
        return {
            "has_activity": bool(recent),
            "last_order_ts": recent[0].updated_at if recent else None,
        }

    def get_system_activity(self) -> dict:
        orders = self.order_repo.get_all(limit=50)
        return {
            "recent_orders": len(orders),
            "last_order_time": orders[0].updated_at if orders else None,
        }