#!/usr/bin/env python3
"""
MASTER MANAGER — FastAPI APPLICATION
=====================================

Exposes:
  GET  /                          → HTML dashboard (requires admin cookie)
  POST /auth/login                → Admin login (returns session cookie)

  GET  /api/clients               → List all clients
  POST /api/clients               → Register / update a client
  GET  /api/clients/{client_id}   → Get one client detail
  DELETE /api/clients/{client_id} → Remove a client

  Service control (admin token or cookie required):
  PUT /api/clients/{client_id}/service/enable
  PUT /api/clients/{client_id}/service/disable
  PUT /api/clients/{client_id}/block
  PUT /api/clients/{client_id}/unblock
  PUT /api/clients/{client_id}/copy-trading/enable
  PUT /api/clients/{client_id}/copy-trading/disable

  GET /api/summary                → Platform-wide summary
  GET /health                     → Service health

Authentication:
  - Admin dashboard: password-based cookie session (MASTER_ADMIN_PASSWORD)
  - REST API: Bearer token (MASTER_API_TOKEN in env)
"""

import logging
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from master.registry import MasterRegistry
from master.poller import HealthPoller

logger = logging.getLogger("master.api")

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _validate_credential(name: str, value: str, forbidden: tuple) -> str:
    """Validate a credential is not a weak default and meets minimum length."""
    if not value or value in forbidden:
        raise RuntimeError(
            f"SECURITY: {name} is not set or uses a default value. "
            f"Set a strong, unique value in your .env file."
        )
    if len(value) < 12:
        raise RuntimeError(
            f"SECURITY: {name} is too short ({len(value)} chars). "
            f"Use at least 12 characters."
        )
    return value


