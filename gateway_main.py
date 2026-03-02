#!/usr/bin/env python3
"""
MULTI-CLIENT GATEWAY (REVERSE PROXY)
=====================================

Purpose:
- Route incoming TradingView webhooks to the correct client's execution service.
- Proxy per-client dashboard traffic to the correct client's dashboard port.
- Single public-facing entry point for all clients on one server.

Architecture:
                    Internet / TradingView
                           │
                     PORT 7000 (gateway)
                           │
            ┌──────────────┼──────────────┐
            ▼                             ▼
    /FA14667/webhook            /FA14667/dashboard/*
    → 127.0.0.1:5001/webhook    → 127.0.0.1:8001/*
            ▼                             ▼
    /FA14668/webhook            /FA14668/dashboard/*
    → 127.0.0.1:5002/webhook    → 127.0.0.1:8002/*

Route registry (config_env/client_routes.json):
    {
      "clients": [
        {
          "alias": "FA14667",
          "webhook_url": "http://127.0.0.1:5001",
          "dashboard_url": "http://127.0.0.1:8001"
        }
      ]
    }

Running:
    python gateway_main.py --config config_env/gateway.env

Environment file (config_env/gateway.env):
    GATEWAY_HOST=0.0.0.0
    GATEWAY_PORT=7000
    GATEWAY_ROUTES_FILE=config_env/client_routes.json
"""

