# ======================================================================
# SHARED UTILITIES FOR DASHBOARD ROUTER SUB-MODULES
# Extracted from router.py during modularisation.
# All route sub-modules import shared constants, DI factories,
# and utility functions from here.
# ======================================================================
import threading
from fastapi import Depends, Query, Body, HTTPException, status
from typing import List, Optional, Any, Dict
import logging
from uuid import uuid4
from pathlib import Path
from datetime import datetime
import sqlite3
import time
import json
import re
from collections import deque
import os

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.services.broker_service import BrokerService
from shoonya_platform.api.dashboard.services.system_service import SystemTruthService
from shoonya_platform.api.dashboard.services.symbols_utility import DashboardSymbolService
from shoonya_platform.api.dashboard.services.intent_utility import DashboardIntentService
from shoonya_platform.api.dashboard.services.option_chain_service import (
    get_active_expiries,
    get_active_symbols,
    find_nearest_option,
)
from shoonya_platform.market_data.feeds import index_tokens_subscriber
from shoonya_platform.strategy_runner.config_schema import validate_config

from shoonya_platform.api.dashboard.api.schemas import (
    StrategyIntentRequest,
    StrategyAction,
    SymbolSearchResult,
    ExpiryView,
    ContractView,
    GenericIntentRequest,
    AdvancedIntentRequest,
    IntentResponse,
    BasketIntentRequest,
    StrategyEntryRequest,
)

# ======================================================================
# CONSTANTS
# ======================================================================

# 🔒 Single canonical storage location (cross-platform)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = (
    _PROJECT_ROOT
    / "shoonya_platform"
    / "market_data"
    / "option_chain"
    / "data"
)

# ✅ BUG-003 FIX: Define STRATEGY_CONFIG_DIR at module level
STRATEGY_CONFIG_DIR = _PROJECT_ROOT / "shoonya_platform" / "strategy_runner" / "saved_configs"
STRATEGY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

_STRATEGY_CONFIGS_DIR = (
    _PROJECT_ROOT
    / "shoonya_platform"
    / "strategy_runner"
    / "saved_configs"
)
_STRATEGY_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

_VALID_SECTIONS = {"identity", "entry", "adjustment", "exit", "rms"}

logger = logging.getLogger("DASHBOARD.INTENT.API")

# ======================================================================
# STUB HELPERS (kept for backward compat)
# ======================================================================

def _drop_empty_conditions(conds):
    """Remove condition objects with missing/empty 'parameter' from a list."""
    if not isinstance(conds, list):
        return conds
    out = []
    for c in conds:
        if not isinstance(c, dict):
            continue
        # Compound condition (operator + rules) — keep as-is, recurse into rules
        if "operator" in c and "rules" in c:
            c = dict(c)
            c["rules"] = _drop_empty_conditions(c.get("rules", []))
            out.append(c)
        else:
            # Simple condition — skip if parameter is absent or blank
            if not c.get("parameter", ""):
                continue
            out.append(c)
    return out


def _sanitize_config_conditions(cfg: Dict) -> Dict:
    """
    Walk the config and strip condition objects with empty 'parameter' from:
    - entry.global_conditions
    - entry.legs[*].conditions / else_conditions
    - adjustment.rules[*].conditions / else_conditions
    - exit.per_leg_exit[*].conditions
    This lets old/partially-filled JSONs import cleanly instead of failing validation.
    """
    if not isinstance(cfg, dict):
        return cfg
    cfg = dict(cfg)  # shallow copy to avoid mutating caller's dict

    # entry.global_conditions
    entry = cfg.get("entry")
    if isinstance(entry, dict):
        entry = dict(entry)
        if "global_conditions" in entry:
            entry["global_conditions"] = _drop_empty_conditions(entry["global_conditions"])
        legs = entry.get("legs")
        if isinstance(legs, list):
            new_legs = []
            for leg in legs:
                if isinstance(leg, dict):
                    leg = dict(leg)
                    if "conditions" in leg:
                        leg["conditions"] = _drop_empty_conditions(leg["conditions"])
                    if "else_conditions" in leg:
                        leg["else_conditions"] = _drop_empty_conditions(leg["else_conditions"])
                new_legs.append(leg)
            entry["legs"] = new_legs
        cfg["entry"] = entry

    # adjustment.rules[*].conditions / else_conditions
    adjustment = cfg.get("adjustment")
    if isinstance(adjustment, dict):
        adjustment = dict(adjustment)
        rules = adjustment.get("rules")
        if isinstance(rules, list):
            new_rules = []
            for rule in rules:
                if isinstance(rule, dict):
                    rule = dict(rule)
                    if "conditions" in rule:
                        rule["conditions"] = _drop_empty_conditions(rule["conditions"])
                    if "else_conditions" in rule:
                        rule["else_conditions"] = _drop_empty_conditions(rule["else_conditions"])
                new_rules.append(rule)
            adjustment["rules"] = new_rules
        cfg["adjustment"] = adjustment

    # exit.per_leg_exit[*].conditions
    exit_cfg = cfg.get("exit")
    if isinstance(exit_cfg, dict):
        exit_cfg = dict(exit_cfg)
        per_leg = exit_cfg.get("per_leg_exit")
        if isinstance(per_leg, list):
            new_per_leg = []
            for rule in per_leg:
                if isinstance(rule, dict):
                    rule = dict(rule)
                    if "conditions" in rule:
                        rule["conditions"] = _drop_empty_conditions(rule["conditions"])
                new_per_leg.append(rule)
            exit_cfg["per_leg_exit"] = new_per_leg
        exit_conds = exit_cfg.get("conditions")
        if exit_conds is not None:
            exit_cfg["conditions"] = _drop_empty_conditions(exit_conds)
        cfg["exit"] = exit_cfg

    return cfg


