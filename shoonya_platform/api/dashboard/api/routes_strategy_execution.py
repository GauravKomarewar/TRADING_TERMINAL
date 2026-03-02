# ======================================================================
# ROUTES: Strategy Execution Control, Config Save/Load/List,
#         Monitoring All-Strategies-Status
# Extracted from router.py during modularisation.
# ======================================================================
from fastapi import APIRouter, Depends, Query, Body, HTTPException
from typing import Optional, Any, Dict
from datetime import datetime
import json
import time
import logging

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.api._shared import (
    logger,
    STRATEGY_CONFIG_DIR,
    _VALID_SECTIONS,
    get_broker,
    get_system,
    get_all_strategies,
    _slugify,
    _resolve_strategy_config_file,
    _strategy_state_file,
    _write_json_file,
    _get_strategy_configs_dir,
    _get_runtime_running_slugs,
    _mode_from_config_dict,
    _mode_from_saved_file,
    validate_config,
)

sub_router = APIRouter()

# ==================================================
# STRATEGY DISCOVERY & MANAGEMENT
# ==================================================

@sub_router.get("/strategies/list")
def list_available_strategies(ctx=Depends(require_dashboard_auth)):
    """List available strategy configs from strategy_runner/saved_configs."""
    strategies = get_all_strategies()
    templates = [
        {
            "id": s["name"],
            "folder": "saved_configs",
            "file": s["filename"],
            "module": "shoonya_platform.strategy_runner.strategy_executor_service",
            "label": s["config"].get("name", s["name"]),
            "slug": s["name"],
        }
        for s in strategies
    ]
    return {
        "strategies": templates,
        "total": len(templates),
        "predefined": templates,
    }


# ==================================================
# PER-STRATEGY RUNNER CONTROL (Individual Start/Stop)
# ==================================================

