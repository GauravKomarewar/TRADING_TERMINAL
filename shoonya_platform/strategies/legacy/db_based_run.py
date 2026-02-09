#!/usr/bin/env python3
"""
STRATEGY ENTRYPOINT — DB BACKED (PRODUCTION)
===========================================

• Expiry resolved ONCE (authoritative)
• Uses SQLite-backed option-chain snapshots
• NO live feeds
• Supervisor must be running
• Restart-safe
• No re-entry after exit
• Engine controls lifecycle

⚠️ SAFE PARALLEL RUNNER
⚠️ Does NOT modify run.py (frozen)
"""

import sys
import time
from shoonya_platform.logging.logger_config import get_component_logger
import importlib
from datetime import datetime, date
from pathlib import Path

import pandas as pd

from shoonya_platform.core.config import Config
from shoonya_platform.execution.engine import Engine
from shoonya_platform.execution.db_market import DBBackedMarket
from shoonya_platform.execution.broker import Broker
# Broker client is provided by the ShoonyaBot (bot.api_proxy)
from shoonya_platform.market_data.instruments.instruments import get_fno_details
from scripts.scriptmaster import refresh_scriptmaster, options_expiry
from shoonya_platform.strategies.delta_neutral.dnss import (
    DeltaNeutralShortStrangleStrategy,
)
from shoonya_platform.execution.trading_bot import ShoonyaBot

bot = ShoonyaBot()

logger = get_component_logger('execution_service')


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main(config_path: str, api_client=None):
    # -------------------------------------------------
    # LOAD CONFIG (IDENTICAL)
    # -------------------------------------------------
    cfg = importlib.import_module(
        f"shoonya_platform.strategies.{config_path}"
    )

    STRATEGY_NAME = cfg.STRATEGY_NAME
    META = cfg.META
    STRATEGY_CONFIG = cfg.CONFIG
    ENGINE_CFG = cfg.ENGINE

    # -------------------------------------------------
    # BOOTSTRAP (LOGIN ONLY) - use injected api_client or bot.api_proxy
    # -------------------------------------------------
    api = api_client or bot.api_proxy

    refresh_scriptmaster()

    # -------------------------------------------------
    # FNO DETAILS (SINGLE SOURCE)
    # -------------------------------------------------
    fno = get_fno_details(
        api_client=api,
        exchange=META["exchange"],
        symbol=META["symbol"],
    )

    lot_size = int(fno["fut_lot_size"])

    # -------------------------------------------------
    # EXPIRY RESOLUTION (IDENTICAL LOGIC)
    # -------------------------------------------------
    if getattr(STRATEGY_CONFIG, "expiry", None):
        expiry = STRATEGY_CONFIG.expiry
        logger.info(f"📌 Using FIXED expiry from config: {expiry}")

    else:
        expiry = fno["option_expiry"]
        today = date.today()

        expiry_date = pd.to_datetime(expiry, format="%d-%b-%Y").date()
        if expiry_date == today:
            expiries = options_expiry(
                META["symbol"],
                META["exchange"],
            )

            parsed = []
            for e in expiries:
                d = pd.to_datetime(e, format="%d-%b-%Y").date()
                if d > today:
                    parsed.append(d)

            if not parsed:
                raise RuntimeError("No future expiry available")

            parsed.sort()
            expiry = parsed[0].strftime("%d-%b-%Y")

            logger.warning(
                f"⚠️ Expiry day detected | rolled to {expiry}"
            )

    logger.info(
        f"📦 Contract resolved | symbol={META['symbol']} "
        f"| expiry={expiry} | lot_size={lot_size}"
    )

    # -------------------------------------------------
    # DB-BACKED MARKET (KEY CHANGE)
    # -------------------------------------------------
    db_path = (
        Path(__file__).resolve().parents[1]
        / "market_data"
        / "option_chain"
        / "data"
        / f"{META['exchange']}_{META['symbol']}_{expiry}.sqlite"
    )

    if not db_path.exists():
        raise RuntimeError(
            f"Option-chain DB not found: {db_path}"
        )

    market = DBBackedMarket(
        db_path=str(db_path),
        exchange=META["exchange"],
        symbol=META["symbol"],
    )

    logger.info("📊 Using DB-backed market source")

    # -------------------------------------------------
    # STRATEGY (UNCHANGED)
    # -------------------------------------------------
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=META["exchange"],
        symbol=META["symbol"],
        expiry=expiry,
        lot_qty=lot_size,
        get_option_func=market.get_nearest_option,  # 🔑 DB-native selector
        config=STRATEGY_CONFIG,
    )

    # -------------------------------------------------
    # BROKER (UNCHANGED)
    # -------------------------------------------------
    broker = Broker(
        bot=bot,
        exchange=META["exchange"],
        symbol=META["symbol"],
        expiry=expiry,
        product_type="M",
    )

    # -------------------------------------------------
    # ENGINE (UNCHANGED)
    # -------------------------------------------------
    ENGINE_ID = f"{STRATEGY_NAME}_DB_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    engine = Engine(
        engine_id=ENGINE_ID,
        strategy=strategy,
        market=market,
        broker=broker,
        engine_cfg=ENGINE_CFG,
    )

    logger.info(f"🚀 Starting DB-backed strategy: {STRATEGY_NAME}")
    engine.run()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m shoonya_platform.strategies.run_db <strategy_config_path>"
        )

    main(sys.argv[1])
