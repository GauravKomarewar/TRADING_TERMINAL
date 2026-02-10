#!/usr/bin/env python3
"""
DASHBOARD SCHEMAS (PRODUCTION)

This file contains TWO categories of schemas:

1️⃣ 🔒 EXECUTION CONTRACT SCHEMAS (FROZEN)
   - Used by execution consumers
   - Persisted into control_intents
   - MUST NOT change without full OMS + consumer audit

2️⃣ 🧾 DASHBOARD VIEW SCHEMAS (EVOLVABLE)
   - Used only for API responses / UI
   - NOT read by execution or OMS
   - Safe to evolve with dashboard features

schemas.py
Version: v1.1.0
Status: PRODUCTION FROZEN
Scope: Dashboard → Control Queue Execution Contract

IMPORTANT:
Only schemas explicitly marked as EXECUTION CONTRACT
are subject to freeze guarantees.
"""
#==============================================
# File        : schemas.py
# Status      : PRODUCTION FROZEN V.1.1.0
# Action :
# EXECUTION CONTRACT — CLOSED (do not modify without OMS + consumer audit)
# DASHBOARD VIEW SCHEMAS — EVOLVABLE

# Role        : Dashboard → Control Queue contract
# Guarantees  :
#   - Enum-safe validation
#   - Exchange-complete
#   - No silent downgrades
#   - No execution coupling
#   - Advanced intent declared (unresolved by design)
# NOTE:
# Instrument-level LIMIT/MARKET constraints are enforced by ScriptMaster
# at execution time. Schema intentionally does NOT hardcode exchange rules.

#==============================================
from datetime import time
from enum import Enum
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, model_validator

# ============================================================
# ENUMS (CANONICAL)
# ============================================================

class GenericSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyAction(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ADJUST = "ADJUST"
    FORCE_EXIT = "FORCE_EXIT"


class Exchange(str, Enum):
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    NSE = "NSE"
    BSE = "BSE"
    CDS = "CDS"

class Product(str, Enum):
    MIS = "MIS"
    NRML = "NRML"
    CNC = "CNC"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SLM = "SLM"


# ============================================================
# GENERIC INTENT (SYMBOL / ORDER LEVEL)
# ============================================================
class GenericIntentRequest(BaseModel):
    """
    Generic OMS intent.

    Represents a SINGLE manual order request.
    Persisted verbatim into control queue.
    """

    # ------------------------
    # Instrument
    # ------------------------
    exchange: Exchange
    symbol: str = Field(..., min_length=1)

    # ------------------------
    # Execution control
    # ------------------------
    execution_type: Literal["ENTRY", "EXIT"] = "ENTRY"
    test_mode: Optional[Literal["SUCCESS", "FAILURE"]] = None

    # ------------------------
    # Order
    # ------------------------
    side: GenericSide
    qty: int = Field(..., gt=0)
    product: Product
    order_type: OrderType

    price: Optional[float] = Field(default=None, gt=0)
    triggered_order: Optional[Literal["YES", "NO"]] = "NO"
    trigger_value: Optional[float] = Field(default=None, gt=0)

    # ------------------------
    # Risk management (optional)
    # ------------------------
    target: Optional[float] = Field(default=None, gt=0)
    stoploss: Optional[float] = Field(default=None, gt=0)
    trail_sl: Optional[float] = Field(default=None, gt=0)
    trail_when: Optional[float] = Field(default=None, gt=0)

    # ------------------------
    # Meta
    # ------------------------
    reason: Optional[str] = "DASHBOARD_GENERIC"

    # ========================================================
    # VALIDATION (HARD FAIL — NO DOWNGRADES)
    # ========================================================
    @model_validator(mode="after")
    def validate_order_contract(self):

        # Trigger contract
        if self.triggered_order == "YES":
            if self.trigger_value is None:
                raise ValueError("trigger_value required when triggered_order=YES")

        # SL / SLM remain broker-style
        if self.order_type in (OrderType.SL, OrderType.SLM):
            if self.triggered_order != "YES":
                raise ValueError(f"{self.order_type} must be triggered")

        # Price rules
        if self.order_type in (OrderType.LIMIT, OrderType.SL):
            if self.price is None:
                raise ValueError(f"{self.order_type} order requires price")

        return self

# ============================================================
# STRATEGY INTENT (STRATEGY LEVEL)
# ============================================================

class StrategyIntentRequest(BaseModel):
    """
    Strategy-scoped control intent.

    This does NOT specify instruments.
    It instructs a running strategy
    to change lifecycle state.
    """

    strategy_name: str = Field(
        ..., min_length=1, description="Registered strategy name"
    )

    action: StrategyAction = Field(
        ..., description="ENTRY / EXIT / ADJUST / FORCE_EXIT"
    )

    reason: Optional[str] = "DASHBOARD_STRATEGY"

class StrategyEntryRequest(BaseModel):
    strategy_name: str
    strategy_version: str

    exchange: Exchange
    symbol: str
    instrument_type: str   # OPTIDX / OPTSTK / FUT / MCX

    entry_time: str        # ISO time
    exit_time: str

    order_type: OrderType
    product: Product

    lot_qty: int
    params: dict

    poll_interval: Optional[float] = 2.0
    cooldown_seconds: Optional[int] = 0

    @model_validator(mode="after")
    def validate_time_fields(self):
        try:
            time.fromisoformat(self.entry_time)
            time.fromisoformat(self.exit_time)
        except Exception:
            raise ValueError(
                "entry_time and exit_time must be ISO time only (HH:MM:SS)"
            )
        return self
        
    @model_validator(mode="after")
    def normalize_cooldown(self):
        if "cooldown_seconds" in self.params:
            self.cooldown_seconds = int(self.params["cooldown_seconds"])
        return self

    @model_validator(mode="after")
    def validate_dnss_contract(self):
        """Validate DNSS-specific params only for DNSS strategies."""
        name_lower = (self.strategy_name or "").lower()
        version_lower = (self.strategy_version or "").lower()
        is_dnss = "dnss" in name_lower or "dnss" in version_lower
        if is_dnss:
            required = [
                "target_entry_delta",
                "delta_adjust_trigger",
                "max_leg_delta",
                "profit_step",
                "cooldown_seconds",
            ]
            for k in required:
                if k not in self.params:
                    raise ValueError(f"Missing DNSS param: {k}")
        return self

    @model_validator(mode="after")
    def validate_instrument_type(self):
        allowed = {"OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK", "MCX", "CASH"}
        if self.instrument_type not in allowed:
            raise ValueError(
                f"instrument_type must be one of {sorted(allowed)}"
            )
        return self


# ============================================================
# STANDARD RESPONSE
# ============================================================

class IntentResponse(BaseModel):
    """
    Control-plane acknowledgment.

    accepted = queued successfully
    NOT execution success.
    """

    accepted: bool
    message: str
    intent_id: Optional[str] = None


# ==========================================================
# ADVANCED INTENT SCHEMAS
# ==========================================================
class AdvancedLegRequest(BaseModel):
    exchange: Exchange
    symbol: str

    side: GenericSide
    execution_type: Literal["ENTRY", "EXIT"]
    test_mode: Optional[Literal["SUCCESS", "FAILURE"]] = None

    qty: int = Field(gt=0)
    product: Product
    order_type: OrderType
    price: Optional[float] = Field(default=None, gt=0)

    target_type: Literal[
        "DELTA",
        "THETA",
        "GAMMA",
        "VEGA",
        "PRICE",
        "PREMIUM",
    ]
    target_value: Optional[float] = None

    @model_validator(mode="after")
    def validate_advanced_contract(self):
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("LIMIT order requires price")
        return self


class AdvancedIntentRequest(BaseModel):
    legs: List[AdvancedLegRequest]
    reason: Optional[str] = "WEB_ADVANCED"


class BasketIntentRequest(BaseModel):
    orders: List[GenericIntentRequest]
    reason: Optional[str] = "WEB_BASKET"


# ============================================================
# ORDERS
# ============================================================

class OrderView(BaseModel):
    command_id: str
    execution_type: str
    source: str
    strategy_name: Optional[str]
    exchange: str
    symbol: str
    side: str
    quantity: int
    order_type: Optional[str]
    price: Optional[float]
    status: str
    broker_order_id: Optional[str]
    created_at: str
    updated_at: str


# ============================================================
# CONTROL INTENTS
# ============================================================

class ControlIntentView(BaseModel):
    id: str
    type: str
    source: str
    status: str
    payload: dict
    created_at: str


# ============================================================
# BROKER POSITIONS
# ============================================================

class PositionView(BaseModel):
    exchange: str
    symbol: str
    product: str
    netqty: int
    rpnl: float
    urmtom: float
    pnl: float


# ============================================================
# RISK STATUS
# ============================================================

class RiskStatusView(BaseModel):
    current_pnl: float
    max_loss: float
    daily_loss_hit: bool
    cooldown_until: Optional[str]
    force_exit_in_progress: bool
    today_high: float
    today_low: float



class SymbolSearchResult(BaseModel):
    exchange: str
    tradingsymbol: str
    instrument: str          # FUT / CE / PE / EQ
    underlying: Optional[str]
    expiry: Optional[str]
    strike: Optional[float]
    option_type: Optional[str]


class ExpiryView(BaseModel):
    expiry: str


class ContractView(BaseModel):
    tradingsymbol: str
    instrument: str
    strike: Optional[float]
    option_type: Optional[str]
