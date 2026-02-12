#!/usr/bin/env python3
"""
UNIVERSAL STRATEGY CONFIG
=========================
Instrument-agnostic, OMS-native, DB-serializable

AUTHORITY:
- Defines WHAT a strategy instance is allowed to do
- Does NOT execute
- Does NOT contain logic
"""

from dataclasses import dataclass, asdict
from datetime import time
from typing import Optional, Dict, Any, Literal
import json


@dataclass(frozen=True)
class UniversalStrategyConfig:
    # -------------------------------------------------
    # IDENTITY
    # -------------------------------------------------
    strategy_name: str
    strategy_version: str

    exchange: str
    symbol: str
    instrument_type: Literal[
        "OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK", "MCX", "CASH"
    ]

    # -------------------------------------------------
    # TIME WINDOW
    # -------------------------------------------------
    entry_time: time
    exit_time: time

    # -------------------------------------------------
    # EXECUTION (OMS-NATIVE)
    # -------------------------------------------------
    order_type: Literal["MARKET", "LIMIT"]
    product: Literal["NRML", "MIS", "CNC"]

    # -------------------------------------------------
    # POSITION SIZING
    # -------------------------------------------------
    lot_qty: int

    # -------------------------------------------------
    # STRATEGY PARAMS (LOGIC-SPECIFIC)
    # Stored as JSON → strategy interprets
    # -------------------------------------------------
    params: Dict[str, Any]

    max_positions: int = 1  # future-safe
    # -------------------------------------------------
    # ENGINE / RUNNER HINTS (NON-AUTHORITATIVE)
    # -------------------------------------------------
    poll_interval: float = 2.0
    cooldown_seconds: int = 0

    # -------------------------------------------------
    # SERIALIZATION
    # -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["entry_time"] = self.entry_time.isoformat()
        d["exit_time"] = self.exit_time.isoformat()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))
