#!/usr/bin/env python3
"""
Dashboard Dependencies (PRODUCTION FROZEN)

RULES:
- Operator-level authentication
- Client identity from session
- Dashboard uses EXISTING ShoonyaBot
- No broker login
- No side effects
"""
from fastapi import Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse
from typing import Optional
import logging

from shoonya_platform.api.dashboard.auth import active_sessions
from shoonya_platform.execution.trading_bot import get_global_bot

logger = logging.getLogger(__name__)


async def require_dashboard_auth(
    request: Request,
    dashboard_session: Optional[str] = Cookie(None),
) -> dict:
    """
    Enforce dashboard authentication.

    RULES:
    - HTML requests → redirect to /
    - API / JS requests → 401
    - No side effects
    """

    def redirect_to_login():
        return RedirectResponse(url="/", status_code=302)

    # -----------------------------
    # Missing cookie
    # -----------------------------
    if not dashboard_session:
        logger.warning("🚫 Dashboard access denied: no session cookie")

        if "text/html" in request.headers.get("accept", ""):
            return redirect_to_login()

        raise HTTPException(status_code=401, detail="Not authenticated")

    # -----------------------------
    # Invalid / expired session
    # -----------------------------
    session = active_sessions.get(dashboard_session)
    if not session:
        logger.warning("🚫 Dashboard access denied: invalid session")

        if "text/html" in request.headers.get("accept", ""):
            return redirect_to_login()

        raise HTTPException(status_code=401, detail="Session expired")

    # -----------------------------
    # Inject canonical bot
    # -----------------------------
    return {
        **session,
        "bot": get_global_bot(),
    }
