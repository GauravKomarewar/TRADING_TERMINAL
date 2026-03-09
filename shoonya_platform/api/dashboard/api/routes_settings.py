# ======================================================================
# ROUTES: Settings — Option Chain Management & UI Preferences
# ======================================================================
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Any, Dict, List
import logging
import re

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.market_data.instruments.instruments import (
    get_expiry,
    get_strike_gap,
    _derive_strike_gap,
    STRIKE_GAP_OVERRIDES,
    EQUITY_STRIKE_GAPS,
    MCX_STRIKE_GAPS,
    FNOError,
)

logger = logging.getLogger("DASHBOARD.SETTINGS.API")

sub_router = APIRouter(tags=["Settings"])


def _get_supervisor(ctx: dict):
    """Extract OptionChainSupervisor from the bot injected by auth."""
    bot = ctx.get("bot")
    if bot is None:
        raise HTTPException(status_code=503, detail="Trading bot unavailable")
    sup = getattr(bot, "option_supervisor", None)
    if sup is None:
        raise HTTPException(status_code=503, detail="Option chain supervisor unavailable")
    return sup


# ── Search symbols via scriptmaster (for custom chain loading) ────────

@sub_router.get("/settings/option-chains/search-expiries")
def search_symbol_expiries(
    exchange: str,
    symbol: str,
    ctx: dict = Depends(require_dashboard_auth),
):
    """
    Look up option expiries for any exchange+symbol from scriptmaster.
    Used by the custom chain loader to support non-default symbols.
    """
    from scripts.scriptmaster import options_expiry as sm_options_expiry

    exchange = exchange.strip().upper()
    symbol = symbol.strip().upper()
    if not exchange or not symbol:
        raise HTTPException(status_code=400, detail="exchange and symbol are required")

    try:
        expiries = sm_options_expiry(symbol, exchange) or []
    except Exception:
        expiries = []

    # Auto-derive suggested strike gap
    suggested_gap = None
    gap_source = None
    if expiries:
        try:
            key = f"{exchange}:{symbol}"
            if key in STRIKE_GAP_OVERRIDES:
                suggested_gap = STRIKE_GAP_OVERRIDES[key]
                gap_source = "override"
            elif exchange == "MCX" and symbol in MCX_STRIKE_GAPS:
                suggested_gap = MCX_STRIKE_GAPS[symbol]
                gap_source = "known"
            elif symbol in EQUITY_STRIKE_GAPS:
                suggested_gap = EQUITY_STRIKE_GAPS[symbol]
                gap_source = "known"
            else:
                suggested_gap = _derive_strike_gap(symbol, exchange)
                gap_source = "auto"
        except Exception:
            pass

    return {
        "exchange": exchange,
        "symbol": symbol,
        "expiries": expiries,
        "strike_gap": suggested_gap,
        "gap_source": gap_source,
    }


# ── Available instruments (from supervisor defaults) ──────────────────

@sub_router.get("/settings/option-chains/available")
def get_available_instruments(ctx: dict = Depends(require_dashboard_auth)):
    """
    Return the default instrument list with their available expiries
    so the UI can populate dropdowns.
    """
    from shoonya_platform.market_data.option_chain.supervisor import DEFAULT_INSTRUMENTS

    result = []
    for inst in DEFAULT_INSTRUMENTS:
        exchange = inst["exchange"]
        symbol = inst["symbol"]
        expiries = []
        for i in range(5):  # up to 5 nearest expiries
            try:
                exp = get_expiry(exchange=exchange, symbol=symbol, kind="option", index=i)
            except Exception:
                break
            if exp:
                expiries.append(exp)
        result.append({
            "exchange": exchange,
            "symbol": symbol,
            "expiries": expiries,
        })
    return {"instruments": result}


# ── Loaded chains (live) ─────────────────────────────────────────────

@sub_router.get("/settings/option-chains/loaded")
def get_loaded_chains(ctx: dict = Depends(require_dashboard_auth)):
    """Return all currently loaded option chains from supervisor."""
    sup = _get_supervisor(ctx)
    chains = sup.list_chains()
    return {"chains": chains}


# ── Load a new chain ─────────────────────────────────────────────────

@sub_router.post("/settings/option-chains/load")
def load_chain(
    payload: Dict[str, Any] = Body(...),
    ctx: dict = Depends(require_dashboard_auth),
):
    """
    Load an option chain into the supervisor.

    Body: {"exchange": "NFO", "symbol": "NIFTY", "expiry": "10-MAR-2026", "strike_gap": 50}
    """
    _EXPIRY_RE = re.compile(r"^\d{1,2}-[A-Z]{3}-\d{4}$")
    try:
        exchange = str(payload.get("exchange") or "").strip().upper()
        symbol = str(payload.get("symbol") or "").strip().upper()
        expiry = str(payload.get("expiry") or "").strip()
        raw_gap = payload.get("strike_gap")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid field types")

    if not exchange or not symbol or not expiry:
        raise HTTPException(status_code=400, detail="exchange, symbol, and expiry are required")
    if not _EXPIRY_RE.match(expiry):
        raise HTTPException(status_code=400, detail=f"Invalid expiry format '{expiry}'. Expected DD-MMM-YYYY")

    # Apply strike-gap override if provided
    if raw_gap is not None:
        try:
            gap_val = int(float(raw_gap))
            if gap_val <= 0:
                raise ValueError
            STRIKE_GAP_OVERRIDES[f"{exchange}:{symbol}"] = gap_val
            logger.info("Strike gap override set: %s:%s = %d", exchange, symbol, gap_val)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="strike_gap must be a positive integer")

    sup = _get_supervisor(ctx)
    ok = sup.ensure_chain(exchange=exchange, symbol=symbol, expiry=expiry)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Failed to start chain {exchange}:{symbol}:{expiry}")

    return {"status": "ok", "key": f"{exchange}:{symbol}:{expiry}"}


# ── Unload a chain ───────────────────────────────────────────────────

@sub_router.post("/settings/option-chains/unload")
def unload_chain(
    payload: Dict[str, Any] = Body(...),
    ctx: dict = Depends(require_dashboard_auth),
):
    """
    Stop and unload an active chain.

    Body: {"key": "NFO:NIFTY:10-MAR-2026"}
    """
    key = (payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="key is required")

    sup = _get_supervisor(ctx)
    removed = sup.remove_chain(key)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Chain {key} not found or already removed")

    return {"status": "ok", "removed": key}


# ── Supervisor health ────────────────────────────────────────────────

@sub_router.get("/settings/option-chains/health")
def get_supervisor_health(ctx: dict = Depends(require_dashboard_auth)):
    """Return supervisor health report."""
    sup = _get_supervisor(ctx)
    return sup.get_health_report()
