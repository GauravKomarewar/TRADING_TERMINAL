"""
NIFTY - Delta Neutral Auto Adjust Short Strangle
CONFIG ONLY
"""

from datetime import time
from shoonya_platform.strategies.delta_neutral.delta_neutral_short_strategy import StrategyConfig

STRATEGY_NAME = "NIFTY_DELTA_AUTO_ADJUST"

META = {
    "exchange": "NFO",
    "symbol": "NIFTY",
}

CONFIG = StrategyConfig(
    entry_time=time(9, 18),
    exit_time=time(15, 28),

    target_entry_delta=0.4,
    delta_adjust_trigger=0.10,
    max_leg_delta=0.65,
    profit_step=1000.0,

    cooldown_seconds=300,
)

ENGINE = {
    "poll_interval": 2.0,
    "sleep_after_exit_sec": 1800,
    "error_retry_sleep_sec": 60,
}
