"""
Trading JSON Builder - Matches PineScript webhook format exactly
Generates entry/exit JSON for options trading execution engine
"""
from typing import List, Dict, Optional, Literal, Tuple
from datetime import datetime
from enum import Enum


class Direction(str, Enum):
    """Trade direction"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order types"""
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP_LIMIT = "SL-LMT"


class Exchange(str, Enum):
    """Supported exchanges"""
    NFO = "NFO"
    NSE = "NSE"
    BFO = "BFO"
    BSE = "BSE"
    MCX = "MCX"


class ProductType(str, Enum):
    """Product types"""
    MIS = "M"      # Intraday (Margin Intraday Square-off)
    NRML = "I"     # Intraday
    CNC = "C"      # Cash and Carry


class OptionType(str, Enum):
    """Option types"""
    CALL = "C"
    PUT = "P"
    CE = "CE"
    PE = "PE"


class ExecutionType(str, Enum):
    """Execution types"""
    ENTRY = "entry"
    EXIT = "exit"


# ═══════════════════════════════════════════════════════════════════════════════
# 🏗️ CORE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

# def build_leg(
#     *,
#     tradingsymbol: str,
#     direction: str,
#     order_type: str = "MKT",
#     qty: int,
#     price: float = 0.0
# ) -> Dict:
#     """
#     Build a single leg matching PineScript format exactly.
    
#     Args:
#         tradingsymbol: Symbol like "NIFTY23DEC25C24500"
#         direction: "BUY" or "SELL"
#         order_type: "MKT", "LMT", or "SL-LMT"
#         qty: Quantity (lot size)
#         price: Limit price (0 for market orders)
    
#     Returns:
#         Dict with leg details
    
#     Example:
#         >>> build_leg(
#         ...     tradingsymbol="NIFTY23DEC25C24500",
#         ...     direction="SELL",
#         ...     order_type="MKT",
#         ...     qty=75,
#         ...     price=0
#         ... )
#     """
#     # Convert enums to strings if passed
#     if isinstance(direction, Direction):
#         direction = direction.value
#     if isinstance(order_type, OrderType):
#         order_type = order_type.value
    
#     # Market orders should have price 0
#     if order_type == "MKT":
#         price = 0.0
    
#     return {
#         "tradingsymbol": tradingsymbol,
#         "direction": direction,
#         "order_type": order_type,
#         "price": str(price),  # Convert to string like PineScript
#         "qty": qty
#     }

def build_leg(
    *,
    tradingsymbol: str,
    direction: str,
    order_type: str = "MKT",
    qty: int,
    price: float = 0.0,
    tag: Optional[str] = None,          # ✅ NEW (optional)
) -> Dict:
    ...
    leg = {
        "tradingsymbol": tradingsymbol,
        "direction": direction,
        "order_type": order_type,
        "price": str(price),
        "qty": qty,
    }

    if tag:
        leg["tag"] = tag              # ✅ ADD ONLY IF PRESENT

    return leg

