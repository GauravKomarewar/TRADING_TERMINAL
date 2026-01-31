"""
FNO Simple Manager (ScriptMaster-first) v2.0
============================================

Design principles:
- ScriptMaster = single source of truth for contracts
- Shoonya API = ONLY for live quotes
- Deterministic, readable, testable
- No searchscrip
- No calendar expiry math
- MCX option expiry ≠ MCX future expiry (handled via ScriptMaster)

COMPATIBLE WITH: ScriptMaster v1.1.0+ (Underlying support)
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, time as dtime

from shoonya_platform.brokers.shoonya.client import ShoonyaClient

from scripts.scriptmaster import (
    options_expiry,
    fut_expiry,
    get_future,
    get_stock_detail,
    SCRIPTMASTER,
    FUTURE_INSTRUMENTS,
    OPTION_INSTRUMENTS,
    refresh_scriptmaster
)
import pandas as pd
logger = logging.getLogger(__name__)

# =============================================================================
# Exceptions
# =============================================================================

class FNOError(Exception):
    pass

# =============================================================================
# SPOT TOKEN MAPS (STABLE, EXCHANGE-DEFINED)
# =============================================================================

SPOT_TOKEN_REGISTRY = {
    # ===== NSE INDEX =====
    "NIFTY":        ("NSE", "26000"),
    "BANKNIFTY":    ("NSE", "26009"),
    "FINNIFTY":     ("NSE", "26037"),
    "MIDCPNIFTY":   ("NSE", "26074"),
    "NIFTYNXT50":   ("NSE", "26013"),
    "INDIAVIX":     ("NSE", "26017"),

    # ===== BSE INDEX =====
    "SENSEX":       ("BSE", "1"),
    "BANKEX":       ("BSE", "12"),
    "SENSEX50":     ("BSE", "47"),

    # ===== MCX SPOT (QUOTE ONLY) =====
    "CRUDEOIL":     ("MCX", "52929"),
    "CRUDEOILM":    ("MCX", "52929"),
    "NATURALGAS":   ("MCX", "52935"),
    "NATGASMINI":   ("MCX", "52935"),
    "GOLD":         ("MCX", "52925"),
    "GOLDM":        ("MCX", "52926"),
    "SILVER":       ("MCX", "52927"),
    "SILVERM":      ("MCX", "52928"),
}

CANONICAL_FUTURE_POLICY = {
    # NFO
    ("NFO", "NIFTY"): {
        "prefix": "NIFTY",
        "exclude": [],
    },
    ("NFO", "BANKNIFTY"): {
        "prefix": "BANKNIFTY",
        "exclude": [],
    },

    # BFO
    ("BFO", "SENSEX"): {
        "prefix": "SENSEX",
        "exclude": ["SENSEX50", "SX50"],
    },
    ("BFO", "SENSEX50"): {
        "prefix": "SENSEX50",
        "exclude": [],
    },
    ("BFO", "BANKEX"): {
        "prefix": "BANKEX",
        "exclude": [],
    },

    # MCX
    ("MCX", "CRUDEOIL"): {
        "prefix": "CRUDEOIL",
        "exclude": ["CRUDEOILM"],
    },
    ("MCX", "CRUDEOILM"): {
        "prefix": "CRUDEOILM",
        "exclude": [],
    },
}

# =============================================================================
# STRIKE GAPS
# =============================================================================

EQUITY_STRIKE_GAPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
    "SENSEX50": 100,
    "BANKEX": 100,
}

MCX_STRIKE_GAPS = {
    "CRUDEOIL": 50,
    "CRUDEOILM": 50,
    "NATURALGAS": 5,
    "NATGASMINI": 5,
    "GOLD": 100,
    "GOLDM": 10,
    "SILVER": 1000,
    "SILVERM": 100,
}


# =============================================================================
# CORE SCRIPTMASTER HELPERS
# =============================================================================

def get_spot_instrument(*, symbol: str) -> Optional[Dict[str, Any]]:
    """
    Resolve STRICT spot instrument for Greeks & analytics.

    Resolution order:
    1. Explicit spot token registry (quote-only or canonical)
    2. ScriptMaster equity (EQ)
    """

    symbol = symbol.upper()

    # 1️⃣ Explicit spot token (index / commodity / special)
    if symbol in SPOT_TOKEN_REGISTRY:
        exchange, token = SPOT_TOKEN_REGISTRY[symbol]
        return {
            "Exchange": exchange,
            "Token": token,
            "TradingSymbol": symbol,
            "Instrument": "SPOT",
        }

    # 2️⃣ Equity spot from ScriptMaster (NSE EQ / BSE EQ)
    rec = get_stock_detail(
        symbol=symbol,
        exchange="NSE",
        instrument_type="EQ",
    )
    if rec:
        return {
            "Exchange": "NSE",
            "Token": rec["Token"],
            "TradingSymbol": rec["TradingSymbol"],
            "Instrument": "EQ",
        }

    return None

def _is_option_expiry_tradable(
    expiry: str,
    *,
    exchange: str,
) -> bool:
    """
    Returns True if option expiry is tradable at current time.
    """

    now = datetime.now()
    exp_date = datetime.strptime(expiry, "%d-%b-%Y").date()

    # Market close times
    if exchange == "MCX":
        market_close = dtime(23, 30)
    else:
        market_close = dtime(15, 30)

    if exp_date > now.date():
        return True

    if exp_date < now.date():
        return False

    # Same day → check time
    return now.time() < market_close


def get_expiry(
    *,
    exchange: str,
    symbol: str,
    kind: str,
    index: int = 0,
) -> Optional[str]:
    """
    Unified expiry resolver using ScriptMaster ONLY.

    kind:
        - "future"
        - "option"

    index:
        0 = nearest
        1 = next
        ...
    """
    exchange = exchange.upper()
    symbol = symbol.upper()
    kind = kind.lower()

    if kind == "future":
        return fut_expiry(symbol, exchange, result=index)

    if kind == "option":
        expiries = options_expiry(symbol, exchange)

        if not expiries:
            return None

        valid = [
            e for e in expiries
            if _is_option_expiry_tradable(e, exchange=exchange)
        ]

        if not valid:
            return None

        if index >= len(valid):
            return None

        return valid[index]


    raise FNOError(f"Invalid expiry kind: {kind}")

def has_options(symbol: str, exchange: str) -> bool:
    symbol = symbol.upper()
    exchange = exchange.upper()
    try:
        expiries = options_expiry(symbol, exchange)
        return bool(expiries)
    except Exception:
        return False

    return bool(expiries)

def get_future_contract(*, exchange: str, symbol: str, index: int = 0) -> Dict[str, Any]:
    exchange = exchange.upper()
    symbol = symbol.upper()

    df = get_future(symbol, exchange)

    if df is None or df.empty:
        raise FNOError(f"No futures found for {symbol} on {exchange}")

    policy = CANONICAL_FUTURE_POLICY.get((exchange, symbol))
    if policy:
        prefix = policy["prefix"]
        excludes = policy.get("exclude", [])

        df = df[df["TradingSymbol"].str.startswith(prefix)]

        for ex in excludes:
            df = df[~df["TradingSymbol"].str.startswith(ex)]

    if df.empty:
        raise FNOError(
            f"Future selection ambiguous or invalid for {symbol} on {exchange}"
        )

    df["_dt"] = pd.to_datetime(df["Expiry"], format="%d-%b-%Y", errors="coerce")

    df = df.sort_values("_dt").reset_index(drop=True)

    if index >= len(df):
        raise FNOError(
            f"Expiry index {index} out of range for {symbol} on {exchange}"
        )

    return df.iloc[index].to_dict()


def get_options(
    *,
    exchange: str,
    symbol: str,
    expiry: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return raw option contract records from ScriptMaster.
    Each item is a ScriptMaster dict with keys like:
    Token, Symbol, TradingSymbol, Expiry, StrikePrice, OptionType, etc.
    
    # Properly filters by exchange-specific instrument types:
    # - NFO: OPTIDX, OPTSTK
    # - BFO: OPTIDX, OPTSTK
    # - MCX: OPTFUT

    
    ✅ FIXED: Now uses Underlying for BFO compatibility
    """
    exchange = exchange.upper()
    symbol = symbol.upper()

    insts = OPTION_INSTRUMENTS.get(exchange, set())

    rows = [
        rec for rec in SCRIPTMASTER.get(exchange, {}).values()
        # ✅ Check both Symbol and Underlying (critical for BFO)
        if (
            (rec.get("Symbol") == symbol or rec.get("Underlying") == symbol)
            and rec.get("Instrument") in insts
            and (not expiry or rec.get("Expiry") == expiry)
        )
    ]

    return rows


# =============================================================================
# Thin wrapper for LIVE PRICE for backward compatibility if required
# =============================================================================

def get_ltp(*, api_client, exchange: str, token: str) -> Optional[float]:
    """
    Thin wrapper for ShoonyaClient.get_ltp
    Exists to avoid refactoring callers.
    """
    return api_client.get_ltp(exchange, token)


# =============================================================================
# STRIKE HELPERS
# =============================================================================

def get_strike_gap(symbol: str, exchange: str) -> int:
    """
    Get strike gap for a symbol.
    """
    symbol = symbol.upper()
    exchange = exchange.upper()

    if exchange == "MCX":
        if symbol not in MCX_STRIKE_GAPS:
            raise FNOError(f"MCX strike gap not defined for {symbol}")
        return MCX_STRIKE_GAPS[symbol]

    if symbol not in EQUITY_STRIKE_GAPS:
        raise FNOError(f"Equity strike gap not defined for {symbol}")

    return EQUITY_STRIKE_GAPS[symbol]


def calculate_atm(price: float, gap: int, method: str = "round") -> Optional[int]:
    """
    Calculate ATM strike based on price and gap.
    
    Args:
        price: Current price
        gap: Strike gap
        method: 'round', 'floor', or 'ceil'
    """
    if not price or not gap:
        return None

    import math

    if method == "floor":
        return int(math.floor(price / gap) * gap)
    if method == "ceil":
        return int(math.ceil(price / gap) * gap)
    return int(round(price / gap) * gap)