def ensure_complete_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return _sanitize_config_conditions(cfg) if cfg else {}


def convert_v2_to_factory_format(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg or {}


def is_v2_config(cfg: Dict[str, Any]) -> bool:
    return False


def get_factory_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg or {}


# ======================================================================
# UTILITY FUNCTIONS
# ======================================================================

def _parse_iso_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp '{value}': {e}")


def _get_historical_service(ctx: dict):
    bot = ctx.get("bot")
    svc = getattr(bot, "historical_analytics_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Historical analytics service unavailable")
    return svc


# ======================================================================
# DEPENDENCY FACTORIES (CLIENT-SCOPED)
# ======================================================================

def get_broker(ctx=Depends(require_dashboard_auth)):
    return BrokerService(ctx["bot"].broker_view)

def get_system(ctx=Depends(require_dashboard_auth)):
    return SystemTruthService(client_id=ctx["client_id"])

def get_intent(ctx=Depends(require_dashboard_auth)):
    return DashboardIntentService(
        client_id=ctx["client_id"],
        parent_client_id=ctx.get("parent_client_id"),
    )

# BUG-027 FIX: Explicit thread-safe singletons instead of lru_cache.
_symbols_service_instance: Optional[DashboardSymbolService] = None
_symbols_service_lock = threading.Lock()


def get_symbols() -> DashboardSymbolService:
    global _symbols_service_instance
    if _symbols_service_instance is None:
        with _symbols_service_lock:
            if _symbols_service_instance is None:
                _symbols_service_instance = DashboardSymbolService()
    return _symbols_service_instance


# ======================================================================
# STRATEGY CONFIG UTILITIES
# ======================================================================

def _get_strategy_configs_dir() -> Path:
    """
    ✅ BUG-M2 FIX: STRATEGY_CONFIG_DIR is now defined at module top-level.
    """
    STRATEGY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return STRATEGY_CONFIG_DIR

def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace a file to avoid partial/empty reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp_path, path)
    except Exception:
        # Clean up leftover temp file on failure (e.g. cross-filesystem)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise

def _write_json_file(path: Path, payload: Dict[str, Any], encoding: str = "utf-8") -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding=encoding,
    )

def _slugify(name: str) -> str:
    """Convert strategy name to safe filename slug."""
    s = name.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_') or 'unnamed'


def _resolve_strategy_config_file(strategy_name: str) -> Optional[Path]:
    """Resolve config by filename slug OR config metadata (id/name)."""
    requested_slug = _slugify(strategy_name)
    direct = STRATEGY_CONFIG_DIR / f"{requested_slug}.json"
    if direct.exists():
        return direct

    for path in sorted(STRATEGY_CONFIG_DIR.glob("*.json")):
        if "schema" in path.stem.lower():
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue

        file_slug = _slugify(path.stem)
        id_slug = _slugify(str(cfg.get("id", ""))) if cfg.get("id") is not None else ""
        name_slug = _slugify(str(cfg.get("name", ""))) if cfg.get("name") is not None else ""
        if requested_slug in {file_slug, id_slug, name_slug}:
            return path
    return None


def _mode_from_config_dict(config: Dict[str, Any]) -> str:
    """Return LIVE/MOCK from config paper/test flags."""
    cfg = config or {}
    identity = cfg.get("identity", {}) or {}
    is_mock = bool(
        identity.get("paper_mode")
        or identity.get("test_mode")
    )
    return "MOCK" if is_mock else "LIVE"


def _mode_from_saved_file(strategy_name: str) -> str:
    """Resolve strategy mode directly from saved config on disk."""
    try:
        path = _resolve_strategy_config_file(strategy_name)
        if not path:
            path = STRATEGY_CONFIG_DIR / f"{_slugify(strategy_name)}.json"
        if not path.exists():
            return "LIVE"
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        return _mode_from_config_dict(cfg)
    except Exception:
        return "LIVE"


