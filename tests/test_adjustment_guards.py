import unittest
from datetime import datetime, timedelta
from shoonya_platform.strategy_runner.state import StrategyState
from shoonya_platform.strategy_runner.adjustment_engine import AdjustmentEngine
from shoonya_platform.strategy_runner.market_reader import MockMarketReader

class TestAdjustmentGuards(unittest.TestCase):
    def setUp(self):
        self.state = StrategyState()
        self.market = MockMarketReader()
        self.engine = AdjustmentEngine(self.state, self.market)

    def test_cooldown(self):
        rule = {
            "name": "test",
            "priority": 1,
            "cooldown_sec": 10,
            "conditions": [],
            "action": {"type": "close_leg"}
        }
        self.engine.rules_config = [rule]
        self.state.last_adjustment_time = datetime.now() - timedelta(seconds=5)
        # cooldown not passed
        self.assertFalse(self.engine._check_guards(rule))

        self.state.last_adjustment_time = datetime.now() - timedelta(seconds=15)
        self.assertTrue(self.engine._check_guards(rule))

    def test_max_per_day(self):
        rule = {
            "name": "test",
            "priority": 1,
            "max_per_day": 2,
            "conditions": [],
            "action": {"type": "close_leg"}
        }
        self.state.adjustments_today = 2
        self.assertFalse(self.engine._check_guards(rule))
        self.state.adjustments_today = 1
        self.assertTrue(self.engine._check_guards(rule))

if __name__ == '__main__':
    unittest.main()