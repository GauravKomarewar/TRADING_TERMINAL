from pathlib import Path
from datetime import datetime
from typing import List

OPTION_CHAIN_DATA_DIR = (
    Path(__file__).resolve().parents[3]
    / "market_data/option_chain/data"
)

def get_active_expiries(exchange: str, symbol: str) -> List[str]:
    """
    Read active option-chain expiries from supervisor DB directory.

    Filename format:
        <EXCHANGE>_<SYMBOL>_<EXPIRY>.sqlite
    Example:
        NFO_NIFTY_10-FEB-2026.sqlite
    """
    expiries = []

    prefix = f"{exchange}_{symbol}_"
    suffix = ".sqlite"

    for p in OPTION_CHAIN_DATA_DIR.glob(f"{prefix}*{suffix}"):
        name = p.name
        expiry = name.replace(prefix, "").replace(suffix, "")
        expiries.append(expiry)

    # Sort nearest → farthest
    def parse_expiry(e: str) -> datetime:
        return datetime.strptime(e, "%d-%b-%Y")

    expiries = sorted(set(expiries), key=parse_expiry)
    return expiries