def _get_runtime_running_slugs(ctx: dict) -> set[str]:
    """Read currently running strategy keys from StrategyExecutorService."""
    try:
        bot = ctx.get("bot")
        svc = getattr(bot, "strategy_executor_service", None)
        if svc is None:
            return set()
        return set(list(getattr(svc, "_strategies", {}).keys()))
    except Exception:
        return set()


# ======================================================================
# STRATEGY VALIDATION & LOGGER HELPERS
# ======================================================================

class _ValidationResult:
    def __init__(self, valid: bool, errors: List[str], warnings: List[str]):
        self.valid = valid
        self.errors = errors
        self.warnings = warnings

    def to_dict(self):
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def validate_strategy(config, strategy_name):
    is_valid, issues = validate_config(config if isinstance(config, dict) else {})
    errors = [f"{e.path}: {e.message}" for e in issues if e.severity == "error"]
    warnings = [f"{e.path}: {e.message}" for e in issues if e.severity == "warning"]
    return _ValidationResult(is_valid, errors, warnings)


class _NoopStrategyLogger:
    def get_recent_logs(self, lines=100, level=None):
        return []


def get_strategy_logger(strategy_name):
    return _NoopStrategyLogger()


class _NoopLoggerManager:
    def __init__(self):
        self.loggers = {}

    def list_active_strategies(self):
        return []

    def get_logs(self, strategy_name, lines=100):
        return []

    def clear_logs(self, strategy_name):
        return True

    def clear_strategy_logs(self, strategy_name):
        return True

    def get_all_logs_combined(self, lines=500):
        return []


def get_logger_manager():
    return _NoopLoggerManager()


def get_all_strategies():
    """List all strategy JSON files from saved_configs/"""
    if not STRATEGY_CONFIG_DIR.exists():
        return []

    strategies = []
    for json_file in STRATEGY_CONFIG_DIR.glob("*.json"):
        if "schema" in json_file.stem.lower():
            continue
        try:
            with open(json_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                strategies.append({
                    "name": json_file.stem,
                    "filename": json_file.name,
                    "created": json_file.stat().st_ctime,
                    "modified": json_file.stat().st_mtime,
                    "config": config
                })
        except Exception as e:
            logger.warning(f"Failed to read strategy {json_file.name}: {e}")

    return strategies


def load_strategy_json(name: str):
    """Load strategy JSON by name (slugified for consistency)."""
    slug = _slugify(name)
    strategy_file = STRATEGY_CONFIG_DIR / f"{slug}.json"
    if not strategy_file.exists():
        # Fallback: try the raw name for backward compat
        raw_file = STRATEGY_CONFIG_DIR / f"{name}.json"
        if not raw_file.exists():
            return None
        strategy_file = raw_file

    with open(strategy_file, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def save_strategy_json(name: str, config: dict):
    """Save strategy JSON by name — ensures ALL schema fields are present."""
    STRATEGY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    strategy_file = STRATEGY_CONFIG_DIR / f"{name}.json"

    complete = ensure_complete_config(config)
    complete["name"] = complete.get("name") or name
    complete["id"] = complete.get("id") or name.upper().replace(" ", "_").strip("_")

    import time as _t
    now = _t.strftime("%Y-%m-%dT%H:%M:%S")
    if not complete.get("created_at"):
        complete["created_at"] = now
    complete["updated_at"] = now

    _write_json_file(strategy_file, complete)
    return strategy_file


# ======================================================================
# RUNNER CONTROL HELPERS
# ======================================================================

# BUG-M3 FIX: Use a regular dict so entries are not GC'd while the bot is alive.
_runner_instances: dict = {}
_runner_instances_lock = threading.Lock()

def _strategy_state_file(service: Any, strategy_key: str) -> Path:
    """Resolve per-strategy runtime state file used by PerStrategyExecutor.

    Falls back to a deterministic app-data directory under the user's home
    when ``service.state_db_path`` is empty, rather than the process CWD.
    """
    state_db_path = getattr(service, "state_db_path", "") or ""
    if state_db_path:
        base_dir = Path(state_db_path).parent
    else:
        base_dir = Path.home() / ".shoonya" / "state"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{strategy_key}_state.pkl"

def get_runner_singleton(ctx: dict):
    """Get StrategyExecutorService singleton for the current client."""
    global _runner_instances
    client_id = ctx.get("client_id")
    if not client_id:
        raise RuntimeError("No client_id in context")

    with _runner_instances_lock:
        if client_id not in _runner_instances:
            logger.info(f"Initializing StrategyExecutorService for client {client_id}")
            try:
                bot = ctx.get("bot")
                if bot is None:
                    raise RuntimeError(f"No bot in context for client {client_id}")
                _runner_instances[client_id] = bot.strategy_executor_service
            except Exception as e:
                logger.error(f"Failed to initialize runner for client {client_id}: {e}")
                raise
        return _runner_instances[client_id]
