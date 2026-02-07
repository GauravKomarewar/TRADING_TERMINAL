#!/usr/bin/env python3
"""
STRATEGY ENTRYPOINT — FINAL (FROZEN)
===================================

• Expiry resolved ONCE (authoritative)
• Config expiry override supported
• live_option_chain created ONCE
• Expiry consistency enforced
• Restart-safe
• No re-entry after exit
• Engine controls lifecycle

# ⚠️ FROZEN FILE
# Any modification REQUIRES full expiry + lifecycle review

"""

import sys
import time
import logging
import importlib
from datetime import datetime, date

import pandas as pd

from shoonya_platform.core.config import Config
from shoonya_platform.execution.engine import Engine
from shoonya_platform.execution.market import LiveMarket
from shoonya_platform.execution.broker import Broker
from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.market_data.instruments.instruments import get_fno_details
from shoonya_platform.market_data.option_chain.option_chain import live_option_chain, get_nearest_greek_option
from scripts.scriptmaster import refresh_scriptmaster,options_expiry
from shoonya_platform.strategies.delta_neutral.dnss import DeltaNeutralShortStrangleStrategy
from shoonya_platform.execution.trading_bot import ShoonyaBot
bot = ShoonyaBot()

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------
logger = logging.getLogger("STRATEGY_RUNNER")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main(config_path: str):
    # -------------------------------------------------
    # LOAD CONFIG
    # -------------------------------------------------
    cfg = importlib.import_module(
        f"shoonya_platform.strategies.{config_path}"
    )

    STRATEGY_NAME = cfg.STRATEGY_NAME
    META = cfg.META
    STRATEGY_CONFIG = cfg.CONFIG
    ENGINE_CFG = cfg.ENGINE

    # -------------------------------------------------
    # BOOTSTRAP (ONCE)
    # -------------------------------------------------
    sys_cfg = Config()
    api = ShoonyaClient(sys_cfg)
    api.login()

    # -------------------------------------------------
    # SCRIPTMASTER (AUTHORITATIVE)
    # -------------------------------------------------
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
    # EXPIRY RESOLUTION (FROZEN LOGIC)
    # -------------------------------------------------
    if getattr(STRATEGY_CONFIG, "expiry", None):
        expiry = STRATEGY_CONFIG.expiry
        logger.info(f"📌 Using FIXED expiry from config: {expiry}")

    else:
        expiry = fno["option_expiry"]
        today = date.today()

        try:
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
                rolled = parsed[0].strftime("%d-%b-%Y")

                logger.warning(
                    f"⚠️ Expiry day detected | rolling {expiry} → {rolled}"
                )
                expiry = rolled

        except Exception as e:
            raise RuntimeError(f"Expiry resolution failed: {e}")

    logger.info(
        f"📦 Contract resolved | symbol={META['symbol']} "
        f"| expiry={expiry} | lot_size={lot_size}"
    )

    # -------------------------------------------------
    # LIVE OPTION CHAIN (ONCE ONLY)
    # -------------------------------------------------
    logger.info("📡 Initializing live option chain")

    while True:
        try:
            option_chain = live_option_chain(
                api_client=api,
                exchange=META["exchange"],
                symbol=META["symbol"],
                expiry=expiry,          # 🔒 LOCKED
                count=10,
                with_greeks=True,
            )
            break
        except Exception as e:
            logger.warning(f"⚠️ Option chain not ready: {e}")
            time.sleep(15)

    stats = option_chain.get_stats()
    chain_expiry = stats.get("expiry")

    if chain_expiry != expiry:
        raise RuntimeError(
            f"🔥 EXPIRY MISMATCH | locked={expiry} chain={chain_expiry}"
        )

    logger.info("✅ Live option chain ACTIVE (single instance)")

    # -------------------------------------------------
    # MARKET WRAPPER
    # -------------------------------------------------
    market = LiveMarket(option_chain=option_chain)

    logger.info("⏳ Waiting 10s for greeks warm-up")
    time.sleep(10)

    greeks = option_chain.get_greeks()
    if greeks is None or greeks.empty:
        logger.warning("⚠️ Greeks not ready after warm-up — strategy will wait")
    else:
        logger.info(
            f"📊 Greeks ready | rows={len(greeks)} | "
            f"expiries={greeks['expiry'].unique() if 'expiry' in greeks else 'N/A'}"
        )

    # -------------------------------------------------
    # STRATEGY
    # -------------------------------------------------
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=META["exchange"],
        symbol=META["symbol"],
        expiry=expiry,
        lot_qty=lot_size,
        get_option_func=lambda df, greek, target, opt_type: get_nearest_greek_option(
            df=df,
            greek=greek,
            target_value=target,
            option_type=opt_type,
        ),
        config=STRATEGY_CONFIG,
    )

    # -------------------------------------------------
    # BROKER
    # -------------------------------------------------
    broker = Broker(
        bot=bot,                               # ✅ REQUIRED
        exchange=META["exchange"],
        symbol=META["symbol"],
        expiry=expiry,
        product_type="M",
    )


    # -------------------------------------------------
    # ENGINE
    # -------------------------------------------------
    ENGINE_ID = f"{STRATEGY_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    engine = Engine(
        engine_id=ENGINE_ID,
        strategy=strategy,
        market=market,
        broker=broker,
        engine_cfg=ENGINE_CFG,
    )

    logger.info(f"🚀 Starting strategy: {STRATEGY_NAME}")
    engine.run()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m shoonya_platform.strategies.run <strategy_config_path>"
        )

    main(sys.argv[1])
