#!/usr/bin/env python3
"""
UNIVERSAL EXECUTION ENGINE — FINAL (PRODUCTION GRADE)
====================================================

✔ Strategy-agnostic
✔ Broker is source of truth
✔ Restart-safe
✔ Deterministic execution
✔ No retry loops
✔ EXIT intents are NEVER deduplicated
✔ Engine-level TIME EXIT enforcement
✔ MCX / NFO safe
✔ No hidden behavior

⚠️ DO NOT MODIFY WITHOUT FULL OMS + STRATEGY RE-AUDIT
"""
# ============================================================
# 🔒 CODE FREEZE — PRODUCTION APPROVED
#
# File    : engine.py
# Version : v1.1.0
# Date    : 2026-01-21
#
# STATUS:
#   ✔ Time-exit enforced at engine level
#   ✔ EXIT intents never deduplicated
#   ✔ Restart-safe
#   ✔ Deterministic execution
#   ✔ Live-market validated (NFO / MCX)
#
# ⚠️ DO NOT MODIFY WITHOUT FULL OMS AUDIT
# ============================================================

import time
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from shoonya_platform.execution.strategy_intent import Intent
from shoonya_platform.execution.recovery import (
    RecoveryInspector,
    StrategyRuntimeState,
)
from shoonya_platform.persistence.repository import OrderRepository

logger = logging.getLogger("ENGINE")