# =============================================================================
# ⭐ MAIN API: FNO DETAILS
# =============================================================================

def get_fno_details(
    *,
    api_client: ShoonyaClient,
    exchange: str = "NFO",
    symbol: str = "NIFTY",
    expiry_index: int = 0,
    atm_method: str = "round",
) -> Dict[str, Any]:
    """
    Unified FNO metadata + live prices.

    - Contracts: ScriptMaster
    - Prices: get_quotes ONLY
    
    Args:
        api_client: Shoonya API client
        exchange: Target exchange (NFO/BFO/MCX)
        symbol: Underlying symbol
        expiry_index: 0=nearest, 1=next, etc.
        atm_method: Strike calculation method
        
    Returns:
        Dict containing spot, future, and option details with live prices
    """

    exchange = exchange.upper()
    symbol = symbol.upper()

    if not SCRIPTMASTER:
        logger.info("🔄 ScriptMaster empty — refreshing once")
        refresh_scriptmaster()

    # -----------------------------
    # Spot instrument
    # -----------------------------
    if exchange == "MCX":
        # MCX has no true spot instrument in Shoonya API
        # Futures price is treated as spot reference
        spot = {
            "Exchange": "MCX",
            "Token": None,
            "Instrument": "SPOT_PROXY",
        }
    else:
        spot = get_spot_instrument(symbol=symbol)
      
        if not spot:
            raise FNOError(f"Spot instrument not found for {symbol}")

    # -----------------------------
    # Future contract
    # -----------------------------
    fut = get_future_contract(
        exchange=exchange,
        symbol=symbol,
        index=expiry_index,
    )

    # -----------------------------
    # Expiries (IMPORTANT: MCX option ≠ future)
    # -----------------------------
    fut_exp = fut.get("Expiry")
    
    # -----------------------------
    # Option expiry (ScriptMaster truth)
    # -----------------------------
    option_expiry = None

    try:
        option_expiry = get_expiry(
            exchange=exchange,
            symbol=symbol,
            kind="option",
            index=expiry_index,
        )

    except Exception:
        option_expiry = None

    # -----------------------------
    # Live prices
    # -----------------------------
    fut_ltp = get_ltp(
        api_client=api_client,
        exchange=exchange,
        token=fut["Token"],
    )

    spot_ltp = (
        fut_ltp
        if exchange == "MCX"
        else get_ltp(
            api_client=api_client,
            exchange=spot["Exchange"],
            token=spot["Token"],
        )
    )

    # -----------------------------
    # ATM strikes
    # -----------------------------
    try:
        gap = get_strike_gap(symbol, exchange)
    except FNOError as e:
        return {
            "exchange": exchange,
            "symbol": symbol,
            "error": str(e),
            "success": False,
        }


    fut_atm = calculate_atm(fut_ltp, gap, atm_method)
    spot_atm = calculate_atm(spot_ltp, gap, atm_method)

    # -----------------------------
    # Final payload
    # -----------------------------
    return {
        "exchange": exchange,
        "symbol": symbol,

        # Spot
        "spot_exchange": spot["Exchange"],
        "spot_token": spot["Token"],
        "spot_ltp": spot_ltp,
        "spot_atm": spot_atm,

        # Future
        "fut_symbol": fut["TradingSymbol"],
        "fut_token": fut["Token"],
        "fut_expiry": fut_exp,
        "fut_ltp": fut_ltp,
        "fut_lot_size": fut["LotSize"],
        "fut_atm": fut_atm,

        # Options
        "option_expiry": option_expiry,

        # Meta
        "strike_gap": gap,
        "success": True,
    }

