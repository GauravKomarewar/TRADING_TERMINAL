#!/usr/bin/env python3
"""
# NOTE:
# Dashboard authentication is OPERATOR-LEVEL.
# Client scoping is applied at request level via session["client_id"].

Dashboard Dependencies (PRODUCTION FROZEN)

Auth dependency used by ALL protected dashboard routes.

RULES:
- Single source of truth: session_store.active_sessions
- Cookie-based authentication
- No side effects
"""
from shoonya_platform.api.dashboard.auth import active_sessions

from fastapi import Cookie, HTTPException
from typing import Optional
import logging

logger = logging.getLogger(__name__)


async def require_dashboard_auth(
    dashboard_session: Optional[str] = Cookie(None),
) -> dict:
    """
    Require valid dashboard authentication.

    Returns:
        session dict

    Raises:
        HTTPException(401) if unauthenticated
    """
    if not dashboard_session:
        logger.warning("🚫 Dashboard access denied: no session cookie")
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    session = active_sessions.get(dashboard_session)
    if not session:
        logger.warning("🚫 Dashboard access denied: invalid session")
        raise HTTPException(
            status_code=401,
            detail="Session expired",
        )

    return session
