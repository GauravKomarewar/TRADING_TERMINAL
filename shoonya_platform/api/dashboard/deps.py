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
import time

from shoonya_platform.api.dashboard.auth import active_sessions, SESSION_TTL_SEC
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
    - Frontend JS handles 401 -> redirect to login
    - No side effects
    """

    if not dashboard_session:
        logger.warning("Dashboard access denied: no session cookie")
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = active_sessions.get(dashboard_session)
    if not session:
        logger.warning("Dashboard access denied: invalid session")
        raise HTTPException(status_code=401, detail="Session expired")

    created_at = int(session.get("created_at", 0))
    if created_at <= 0 or (int(time.time()) - created_at) > SESSION_TTL_SEC:
        active_sessions.pop(dashboard_session, None)
        raise HTTPException(status_code=401, detail="Session expired")

    return {
        **session,
        "bot": get_global_bot(),
    }