@sub_router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(
    strategy_name: str,
    payload: dict = Body(default={}),
    ctx=Depends(require_dashboard_auth)
):
    """Start a specific strategy by name from saved_configs/"""
    try:
        requested_key = _slugify(strategy_name)
        bot = ctx["bot"]
        service = bot.strategy_executor_service
        strategy_file = _resolve_strategy_config_file(strategy_name)

        if not strategy_file:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy config not found for '{strategy_name}'"
            )

        strategy_key = strategy_file.stem

        if strategy_key in service._strategies:
            logger.info(f"Strategy {strategy_key} already running")
            return {
                "success": False,
                "strategy_name": strategy_key,
                "message": "Strategy already running",
                "timestamp": datetime.now().isoformat()
            }

        fresh_start = bool((payload or {}).get("fresh_start", False))
        stale_state_reset = False
        if fresh_start:
            try:
                sf = _strategy_state_file(service, strategy_key)
                if sf.exists():
                    sf.unlink()
                    logger.info("Cleared strategy state file for fresh start: %s", sf)
                if hasattr(service, "state_mgr"):
                    try:
                        service.state_mgr.clear_monitor_snapshot(strategy_key)
                        logger.info("Cleared monitor snapshot for fresh start: %s", strategy_key)
                    except Exception as clear_err:
                        logger.warning("Could not clear monitor snapshot for %s: %s", strategy_key, clear_err)
            except Exception as se:
                logger.warning("Could not clear state file for %s: %s", strategy_key, se)
        else:
            try:
                sf = _strategy_state_file(service, strategy_key)
                if sf.exists():
                    raw = json.loads(sf.read_text(encoding="utf-8"))
                    entered_today = bool(raw.get("entered_today"))
                    legs_raw = raw.get("legs") or {}
                    has_open_legs = False
                    if isinstance(legs_raw, dict):
                        for leg in legs_raw.values():
                            if not isinstance(leg, dict):
                                continue
                            if bool(leg.get("is_active")):
                                has_open_legs = True
                                break
                            if str(leg.get("order_status", "")).upper() == "PENDING":
                                has_open_legs = True
                                break
                    if entered_today and not has_open_legs:
                        sf.unlink()
                        stale_state_reset = True
                        logger.info("Cleared stale blocked state file: %s", sf)
                        if hasattr(service, "state_mgr"):
                            try:
                                service.state_mgr.clear_monitor_snapshot(strategy_key)
                                logger.info("Cleared stale monitor snapshot for %s", strategy_key)
                            except Exception as clear_err:
                                logger.warning("Could not clear monitor snapshot for %s: %s", strategy_key, clear_err)
            except Exception as stale_err:
                logger.warning("Could not evaluate stale state for %s: %s", strategy_key, stale_err)

        config = json.loads(strategy_file.read_text(encoding="utf-8"))
        bot.start_strategy_executor(strategy_name=strategy_key, config=config)
        if strategy_key not in service._strategies:
            logger.warning(
                "start-execution: strategy not registered via bot path, using direct register fallback | %s",
                strategy_key,
            )
            service.register_strategy(name=strategy_key, config_path=str(strategy_file))

        if not getattr(service, "_running", False):
            logger.warning("Strategy runner loop was stopped; restarting runner service")
            service.start()

        if strategy_key not in service._strategies:
            raise RuntimeError(f"Strategy '{strategy_key}' was not registered in executor service")

        config["status"] = "RUNNING"
        config["status_updated_at"] = datetime.now().isoformat()
        _write_json_file(strategy_file, config)

        return {
            "success": True,
            "strategy_name": strategy_key,
            "requested_strategy_name": requested_key,
            "fresh_start": fresh_start,
            "stale_state_reset": stale_state_reset,
            "message": f"Strategy {strategy_key} started",
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting strategy execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@sub_router.post("/strategy/{strategy_name}/stop-execution")
def stop_strategy_execution(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth)
):
    """Stop a specific running strategy."""
    try:
        requested_key = _slugify(strategy_name)
        bot = ctx["bot"]
        service = bot.strategy_executor_service
        strategy_file = _resolve_strategy_config_file(strategy_name)
        strategy_key = strategy_file.stem if strategy_file else requested_key
        logger.info(f"Stop requested for strategy: {strategy_key} (requested={requested_key})")

        was_running_in_memory = strategy_key in service._strategies

        if was_running_in_memory:
            service.unregister_strategy(strategy_key)
            with bot._live_strategies_lock:
                bot._live_strategies.pop(strategy_key, None)

        if hasattr(service, "state_mgr") and service.state_mgr:
            try:
                service.state_mgr.delete(strategy_key)
            except Exception as se:
                logger.warning(f"Could not clear persisted state for {strategy_key}: {se}")

        try:
            sf = _strategy_state_file(service, strategy_key)
            if sf.exists():
                sf.unlink()
                logger.info("Cleared runtime state snapshot for %s: %s", strategy_key, sf)
        except Exception as se:
            logger.warning(f"Could not clear runtime state snapshot for {strategy_key}: {se}")

        try:
            strategy_file = _resolve_strategy_config_file(strategy_key) or (STRATEGY_CONFIG_DIR / f"{strategy_key}.json")
            if strategy_file.exists():
                cfg = json.loads(strategy_file.read_text(encoding="utf-8"))
                cfg["status"] = "STOPPED"
                cfg["status_updated_at"] = datetime.now().isoformat()
                _write_json_file(strategy_file, cfg)
        except Exception as se:
            logger.warning(f"Could not update status for {strategy_key}: {se}")

        logger.info(
            "Strategy stop completed: %s (in_memory=%s)",
            strategy_key,
            was_running_in_memory,
        )
        return {
            "success": True,
            "strategy_name": strategy_key,
            "requested_strategy_name": requested_key,
            "message": f"Strategy {strategy_key} stopped",
            "in_memory_running": was_running_in_memory,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error stopping strategy execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================
# STRATEGY CONFIG — Save / Load / List
# ==================================================

@sub_router.post("/strategy/config/save")
def save_strategy_config(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Save a strategy config section (entry/adjustment/exit/rms)."""
    name = payload.get("name", "").strip()
    section = payload.get("section", "").strip().lower()
    config = payload.get("config")

    if not name:
        raise HTTPException(400, "Strategy name is required")
    if section not in _VALID_SECTIONS:
        raise HTTPException(400, f"Invalid section '{section}'. Must be one of: {', '.join(sorted(_VALID_SECTIONS))}")
    if not isinstance(config, dict):
        raise HTTPException(400, "config must be a JSON object")

    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    existing = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["name"] = name
    existing[section] = config
    existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    _write_json_file(filepath, existing)
    logger.info("Strategy config saved: %s / %s", name, section)
    return {"saved": True, "name": name, "section": section, "file": slug + ".json"}


@sub_router.get("/strategy/config/{name}")
def load_strategy_config(
    name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Load a saved strategy config by name."""
    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    if not filepath.exists():
        return {"name": name, "entry": {}, "adjustment": {}, "exit": {}, "rms": {}}

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        raise HTTPException(500, f"Failed to read config: {e}")


@sub_router.get("/strategy/configs")
def list_strategy_configs(ctx=Depends(require_dashboard_auth)):
    """List all saved strategy configs with full data and live/mock mode."""
    cfg_dir = _get_strategy_configs_dir()
    runtime_running = _get_runtime_running_slugs(ctx)
    configs = []
    parse_errors = []

    bot = ctx["bot"]
    service = getattr(bot, "strategy_executor_service", None)

    for f in sorted(cfg_dir.glob("*.json")):
        if f.name == "STRATEGY_CONFIG_SCHEMA.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            slug = f.stem
            file_status = str(data.get("status", "IDLE") or "IDLE").upper()
            effective_status = "RUNNING" if slug in runtime_running else ("IDLE" if file_status == "RUNNING" else file_status)

            mode = _mode_from_config_dict(data)
            can_change = True
            mode_change_reason = None
            if service:
                try:
                    if hasattr(service, "_strategies") and slug in getattr(service, "_strategies", {}):
                        mode = service.get_strategy_mode(slug) if hasattr(service, "get_strategy_mode") else mode
                except Exception:
                    pass
                try:
                    if hasattr(service, "_validate_mode_change_allowed"):
                        allowed, reason = service._validate_mode_change_allowed(slug)
                        can_change = bool(allowed)
                        mode_change_reason = reason or None
                    else:
                        has_pos = service.has_position(slug) if hasattr(service, "has_position") else False
                        if has_pos:
                            can_change = False
                            mode_change_reason = "Strategy has active positions"
                except Exception:
                    pass

            configs.append({
                "schema_version": data.get("schema_version", "1.0"),
                "name": data.get("name", f.stem),
                "id": data.get("id", f.stem),
                "type": data.get("type"),
                "strategy_type": data.get("strategy_type") or data.get("type"),
                "description": data.get("description", ""),
                "tags": data.get("tags", []),
                "file": f.name,
                "updated_at": data.get("updated_at", ""),
                "created_at": data.get("created_at", ""),
                "status": effective_status,
                "status_file": file_status,
                "status_runtime_running": slug in runtime_running,
                "sections": [s for s in _VALID_SECTIONS if s in data and data[s]],
                "identity": data.get("identity", {}),
                "entry": data.get("entry", {}),
                "adjustment": data.get("adjustment", {}),
                "exit": data.get("exit", {}),
                "rms": data.get("rms", {}),
                "mode": mode,
                "can_change_mode": can_change,
                "mode_change_reason": mode_change_reason,
            })
        except Exception as e:
            parse_errors.append(f"{f.name}: {e}")
            continue
    return {
        "configs": configs,
        "total": len(configs),
        "directory": str(cfg_dir),
        "parse_errors": parse_errors[:20],
    }


# ==================================================
# 📊 MONITORING — ALL STRATEGIES STATUS
# ==================================================

@sub_router.get("/monitoring/all-strategies-status")
def get_all_strategies_execution_status(
    broker=Depends(get_broker),
    system=Depends(get_system),
    ctx=Depends(require_dashboard_auth),
):
    """Comprehensive visibility endpoint showing execution status of ALL strategies."""
    try:
        cfg_dir = _get_strategy_configs_dir()
        runtime_running = _get_runtime_running_slugs(ctx)
        all_configs = []
        for f in sorted(cfg_dir.glob("*.json")):
            if f.name == "STRATEGY_CONFIG_SCHEMA.json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                slug = f.stem
                file_status = str(data.get("status", "IDLE") or "IDLE").upper()
                effective_status = "RUNNING" if slug in runtime_running else ("IDLE" if file_status == "RUNNING" else file_status)
                all_configs.append({
                    "name": data.get("name", f.stem),
                    "status": effective_status,
                    "status_file": file_status,
                    "runtime_running": slug in runtime_running,
                    "status_updated_at": data.get("status_updated_at"),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "identity": data.get("identity", {}).get("underlying", "N/A"),
                })
            except Exception:
                continue

        control_intents = system.get_control_intents(100) or []
        intent_by_strategy = {}
        for intent in control_intents:
            strat_name = intent.get("strategy_name", "UNKNOWN")
            if strat_name not in intent_by_strategy:
                intent_by_strategy[strat_name] = []
            intent_by_strategy[strat_name].append({
                "intent_id": intent.get("intent_id"),
                "action": intent.get("action"),
                "status": intent.get("status", "PENDING"),
                "created_at": intent.get("created_at"),
            })

        positions = broker.get_positions() or []
        positions_by_strategy = {}
        for pos in positions:
            symbol = pos.get("tsym", "")
            try:
                netqty = int(pos.get("netqty", 0))
            except (ValueError, TypeError):
                netqty = 0
            if netqty == 0 or not symbol:
                continue
            strat = "ACTIVE_POSITION"
            if strat not in positions_by_strategy:
                positions_by_strategy[strat] = []
            positions_by_strategy[strat].append({
                "symbol": symbol,
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "ltp": float(pos.get("ltp", 0)),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
            })

        strategies_execution = []
        seen_strategies = set()

        for config in all_configs:
            name = config["name"]
            seen_strategies.add(name)
            strategies_execution.append({
                "name": name,
                "status": config["status"],
                "status_updated_at": config["status_updated_at"],
                "created_at": config["created_at"],
                "underlying": config["identity"],
                "pending_intents": intent_by_strategy.get(name, []),
                "active_positions": [],
                "intent_count": len(intent_by_strategy.get(name, [])),
                "position_count": 0,
                "is_hidden": False,
            })

        for strat_name in intent_by_strategy:
            if strat_name not in seen_strategies:
                seen_strategies.add(strat_name)
                strategies_execution.append({
                    "name": strat_name,
                    "status": "UNKNOWN",
                    "status_updated_at": None,
                    "created_at": None,
                    "underlying": "N/A",
                    "pending_intents": intent_by_strategy[strat_name],
                    "active_positions": positions_by_strategy.get(strat_name, []),
                    "intent_count": len(intent_by_strategy[strat_name]),
                    "position_count": len(positions_by_strategy.get(strat_name, [])),
                    "is_hidden": True,
                })

        running_count = sum(1 for s in strategies_execution if s["status"] == "RUNNING")
        paused_count = sum(1 for s in strategies_execution if s["status"] == "PAUSED")
        pending_intents = sum(s["intent_count"] for s in strategies_execution)
        active_positions_total = sum(len(positions_by_strategy.get(s["name"], [])) for s in strategies_execution)

        _STATUS_ORDER = {"RUNNING": 0, "PAUSED": 1, "STOPPED": 2, "IDLE": 3, "UNKNOWN": 4}
        return {
            "timestamp": datetime.now().isoformat(),
            "audit": {
                "total_configured_strategies": len(all_configs),
                "total_unique_strategies": len(strategies_execution),
                "strategies_running": running_count,
                "strategies_paused": paused_count,
                "strategies_idle": sum(1 for s in strategies_execution if s["status"] == "IDLE"),
                "strategies_unknown": sum(1 for s in strategies_execution if s["status"] == "UNKNOWN"),
                "pending_intents_in_queue": pending_intents,
                "active_positions_total": active_positions_total,
                "has_hidden_strategies": any(s["is_hidden"] for s in strategies_execution),
            },
            "strategies": sorted(strategies_execution, key=lambda x: _STATUS_ORDER.get(x["status"], 99)),
            "control_intents": control_intents,
        }

    except Exception as e:
        logger.exception("Failed to get strategy execution status")
        raise HTTPException(status_code=500, detail=str(e))
