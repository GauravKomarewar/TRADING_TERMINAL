"""
BROKER INTERFACE (FINAL — BOT-ROUTED)
====================================

• NO direct broker calls
• Converts Engine intents → TradingBot alerts
• Single execution per cycle
• Restart-safe
• Production frozen
"""

import logging
from typing import List, Optional, Dict, Any

from shoonya_platform.execution.strategy_intent import Intent
from shoonya_platform.utils.json_builder import (
    build_leg,
    build_strategy_json,
)

logger = logging.getLogger(__name__)


class Broker:
    def __init__(
        self,
        *,
        bot,                     # ✅ ShoonyaBot instance
        exchange: str,
        symbol: str,
        expiry: str,
        product_type: str = "M",
        test_mode: bool = False,
    ):
        self.bot = bot
        self.exchange = exchange
        self.symbol = symbol
        self.expiry = expiry
        self.product_type = product_type
        self.test_mode = test_mode

        # REQUIRED by Engine
        self.strategy_name = f"{symbol}_{expiry}"
        self.underlying = symbol

    # -------------------------------------------------
    # ENGINE → BROKER
    # -------------------------------------------------
    def send(self, intents: List[Intent]) -> Optional[Dict[str, Any]]:
        """
        Send intents to TradingBot.

        MUST return full execution result dict.
        Engine decides how to react.
        """
        if not intents:
            return None

        # -------------------------------------------------
        # 1️⃣ Resolve execution_type ONCE
        # -------------------------------------------------
        first_tag = intents[0].tag.upper()

        if first_tag.startswith("ENTRY"):
            execution_type = "entry"
        elif first_tag.startswith("EXIT"):
            execution_type = "exit"
        else:
            raise RuntimeError(f"Unknown intent tag: {first_tag}")

        # -------------------------------------------------
        # 2️⃣ Build legs from ALL intents
        # -------------------------------------------------
        legs = []

        for intent in intents:
            logger.info(
                f"📤 BROKER → BOT | {intent.action} {intent.symbol} x{intent.qty} | {intent.tag}"
            )

            legs.append(
                build_leg(
                    tradingsymbol=intent.symbol,
                    direction=intent.action,
                    order_type="LIMIT" if intent.order_type == "LMT" else "MARKET",
                    qty=intent.qty,
                    price=intent.price,
                )
            )

        # -------------------------------------------------
        # 3️⃣ Build webhook JSON (PineScript exact)
        # -------------------------------------------------
        payload = build_strategy_json(
            secret_key=self.bot.config.webhook_secret,
            execution_type=execution_type,
            strategy_name=self.strategy_name,
            exchange=self.exchange,
            underlying=self.underlying,
            expiry=self._format_expiry(self.expiry),
            product_type=self.product_type,
            legs=legs,
        )

        # -------------------------------------------------
        # 4️⃣ Route to TradingBot (AUTHORITATIVE)
        # -------------------------------------------------
        try:
            result = self.bot.process_alert(payload)
            logger.info(f"✅ BOT EXECUTION RESULT | {result}")
            return result
        except Exception as e:
            logger.exception(f"❌ BOT EXECUTION FAILED: {e}")
            return None

    # -------------------------------------------------
    # INTERNAL
    # -------------------------------------------------

    @staticmethod
    def _format_expiry(expiry: str) -> str:
        """
        Convert '27-Jan-2026' → '27JAN26'
        """
        from datetime import datetime

        return datetime.strptime(expiry, "%d-%b-%Y").strftime("%d%b%y").upper()
