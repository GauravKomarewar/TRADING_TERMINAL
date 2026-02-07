# shoonya_platform/api/dashboard/services/broker_service.py
from shoonya_platform.brokers.shoonya.client import ShoonyaClient

class BrokerView:
    def __init__(self, api: ShoonyaClient):
        self.api = api

    def get_positions(self):
        return self.api.get_positions() or []

    def get_order_book(self):
        return self.api.get_order_book() or []

    def get_holdings(self):
        return self.api.get_holdings() or []

    def get_limits(self):
        return self.api.get_limits() or {}

class BrokerService:
    """
    BROKER TRUTH — READ ONLY (Dashboard Layer)

    ✔ Uses ShoonyaBot session
    ✔ Single broker truth
    ✔ Zero extra login
    ❌ No execution
    ❌ No new client
    """

    def __init__(self, broker_view):
        """
        Args:
            broker_view: ReadOnlyBrokerView (from ShoonyaBot)
        """
        self.broker = broker_view

    # ==================================================
    # RAW BROKER DATA (PASS-THROUGH)
    # ==================================================
    def get_order_book(self) -> list:
        return self.broker.get_order_book()

    def get_positions(self) -> list:
        return self.broker.get_positions()

    def get_holdings(self) -> list:
        return self.broker.get_holdings()

    def get_limits(self) -> dict:
        return self.broker.get_limits()

    # ==================================================
    # DERIVED ANALYTICS (UNCHANGED)
    # ==================================================
    def get_positions_summary(self) -> dict:
        positions = self.get_positions()

        summary = {
            "open_count": 0,
            "net_pnl": 0.0,
            "gross_realized": 0.0,
            "gross_unrealized": 0.0,
            "long_qty": 0,
            "short_qty": 0,
            "by_symbol": {},
        }

        for p in positions:
            netqty = int(p.get("netqty", 0))
            rpnl = float(p.get("rpnl", 0) or 0)
            urmtom = float(p.get("urmtom", 0) or 0)

            if netqty != 0:
                summary["open_count"] += 1

            summary["gross_realized"] += rpnl
            summary["gross_unrealized"] += urmtom
            summary["net_pnl"] += rpnl + urmtom

            if netqty > 0:
                summary["long_qty"] += netqty
            elif netqty < 0:
                summary["short_qty"] += abs(netqty)

            symbol = p.get("tsym")
            if symbol:
                summary["by_symbol"].setdefault(symbol, 0)
                summary["by_symbol"][symbol] += netqty

        summary["net_pnl"] = round(summary["net_pnl"], 2)
        summary["gross_realized"] = round(summary["gross_realized"], 2)
        summary["gross_unrealized"] = round(summary["gross_unrealized"], 2)

        return summary
