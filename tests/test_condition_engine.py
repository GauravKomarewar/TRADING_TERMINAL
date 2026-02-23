import unittest
from datetime import datetime
from shoonya_platform.strategy_runner.state import StrategyState, LegState
from shoonya_platform.strategy_runner.condition_engine import ConditionEngine
from shoonya_platform.strategy_runner.models import Condition, Comparator, JoinOperator, InstrumentType, Side, OptionType

class TestConditionEngine(unittest.TestCase):
    def setUp(self):
        self.state = StrategyState()
        self.state.spot_price = 25000
        self.state.combined_pnl = 1000
        self.state.net_delta = 0.5
        self.engine = ConditionEngine(self.state)

    def test_simple_gt(self):
        cond = Condition(parameter="spot_price", comparator=Comparator.GT, value=24000)
        self.assertTrue(self.engine.evaluate([cond]))

    def test_tag_reference(self):
        leg = LegState(
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
            delta=0.3
        )
        self.state.legs["LEG@1"] = leg
        cond = Condition(parameter="tag.LEG@1.delta", comparator=Comparator.GT, value=0.2)
        self.assertTrue(self.engine.evaluate([cond]))

    def test_between(self):
        cond = Condition(parameter="spot_price", comparator=Comparator.BETWEEN, value=24000, value2=26000)
        self.assertTrue(self.engine.evaluate([cond]))

    def test_and_or(self):
        c1 = Condition(parameter="spot_price", comparator=Comparator.GT, value=24000, join=JoinOperator.AND)
        c2 = Condition(parameter="combined_pnl", comparator=Comparator.LT, value=500)
        # spot > 24000 (true) AND pnl < 500 (false) => false
        self.assertFalse(self.engine.evaluate([c1, c2]))

        c2.join = JoinOperator.OR
        # true OR false => true
        self.assertTrue(self.engine.evaluate([c1, c2]))

    def test_is_true_is_false_without_value(self):
        self.state.legs = {}
        c_false = Condition(parameter="any_leg_active", comparator=Comparator.IS_FALSE, value=None)
        c_true = Condition(parameter="all_legs_active", comparator=Comparator.IS_TRUE, value=None)
        self.assertTrue(self.engine.evaluate([c_false]))
        self.assertTrue(self.engine.evaluate([c_true]))

if __name__ == '__main__':
    unittest.main()