def build_strategy_json(
    *,
    secret_key: str,
    execution_type: str,
    strategy_name: str,
    exchange: str,
    underlying: str,
    expiry: str,
    product_type: str,
    legs: List[Dict],
    strategy_stoploss: float = 0.0,
    trailing_stoploss: float = 0.0,
    target: float = 0.0,
    when_price: float = 0.0
) -> Dict:
    """
    Build complete webhook JSON matching PineScript format exactly.
    
    Args:
        secret_key: Webhook authentication key
        execution_type: "entry" or "exit"
        strategy_name: Name of strategy
        exchange: "NFO", "BFO", etc.
        underlying: "NIFTY", "BANKNIFTY", etc.
        expiry: Format "23DEC25" (DDMMMYY)
        product_type: "M" (MIS), "I" (NRML), "C" (CNC)
        legs: List of leg dicts from build_leg()
        strategy_stoploss: Strategy level SL (negative value)
        trailing_stoploss: Trailing SL amount
        target: Target profit
        when_price: Price threshold for trailing SL activation
    
    Returns:
        Complete JSON dict ready for webhook
    
    Example:
        >>> legs = [
        ...     build_leg(tradingsymbol="NIFTY23DEC25C24500", direction="SELL", qty=75),
        ...     build_leg(tradingsymbol="NIFTY23DEC25P24500", direction="SELL", qty=75)
        ... ]
        >>> json_data = build_strategy_json(
        ...     secret_key="YOUR_SECRET",
        ...     execution_type="entry",
        ...     strategy_name="short_straddle",
        ...     exchange="NFO",
        ...     underlying="NIFTY",
        ...     expiry="23DEC25",
        ...     product_type="M",
        ...     legs=legs,
        ...     strategy_stoploss=-5000,
        ...     target=10000
        ... )
    """
    # Convert enums to strings if passed
    if isinstance(execution_type, ExecutionType):
        execution_type = execution_type.value
    if isinstance(exchange, Exchange):
        exchange = exchange.value
    if isinstance(product_type, ProductType):
        product_type = product_type.value
    
    return {
        "secret_key": secret_key,
        "execution_type": execution_type,
        "strategy_name": strategy_name,
        "exchange": exchange,
        "underlying": underlying,
        "expiry": expiry,
        "strategy_stoploss": strategy_stoploss,
        "trailing_stoploss": trailing_stoploss,
        "target": target,
        "when_price": when_price,
        "product_type": product_type,
        "legs": legs
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 🛠️ HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def create_tradingsymbol(
    underlying: str,
    expiry: str,
    option_type: str,
    strike: int
) -> str:
    """
    Create trading symbol exactly like PineScript.
    
    Args:
        underlying: "NIFTY", "BANKNIFTY", etc.
        expiry: "23DEC25" format (DDMMMYY)
        option_type: "C" or "P" (or "CE"/"PE")
        strike: Strike price as integer
    
    Returns:
        Trading symbol string
    
    Example:
        >>> create_tradingsymbol("NIFTY", "23DEC25", "C", 24500)
        'NIFTY23DEC25C24500'
    """
    # Convert CE/PE to C/P if needed
    if option_type in ["CE", "CALL"]:
        option_type = "C"
    elif option_type in ["PE", "PUT"]:
        option_type = "P"
    
    return f"{underlying}{expiry}{option_type}{strike}"


def format_expiry(date: datetime) -> str:
    """
    Format datetime to expiry string like PineScript: DDMMMYY
    
    Args:
        date: datetime object
    
    Returns:
        Formatted expiry string
    
    Example:
        >>> from datetime import datetime
        >>> format_expiry(datetime(2025, 12, 23))
        '23DEC25'
    """
    month_map = {
        1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
        7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"
    }
    
    day = date.strftime("%d")
    month = month_map[date.month]
    year = date.strftime("%y")
    
    return f"{day}{month}{year}"


def reverse_direction(direction: str) -> str:
    """
    Reverse direction for exit legs.
    BUY -> SELL, SELL -> BUY
    
    Example:
        >>> reverse_direction("BUY")
        'SELL'
    """
    if isinstance(direction, Direction):
        direction = direction.value
    
    return "SELL" if direction == "BUY" else "BUY"


def get_atm_strike(spot_price: float, strike_gap: int) -> int:
    """
    Calculate ATM strike from spot price.
    
    Args:
        spot_price: Current underlying price
        strike_gap: Strike interval (50 for NIFTY, 100 for BANKNIFTY)
    
    Returns:
        Nearest ATM strike
    
    Example:
        >>> get_atm_strike(24567.50, 50)
        24550
    """
    return round(spot_price / strike_gap) * strike_gap


def calculate_strike(
    atm_strike: int,
    strike_gap: int,
    offset: int
) -> int:
    """
    Calculate strike with offset from ATM.
    
    Args:
        atm_strike: ATM strike price
        strike_gap: Strike interval
        offset: Number of strikes away (positive=OTM, negative=ITM)
    
    Returns:
        Calculated strike
    
    Example:
        >>> calculate_strike(24500, 50, 2)  # 2 strikes OTM
        24600
    """
    return atm_strike + (strike_gap * offset)


# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 STRATEGY BUILDERS (Common Patterns)
# ═══════════════════════════════════════════════════════════════════════════════

def build_straddle(
    *,
    secret_key: str,
    execution_type: str,
    strategy_name: str,
    exchange: str = "NFO",
    underlying: str,
    expiry: str,
    atm_strike: int,
    product_type: str = "M",
    qty: int = 75,
    direction: str = "SELL",
    order_type: str = "MKT",
    ce_price: float = 0.0,
    pe_price: float = 0.0,
    strategy_stoploss: float = -5000,
    trailing_stoploss: float = 200,
    target: float = 10000,
    when_price: float = 200
) -> Dict:
    """
    Build straddle strategy (ATM CE + ATM PE).
    
    Example:
        >>> straddle = build_straddle(
        ...     secret_key="YOUR_SECRET",
        ...     execution_type="entry",
        ...     strategy_name="short_straddle",
        ...     underlying="NIFTY",
        ...     expiry="23DEC25",
        ...     atm_strike=24500,
        ...     qty=75,
        ...     direction="SELL"
        ... )
    """
    ce_symbol = create_tradingsymbol(underlying, expiry, "C", atm_strike)
    pe_symbol = create_tradingsymbol(underlying, expiry, "P", atm_strike)
    
    # Reverse direction for exit
    leg_direction = direction if execution_type == "entry" else reverse_direction(direction)
    
    legs = [
        build_leg(
            tradingsymbol=ce_symbol,
            direction=leg_direction,
            order_type=order_type,
            qty=qty,
            price=ce_price
        ),
        build_leg(
            tradingsymbol=pe_symbol,
            direction=leg_direction,
            order_type=order_type,
            qty=qty,
            price=pe_price
        )
    ]
    
    return build_strategy_json(
        secret_key=secret_key,
        execution_type=execution_type,
        strategy_name=strategy_name,
        exchange=exchange,
        underlying=underlying,
        expiry=expiry,
        product_type=product_type,
        legs=legs,
        strategy_stoploss=strategy_stoploss,
        trailing_stoploss=trailing_stoploss,
        target=target,
        when_price=when_price
    )


def build_strangle(
    *,
    secret_key: str,
    execution_type: str,
    strategy_name: str,
    exchange: str = "NFO",
    underlying: str,
    expiry: str,
    ce_strike: int,
    pe_strike: int,
    product_type: str = "M",
    qty: int = 75,
    direction: str = "SELL",
    order_type: str = "MKT",
    ce_price: float = 0.0,
    pe_price: float = 0.0,
    strategy_stoploss: float = -5000,
    trailing_stoploss: float = 200,
    target: float = 10000,
    when_price: float = 200
) -> Dict:
    """
    Build strangle strategy (OTM CE + OTM PE).
    
    Example:
        >>> strangle = build_strangle(
        ...     secret_key="YOUR_SECRET",
        ...     execution_type="entry",
        ...     strategy_name="short_strangle",
        ...     underlying="NIFTY",
        ...     expiry="23DEC25",
        ...     ce_strike=24600,
        ...     pe_strike=24400,
        ...     qty=75,
        ...     direction="SELL"
        ... )
    """
    ce_symbol = create_tradingsymbol(underlying, expiry, "C", ce_strike)
    pe_symbol = create_tradingsymbol(underlying, expiry, "P", pe_strike)
    
    leg_direction = direction if execution_type == "entry" else reverse_direction(direction)
    
    legs = [
        build_leg(
            tradingsymbol=ce_symbol,
            direction=leg_direction,
            order_type=order_type,
            qty=qty,
            price=ce_price
        ),
        build_leg(
            tradingsymbol=pe_symbol,
            direction=leg_direction,
            order_type=order_type,
            qty=qty,
            price=pe_price
        )
    ]
    
    return build_strategy_json(
        secret_key=secret_key,
        execution_type=execution_type,
        strategy_name=strategy_name,
        exchange=exchange,
        underlying=underlying,
        expiry=expiry,
        product_type=product_type,
        legs=legs,
        strategy_stoploss=strategy_stoploss,
        trailing_stoploss=trailing_stoploss,
        target=target,
        when_price=when_price
    )


def build_iron_condor(
    *,
    secret_key: str,
    execution_type: str,
    strategy_name: str,
    exchange: str = "NFO",
    underlying: str,
    expiry: str,
    buy_ce_strike: int,
    sell_ce_strike: int,
    sell_pe_strike: int,
    buy_pe_strike: int,
    product_type: str = "M",
    qty: int = 75,
    order_type: str = "MKT",
    strategy_stoploss: float = -5000,
    trailing_stoploss: float = 200,
    target: float = 10000,
    when_price: float = 200
) -> Dict:
    """
    Build iron condor strategy (Buy OTM + Sell closer OTM on both sides).
    
    Example:
        >>> iron_condor = build_iron_condor(
        ...     secret_key="YOUR_SECRET",
        ...     execution_type="entry",
        ...     strategy_name="iron_condor",
        ...     underlying="NIFTY",
        ...     expiry="23DEC25",
        ...     buy_ce_strike=24700,
        ...     sell_ce_strike=24600,
        ...     sell_pe_strike=24400,
        ...     buy_pe_strike=24300,
        ...     qty=75
        ... )
    """
    legs = []
    
    # Determine directions based on execution type
    if execution_type == "entry":
        sell_dir = "SELL"
        buy_dir = "BUY"
    else:
        sell_dir = "BUY"
        buy_dir = "SELL"
    
    # Sell CE (closer to ATM)
    legs.append(build_leg(
        tradingsymbol=create_tradingsymbol(underlying, expiry, "C", sell_ce_strike),
        direction=sell_dir,
        order_type=order_type,
        qty=qty
    ))
    
    # Buy CE (further from ATM)
    legs.append(build_leg(
        tradingsymbol=create_tradingsymbol(underlying, expiry, "C", buy_ce_strike),
        direction=buy_dir,
        order_type=order_type,
        qty=qty
    ))
    
    # Sell PE (closer to ATM)
    legs.append(build_leg(
        tradingsymbol=create_tradingsymbol(underlying, expiry, "P", sell_pe_strike),
        direction=sell_dir,
        order_type=order_type,
        qty=qty
    ))
    
    # Buy PE (further from ATM)
    legs.append(build_leg(
        tradingsymbol=create_tradingsymbol(underlying, expiry, "P", buy_pe_strike),
        direction=buy_dir,
        order_type=order_type,
        qty=qty
    ))
    
    return build_strategy_json(
        secret_key=secret_key,
        execution_type=execution_type,
        strategy_name=strategy_name,
        exchange=exchange,
        underlying=underlying,
        expiry=expiry,
        product_type=product_type,
        legs=legs,
        strategy_stoploss=strategy_stoploss,
        trailing_stoploss=trailing_stoploss,
        target=target,
        when_price=when_price
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 📤 OUTPUT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def to_json_string(data: Dict, pretty: bool = False) -> str:
    """
    Convert dict to JSON string.
    
    Args:
        data: Dictionary to convert
        pretty: If True, format with indentation
    
    Returns:
        JSON string
    """
    import json
    if pretty:
        return json.dumps(data, indent=2)
    return json.dumps(data)


def validate_json(data: Dict) -> Tuple[bool, str]:
    """
    Validate if JSON has all required fields.
    
    Returns:
        (is_valid, error_message)
    """
    required_fields = [
        "secret_key", "execution_type", "strategy_name",
        "exchange", "underlying", "expiry", "product_type", "legs"
    ]
    
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    if not isinstance(data["legs"], list) or len(data["legs"]) == 0:
        return False, "Legs must be a non-empty list"
    
    for i, leg in enumerate(data["legs"]):
        leg_required = ["tradingsymbol", "direction", "order_type", "qty"]
        for field in leg_required:
            if field not in leg:
                return False, f"Leg {i} missing field: {field}"
    
    return True, "Valid"


# ═══════════════════════════════════════════════════════════════════════════════
# 📝 LIBRARY MODULE — NO EXAMPLES
# ═══════════════════════════════════════════════════════════════════════════════
# 
# For usage examples, see: DOCS/JSON_BUILDER_USAGE_GUIDE.md
# This module is strictly for production use via imports.