#!/usr/bin/env python3
"""
STRATEGY ENTRYPOINT — DB BACKED (PRODUCTION SAFE)
================================================

• Uses SQLite-backed option-chain snapshots
• NO live feeds
• NO websocket subscriptions
• Supervisor owns option chain & DB writes
• Strategy reads DB ONLY
• SINGLE ShoonyaBot (owned by execution service)
• SINGLE broker session
• EXITs routed via OrderWatcherEngine

⚠️ MUST run INSIDE execution-service process
⚠️ HARD-FAIL if bot is not initialized
"""

import sys
import logging
import importlib
from datetime import datetime
from pathlib import Path

from shoonya_platform.execution.engine_no_recovery import Engine
from shoonya_platform.execution.db_market import DBBackedMarket
from shoonya_platform.execution.broker import Broker
from shoonya_platform.execution.trading_bot import get_global_bot

from shoonya_platform.strategies.delta_neutral.delta_neutral_short_strategy import (
    DeltaNeutralShortStrangleStrategy,
)

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------
logger = logging.getLogger("STRATEGY_RUNNER_DB")

# ------------------------------------------------------------------
# MAIN (EXECUTION SERVICE ONLY)
# ------------------------------------------------------------------
def main(config_path: str):
    # -------------------------------------------------
    # HARD GUARD: execution service must own the bot
    # -------------------------------------------------
    try:
        bot = get_global_bot()
    except Exception:
        raise RuntimeError(
            "❌ DB strategy cannot start — ShoonyaBot not initialized.\n"
            "This strategy MUST run inside execution service."
        )

    # -------------------------------------------------
    # LOAD STRATEGY CONFIG (DATA ONLY)
    # -------------------------------------------------
    cfg = importlib.import_module(
        f"shoonya_platform.strategies.{config_path}"
    )

    STRATEGY_NAME = cfg.STRATEGY_NAME
    META = cfg.META
    STRATEGY_CONFIG = cfg.CONFIG
    ENGINE_CFG = cfg.ENGINE

    logger.info(f"📌 Loading strategy config: {STRATEGY_NAME}")

    # -------------------------------------------------
    # EXPIRY RESOLUTION (DB IS SOURCE OF TRUTH)
    # -------------------------------------------------
    data_dir = (
        Path(__file__).resolve().parents[1]
        / "market_data"
        / "option_chain"
        / "data"
    )

    matches = sorted(
        data_dir.glob(f"{META['exchange']}_{META['symbol']}_*.sqlite")
    )

    if not matches:
        raise RuntimeError("❌ No option-chain DB found")

    db_file = matches[-1]
    expiry = db_file.stem.split("_")[-1]

    logger.info(f"📦 Using DB expiry: {expiry}")

    # -------------------------------------------------
    # DB-BACKED MARKET (READ-ONLY)
    # -------------------------------------------------
    market = DBBackedMarket(
        db_path=str(db_file),
        exchange=META["exchange"],
        symbol=META["symbol"],
    )

    # -------------------------------------------------
    # STRATEGY (PURE LOGIC)
    # -------------------------------------------------
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=META["exchange"],
        symbol=META["symbol"],
        expiry=expiry,
        lot_qty=STRATEGY_CONFIG.lot_qty,
        get_option_func=market.get_nearest_option,
        config=STRATEGY_CONFIG,
    )

    # -------------------------------------------------
    # BROKER (BOT OWNED BY EXECUTION SERVICE)
    # -------------------------------------------------
    broker = Broker(
        bot=bot,
        exchange=META["exchange"],
        symbol=META["symbol"],
        expiry=expiry,
        product_type="M",
    )

    # -------------------------------------------------
    # ENGINE (NO RECOVERY — CLEAN START)
    # -------------------------------------------------
    engine = Engine(
        engine_id=f"{STRATEGY_NAME}_DB_{datetime.now():%Y%m%d_%H%M%S}",
        strategy=strategy,
        market=market,
        broker=broker,
        engine_cfg=ENGINE_CFG,
    )

    logger.info(f"🚀 DB-backed strategy armed: {STRATEGY_NAME}")
    engine.run()


# ------------------------------------------------------------------
# CLI (DEV ONLY)
# ------------------------------------------------------------------
if __name__ == "__main__":
    raise SystemExit(
        "❌ Do NOT run DB strategies directly.\n"
        "They must be started by execution service."
    )
