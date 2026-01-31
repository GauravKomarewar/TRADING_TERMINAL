#!/usr/bin/env python3
"""
Dashboard Authentication Router (PRODUCTION FROZEN)
# NOTE:
# Dashboard authentication is OPERATOR-LEVEL.
# Client scoping is applied at request level via session["client_id"].

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

#=======================================
# session_id -> session_data
#=======================================
active_sessions: Dict[str, dict] = {}

#=======================================
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# --------------------------------------------------
# CONFIG (REQUIRED)
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
    Authenticate dashboard user.

    Rules:
    - Username is ignored
    - Password must match DASHBOARD_PASSWORD
    - Session is cookie-based
    """
    if form_data.password != DASHBOARD_PASSWORD:
        logger.warning("❌ Dashboard login failed")
        raise HTTPException(status_code=401, detail="Invalid password")

    session_id = secrets.token_urlsafe(32)

    active_sessions[session_id] = {
        "authenticated": True,
        "username": "dashboard",
    }

    response.set_cookie(
        key="dashboard_session",
        value=session_id,
        httponly=True,
        max_age=60 * 60 * 8,   # 8 hours
        samesite="lax",
        secure=False,          # set True when HTTPS
        path="/",
    )

    logger.info("✅ Dashboard login success")

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

    return {"authenticated": True}