import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [GATEWAY] %(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Route Registry
# ---------------------------------------------------------------------------

class ClientRoute:
    """Represents one client's routing entry."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.alias: str = data["alias"].strip().lower()
        self.webhook_url: str = data["webhook_url"].rstrip("/")
        self.dashboard_url: str = data["dashboard_url"].rstrip("/")
        self.display_name: str = data.get("display_name", self.alias)
        self.enabled: bool = data.get("enabled", True)


class RouteRegistry:
    """
    Loads and hot-reloads the JSON route registry.
    Thread-safe: routes dict is replaced atomically.
    """

    def __init__(self, routes_file: str) -> None:
        self._file = Path(routes_file)
        self._routes: Dict[str, ClientRoute] = {}
        self._last_mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        try:
            mtime = self._file.stat().st_mtime
            if mtime == self._last_mtime:
                return

            with self._file.open(encoding="utf-8") as fh:
                data = json.load(fh)

            new_routes: Dict[str, ClientRoute] = {}
            for entry in data.get("clients", []):
                route = ClientRoute(entry)
                new_routes[route.alias] = route

            self._routes = new_routes
            self._last_mtime = mtime
            logger.info("Route registry loaded: %d clients", len(new_routes))

        except FileNotFoundError:
            logger.warning("Routes file not found: %s", self._file)
        except Exception as exc:
            logger.error("Failed to load routes: %s", exc)

    def get(self, alias: str) -> Optional[ClientRoute]:
        self._load()  # Check for updates on each request (cheap mtime check)
        route = self._routes.get(alias.lower())
        if route and not route.enabled:
            return None
        return route

    def all_routes(self) -> List[ClientRoute]:
        self._load()
        return list(self._routes.values())


# ---------------------------------------------------------------------------
# FastAPI App Factory
# ---------------------------------------------------------------------------

# Maximum allowed body size forwarded to upstream clients (1 MiB).
# Protects against memory exhaustion from oversized payloads.
MAX_BODY_BYTES = 1_048_576  # 1 MiB


def create_gateway_app(routes_file: str) -> FastAPI:
    """Build the FastAPI gateway application."""

    registry = RouteRegistry(routes_file)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Manage the shared async HTTP client lifecycle."""
        application.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=False,
            verify=False,  # Internal loopback — no TLS needed
        )
        logger.info("Gateway HTTP client created")
        try:
            yield
        finally:
            await application.state.http_client.aclose()
            logger.info("Gateway HTTP client closed")

    app = FastAPI(
        title="Shoonya Multi-Client Gateway",
        version="1.0.0",
        docs_url=None,  # Disable Swagger UI on gateway
        redoc_url=None,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    HOP_BY_HOP = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade",
    }

    def _forward_headers(request: Request) -> dict:
        """Copy safe headers from incoming request, add forwarding metadata."""
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP
        }
        headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
        headers["X-Gateway"] = "shoonya-gateway/1.0"
        return headers

    def _response_headers(upstream_response: httpx.Response) -> dict:
        return {
            k: v for k, v in upstream_response.headers.items()
            if k.lower() not in HOP_BY_HOP
        }

    # ------------------------------------------------------------------
    # Webhook Route  →  POST /{alias}/webhook
    # ------------------------------------------------------------------

    @app.post("/{alias}/webhook")
    async def proxy_webhook(alias: str, request: Request) -> Response:
        route = registry.get(alias)
        if not route:
            raise HTTPException(status_code=404, detail=f"Unknown client: {alias}")

        # Reject oversized payloads before buffering
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")

        target = route.webhook_url + "/webhook"
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")
        headers = _forward_headers(request)

        try:
            upstream = await request.app.state.http_client.post(target, content=body, headers=headers)
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers=_response_headers(upstream),
                media_type=upstream.headers.get("content-type", "application/json"),
            )
        except httpx.RequestError as exc:
            logger.error("Webhook proxy error for %s: %s", alias, exc)
            return JSONResponse(
                {"error": "upstream unavailable", "client": alias},
                status_code=503,
            )

    # ------------------------------------------------------------------
    # Dashboard Proxy  →  GET/POST /{alias}/dashboard/{rest_of_path}
    # Strips the /{alias}/dashboard prefix before forwarding.
    # ------------------------------------------------------------------

    @app.api_route(
        "/{alias}/dashboard/{rest_path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    async def proxy_dashboard(alias: str, rest_path: str, request: Request) -> Response:
        route = registry.get(alias)
        if not route:
            raise HTTPException(status_code=404, detail=f"Unknown client: {alias}")

        target = route.dashboard_url + ("/" + rest_path if rest_path else "/")
        # Preserve query string
        if request.url.query:
            target += "?" + request.url.query

        # Reject oversized payloads before buffering
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")

        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")
        headers = _forward_headers(request)

        try:
            upstream = await request.app.state.http_client.request(
                method=request.method,
                url=target,
                content=body,
                headers=headers,
            )
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers=_response_headers(upstream),
                media_type=upstream.headers.get("content-type"),
            )
        except httpx.RequestError as exc:
            logger.error("Dashboard proxy error for %s: %s", alias, exc)
            return JSONResponse(
                {"error": "dashboard unavailable", "client": alias},
                status_code=503,
            )

    # ------------------------------------------------------------------
    # Gateway Index  →  GET /
    # ------------------------------------------------------------------

    @app.get("/")
    async def gateway_index() -> JSONResponse:
        routes = registry.all_routes()
        return JSONResponse({
            "service": "Shoonya Multi-Client Gateway",
            "version": "1.0.0",
            "clients": [
                {
                    "alias": r.alias,
                    "display_name": r.display_name,
                    "webhook_endpoint": f"/{r.alias}/webhook",
                    "dashboard_endpoint": f"/{r.alias}/dashboard/",
                    "enabled": r.enabled,
                }
                for r in routes
            ],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # ------------------------------------------------------------------
    # Health  →  GET /health
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "clients": len(registry.all_routes())})

    return app


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    import uvicorn

    parser = argparse.ArgumentParser(description="Shoonya Multi-Client Gateway")
    parser.add_argument("--env", default="config_env/gateway.env", help="Gateway env file")
    args = parser.parse_args()

    env_path = Path(args.env)
    if not env_path.exists():
        # Try relative to project root
        env_path = Path(__file__).resolve().parent / args.env

    if env_path.exists():
        load_dotenv(env_path)
        logger.info("Gateway config loaded from: %s", env_path)
    else:
        logger.warning("Gateway env file not found: %s — using defaults", args.env)

    host = os.getenv("GATEWAY_HOST", "0.0.0.0")
    port = int(os.getenv("GATEWAY_PORT", "7000"))
    routes_file = os.getenv(
        "GATEWAY_ROUTES_FILE",
        str(Path(__file__).resolve().parent / "config_env" / "client_routes.json"),
    )

    app = create_gateway_app(routes_file)

    logger.info("=" * 60)
    logger.info("🚀 Shoonya Gateway starting on %s:%d", host, port)
    logger.info("   Routes file: %s", routes_file)
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )
