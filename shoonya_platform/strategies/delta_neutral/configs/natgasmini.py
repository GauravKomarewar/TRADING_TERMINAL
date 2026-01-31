"""
MCX NATGASMINI - Delta Neutral Auto Adjust Short Strangle
CONFIG ONLY
"""

from datetime import time
from shoonya_platform.strategies.delta_neutral.delta_neutral_short_strategy import StrategyConfig

STRATEGY_NAME = "NATGASMINI_DELTA_AUTO_ADJUST"

META = {
    "exchange": "MCX",
    "symbol": "NATGASMINI",
}

CONFIG = StrategyConfig(
    # MCX market timings (IST)
    entry_time=time(9, 5),          # MCX opens at 09:00, safe entry after warm-up
    exit_time=time(23, 00),         # Exit before MCX close (23:30)

    # Delta parameters (NATGASMINI is more volatile than NIFTY)
    target_entry_delta=0.35,
    delta_adjust_trigger=0.18,
    max_leg_delta=0.60,

    # Profit booking (₹)
    profit_step=1500.0,

    # Cooldown between adjustments (seconds)
    cooldown_seconds=300,
)

ENGINE = {
    "poll_interval": 2.0,
    "sleep_after_exit_sec": 1800,
    "error_retry_sleep_sec": 60,
}
