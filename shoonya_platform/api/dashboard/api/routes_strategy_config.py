# ======================================================================
# ROUTES: Config CRUD (save-all, delete, status, rename, clone),
#         Strategy JSON CRUD (list, get, validate, create, update, delete)
# Extracted from router.py during modularisation.
# ======================================================================
from fastapi import APIRouter, Depends, Body, HTTPException
from typing import Dict, Any
from datetime import datetime
import json
import time
import logging

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.api._shared import (
    logger,
    STRATEGY_CONFIG_DIR,
    _STRATEGY_CONFIGS_DIR,
    _slugify,
    _get_strategy_configs_dir,
    _write_json_file,
    validate_config,
    ensure_complete_config,
    validate_strategy,
    get_all_strategies,
    load_strategy_json,
    save_strategy_json,
    get_logger_manager,
    get_strategy_logger,
)

sub_router = APIRouter()

# ==================================================
# STRATEGY CONFIG — Save All / Delete / Status / Rename / Clone
# ==================================================

@sub_router.post("/strategy/config/save-all")
def save_strategy_config_all(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    name = payload.get("name", "").strip()
    strat_id = payload.get("id", "").strip()

    if not name:
        raise HTTPException(400, "Strategy name is required")
    if not strat_id:
        strat_id = _slugify(name).upper()

    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    # Load existing (if any)
    existing = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # Merge the entire payload, preserving all keys
    merged = {**existing, **payload}
    merged["id"] = strat_id

    # Ensure backward-compatible fields are present
    merged = ensure_complete_config(merged)

    # Validate before persisting
    is_valid, issues = validate_config(merged if isinstance(merged, dict) else {})
    if not is_valid:
        errors = [f"{e.path}: {e.message}" for e in issues if e.severity == "error"]
        warnings = [f"{e.path}: {e.message}" for e in issues if e.severity == "warning"]
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Strategy validation failed",
                "validation": {"valid": False, "errors": errors, "warnings": warnings},
            },
        )

    # Write back
    _write_json_file(filepath, merged)
    logger.info("Strategy config saved (all): %s", name)

    return {"saved": True, "name": name, "id": strat_id, "file": slug + ".json"}


@sub_router.delete("/strategy/config/{name}")
def delete_strategy_config(
    name: str,
    ctx=Depends(require_dashboard_auth),
):
    """Delete a saved strategy config by name."""
    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    if not filepath.exists():
        raise HTTPException(404, f"Config '{name}' not found")

    filepath.unlink()
    logger.info("Strategy config deleted: %s", name)
    return {"deleted": True, "name": name}


