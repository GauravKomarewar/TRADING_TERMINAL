# ======================================================================
# ROUTES: Analytics History, Runner Control, Strategy Logs, WebSocket
#         Log Stream, File Logs, Mode Management, Positions Check
# Extracted from router.py during modularisation.
# ======================================================================
from fastapi import APIRouter, Depends, Query, Body, HTTPException, WebSocket
from typing import Optional, Any
from pathlib import Path
from datetime import datetime
from collections import deque
import asyncio
import re as _re
import time
import logging

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.api._shared import (
    logger,
    _PROJECT_ROOT,
    STRATEGY_CONFIG_DIR,
    _parse_iso_ts,
    _get_historical_service,
    _slugify,
    _mode_from_config_dict,
    _strategy_state_file,
    get_runner_singleton,
    get_strategy_logger,
    get_logger_manager,
    get_all_strategies,
    load_strategy_json,
    save_strategy_json,
    get_broker,
    get_system,
)

sub_router = APIRouter()

# ======================================================================
# HISTORICAL ANALYTICS API (POSTGRESQL LAYER)
# ======================================================================

@sub_router.get("/analytics/history/health")
def analytics_history_health(ctx=Depends(require_dashboard_auth)):
    svc = _get_historical_service(ctx)
    return svc.health()


@sub_router.get("/analytics/history/strategy-samples")
def analytics_strategy_samples(
    strategy_name: str = Query(..., min_length=1),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(5000, ge=1, le=20000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    return {
        "strategy_name": strategy_name,
        "rows": svc.store.fetch_strategy_samples(
            strategy_name=strategy_name,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


@sub_router.get("/analytics/history/strategy-events")
def analytics_strategy_events(
    strategy_name: str = Query(..., min_length=1),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(2000, ge=1, le=20000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    return {
        "strategy_name": strategy_name,
        "rows": svc.store.fetch_strategy_events(
            strategy_name=strategy_name,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


@sub_router.get("/analytics/history/index-ticks")
def analytics_index_ticks(
    symbols: str = Query(..., description="Comma-separated symbol list"),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(20000, ge=1, le=50000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    syms = [s.strip().upper() for s in str(symbols).split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    return {
        "symbols": syms,
        "rows": svc.store.fetch_index_ticks(
            symbols=syms,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


@sub_router.get("/analytics/history/option-metrics")
def analytics_option_metrics(
    exchange: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    expiry: Optional[str] = Query(None),
    from_ts: Optional[str] = Query(None, description="ISO datetime"),
    to_ts: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(5000, ge=1, le=20000),
    ctx=Depends(require_dashboard_auth),
):
    svc = _get_historical_service(ctx)
    if not svc.enabled or svc.store is None:
        raise HTTPException(status_code=503, detail="Historical PostgreSQL layer disabled")
    return {
        "exchange": exchange,
        "symbol": symbol,
        "expiry": expiry,
        "rows": svc.store.fetch_option_metrics(
            exchange=(exchange.upper() if exchange else None),
            symbol=(symbol.upper() if symbol else None),
            expiry=expiry,
            from_ts=_parse_iso_ts(from_ts),
            to_ts=_parse_iso_ts(to_ts),
            limit=limit,
        ),
    }


# ======================================================================
# RUNNER CONTROL
# ======================================================================

@sub_router.post("/runner/start")
def start_runner(ctx=Depends(require_dashboard_auth)):
    """Start the strategy runner - loads all strategies from saved_configs/."""
    try:
        bot = ctx["bot"]
        runner = get_runner_singleton(ctx)

        loaded = []
        errors = []
        for cfg_path in sorted(STRATEGY_CONFIG_DIR.glob("*.json")):
            if cfg_path.name == "STRATEGY_CONFIG_SCHEMA.json":
                continue
            # ✅ BUG FIX: Skip schema / template files that are not real strategy configs
            if "schema" in cfg_path.stem.lower() or cfg_path.stem.lower() in ("template", "example"):
                continue
            name = cfg_path.stem
            if name in runner._strategies:
                loaded.append(name)
                continue
            try:
                runner.register_strategy(name=name, config_path=str(cfg_path))
                with bot._live_strategies_lock:
                    bot._live_strategies[name] = {
                        "type": "executor_service",
                        "config_path": str(cfg_path),
                        "started_at": time.time(),
                    }
                loaded.append(name)
            except Exception as e:
                logger.warning(f"Failed to load strategy {name}: {e}")
                errors.append(name)

        if not runner._running:
            runner.start()

        return {
            "success": True,
            "runner_started": True,
            "strategies_loaded": len(loaded),
            "strategies": loaded,
            "errors": errors,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error starting runner: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@sub_router.post("/runner/stop")
def stop_runner(ctx=Depends(require_dashboard_auth)):
    """Stop the strategy runner."""
    try:
        bot = ctx["bot"]
        runner = get_runner_singleton(ctx)

        stopped_count = len(runner._strategies)
        for name in list(runner._strategies.keys()):
            runner.unregister_strategy(name)
        with bot._live_strategies_lock:
            bot._live_strategies.clear()
        runner.stop()

        return {
            "success": True,
            "runner_stopped": True,
            "strategies_stopped": stopped_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error stopping runner: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@sub_router.get("/runner/status")
def get_runner_status(ctx=Depends(require_dashboard_auth)):
    """Get runner status and active strategies."""
    try:
        runner = get_runner_singleton(ctx)
        return {
            "runner_active": runner is not None,
            "is_running": bool(runner._running),
            "strategies_active": len(runner._strategies),
            "active_strategies": list(runner._strategies.keys()),
            "total_strategies_available": len(get_all_strategies()),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting runner status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# STRATEGY LOGGING
# ======================================================================

@sub_router.get("/strategy/{strategy_name}/logs")
def get_strategy_logs(
    strategy_name: str,
    lines: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None, description="Filter by log level"),
    ctx=Depends(require_dashboard_auth)
):
    """Get recent logs for specific strategy."""
    try:
        logger_obj = get_strategy_logger(strategy_name)
        logs = logger_obj.get_recent_logs(lines=lines, level=level)

        return {
            "strategy": strategy_name,
            "lines_returned": len(logs),
            "logs": logs,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting logs for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@sub_router.get("/runner/logs")
def get_all_runner_logs(
    lines: int = Query(50, ge=1, le=500),
    ctx=Depends(require_dashboard_auth)
):
    """Get recent logs from all running strategies combined."""
    try:
        manager = get_logger_manager()
        combined_logs = manager.get_all_logs_combined(lines=lines)

        return {
            "strategies_with_logs": len(manager.loggers),
            "total_lines": len(combined_logs),
            "logs": combined_logs,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting all logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ======================================================================
# WEBSOCKET - LOG STREAMING
# ======================================================================
@sub_router.websocket("/runner/logs/stream")
async def websocket_log_stream(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Dashboard auth token (pass as ?token=...)"),
):
    """
    WebSocket endpoint for real-time log streaming.
    Auth: pass session token as query param ?token=<value>
    Connect to: ws://localhost:8000/dashboard/runner/logs/stream?token=<token>
    """
    from shoonya_platform.api.dashboard.deps import verify_dashboard_token
    try:
        verify_dashboard_token(token)
    except Exception:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        manager = get_logger_manager()
        sent_count = {}

        while True:
            for strategy_name, logger_obj in manager.loggers.items():
                logs = logger_obj.get_recent_logs(lines=50)

                if strategy_name not in sent_count:
                    sent_count[strategy_name] = 0

                total_available = len(logs)
                already_sent = sent_count[strategy_name]

                if total_available < already_sent:
                    already_sent = 0

                new_logs = logs[already_sent:] if already_sent < total_available else []
                for log in new_logs:
                    await websocket.send_json({
                        "strategy": strategy_name,
                        "timestamp": log.get("timestamp") if isinstance(log, dict) else str(log),
                        "level": log.get("level") if isinstance(log, dict) else "INFO",
                        "message": log.get("message") if isinstance(log, dict) else str(log),
                    })

                sent_count[strategy_name] = total_available

            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass

# ======================================================================
# FILE-BASED LOG VIEW (REAL RUNTIME LOGS)
# ======================================================================

def _resolve_client_log_file(ctx: dict, component: str = "application") -> Path:
    """Resolve client-scoped log path by component."""
    client_id = str(ctx.get("client_id", "") or "")
    short_id = client_id.split(":")[-1].strip() if client_id else ""
    # Sanitize short_id to prevent path traversal
    short_id = _re.sub(r'[^a-zA-Z0-9_\-]', '', short_id)
    log_root = _PROJECT_ROOT / "logs"
    comp = str(component or "application").strip().lower()

    filename_map = {
        "application": "application.log",
        "app": "application.log",
        "strategy_executor": "strategy_executor.log",
        "strategy": "strategy_executor.log",
        "runner": "strategy_executor.log",
    }
    filename = filename_map.get(comp, "application.log")

    if short_id:
        candidate = log_root / short_id / filename
        if candidate.resolve().is_relative_to(log_root.resolve()) and candidate.exists():
            return candidate

    fallback = log_root / filename
    return fallback


@sub_router.get("/runner/file-logs")
def get_runner_file_logs(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    lines: int = Query(300, ge=1, le=5000),
    level: Optional[str] = Query(None, description="DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    component: str = Query("application", description="application | strategy_executor"),
    ctx=Depends(require_dashboard_auth),
):
    """Read real runtime logs from application.log (client-scoped)."""
    try:
        log_path = _resolve_client_log_file(ctx, component=component)
        if not log_path.exists():
            return {
                "path": str(log_path),
                "strategy": strategy,
                "level": level,
                "component": component,
                "lines_returned": 0,
                "lines": [],
                "timestamp": datetime.now().isoformat(),
            }

        strategy_q = (strategy or "").strip().lower()
        level_q = (level or "").strip().upper()

        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=max(lines * 10, lines))

        filtered = []
        for raw in tail:
            line = raw.rstrip("\n")
            if strategy_q and strategy_q not in line.lower():
                continue
            if level_q and f"| {level_q} " not in line:
                continue
            filtered.append(line)

        if len(filtered) > lines:
            filtered = filtered[-lines:]

        return {
            "path": str(log_path),
            "strategy": strategy,
            "level": level_q or None,
            "component": component,
            "lines_returned": len(filtered),
            "lines": filtered,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error reading file logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================================
# LIVE/MOCK MODE MANAGEMENT (PRODUCTION SAFE)
# ======================================================================

@sub_router.get("/strategy/{strategy_name}/mode")
def get_strategy_mode(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Get current execution mode (LIVE/MOCK) for a strategy."""
    try:
        slug = _slugify(strategy_name)
        config = load_strategy_json(slug)

        if not config:
            raise HTTPException(404, f"Strategy '{strategy_name}' not found")

        identity = config.get("identity", {}) or {}
        paper_mode = bool(
            identity.get("paper_mode")
        )
        test_mode = identity.get("test_mode")
        mode = _mode_from_config_dict(config)

        can_change = True
        reason = None
        position_details = {}

        try:
            bot = ctx["bot"]
            service = bot.strategy_executor_service
            exec_state = service._exec_states.get(slug)

            if bool(getattr(exec_state, "any_leg_active", False)):
                can_change = False
                reason = "Strategy has active positions - close all positions before changing mode"
                active_legs = [
                    {
                        "tag": getattr(leg, "tag", ""),
                        "symbol": getattr(leg, "trading_symbol", None) or getattr(leg, "symbol", ""),
                        "qty": getattr(leg, "qty", 0),
                        "side": getattr(getattr(leg, "side", None), "value", getattr(leg, "side", "")),
                    }
                    for leg in (getattr(exec_state, "legs", {}) or {}).values()
                    if bool(getattr(leg, "is_active", False))
                ]
                position_details = {
                    "state_type": type(exec_state).__name__,
                    "active_legs": active_legs,
                }
        except Exception as e:
            logger.warning(f"Could not check positions for {strategy_name}: {e}")

        return {
            "strategy_name": strategy_name,
            "mode": mode,
            "can_change": can_change,
            "reason": reason,
            "position_details": position_details,
            "config": {
                "paper_mode": paper_mode,
                "test_mode": test_mode,
            },
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting mode for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.post("/strategy/{strategy_name}/mode")
def set_strategy_mode(
    strategy_name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Change execution mode for a strategy (LIVE <-> MOCK). Only allowed when no active positions."""
    try:
        new_mode = str(payload.get("mode", "")).strip().upper()

        if new_mode not in ("LIVE", "MOCK"):
            raise HTTPException(400, "mode must be 'LIVE' or 'MOCK'")

        slug = _slugify(strategy_name)
        config = load_strategy_json(slug)

        if not config:
            raise HTTPException(404, f"Strategy '{strategy_name}' not found")

        # CRITICAL: Check for active positions
        bot = ctx["bot"]
        service = bot.strategy_executor_service

        allowed, block_reason = service._validate_mode_change_allowed(slug)

        if not allowed:
            raise HTTPException(
                409,
                {
                    "error": "Cannot change mode with active positions",
                    "detail": block_reason,
                    "has_position": True,
                }
            )

        identity = config.get("identity", {}) or {}
        paper_mode = bool(
            identity.get("paper_mode")
        )
        test_mode = identity.get("test_mode")
        previous_mode = _mode_from_config_dict(config)

        if previous_mode == new_mode:
            return {
                "success": True,
                "strategy_name": strategy_name,
                "previous_mode": previous_mode,
                "new_mode": new_mode,
                "message": "Mode unchanged (already in requested mode)",
                "timestamp": datetime.now().isoformat()
            }

        if "identity" not in config:
            config["identity"] = {}

        if new_mode == "MOCK":
            config["identity"]["paper_mode"] = True
            config["identity"]["test_mode"] = "SUCCESS"
        else:  # LIVE
            config["identity"]["paper_mode"] = False
            config["identity"]["test_mode"] = None

        save_strategy_json(slug, config)

        needs_restart = slug in service._strategies
        restart_message = ""

        if needs_restart:
            logger.critical(
                f"MODE CHANGE: {strategy_name} | {previous_mode} -> {new_mode} | "
                f"Strategy is running and will be restarted"
            )

            try:
                service.unregister_strategy(slug)
                with bot._live_strategies_lock:
                    bot._live_strategies.pop(slug, None)

                strategy_file = STRATEGY_CONFIG_DIR / f"{slug}.json"
                service.register_strategy(name=slug, config_path=str(strategy_file))
                with bot._live_strategies_lock:
                    bot._live_strategies[slug] = {
                        "type": "executor_service",
                        "config_path": str(strategy_file),
                        "started_at": time.time(),
                    }

                restart_message = "Strategy restarted with new mode"
            except Exception as restart_err:
                logger.error(f"Failed to restart strategy: {restart_err}")
                restart_message = f"Warning: Strategy restart failed - {restart_err}"

        logger.critical(
            f"MODE CHANGED: {strategy_name} | {previous_mode} -> {new_mode}"
        )

        if bot.telegram_enabled:
            mode_emoji = "⚡" if new_mode == "LIVE" else "🧪"
            bot.send_telegram(
                f"{mode_emoji} MODE CHANGE\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"Strategy: {strategy_name}\n"
                f"Previous: {previous_mode}\n"
                f"New: {new_mode}\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"{restart_message if needs_restart else 'Strategy not running'}",
                category="strategy"
            )

        return {
            "success": True,
            "strategy_name": strategy_name,
            "previous_mode": previous_mode,
            "new_mode": new_mode,
            "was_running": needs_restart,
            "restart_message": restart_message,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting mode for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.get("/strategy/{strategy_name}/positions/active")
def check_strategy_positions(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Check if strategy has active positions."""
    try:
        slug = _slugify(strategy_name)

        bot = ctx["bot"]
        service = bot.strategy_executor_service
        exec_state = service._exec_states.get(slug)

        if not exec_state:
            return {
                "strategy_name": strategy_name,
                "has_position": False,
                "message": "Strategy not found in executor",
                "timestamp": datetime.now().isoformat()
            }

        if not bool(getattr(exec_state, "any_leg_active", False)):
            return {
                "strategy_name": strategy_name,
                "has_position": False,
                "timestamp": datetime.now().isoformat()
            }

        legs = getattr(exec_state, "legs", {}) or {}
        active_legs = [
            {
                "tag": getattr(leg, "tag", ""),
                "symbol": getattr(leg, "trading_symbol", None) or getattr(leg, "symbol", ""),
                "qty": getattr(leg, "qty", 0),
                "side": getattr(getattr(leg, "side", None), "value", getattr(leg, "side", "")),
            }
            for leg in legs.values()
            if bool(getattr(leg, "is_active", False))
        ]
        entry_time_obj = getattr(exec_state, "entry_time", None)
        return {
            "strategy_name": strategy_name,
            "has_position": True,
            "active_legs": active_legs,
            "entry_time": entry_time_obj.isoformat() if entry_time_obj else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error checking positions for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
