#===========================================================
#UniversalOrderCommand
# Version : v2.0.0
# Status  : PRODUCTION FROZEN
# Audit   : PASSED — compatibility hardening only
# Note    : No execution semantics changed
#===========================================================

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
import uuid

from shoonya_platform.persistence.models import OrderRecord

# =========================
# ENUM-LIKE TYPES
# =========================

OrderSide = Literal["BUY", "SELL"]

OrderType = Literal[
    "MARKET",
    "LIMIT",
    "SL",
    "SLM",
    "LEVEL",      # Buy/Sell at level
    "BRACKET",    # Entry + SL + Target
    "COVER",      # Entry + SL
]

Product = Literal["MIS", "NRML", "CNC"]

TriggerType = Literal[
    "NONE",
    "ABOVE_PRICE",
    "BELOW_PRICE",
]

TrailingType = Literal[
    "NONE",
    "POINTS",
    "PERCENT",
    "ABSOLUTE",
]

CommandSource = Literal[
    "WEB",
    "STRATEGY",
    "SYSTEM",
]

ORDER_TYPE_ALIASES = {
    # MARKET
    "MARKET": "MARKET",
    "MKT": "MARKET",

    # LIMIT
    "LIMIT": "LIMIT",
    "LMT": "LIMIT",

    # STOP LOSS
    "SL": "SL",
    "SL-LMT": "SL",

    # STOP LOSS MARKET
    "SLM": "SLM",
    "SL-MKT": "SLM",
}

# =========================
# UNIVERSAL ORDER COMMAND
# =========================

