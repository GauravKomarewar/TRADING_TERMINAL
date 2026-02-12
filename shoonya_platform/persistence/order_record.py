#===================================================================
# 🔒 OMS STATUS CONTRACT — PRODUCTION FROZEN (2026-01-29)

# CREATED         : OMS intent only (not sent to broker)
# SENT_TO_BROKER  : Broker accepted order, order_id assigned
# EXECUTED        : Filled at broker
# FAILED           → Broker cancelled / rejected / expired

# TRIGGERED / EXITED / FAILED are forbidden.
#===================================================================

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class OrderRecord:
    # ---- Identity ----
    command_id: str
    source: str                 # STRATEGY | ENGINE | MANUAL
    user: str                   # broker user (FAxxxx)
    strategy_name: str          

    # ---- Instrument ----
    exchange: str
    symbol: str
    side: str                   # BUY | SELL
    quantity: int
    product: str                # M / I / C

    # ---- Order ----
    order_type: str             # MKT | LMT | SL
    price: float

    # ---- Risk ----
    stop_loss: Optional[float]
    target: Optional[float]
    trailing_type: Optional[str]
    trailing_value: Optional[float]

    # ---- Execution ----
    broker_order_id: Optional[str]
    execution_type: str         # ENTRY | EXIT | ADJUST

    # ---- State ----
    status: str                # CREATED | SENT_TO_BROKER | EXECUTED | FAILED
    created_at: str
    updated_at: str
    tag: Optional[str]          # ENTRY_CE | ENTRY_PE | EXIT | MANUAL_EXIT