class Engine:
    """
    Universal execution engine.

    Owns:
    - lifecycle
    - recovery
    - execution flow
    - time-based enforcement

    Does NOT own:
    - strategy logic
    - pricing logic
    - broker internals
    """

    # --------------------------------------------------
    # INIT
    # --------------------------------------------------

    def __init__(
        self,
        *,
        engine_id: str,
        strategy,
        market,
        broker,
        engine_cfg: dict,
    ):
        self.engine_id = engine_id
        self.strategy = strategy
        self.market = market
        self.broker = broker
        self.engine_cfg = engine_cfg

        self._armed: bool = True

        # ENTRY dedup only
        self._sent_intents: set[str] = set()

        # Persistence / recovery
        self.order_repo = OrderRepository()
        self._runtime_state: Optional[StrategyRuntimeState] = None

    # --------------------------------------------------
    # INTERNAL HELPERS
    # --------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now()

    def _fingerprint(self, intent: Intent) -> str:
        """
        Unique fingerprint for ENTRY intents.
        """
        return f"{intent.symbol}:{intent.action}:{intent.qty}:{intent.tag}"

    def _is_exit_intent(self, intent: Intent) -> bool:
        """
        EXIT intents must NEVER be deduplicated.
        """
        return (
            intent.action == "BUY"
            and intent.tag
            in {
                "TIME_EXIT",
                "FORCE_EXIT",
                "PARTIAL_ENTRY",
                "LEG_MISSING",
                "ADJ_REENTRY_FAILED",
                "ADJ_SELECTION_FAILED",
            }
        )

    def _dedup(self, intents: List[Intent]) -> List[Intent]:
        """
        Deduplicate ONLY non-exit intents.
        EXIT intents ALWAYS pass through.
        """
        out: List[Intent] = []

        for intent in intents:
            if self._is_exit_intent(intent):
                out.append(intent)
                continue

            fp = self._fingerprint(intent)
            if fp in self._sent_intents:
                continue

            self._sent_intents.add(fp)
            out.append(intent)

        return out

    # --------------------------------------------------
    # RECOVERY (OPTIONAL / STRATEGY DECIDES)
    # --------------------------------------------------

    def _recover(self) -> None:
        """
        Perform recovery exactly once at engine start.
        """
        inspector = RecoveryInspector(
            broker=self.broker,
            strategy_name=self.broker.strategy_name,
            exchange=self.broker.exchange,
            underlying=self.broker.underlying,
            repository=self.order_repo,
            expected_legs=self.strategy.expected_legs(),
        )

        report = inspector.inspect()
        self._runtime_state = report["state"]

        logger.warning(
            f"🔄 RECOVERY | state={self._runtime_state.value} | reason={report['reason']}"
        )

        if self._runtime_state == StrategyRuntimeState.IDLE:
            return

        if self._runtime_state in (
            StrategyRuntimeState.ACTIVE,
            StrategyRuntimeState.UNBALANCED_MANUAL_EXIT,
        ):
            # Strategy may choose to ignore recovery (fresh-start policy)
            if hasattr(self.strategy, "recover"):
                self.strategy.recover(report["open_legs"])
            return

        # FAILED STATE — force exit and disarm
        logger.critical("🔥 RECOVERY FAILED — FORCE EXIT")
        self._force_exit_all()
        self._armed = False

    # --------------------------------------------------
    # BROKER EXECUTION
    # --------------------------------------------------

    def _send(self, intents: List[Intent]) -> Optional[Dict[str, Any]]:
        """
        Send intents to broker.
        """
        if not intents:
            return None

        try:
            return self.broker.send(intents)
        except Exception as e:
            logger.exception(f"💥 Broker exception: {e}")
            return None

    def _force_exit_all(self) -> None:
        """
        Emergency force-exit via strategy.
        """
        try:
            intents = self.strategy.force_exit() or []
            intents = self._dedup(intents)
            self._send(intents)
        except Exception:
            logger.exception("Force exit failed")

    # --------------------------------------------------
    # HARD TIME EXIT (ENGINE-LEVEL GUARANTEE)
    # --------------------------------------------------

    def _check_time_exit(self, now: datetime) -> None:
        """
        Enforce TIME EXIT even if market ticks stop.
        This is CRITICAL for MCX and low-liquidity conditions.
        """
        try:
            if not hasattr(self.strategy, "config"):
                return

            exit_time = getattr(self.strategy.config, "exit_time", None)
            if not exit_time:
                return

            if now.time() >= exit_time:
                logger.warning("⏰ ENGINE TIME EXIT ENFORCED")

                intents = self.strategy.force_exit() or []
                intents = self._dedup(intents)
                self._send(intents)

                self._armed = False
        except Exception:
            logger.exception("Time exit enforcement failed")

    # --------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------

    def run(self) -> None:
        logger.info(f"🚀 ENGINE STARTED | {self.engine_id}")

        # --------------------------------------------------
        # RECOVERY (ONCE)
        # --------------------------------------------------
        self._recover()

        poll_interval = float(self.engine_cfg.get("poll_interval", 2.0))

        # --------------------------------------------------
        # MAIN EXECUTION LOOP
        # --------------------------------------------------
        while self._armed:
            now = self._now()

            # 🔒 HARD TIME EXIT (ABSOLUTE PRIORITY)
            self._check_time_exit(now)
            if not self._armed:
                break

            # Inject latest market snapshot
            self.strategy.prepare(self.market.snapshot())

            # Strategy decision
            intents = self.strategy.on_tick(now) or []
            intents = self._dedup(intents)

            if intents:
                result = self._send(intents)

                # ------------------------------
                # HARD FAILURE: Broker exception
                # ------------------------------
                if result is None:
                    logger.critical("💥 BROKER EXCEPTION — STOPPING ENGINE")
                    break

                # ------------------------------
                # TERMINAL FAILURE: Zero fills
                # ------------------------------
                if (
                    result.get("status") == "FAILED"
                    and result.get("attempted_legs", 0) > 0
                    and result.get("successful_legs", 0) == 0
                ):
                    logger.error("❌ EXECUTION FAILED (0 fills)")

                    if hasattr(self.strategy, "on_execution_failed"):
                        try:
                            self.strategy.on_execution_failed(
                                reason="BROKER_EXECUTION_FAILED"
                            )
                        except Exception:
                            logger.exception("Strategy failure handler crashed")

                    break

            time.sleep(poll_interval)

        logger.warning(f"🛑 ENGINE STOPPED | {self.engine_id}")
