# shoonya_platform/api/dashboard/services/system_service.py

import json
import time
from pathlib import Path
from typing import Optional

from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.core.config import Config

# --------------------------------------------------
# SYSTEM-WIDE (NON CLIENT-SCOPED) FILES
# --------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[4]

OPTION_DATA_HEARTBEAT = (
    PROJECT_ROOT / "market_data/option_chain/data/.supervisor_heartbeat"
)


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
        path = Path(self.config.risk_state_file)
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    # ==================================================
    # MARKET DATA HEARTBEAT (SYSTEM-SCOPED)
    # ==================================================
    def get_option_data_heartbeat(self) -> Optional[dict]:
        if not OPTION_DATA_HEARTBEAT.exists():
            return None

        with open(OPTION_DATA_HEARTBEAT) as f:
            ts = float(f.readline().strip())
            chains = int(f.readline().strip())
            login = f.readline().strip()

        return {
            "timestamp": ts,
            "age_sec": round(time.time() - ts, 1),
            "chains": chains,
            "login": login,
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