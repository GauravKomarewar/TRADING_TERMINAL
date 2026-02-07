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

from fastapi import Cookie, HTTPException
from typing import Optional
import logging

from shoonya_platform.api.dashboard.auth import active_sessions
from shoonya_platform.execution.trading_bot import get_global_bot

logger = logging.getLogger(__name__)


async def require_dashboard_auth(
    dashboard_session: Optional[str] = Cookie(None),
) -> dict:
    if not dashboard_session:
        logger.warning("🚫 Dashboard access denied: no session cookie")
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = active_sessions.get(dashboard_session)
    if not session:
        logger.warning("🚫 Dashboard access denied: invalid session")
        raise HTTPException(status_code=401, detail="Session expired")

    # 🔒 Inject the ONE TRUE ShoonyaBot
    return {
        **session,
        "bot": get_global_bot(),
    }
