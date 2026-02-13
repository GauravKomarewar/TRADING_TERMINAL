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
    - Always raise 401 for unauthenticated requests
    - Frontend JS handles 401 → redirect to login
    - No side effects
    """

    # -----------------------------
    # Missing cookie
    # -----------------------------
    if not dashboard_session:
        logger.warning("🚫 Dashboard access denied: no session cookie")
        raise HTTPException(status_code=401, detail="Not authenticated")

    # -----------------------------
    # Invalid / expired session
    # -----------------------------
    session = active_sessions.get(dashboard_session)
    if not session:
        logger.warning("🚫 Dashboard access denied: invalid session")
        raise HTTPException(status_code=401, detail="Session expired")

    # -----------------------------
    # Inject canonical bot
    # -----------------------------
    return {
        **session,
        "bot": get_global_bot(),
    }
