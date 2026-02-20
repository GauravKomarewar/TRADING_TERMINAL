import unittest
from shoonya_platform.strategy_runner.state import StrategyState, LegState
from shoonya_platform.strategy_runner.reconciliation import BrokerReconciliation
from shoonya_platform.strategy_runner.models import InstrumentType, OptionType, Side

class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.state = StrategyState()
        self.leg = LegState(
            tag="LEG@1",
            symbol="NIFTY",
            instrument=InstrumentType.OPT,
            option_type=OptionType.CE,
            strike=25000,
            expiry="2025-01-30",
            side=Side.SELL,
            qty=1,
            entry_price=100,
            ltp=120,
            is_active=True
        )
        self.state.legs["LEG@1"] = self.leg
        self.recon = BrokerReconciliation(self.state)

    def test_missing_in_broker(self):
        broker_positions = []
        warnings = self.recon.reconcile(broker_positions)
        self.assertEqual(len(warnings), 1)
        self.assertIn("missing in broker", warnings[0])
        self.assertFalse(self.state.legs["LEG@1"].is_active)

    def test_extra_in_broker(self):
        broker_positions = [
            {"tag": "LEG@1", "symbol": "NIFTY", "qty": 1, "ltp": 120},
            {"tag": "LEG@2", "symbol": "NIFTY", "qty": 2, "ltp": 50}
        ]
        warnings = self.recon.reconcile(broker_positions)
        self.assertEqual(len(warnings), 1)
        self.assertIn("extra position LEG@2", warnings[0])
        self.assertIn("LEG@2", self.state.legs)

if __name__ == '__main__':
    unittest.main()