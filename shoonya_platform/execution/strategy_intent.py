"""
ENGINE INTENT MODELS
====================

• Shared between strategy & engine
• Immutable intent description
• No broker logic here
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Intent:
    # Strategy intent (immutable)
    action: Literal["BUY", "SELL"]
    symbol: str
    qty: int
    tag: str

    # Execution parameters (engine/broker responsibility)
    order_type: Literal["MKT", "LMT"] = "MKT"
    price: float = 0.0

