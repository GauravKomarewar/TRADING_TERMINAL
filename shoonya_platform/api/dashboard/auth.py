#!/usr/bin/env python3
"""
Dashboard Authentication Router (PRODUCTION FROZEN)

NOTE:
- Dashboard authentication is OPERATOR-LEVEL
- Client identity is resolved ONLY via Config.get_client_identity()
- Dashboard NEVER invents or derives client_id

AUTH CONTRACT (DO NOT CHANGE):
POST   /auth/login
POST   /auth/logout
GET    /auth/status

- Cookie-based authentication
- In-memory session store (shared)
- Frontend NEVER sees session_id
"""

from fastapi import APIRouter, HTTPException, Response, Cookie, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional, Dict
import os
import secrets
import logging
import time

from shoonya_platform.core.config import Config

# --------------------------------------------------
# SESSION STORE (IN-MEMORY)
# session_id -> session_data
# --------------------------------------------------
active_sessions: Dict[str, dict] = {}
SESSION_TTL_SEC = int(os.getenv("DASHBOARD_SESSION_TTL_SEC", str(60 * 60 * 8)))
COOKIE_SECURE = os.getenv("DASHBOARD_COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# --------------------------------------------------
# REQUIRED ENV
# --------------------------------------------------
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
if not DASHBOARD_PASSWORD:
    raise RuntimeError("DASHBOARD_PASSWORD not set in environment")

# --------------------------------------------------
# MODELS
# --------------------------------------------------
class LoginResponse(BaseModel):
    authenticated: bool

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """
    Authenticate dashboard operator.

    Rules:
    - Username is ignored
    - Password must match DASHBOARD_PASSWORD
    - Session is cookie-based
    - Client identity comes ONLY from Config
    """
    if form_data.password != DASHBOARD_PASSWORD:
        logger.warning("❌ Dashboard login failed")
        raise HTTPException(status_code=401, detail="Invalid password")

    # 🔒 Resolve canonical identity at REQUEST time
    identity = Config().get_client_identity()

    session_id = secrets.token_urlsafe(32)

    active_sessions[session_id] = {
        "authenticated": True,
        "username": "dashboard",
        "created_at": int(time.time()),

        # 🔒 Canonical client identity
        "client_id": identity["client_id"],
        "user_id": identity["user_id"],
        "user_name": identity["user_name"],
    }

    response.set_cookie(
        key="dashboard_session",
        value=session_id,
        httponly=True,
        max_age=SESSION_TTL_SEC,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )

    logger.info(
        "✅ Dashboard login success | client_id=%s",
        identity["client_id"],
    )

    return {"authenticated": True}


@router.post("/logout")
async def logout(
    response: Response,
    dashboard_session: Optional[str] = Cookie(None),
):
    """
    Destroy dashboard session.
    """
    if dashboard_session:
        active_sessions.pop(dashboard_session, None)

    response.delete_cookie("dashboard_session", path="/")

    logger.info("👋 Dashboard logout")

    return {"authenticated": False}


@router.get("/status")
async def status(
    dashboard_session: Optional[str] = Cookie(None),
):
    """
    Check authentication status.
    """
    if not dashboard_session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if dashboard_session not in active_sessions:
        raise HTTPException(status_code=401, detail="Session expired")

    session = active_sessions.get(dashboard_session, {})
    created_at = int(session.get("created_at", 0))
    if created_at <= 0 or (int(time.time()) - created_at) > SESSION_TTL_SEC:
        active_sessions.pop(dashboard_session, None)
        raise HTTPException(status_code=401, detail="Session expired")

    return {"authenticated": True}
