from pathlib import Path
from datetime import datetime
from typing import List
import time
import sqlite3
from typing import Dict, Any, Optional

from shoonya_platform.market_data.option_chain.db_access import OptionChainDBReader

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


def find_nearest_option(
    db_path: str,
    *,
    target: float,
    metric: str = "ltp",
    option_type: Optional[str] = None,
    max_age: float = 5.0,
) -> Dict[str, Any]:
    """
    Find the nearest option contract in a snapshot DB by a target value.

    Args:
        db_path: Path to option-chain sqlite DB
        target: numeric target to match (price or greek)
        metric: which column to use for distance ('ltp', 'iv', 'delta', etc.)
        option_type: 'CE' or 'PE' to filter, or None for both
        max_age: maximum allowed snapshot age in seconds

    Returns:
        A single row dict representing the nearest contract.
    """

    reader = OptionChainDBReader(str(db_path))
    meta, rows = reader.read(max_age=max_age)

    best = None
    best_dist = None

    for r in rows:
        if option_type and r.get("option_type") != option_type:
            continue
        val = r.get(metric)
        if val is None:
            continue
        try:
            dist = abs(float(val) - float(target))
        except Exception:
            continue

        if best is None or dist < best_dist:
            best = r
            best_dist = dist

    if best is None:
        raise RuntimeError("No matching option found")

    return best