def create_master_app(registry: MasterRegistry, poller: HealthPoller) -> FastAPI:
    """Build the FastAPI master manager application."""

    _WEAK_PASSWORDS = (
        "change_me", "password", "admin", "master", "12345678",
        "123456789012", "change_me_master_token",
    )

    admin_password: str = os.getenv("MASTER_ADMIN_PASSWORD", "")
    api_token: str = os.getenv("MASTER_API_TOKEN", "")

    _validate_credential("MASTER_ADMIN_PASSWORD", admin_password, _WEAK_PASSWORDS)
    _validate_credential("MASTER_API_TOKEN", api_token, _WEAK_PASSWORDS)

    # In-memory sessions: session_id → expiry_timestamp (seconds since epoch)
    _sessions: Dict[str, float] = {}

    def _valid_session(session_id: str) -> bool:
        """Constant-time session lookup with TTL expiry check."""
        found_expiry: Optional[float] = None
        for k, expiry in list(_sessions.items()):
            if secrets.compare_digest(k, session_id):
                found_expiry = expiry
                break
        if found_expiry is None:
            return False
        if time.time() > found_expiry:
            _sessions.pop(session_id, None)
            return False
        return True

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    app = FastAPI(
        title="Shoonya Master Account Manager",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _check_api_token(request: Request) -> None:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not secrets.compare_digest(auth[7:], api_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API token",
            )

    def _check_session(request: Request) -> None:
        session_id = request.cookies.get("master_session")
        if not session_id or not _valid_session(session_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

    def _require_auth(request: Request) -> None:
        """Accept either cookie session OR Bearer token."""
        session_id = request.cookies.get("master_session")
        if session_id and _valid_session(session_id):
            return
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], api_token):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # ------------------------------------------------------------------
    # Auth Routes
    # ------------------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("master_login.html", {"request": request, "error": None})

    @app.post("/auth/login")
    async def do_login(
        response: Response,
        password: str = Form(...),
    ) -> RedirectResponse:
        if not secrets.compare_digest(password, admin_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin password",
            )
        session_id = secrets.token_urlsafe(32)
        _sessions[session_id] = time.time() + 86400  # expires in 1 day
        redirect = RedirectResponse(url="/", status_code=302)
        redirect.set_cookie(
            key="master_session",
            value=session_id,
            httponly=True,
            samesite="Strict",
            secure=True,
            max_age=86400,  # 1 day
        )
        return redirect

    @app.post("/auth/logout")
    async def do_logout(request: Request) -> RedirectResponse:
        session_id = request.cookies.get("master_session")
        if session_id:
            _sessions.pop(session_id, None)
        redirect = RedirectResponse(url="/login", status_code=302)
        redirect.delete_cookie("master_session")
        return redirect

    # ------------------------------------------------------------------
    # Dashboard  →  GET /
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        # Redirect to login if not authenticated
        session_id = request.cookies.get("master_session")
        if not session_id or not _valid_session(session_id):
            return RedirectResponse(url="/login", status_code=302)

        clients = registry.list_all()
        # Sanitize dashboard_url — only allow http:// or https:// to prevent open-redirect
        for client in clients:
            url = client.get("dashboard_url", "")
            if url and not (url.startswith("http://") or url.startswith("https://")):
                client["dashboard_url"] = ""
        summary = _build_summary(clients)

        return templates.TemplateResponse(
            "master_dashboard.html",
            {
                "request": request,
                "clients": clients,
                "summary": summary,
                "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            },
        )

    # ------------------------------------------------------------------
    # API Routes  (Bearer token OR cookie)
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "master-manager"})

    @app.get("/api/summary")
    async def api_summary(request: Request) -> JSONResponse:
        _require_auth(request)
        clients = registry.list_all()
        return JSONResponse(_build_summary(clients))

    @app.get("/api/clients")
    async def list_clients(request: Request) -> JSONResponse:
        _require_auth(request)
        return JSONResponse({"clients": registry.list_all()})

    @app.post("/api/clients")
    async def register_client(request: Request) -> JSONResponse:
        _require_auth(request)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        result = registry.register(body)
        return JSONResponse(result, status_code=201)

    @app.get("/api/clients/{client_id}")
    async def get_client(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        client = registry.get(client_id)
        if not client:
            raise HTTPException(404, f"Client not found: {client_id}")
        return JSONResponse(client)

    @app.delete("/api/clients/{client_id}")
    async def delete_client(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        removed = registry.delete(client_id)
        if not removed:
            raise HTTPException(404, f"Client not found: {client_id}")
        return JSONResponse({"deleted": client_id})

    # Service control

    @app.put("/api/clients/{client_id}/service/enable")
    async def enable_service(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        return JSONResponse(_safe_update(registry.enable_service, client_id))

    @app.put("/api/clients/{client_id}/service/disable")
    async def disable_service(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        return JSONResponse(_safe_update(registry.disable_service, client_id))

    @app.put("/api/clients/{client_id}/block")
    async def block_client(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        body = await _optional_json(request)
        reason = body.get("reason", "Blocked by admin") if body else "Blocked by admin"
        return JSONResponse(_safe_update(registry.block_trading, client_id, reason))

    @app.put("/api/clients/{client_id}/unblock")
    async def unblock_client(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        return JSONResponse(_safe_update(registry.unblock_trading, client_id))

    # Copy trading control

    @app.put("/api/clients/{client_id}/copy-trading/enable")
    async def enable_copy_trading(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        body = await _optional_json(request)
        role = (body or {}).get("role", "follower")
        master_id = (body or {}).get("master_id")
        followers = (body or {}).get("followers")
        return JSONResponse(
            _safe_update(
                registry.enable_copy_trading,
                client_id,
                role,
                master_id,
                followers,
            )
        )

    @app.put("/api/clients/{client_id}/copy-trading/disable")
    async def disable_copy_trading(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        return JSONResponse(_safe_update(registry.disable_copy_trading, client_id))

    # ------------------------------------------------------------------
    # Client self-registration (called by client bots on startup)
    # Secured by the shared MASTER_API_TOKEN.
    # ------------------------------------------------------------------

    @app.post("/api/register")
    async def self_register(request: Request) -> JSONResponse:
        auth = request.headers.get("X-Master-Token", "")
        if not secrets.compare_digest(auth, api_token):
            raise HTTPException(401, "Invalid master token")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        result = registry.register(body)
        # Return the client's current permissions
        return JSONResponse({
            "registered": True,
            "client_id": result.get("client_id"),
            "service_enabled": result.get("service_enabled"),
            "trading_blocked": result.get("trading_blocked"),
            "copy_trading_enabled": result.get("copy_trading_enabled"),
            "copy_trading_role": result.get("copy_trading_role"),
        })

    # ------------------------------------------------------------------
    # Client permission check (polled by bots every N seconds)
    # ------------------------------------------------------------------

    @app.get("/api/permission/{client_id}")
    async def get_permission(client_id: str, request: Request) -> JSONResponse:
        auth = request.headers.get("X-Master-Token", "")
        if not secrets.compare_digest(auth, api_token):
            raise HTTPException(401, "Invalid master token")
        client = registry.get(client_id)
        if not client:
            raise HTTPException(404, f"Client not found: {client_id}")
        return JSONResponse({
            "client_id": client_id,
            "service_enabled": client["service_enabled"],
            "trading_blocked": client["trading_blocked"],
            "block_reason": client.get("block_reason"),
            "copy_trading_enabled": client["copy_trading_enabled"],
            "copy_trading_role": client["copy_trading_role"],
        })

    # ------------------------------------------------------------------
    # Systemd Service Control (admin auth required)
    # Requires sudoers rule: utilities/deployment/sudoers.d/trading-master
    # ------------------------------------------------------------------

    @app.post("/api/clients/{client_id}/systemd/start")
    async def systemd_start(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        result = _run_systemctl("start", _service_name_for_client(client_id))
        if result["success"]:
            # Mark service as enabled in registry (best-effort)
            try:
                registry.enable_service(client_id)
            except KeyError:
                pass
        return JSONResponse(result, status_code=200 if result["success"] else 500)

    @app.post("/api/clients/{client_id}/systemd/stop")
    async def systemd_stop(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        result = _run_systemctl("stop", _service_name_for_client(client_id))
        if result["success"]:
            try:
                registry.disable_service(client_id)
            except KeyError:
                pass
        return JSONResponse(result, status_code=200 if result["success"] else 500)

    @app.post("/api/clients/{client_id}/systemd/restart")
    async def systemd_restart(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        result = _run_systemctl("restart", _service_name_for_client(client_id))
        return JSONResponse(result, status_code=200 if result["success"] else 500)

    @app.get("/api/clients/{client_id}/systemd/status")
    async def systemd_status(client_id: str, request: Request) -> JSONResponse:
        _require_auth(request)
        result = _run_systemctl("status", _service_name_for_client(client_id))
        return JSONResponse(result)

    return app
# ---------------------------------------------------------------------------

_ALLOWED_SYSTEMD_ACTIONS = frozenset({"start", "stop", "restart", "status"})


def _service_name_for_client(client_id: str) -> str:
    """Return the systemd service unit name for a client."""
    # Instance name must only contain safe chars; strip anything odd.
    safe = "".join(c for c in client_id if c.isalnum() or c in "-_.")
    return f"trading@{safe}.service"


def _run_systemctl(action: str, unit: str) -> Dict[str, Any]:
    """
    Run `sudo systemctl <action> <unit>` and return structured result.
    Requires the sudoers rule at utilities/deployment/sudoers.d/trading-master.
    """
    if action not in _ALLOWED_SYSTEMD_ACTIONS:
        raise ValueError(f"Invalid systemd action: {action!r}")
    cmd = ["sudo", "/usr/bin/systemctl", action, unit]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "unit": unit,
            "action": action,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"unit": unit, "action": action, "success": False, "error": "systemctl timed out"}
    except Exception as exc:
        return {"unit": unit, "action": action, "success": False, "error": str(exc)}

def _build_summary(clients) -> Dict[str, Any]:
    total = len(clients)
    active = sum(1 for c in clients if c.get("service_enabled", True))
    blocked = sum(1 for c in clients if c.get("trading_blocked", False))
    copy_enabled = sum(1 for c in clients if c.get("copy_trading_enabled", False))
    masters = sum(1 for c in clients if c.get("copy_trading_role") == "master")
    followers = sum(1 for c in clients if c.get("copy_trading_role") == "follower")
    return {
        "total_clients": total,
        "active_clients": active,
        "blocked_clients": blocked,
        "copy_trading_active": copy_enabled,
        "masters": masters,
        "followers": followers,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _safe_update(fn, *args, **kwargs) -> Dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


async def _optional_json(request: Request) -> Optional[Dict]:
    try:
        body = await request.body()
        if body:
            return await request.json()
    except Exception:
        pass
    return None