# =============================================================================
# OPTION SYMBOL BUILDER (FOR SHOONYA OPTION CHAIN)
# =============================================================================

def build_option_symbol(
    *,
    exchange: str,
    symbol: str,
    expiry: str,
    strike: int,
    opt_type: str,
) -> str:
    """
    Build Shoonya-compatible option trading symbol.

    EXACT FORMATS (verified with ScriptMaster):

    NFO:
        NIFTY13JAN26C25950

    BFO:
        SENSEX26SEP91000PE

    MCX:
        CRUDEOILM14JAN26C5250

    Args:
        exchange: NFO / BFO / MCX
        symbol: Underlying symbol (e.g. NIFTY, SENSEX)
        expiry: DD-MMM-YYYY (e.g. 13-JAN-2026)
        strike: Strike price
        opt_type: CE / PE / C / P

    Returns:
        Fully-qualified Shoonya trading symbol
    """

    exchange = exchange.upper()
    symbol = symbol.upper()
    opt_type = opt_type.upper()

    # ------------------------------------------------------------
    # Normalize option type
    # ------------------------------------------------------------
    if opt_type in ("CE", "CALL", "C"):
        call_put = "C"
        cepe = "CE"
    elif opt_type in ("PE", "PUT", "P"):
        call_put = "P"
        cepe = "PE"
    else:
        raise ValueError(f"Invalid option type: {opt_type}")

    # ------------------------------------------------------------
    # NFO FORMAT
    # SYMBOL + DDMMMYY + C/P + STRIKE
    # Example: NIFTY13JAN26C25950
    # ------------------------------------------------------------
    if exchange == "NFO":
        dt = datetime.strptime(expiry, "%d-%b-%Y")
        exp = dt.strftime("%d%b%y").upper()
        result = f"{symbol}{exp}{call_put}{strike}"
        return result

    # ------------------------------------------------------------
    # BFO FORMAT (CRITICAL FIX)
    # SYMBOL + YYMMM + STRIKE + CE/PE
    # Example: SENSEX26SEP91000PE
    # ------------------------------------------------------------
    if exchange == "BFO":
        dt = datetime.strptime(expiry, "%d-%b-%Y")
        exp = dt.strftime("%y%b").upper()
        result = f"{symbol}{exp}{strike}{cepe}"
        return result

    # ------------------------------------------------------------
    # MCX FORMAT
    # SYMBOL + M + DDMMMYY + C/P + STRIKE
    # Example: CRUDEOILM14JAN26C5250
    # ------------------------------------------------------------
    if exchange == "MCX":
        dt = datetime.strptime(expiry, "%d-%b-%Y")
        exp = dt.strftime("%d%b%y").upper()
        result = f"{symbol}{exp}{call_put}{strike}"
        return result

    # ------------------------------------------------------------
    # Unsupported exchange
    # ------------------------------------------------------------
    raise ValueError(f"Unsupported exchange: {exchange}")