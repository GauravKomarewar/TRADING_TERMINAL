"""
FyersSymbolMapper — translates between Fyers and Shoonya symbol formats.

Symbol formats
--------------
Fyers:
    Index     : NSE:NIFTY50-INDEX, NSE:NIFTYBANK-INDEX
    Equity    : NSE:RELIANCE-EQ
    Option    : NSE:NIFTY2531024550CE  (exchange:underlying + YYMMDDSTRIKETYPE)
    Futures   : NSE:NIFTY25MARFUT

Shoonya (tick_data_store key):
    NSE|22    (exchange|numeric-token)   — for index / equity
    NFO|39547 (exchange|numeric-token)   — for options / futures

Scriptmaster (SCRIPTMASTER dict in scripts/scriptmaster.py):
    SCRIPTMASTER[exchange][token] = {
        "Token": "39547",
        "TradingSymbol": "NIFTY25MAR24550CE",
        "Expiry": "25-MAR-2025",
        "StrikePrice": "24550",
        "OptionType": "CE",
        "Instrument": "OPTIDX",
        ...
    }

Usage
-----
    mapper = FyersSymbolMapper()
    shoonya_key = mapper.fyers_to_shoonya_key("NSE:NIFTY2531024550CE")
    # → "NFO|39547"  (if scriptmaster is loaded and symbol matches)

    fyers_sym = mapper.shoonya_key_to_fyers("NFO|39547")
    # → "NSE:NIFTY2531024550CE"

Note: The mapper requires the scriptmaster to be loaded
      (scripts.scriptmaster.refresh_scriptmaster() must have been called).
      If the scriptmaster is not yet loaded, methods return None gracefully.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Well-known index symbol mapping (Fyers → Shoonya exchange|token)
# ---------------------------------------------------------------------------
# These are stable tokens that do not change between sessions.
INDEX_FYERS_TO_SHOONYA: Dict[str, str] = {
    "NSE:NIFTY50-INDEX":    "NSE|26000",
    "NSE:NIFTYBANK-INDEX":  "NSE|26009",
    "NSE:FINNIFTY-INDEX":   "NSE|26037",
    "NSE:MIDCPNIFTY-INDEX": "NSE|26074",
    "BSE:SENSEX-INDEX":     "BSE|1",
    "NSE:INDIA VIX-INDEX":  "NSE|26002",
}

# Reverse (Shoonya key → Fyers symbol) for the static index map
INDEX_SHOONYA_TO_FYERS: Dict[str, str] = {v: k for k, v in INDEX_FYERS_TO_SHOONYA.items()}

# Fyers exchange → Shoonya exchange for FnO instruments
_FYERS_EXCHANGE_MAP = {
    "NSE": "NFO",   # NSE options/futures trade on NFO in Shoonya
    "BSE": "BFO",
    "MCX": "MCX",
}

# Underlying name differences
_UNDERLYING_FYERS_TO_SHOONYA = {
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "SENSEX": "SENSEX",
}

# Month abbreviation → zero-padded month number
_MONTH_ABBR = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
               "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
               "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}

# Fyers option symbol regex: UNDERLYING + YY + MM + DD + STRIKE + TYPE
# e.g. NIFTY2531024550CE  (not the NSE: prefix)
_FYERS_OPT_RE = re.compile(
    r"^([A-Z]+?)(\d{2})(\d{2})(\d{2})(\d+)(CE|PE)$"
)
# Fyers futures symbol regex: UNDERLYING + YY + MON + FUT
# e.g. NIFTY25MARFUT
_FYERS_FUT_RE = re.compile(
    r"^([A-Z]+?)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)FUT$",
    re.IGNORECASE,
)


class FyersSymbolMapper:
    """Bi-directional Fyers ↔ Shoonya symbol converter."""

    def __init__(self) -> None:
        # Additional cache populated from live scriptmaster lookups
        self._fyers_to_shoonya: Dict[str, str] = dict(INDEX_FYERS_TO_SHOONYA)
        self._shoonya_to_fyers: Dict[str, str] = dict(INDEX_SHOONYA_TO_FYERS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fyers_to_shoonya_key(self, fyers_symbol: str) -> Optional[str]:
        """
        Convert a Fyers symbol (with exchange prefix) to a Shoonya tick-store
        key of the form "EXCHANGE|TOKEN".

        Returns None if the symbol cannot be mapped.
        """
        # Check cache first (includes static index map)
        if fyers_symbol in self._fyers_to_shoonya:
            return self._fyers_to_shoonya[fyers_symbol]

        # Try dynamic lookup via scriptmaster
        result = self._lookup_via_scriptmaster(fyers_symbol)
        if result:
            # Cache for future calls
            self._fyers_to_shoonya[fyers_symbol] = result
            self._shoonya_to_fyers[result] = fyers_symbol
        return result

    def shoonya_key_to_fyers(self, shoonya_key: str) -> Optional[str]:
        """
        Convert a Shoonya "EXCHANGE|TOKEN" key to a Fyers symbol string.

        Returns None if the mapping is not known.
        """
        return self._shoonya_to_fyers.get(shoonya_key)

    def fyers_exchange(self, fyers_symbol: str) -> str:
        """Return the exchange portion of a Fyers symbol (e.g. 'NSE')."""
        return fyers_symbol.split(":")[0] if ":" in fyers_symbol else "NSE"

    def fyers_ticker(self, fyers_symbol: str) -> str:
        """Return the ticker portion of a Fyers symbol (everything after ':')."""
        return fyers_symbol.split(":", 1)[1] if ":" in fyers_symbol else fyers_symbol

    # ------------------------------------------------------------------
    # Fyers → Shoonya option/futures symbol string (NOT the key)
    # ------------------------------------------------------------------

    def fyers_option_to_shoonya_symbol(self, fyers_symbol: str) -> Optional[str]:
        """
        Convert a Fyers option symbol to a Shoonya TradingSymbol string.

        Example:
            "NSE:NIFTY2531024550CE"  →  "NIFTY25MAR24550CE"
        """
        ticker = self.fyers_ticker(fyers_symbol)
        m = _FYERS_OPT_RE.match(ticker)
        if not m:
            return None
        underlying, yy, mm, dd, strike, opt_type = m.groups()

        # Map month number to abbreviation used by Shoonya scriptmaster
        month_abbr = {v: k for k, v in _MONTH_ABBR.items()}.get(mm)
        if not month_abbr:
            return None

        # Shoonya format: NIFTY25MAR24550CE (no leading zeros on strike)
        return f"{underlying}{yy}{month_abbr}{int(strike)}{opt_type}"

    def fyers_futures_to_shoonya_symbol(self, fyers_symbol: str) -> Optional[str]:
        """
        Convert a Fyers futures symbol to a Shoonya TradingSymbol string.

        Example:
            "NSE:NIFTY25MARFUT"  →  "NIFTY25MARFUT"
        """
        ticker = self.fyers_ticker(fyers_symbol)
        m = _FYERS_FUT_RE.match(ticker)
        if not m:
            return None
        underlying, yy, mon = m.groups()
        return f"{underlying}{yy}{mon.upper()}FUT"

    # ------------------------------------------------------------------
    # Tick normalisation helper
    # ------------------------------------------------------------------

    def normalize_fyers_tick(self, raw: dict) -> dict:
        """
        Normalise a raw Fyers WebSocket tick to the same schema as
        shoonya_platform.market_data.feeds.live_feed.normalize_tick().

        Fyers tick keys (FyersDataSocket "SymbolUpdate" type):
            symbol, ltp, vol_traded_today, open_price, high_price, low_price,
            close_price, avg_trade_price, oi, prev_close_price, ch, chp, ...

        Output keys (Shoonya-normalised):
            lp, pc, v, o, h, l, c, ap, oi, tt, sym, bp1, sp1, bq1, sq1
        """
        if not isinstance(raw, dict):
            return {}

        def _f(key: str, default: float = 0.0) -> float:
            try:
                return float(raw.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        sym = raw.get("symbol", "")
        ltp = _f("ltp")
        prev_close = _f("prev_close_price")

        return {
            "ltp": ltp,   # normalised key (matches live_feed.normalize_tick output)
            "pc":  round(((ltp - prev_close) / prev_close * 100) if prev_close else 0.0, 2),
            "v":   int(_f("vol_traded_today")),
            "o":   _f("open_price"),
            "h":   _f("high_price"),
            "l":   _f("low_price"),
            "c":   _f("close_price"),
            "ap":  _f("avg_trade_price"),
            "oi":  int(_f("oi")),
            "tt":  int(_f("timestamp", 0)),
            "sym": sym,
            # Best bid/ask (Fyers uses bid_size/ask_size)
            "bp1": _f("bid_price"),
            "sp1": _f("ask_price"),
            "bq1": int(_f("bid_size")),
            "sq1": int(_f("ask_size")),
            # Extra Fyers fields preserved for diagnostics
            "_source": "fyers",
        }

    # ------------------------------------------------------------------
    # Internal: scriptmaster lookup
    # ------------------------------------------------------------------

    def _lookup_via_scriptmaster(self, fyers_symbol: str) -> Optional[str]:
        """
        Try to resolve a Fyers symbol to its Shoonya exchange|token key
        by looking it up in the loaded scriptmaster.
        """
        try:
            from scripts.scriptmaster import SCRIPTMASTER  # type: ignore
        except ImportError:
            return None

        if not SCRIPTMASTER:
            return None

        exchange = self.fyers_exchange(fyers_symbol)
        ticker = self.fyers_ticker(fyers_symbol)

        # Try option/futures conversion first
        shoonya_sym = (
            self.fyers_option_to_shoonya_symbol(fyers_symbol)
            or self.fyers_futures_to_shoonya_symbol(fyers_symbol)
        )
        if shoonya_sym is None:
            shoonya_sym = ticker  # plain equity

        # For FnO, the exchange in Shoonya is NFO/BFO not NSE/BSE
        shoonya_exchange = _FYERS_EXCHANGE_MAP.get(exchange, exchange)
        exch_data = SCRIPTMASTER.get(shoonya_exchange, {})

        # Linear scan for TradingSymbol match (scriptmaster keyed by token)
        for token, rec in exch_data.items():
            if rec.get("TradingSymbol") == shoonya_sym:
                return f"{shoonya_exchange}|{token}"

        logger.debug("FyersSymbolMapper: no scriptmaster match for %s", fyers_symbol)
        return None