@sub_router.post("/strategy/config/{name}/status")
def update_strategy_status(
    name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Update the status of a saved strategy (IDLE/RUNNING/PAUSED/STOPPED)."""
    new_status = payload.get("status", "").strip().upper()
    valid_statuses = {"IDLE", "RUNNING", "PAUSED", "STOPPED"}
    if new_status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}")

    slug = _slugify(name)
    filepath = _get_strategy_configs_dir() / f"{slug}.json"

    if not filepath.exists():
        raise HTTPException(404, f"Config '{name}' not found")

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception as parse_err:
        raise HTTPException(500, f"Failed to parse config for '{name}': {parse_err}")

    data["status"] = new_status
    data["status_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_json_file(filepath, data)

    return {"updated": True, "name": name, "status": new_status}


@sub_router.post("/strategy/config/{name}/rename")
def rename_strategy_config(
    name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Rename a saved strategy config (changes filename + internal name/id)."""
    new_name = payload.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(400, "new_name is required")

    old_slug = _slugify(name)
    new_slug = _slugify(new_name)
    old_path = _STRATEGY_CONFIGS_DIR / f"{old_slug}.json"
    new_path = _STRATEGY_CONFIGS_DIR / f"{new_slug}.json"

    if not old_path.exists():
        raise HTTPException(404, f"Config '{name}' not found")
    if new_path.exists() and old_slug != new_slug:
        raise HTTPException(409, f"Config '{new_name}' already exists")

    try:
        data = json.loads(old_path.read_text(encoding="utf-8"))
    except Exception as parse_err:
        raise HTTPException(500, f"Failed to parse config for '{name}': {parse_err}")

    data["name"] = new_name
    data["id"] = _slugify(new_name).upper()
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    _write_json_file(new_path, data)
    if old_slug != new_slug and old_path.exists():
        old_path.unlink()

    logger.info("Strategy config renamed: %s -> %s", name, new_name)
    return {"renamed": True, "old_name": name, "new_name": new_name, "file": new_slug + ".json"}


@sub_router.post("/strategy/config/{name}/clone")
def clone_strategy_config(
    name: str,
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Clone a saved strategy config with a new name (optionally new underlying)."""
    new_name = payload.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(400, "new_name is required")

    src_slug = _slugify(name)
    dst_slug = _slugify(new_name)
    src_path = _STRATEGY_CONFIGS_DIR / f"{src_slug}.json"
    dst_path = _STRATEGY_CONFIGS_DIR / f"{dst_slug}.json"

    if not src_path.exists():
        raise HTTPException(404, f"Config '{name}' not found")
    if dst_path.exists():
        raise HTTPException(409, f"Config '{new_name}' already exists")

    try:
        data = json.loads(src_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Failed to read source: {e}")

    data["name"] = new_name
    data["id"] = new_name.upper().replace(" ", "_").strip("_")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["created_at"] = now
    data["updated_at"] = now
    data["status"] = "IDLE"
    data.pop("status_updated_at", None)

    # Apply instrument override if provided
    new_underlying = payload.get("underlying", "").strip()
    if new_underlying:
        if isinstance(data.get("identity"), dict):
            data["identity"]["underlying"] = new_underlying
        if isinstance(data.get("entry"), dict):
            data["entry"]["underlying"] = new_underlying

    _write_json_file(dst_path, data)
    logger.info("Strategy config cloned: %s -> %s", name, new_name)
    return {"cloned": True, "source": name, "new_name": new_name, "file": dst_slug + ".json"}


# ==================================================
# STRATEGY JSON CRUD — list / get / validate / create / update / delete
# ==================================================

@sub_router.get("/strategy/list")
def list_all_strategies(ctx=Depends(require_dashboard_auth)):
    """List all saved strategies from saved_configs/ directory."""
    try:
        strategies = get_all_strategies()
        return {
            "total": len(strategies),
            "strategies": strategies,
            "timestamp": datetime.now().isoformat(),
            "directory": str(STRATEGY_CONFIG_DIR)
        }
    except Exception as e:
        logger.error(f"Error listing strategies: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.get("/strategy/{strategy_name}")
def get_strategy_by_name(strategy_name: str, ctx=Depends(require_dashboard_auth)):
    """Get specific strategy by name."""
    try:
        config = load_strategy_json(strategy_name)
        if not config:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{strategy_name}' not found"
            )

        normalized = ensure_complete_config(config)
        validation_result = validate_strategy(normalized, strategy_name)

        return {
            "name": strategy_name,
            "config": config,
            "validation": validation_result.to_dict(),
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.post("/strategy/validate")
def validate_strategy_config(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Validate strategy JSON configuration BEFORE saving."""
    strategy_name = "UNKNOWN"
    try:
        strategy_name = payload.get("name", "UNKNOWN")
        strategy_config = ensure_complete_config(payload)
        result = validate_strategy(strategy_config, strategy_name)
        return {
            **result.to_dict(),
            "name": strategy_name,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error validating strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.post("/strategy/create")
def create_new_strategy(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Create new strategy. Validates, ensures all fields, then saves."""
    try:
        strategy_name = (payload.get("name") or "").strip()
        if not strategy_name:
            raise HTTPException(400, "Strategy name is required (payload.name)")

        complete = ensure_complete_config(payload)
        validation_result = validate_strategy(complete, strategy_name)

        if not validation_result.valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Strategy validation failed",
                    "validation": validation_result.to_dict(),
                },
            )

        slug = _slugify(strategy_name)
        existing = load_strategy_json(slug)
        if existing:
            raise HTTPException(409, f"Strategy '{strategy_name}' already exists")

        filepath = save_strategy_json(slug, complete)

        return {
            "success": True,
            "name": strategy_name,
            "filename": f"{slug}.json",
            "path": str(filepath),
            "validation": validation_result.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating strategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.put("/strategy/{strategy_name}")
def update_strategy(
    strategy_name: str,
    strategy_config: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Update existing strategy — validates before saving."""
    try:
        complete = ensure_complete_config(strategy_config)
        validation_result = validate_strategy(complete, strategy_name)

        if not validation_result.valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Strategy validation failed",
                    "validation": validation_result.to_dict(),
                },
            )

        existing = load_strategy_json(strategy_name)
        if not existing:
            raise HTTPException(404, f"Strategy '{strategy_name}' not found")

        filepath = save_strategy_json(strategy_name, complete)

        return {
            "success": True,
            "name": strategy_name,
            "updated": True,
            "path": str(filepath),
            "validation": validation_result.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.delete("/strategy/{strategy_name}")
def delete_strategy(strategy_name: str, ctx=Depends(require_dashboard_auth)):
    """Delete strategy file from saved_configs/."""
    try:
        strategy_file = STRATEGY_CONFIG_DIR / f"{strategy_name}.json"

        if not strategy_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{strategy_name}' not found"
            )

        bot = ctx.get("bot")
        if bot:
            try:
                service = bot.strategy_executor_service
                if strategy_name in service._strategies or _slugify(strategy_name) in service._strategies:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Cannot delete running strategy '{strategy_name}'"
                    )
            except HTTPException:
                raise
            except AttributeError:
                logger.debug("strategy_executor_service not available for running check")

        strategy_file.unlink()
        get_logger_manager().clear_strategy_logs(strategy_name)

        return {
            "success": True,
            "name": strategy_name,
            "deleted": True,
            "path": str(strategy_file),
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
