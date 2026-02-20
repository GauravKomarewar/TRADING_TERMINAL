import unittest
from shoonya_platform.strategy_runner.market_reader import MockMarketReader
from shoonya_platform.strategy_runner.models import StrikeConfig, StrikeMode, Side, OptionType

class TestStrikeSelection(unittest.TestCase):
    def setUp(self):
        self.market = MockMarketReader()
        self.market._spot = 25000
        self.market._atm = 25000

    def test_atm(self):
        cfg = StrikeConfig(
            mode=StrikeMode.STANDARD,
            side=Side.SELL,
            option_type=OptionType.CE,
            lots=1,
            strike_selection="atm"
        )
        strike, data = self.market.resolve_strike(cfg, "NIFTY", "weekly")
        self.assertEqual(strike, 25000)

    def test_exact(self):
        cfg = StrikeConfig(
            mode=StrikeMode.EXACT,
            side=Side.SELL,
            option_type=OptionType.CE,
            lots=1,
            exact_strike=25150,
            rounding=50
        )
        strike, data = self.market.resolve_strike(cfg, "NIFTY", "weekly")
        self.assertEqual(strike, 25150)

    def test_atm_points(self):
        cfg = StrikeConfig(
            mode=StrikeMode.ATM_POINTS,
            side=Side.SELL,
            option_type=OptionType.CE,
            lots=1,
            atm_offset_points=100,
            rounding=50
        )
        strike, data = self.market.resolve_strike(cfg, "NIFTY", "weekly")
        self.assertEqual(strike, 25100)

if __name__ == '__main__':
    unittest.main()