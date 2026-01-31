#shoonya_platform/api/dashboard/services/symbols_service.py
#!/usr/bin/env python3
"""
DASHBOARD SYMBOL DISCOVERY SERVICE (PRODUCTION)
===============================================

Responsibilities:
- Provide symbol search & discovery for dashboard UI
- Power autocomplete, expiry dropdowns, option chain selectors
- Use ScriptMaster as the SINGLE source of truth

STRICT GUARANTEES:
- READ-ONLY
- No broker calls
- No execution imports
- No DataFrame assumptions
- JSON-safe outputs (no NaN / inf leakage)

Data source:
- SCRIPTMASTER_UNIVERSAL (dict-based, ScriptMaster v2)
"""

from typing import List
import math

from scripts.scriptmaster import SCRIPTMASTER_UNIVERSAL


# ============================================================
# SEARCH MODES → ALLOWED INSTRUMENTS
# ============================================================

ALLOWED_BY_MODE = {
    "all": None,
    "derivatives": {"OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK"},
    "options": {"OPTIDX", "OPTSTK"},
    "futures": {"FUTIDX", "FUTSTK"},
    "cash": {"EQ"},
    "indices": {"INDEX"},
}


# ============================================================
# HELPERS
# ============================================================

def _safe_number(val):
    """
    Ensure JSON-safe numeric output.

    Converts:
    - NaN → None
    - +inf / -inf → None
    """
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
    return val


# ============================================================
# SERVICE
# ============================================================

class DashboardSymbolService:
    """
    ScriptMaster-powered symbol discovery service.

    Operates on:
    - SCRIPTMASTER_UNIVERSAL (dict[str, dict])

    This service is SAFE to use inside:
    - Dashboard APIs
    - Autocomplete search
    - Option chain UI
    """

    def __init__(self):
        # ScriptMaster must already be initialized at app startup
        self.records = SCRIPTMASTER_UNIVERSAL or {}

    # --------------------------------------------------
    # SEARCH (AUTOCOMPLETE)
    # --------------------------------------------------
    def search(
        self,
        query: str,
        limit: int = 20,
        mode: str = "all",
    ) -> List[dict]:
        """
        Search tradable symbols.

        Parameters:
        - query: user typed text
        - limit: max results
        - mode: all / derivatives / options / futures / cash / indices
        """

        q = query.upper().strip()
        if not q or not self.records:
            return []

        mode = mode.lower()
        allowed = ALLOWED_BY_MODE.get(mode)

        results = []

        for rec in self.records.values():
            instrument = rec.get("Instrument")

            # Instrument filter
            if allowed and instrument not in allowed:
                continue

            ts = rec.get("TradingSymbol", "")
            sym = rec.get("Symbol", "")

            if q not in ts and q not in sym:
                continue

            results.append(
                {
                    "exchange": rec.get("Exchange"),
                    "tradingsymbol": ts,
                    "instrument": instrument,
                    "underlying": sym,
                    "expiry": rec.get("Expiry"),
                    "strike": _safe_number(rec.get("StrikePrice")),
                    "option_type": rec.get("OptionType"),
                }
            )

            if len(results) >= limit:
                break

        return results

    # --------------------------------------------------
    # EXPIRIES (FOR OPTION CHAIN)
    # --------------------------------------------------
    def get_expiries(self, exchange: str, symbol: str) -> List[str]:
        """
        Return sorted unique expiries for a given symbol.
        """
        if not self.records:
            return []

        expiries = set()

        for rec in self.records.values():
            if (
                rec.get("Exchange") == exchange
                and rec.get("Symbol") == symbol
                and rec.get("Expiry")
            ):
                expiries.add(rec["Expiry"])

        return sorted(expiries)

    # --------------------------------------------------
    # CONTRACTS (FOR OPTION CHAIN TABLE)
    # --------------------------------------------------
    def get_contracts(
        self,
        exchange: str,
        symbol: str,
        expiry: str,
    ) -> List[dict]:
        """
        Return all contracts for a symbol+expiry.
        """
        if not self.records:
            return []

        contracts = []

        for rec in self.records.values():
            if (
                rec.get("Exchange") == exchange
                and rec.get("Symbol") == symbol
                and rec.get("Expiry") == expiry
            ):
                contracts.append(
                    {
                        "tradingsymbol": rec.get("TradingSymbol"),
                        "instrument": rec.get("Instrument"),
                        "strike": _safe_number(rec.get("StrikePrice")),
                        "option_type": rec.get("OptionType"),
                    }
                )

        return contracts