@dataclass(frozen=True)
class UniversalOrderCommand:
    """
    Single immutable order command.

    ALL trading actions (manual or automated)
    MUST flow through this structure.
    """

    # Legacy compatibility field (some tests pass 'intent')
    intent: Optional[str] = None

    # ---- Identity / Audit ----
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    source: CommandSource = "WEB"
    user: str = "TEST"

    # ---- Instrument ----
    exchange: Optional[str] = None
    symbol: Optional[str] = None
    quantity: int = 0
    side: Optional[OrderSide] = None
    product: Optional[Product] = None

    # ---- Primary Order ----
    order_type: OrderType = "MARKET"
    price: Optional[float] = None

    # ---- Trigger / Level Order ----
    trigger_type: TriggerType = "NONE"
    trigger_price: Optional[float] = None
    trigger_execution: Literal["MARKET", "LIMIT"] = "MARKET"
    trigger_limit_price: Optional[float] = None

    # ---- Risk Controls ----
    stop_loss: Optional[float] = None
    target: Optional[float] = None

    # ---- Trailing Stop ----
    trailing_type: TrailingType = "NONE"
    trailing_value: Optional[float] = None
    trail_step: Optional[float] = None

    # ---- Meta ----
    strategy_name: Optional[str] = None
    comment: Optional[str] = None

    # =========================
    # FACTORY
    # =========================
    @staticmethod
    def new(**kwargs) -> "UniversalOrderCommand":
        return UniversalOrderCommand(
            command_id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            **kwargs,
        )

    @classmethod
    def from_order_params(cls, *, order_params, source: str, user: str):
        def get(key, default=None):
            if isinstance(order_params, dict):
                return order_params.get(key, default)
            return getattr(order_params, key, default)

        def req(key):
            val = get(key)
            if val is None:
                raise KeyError(f"Missing required order param: {key}")
            return val

        # ✅ ORDER TYPE NORMALIZATION (ONLY PLACE IT SHOULD EXIST)
        raw_order_type = get("order_type", "MARKET")
        normalized_order_type = ORDER_TYPE_ALIASES.get(
            str(raw_order_type).upper()
        )

        if not normalized_order_type:
            raise ValueError(f"Unsupported order_type: {raw_order_type}")

        # Flexible key mapping to support different callers
        exchange_val = get("exchange") or get("exch")
        symbol_val = get("symbol") or get("tradingsymbol")
        quantity_val = get("quantity") or get("qty")
        side_val = get("side") or get("direction")
        product_val = get("product") or get("prd") or get("product_type")

        def req_flex(key, val):
            if val is None:
                raise KeyError(f"Missing required order param: {key}")
            return val

        return cls.new(
            source=source,
            user=user,

            exchange=req_flex("exchange", exchange_val),
            symbol=req_flex("symbol", symbol_val),
            quantity=req_flex("quantity", quantity_val),
            side=req_flex("side", side_val),
            product=req_flex("product", product_val),

            order_type=normalized_order_type,   # ✅ CANONICAL
            price=get("price"),

            stop_loss=get("stop_loss"),
            target=get("target"),

            trailing_type=get("trailing_type", "NONE"),
            trailing_value=get("trailing_value"),
            trail_step=get("trail_step"),

            strategy_name=get("strategy_name"),
            comment=get("comment"),
        )


    def to_broker_params(self) -> dict:
        """
        Convert canonical UniversalOrderCommand
        into Shoonya API order parameters.

        Shoonya Docs:
        - prd      : C / M / I / B / H
        - trantype : B / S
        - prctyp   : MKT / LMT / SL-LMT / SL-MKT
        """

        # ----------------------------
        # PRODUCT MAPPING with NORMALIZATION
        # ----------------------------
        product_map = {
            # Canonical names
            "CNC": "C",
            "NRML": "M",
            "MIS": "I",
            "BRACKET": "B",
            "COVER": "H",

            # Shoonya direct codes (already normalized)
            "C": "C",
            "M": "M",
            "I": "I",
            "B": "B",
            "H": "H",
        }


        # ----------------------------
        # ORDER TYPE MAPPING
        # ----------------------------
        order_type_map = {
            "MARKET": "MKT",
            "LIMIT": "LMT",
            "SL": "SL-LMT",
            "SLM": "SL-MKT",
        }

        # ----------------------------
        # SIDE MAPPING
        # ----------------------------
        side_map = {
            "BUY": "B",
            "SELL": "S",
        }

        prd = product_map.get(self.product)
        if not prd:
            raise ValueError(f"Unsupported product type: {self.product}")

        prctyp = order_type_map.get(self.order_type)
        if not prctyp:
            raise ValueError(f"Unsupported order type: {self.order_type}")

        trantype = side_map.get(self.side)
        if not trantype:
            raise ValueError(f"Unsupported side: {self.side}")

        # params = {
        #     "exchange": self.exchange,
        #     "tradingsymbol": self.symbol,
        #     "quantity": int(self.quantity),
        #     "buy_or_sell": trantype,
        #     "product_type": prd,
        #     "price_type": prctyp,
        # }
        params = {
            "exchange": self.exchange,
            "tradingsymbol": self.symbol,
            "quantity": int(self.quantity),
            "buy_or_sell": trantype,        # "B" / "S"
            "product_type": prd,            # "M" for MCX
            "price_type": prctyp,           # "LMT" / "MKT"
            "price": float(self.price) if prctyp == "LMT" else 0,
            "discloseqty": 0,
            "retention": "DAY",
            "remarks": self.strategy_name,
        }


        # ----------------------------
        # PRICE HANDLING
        # ----------------------------
        if prctyp == "LMT":
            if self.price is None:
                raise ValueError("LIMIT order requires price")
            params["price"] = float(self.price)
        else:
            params["price"] = 0

        # ----------------------------
        # OPTIONAL TRIGGER (SL)
        # ----------------------------
        if prctyp in ("SL-LMT", "SL-MKT"):
            if self.trigger_price is None:
                raise ValueError("SL order requires trigger_price")
            params["trigger_price"] = float(self.trigger_price)

        return params


    def to_record(self, execution_type: str = "ENTRY") -> OrderRecord:
        """
        Convert to OrderRecord for persistence.
        """
        now = datetime.utcnow().isoformat()
        return OrderRecord(
            command_id=self.command_id,
            source=self.source,
            user=self.user,
            strategy_name=self.strategy_name or "",
            
            exchange=self.exchange,
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity,
            product=self.product,
            
            order_type=self.order_type,
            price=self.price,
            
            stop_loss=self.stop_loss,
            target=self.target,
            trailing_type=self.trailing_type,
            trailing_value=self.trailing_value,
            
            broker_order_id=None,
            execution_type=execution_type,
            
            status="CREATED",
            created_at=now,
            updated_at=now,
            tag=None,
        )
