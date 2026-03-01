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
        now = datetime.now()
        # Simulate rule having fired 5s ago (per-rule cooldown tracking)
        self.engine._rule_last_fired["test"] = now - timedelta(seconds=5)
        # cooldown not passed
        self.assertFalse(self.engine._check_guards(rule, now))

        # Simulate rule having fired 15s ago
        self.engine._rule_last_fired["test"] = now - timedelta(seconds=15)
        self.assertTrue(self.engine._check_guards(rule, now))

    def test_max_per_day(self):
        rule = {
            "name": "test",
            "priority": 1,
            "max_per_day": 2,
            "conditions": [],
            "action": {"type": "close_leg"}
        }
        self.state.adjustments_today = 2
        self.assertFalse(self.engine._check_guards(rule, datetime.now()))
        self.state.adjustments_today = 1
        self.assertTrue(self.engine._check_guards(rule, datetime.now()))

    def test_cooldown_uses_supplied_current_time(self):
        rule = {
            "name": "test",
            "priority": 1,
            "cooldown_sec": 10,
            "conditions": [],
            "action": {"type": "close_leg"}
        }
        # Set per-rule last fired time to ensure deterministic behavior
        # depends only on supplied current_time.
        base = datetime(2026, 2, 22, 10, 0, 0)
        self.engine._rule_last_fired["test"] = base
        # 5s later -> still in cooldown.
        self.assertFalse(self.engine._check_guards(rule, base + timedelta(seconds=5)))
        # 15s later -> cooldown over.
        self.assertTrue(self.engine._check_guards(rule, base + timedelta(seconds=15)))

if __name__ == '__main__':
    unittest.main()
