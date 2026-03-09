# ======================================================================
# ROUTES: Settings — Option Chain Management & UI Preferences
# ======================================================================
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Any, Dict, List
import logging
import re

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.market_data.instruments.instruments import get_expiry

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

    Body: {"exchange": "NFO", "symbol": "NIFTY", "expiry": "10-MAR-2026"}
    """
    _EXPIRY_RE = re.compile(r"^\d{1,2}-[A-Z]{3}-\d{4}$")
    try:
        exchange = str(payload.get("exchange") or "").strip().upper()
        symbol = str(payload.get("symbol") or "").strip().upper()
        expiry = str(payload.get("expiry") or "").strip()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid field types")

    if not exchange or not symbol or not expiry:
        raise HTTPException(status_code=400, detail="exchange, symbol, and expiry are required")
    if not _EXPIRY_RE.match(expiry):
        raise HTTPException(status_code=400, detail=f"Invalid expiry format '{expiry}'. Expected DD-MMM-YYYY")

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
