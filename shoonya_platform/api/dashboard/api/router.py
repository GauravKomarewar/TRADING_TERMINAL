# ======================================================================
# 🔒 DASHBOARD ROUTER — HUB (modularised)
#
# This file is the single entry-point for the /dashboard API.
# All route handlers live in dedicated sub-modules under this package.
# External code should continue to import from THIS file:
#
#   from shoonya_platform.api.dashboard.api.router import router
#   from shoonya_platform.api.dashboard.api.router import get_live_positions_overview
#
# Sub-modules:
#   routes_orders_recovery      – symbols, orderbook, orders, recovery, orphans
#   routes_strategy_execution   – strategy lifecycle, config save/load/list, all-status
#   routes_strategy_config      – config CRUD, strategy JSON CRUD
#   routes_intents_optionchain  – intents, dashboard home, option chain, diagnostics
#   routes_monitoring           – positions, greeks, live overview, index tokens
#   routes_runner               – analytics, runner control, logs, WS, mode, positions
# ======================================================================
from fastapi import APIRouter

# --------------- main router ---------------
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# --------------- include sub-routers ---------------
from shoonya_platform.api.dashboard.api.routes_orders_recovery import sub_router as _orders_recovery
from shoonya_platform.api.dashboard.api.routes_strategy_execution import sub_router as _strategy_execution
from shoonya_platform.api.dashboard.api.routes_strategy_config import sub_router as _strategy_config
from shoonya_platform.api.dashboard.api.routes_intents_optionchain import sub_router as _intents_optionchain
from shoonya_platform.api.dashboard.api.routes_monitoring import sub_router as _monitoring
from shoonya_platform.api.dashboard.api.routes_runner import sub_router as _runner
from shoonya_platform.api.dashboard.api.routes_telegram import sub_router as _telegram

router.include_router(_orders_recovery)
router.include_router(_strategy_execution)
router.include_router(_strategy_config)
router.include_router(_intents_optionchain)
router.include_router(_monitoring)
router.include_router(_runner)
router.include_router(_telegram)

# --------------- backward-compatible re-exports ---------------
# tests/test_strategy_hardening_regression.py imports this directly:
from shoonya_platform.api.dashboard.api.routes_monitoring import get_live_positions_overview  # noqa: F401

# Re-export shared constants & utilities that external code may reference
from shoonya_platform.api.dashboard.api._shared import (  # noqa: F401
    _PROJECT_ROOT,
    DATA_DIR,
    STRATEGY_CONFIG_DIR,
    get_all_strategies,
    load_strategy_json,
    save_strategy_json,
)
