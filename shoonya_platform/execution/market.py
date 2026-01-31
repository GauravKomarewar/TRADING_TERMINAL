"""
LIVE MARKET SNAPSHOT (NEW PLATFORM)
==================================

• Read-only
• Single source of market data
• Strategy-agnostic
"""

class LiveMarket:
    def __init__(self, *, option_chain):
        self.option_chain = option_chain

    def snapshot(self) -> dict:
        """
        Returns market snapshot for engine → strategy injection.
        """
        stats = self.option_chain.get_stats()

        return {
            "greeks": self.option_chain.get_greeks(),
            "spot": stats.get("spot_ltp"),
        }
