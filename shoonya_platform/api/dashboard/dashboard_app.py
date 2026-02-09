#!/usr/bin/env python3
"""
Shoonya OMS Dashboard – FastAPI Application
===========================================

Responsibilities:
- Serve dashboard web UI (login + static assets)
- Expose authenticated dashboard APIs
- NEVER access broker or strategy engines
- Emit INTENTS only (read-only control plane)

CRITICAL:
- Environment variables MUST be loaded BEFORE importing auth/deps modules
"""

# ======================================================================
# 🔒 CODE FREEZE — PRODUCTION APPROVED
#
# Component : Dashboard FastAPI App
# Version   : v1.1.3
# Status    : PRODUCTION FROZEN
# Scope     : Dashboard Control Plane
# ======================================================================

# ==================================================
# 🔒 ENV BOOTSTRAP (MUST RUN FIRST – NO EXCEPTIONS)
# ==================================================

import os
from pathlib import Path

# --------------------------------------------------
# ENV SELECTION (systemd controls this)
# --------------------------------------------------
env_name = os.environ.get("DASHBOARD_ENV", "primary")

ENV_FILE = (
    Path(__file__).resolve().parents[3]
    / "config_env"
    / f"{env_name}.env"
)

if not ENV_FILE.exists():
    raise RuntimeError(
        f"DASHBOARD ENV file not found: {ENV_FILE} "
        f"(DASHBOARD_ENV={env_name})"
    )

# Load env vars ONLY if not already set
with ENV_FILE.open(encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            # Strip comments from value (everything after #)
            v = v.strip()
            if '#' in v:
                v = v.split('#')[0].strip()
            os.environ.setdefault(k.strip(), v)

# Fail fast on required secret
if "DASHBOARD_PASSWORD" not in os.environ:
    raise RuntimeError("DASHBOARD_PASSWORD not set after env bootstrap")

# ==================================================
# STANDARD IMPORTS (SAFE AFTER ENV LOAD)
# ==================================================

import logging
from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ==================================================
# INTERNAL DASHBOARD IMPORTS
# ==================================================

from shoonya_platform.api.dashboard.auth import router as auth_router
from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.api.router import router as dashboard_router

from scripts.scriptmaster import refresh_scriptmaster

# ==================================================
# PATHS & LOGGING
# ==================================================

WEB_DIR = Path(__file__).parent / "web"
logger = logging.getLogger("DASHBOARD.APP")

# ==================================================
# APPLICATION FACTORY
# ==================================================

def create_dashboard_app() -> FastAPI:
    """
    Create and configure the Dashboard FastAPI app.
    """
    app = FastAPI(
        title="Shoonya OMS Dashboard",
        version="1.1.3",
        description="OMS Control Console (Intent-Only)",
    )

    # --------------------------------------------------
    # 🔧 ScriptMaster bootstrap (ONCE per process)
    # --------------------------------------------------
    logger.info(
        "🔄 Initializing ScriptMaster (dashboard) | env=%s",
        env_name,
    )
    refresh_scriptmaster()
    logger.info("✅ ScriptMaster initialized")

    # --------------------------------------------------
    # 🏠 HOME (UNPROTECTED – LOGIN PAGE)
    # --------------------------------------------------
    @app.get("/")
    def home():
        return FileResponse(WEB_DIR / "login.html")

    # --------------------------------------------------
    # ❤️ HEALTH CHECK (UNPROTECTED)
    # --------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok", "env": env_name}

    # --------------------------------------------------
    # 📊 DASHBOARD HOME PAGE (PROTECTED)
    # --------------------------------------------------
    @app.get("/dashboard/home")
    async def dashboard_home(
        session: dict = Depends(require_dashboard_auth),
    ):
        dashboard_file = WEB_DIR / "dashboard.html"
        if not dashboard_file.exists():
            logger.error("Dashboard file not found: %s", dashboard_file)
            return {"error": "Dashboard page not found"}
        return FileResponse(dashboard_file)

    # --------------------------------------------------
    # 📊 DASHBOARD STATUS (PROTECTED)
    # --------------------------------------------------
    @app.get("/dashboard/status")
    async def dashboard_status(
        session: dict = Depends(require_dashboard_auth),
    ):
        return {
            "authenticated": True,
            "username": session.get("username", "dashboard"),
            "status": "active",
            "env": env_name,
        }

    # --------------------------------------------------
    # 🔓 AUTH ROUTES (UNPROTECTED)
    # --------------------------------------------------
    app.include_router(auth_router)
    logger.info("✅ Auth router mounted")

    # --------------------------------------------------
    # 🔒 DASHBOARD API ROUTES (PROTECTED)
    # --------------------------------------------------
    app.include_router(
        dashboard_router,
        dependencies=[Depends(require_dashboard_auth)],
    )
    logger.info("✅ Dashboard API router mounted")

    # --------------------------------------------------
    # 🎨 STATIC WEB ASSETS
    # --------------------------------------------------
    app.mount(
        "/dashboard/web",
        StaticFiles(directory=WEB_DIR),
        name="dashboard-web",
    )
    logger.info("✅ Static files mounted from %s", WEB_DIR)

    logger.info(
        "🚀 Dashboard initialized | env=%s | pid=%s",
        env_name,
        os.getpid(),
    )
    return app

# ==================================================
# ASGI APPLICATION (NO RUN LOOP)
# ==================================================

app = create_dashboard_app()
