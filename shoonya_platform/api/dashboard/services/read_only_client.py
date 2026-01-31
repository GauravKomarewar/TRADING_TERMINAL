import logging
from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient

logger = logging.getLogger("DASHBOARD.BROKER")


class ReadOnlyShoonyaClient:
    """
    Dashboard-safe Shoonya client (READ-ONLY).

    ✔ Client-scoped
    ✔ Multi-client safe
    ✔ Copy-trading compatible
    ❌ No order placement
    """

    def __init__(self, client_id: str):
        self.client_id = client_id

        # Each dashboard client gets its OWN Shoonya session
        self._client = ShoonyaClient(Config(client_id=client_id))

    # --------------------------------------------------
    # INTERNAL
    # --------------------------------------------------
    def _ensure_login(self):
        if not self._client.is_logged_in():
            logger.warning(
                "🔐 DASHBOARD LOGIN | client=%s | reason=session_expired",
                self.client_id,
            )
            self._client.login()

    # --------------------------------------------------
    # READ-ONLY API
    # --------------------------------------------------
    def get_positions(self):
        self._ensure_login()
        return self._client.get_positions() or []

    def get_holdings(self):
        self._ensure_login()
        return self._client.get_holdings() or []

    def get_order_book(self):
        self._ensure_login()
        return self._client.get_order_book() or []

    def get_limits(self):
        self._ensure_login()
        return self._client.get_limits() or []

    # --------------------------------------------------
    # HARD SAFETY: BLOCK ALL WRITES
    # --------------------------------------------------
    def __getattr__(self, name):
        """
        Prevent accidental access to write APIs like place_order.
        """
        if name in {
            "place_order",
            "modify_order",
            "cancel_order",
            "exit_order",
        }:
            raise RuntimeError(
                f"❌ Dashboard attempted WRITE operation: {name}"
            )
        raise AttributeError(name)