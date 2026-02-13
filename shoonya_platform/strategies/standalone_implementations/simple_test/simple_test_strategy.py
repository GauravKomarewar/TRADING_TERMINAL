#!/usr/bin/env python3
"""
SIMPLE TEST STRATEGY
====================
A minimal strategy for testing the execution pipeline end-to-end.

Lifecycle (time-driven, no fill dependency):
    IDLE → ENTERED → ADJUSTED → EXITED

Flow:
    1. At entry_time: Find CE+PE at target_delta (0.3), short both (1 lot = 65 qty)
    2. After 60s: Close the most profitable leg, re-short same type at target_delta
    3. After another 60s: Exit all legs
    4. At exit_time: Force exit if still holding

Compatible with:
    - StrategyRunner (prepare + on_tick interface)
    - strategy_factory (config dict constructor)
    - Dashboard start/stop controls
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from typing import List, Optional, Dict, Any, Literal

from shoonya_platform.execution.intent import UniversalOrderCommand

logger = logging.getLogger("STRATEGY.SIMPLE_TEST")


# ============================================================
# STRATEGY
# ============================================================

class SimpleTestStrategy:
    """
    Simple test strategy: entry → hold 1min → adjust → hold 1min → exit.

    Accepts flat factory config dict from strategy_factory.create_strategy().
    """

    def __init__(self, config: dict):
        # ── Identity ──
        self.exchange = config.get("exchange", "NFO")
        self.symbol = config.get("symbol", "NIFTY")
        self.order_type = config.get("order_type", "MARKET")
        self.product = config.get("product", "NRML")
        self.strategy_name = config.get("strategy_name", f"{self.symbol}_SIMPLE_TEST")

        # ── Quantity ──
        # lot_qty from config is "lots count" — multiply by lot_size for actual qty
        params = config.get("params", {}) or {}
        lots = int(config.get("lot_qty", 1))
        lot_size = int(params.get("lot_size", 65))  # NIFTY = 65
        self.lot_qty = lots * lot_size

        # ── Timing ──
        self.entry_time = self._parse_time(config.get("entry_time", "09:16"))
        self.exit_time = self._parse_time(config.get("exit_time", "15:29"))
        entry_end = config.get("entry_end_time") or params.get("entry_end_time", "15:28")
        self.entry_end_time = self._parse_time(entry_end)

        # ── Strategy params ──
        self.target_delta = float(params.get("target_entry_delta", 0.3))
        self.adjust_wait = int(params.get("adjust_wait_seconds", 60))
        self.exit_wait = int(params.get("exit_wait_seconds", 60))

        # ── Market config ──
        mc = config.get("market_config", {}) or {}
        self.db_path = mc.get("db_path")

        # ── State ──
        self.phase: Literal[
            "IDLE", "ENTERED", "ADJUSTED", "EXITED"
        ] = "IDLE"
        self.option_chain: list = []
        self.spot_price: Optional[float] = None

        # Leg tracking: {symbol, entry_ltp, option_type}
        self.ce_leg: Optional[dict] = None
        self.pe_leg: Optional[dict] = None

        self.entry_timestamp: Optional[datetime] = None
        self.adjust_timestamp: Optional[datetime] = None

        logger.info(
            f"SimpleTestStrategy init | {self.exchange}:{self.symbol} | "
            f"qty={self.lot_qty} | delta={self.target_delta} | "
            f"entry={self.entry_time} exit={self.exit_time}"
        )

    # ================================================================
    # ENGINE CONTRACT
    # ================================================================

    def prepare(self, market: dict) -> None:
        """Store latest market snapshot for option lookup."""
        if not market:
            return
        if "option_chain" in market:
            self.option_chain = market.get("option_chain", [])
            self.spot_price = market.get("spot_price") or market.get("spot")
        elif "greeks" in market:
            # Legacy format
            self.option_chain = []
            self.spot_price = market.get("spot")

    def on_tick(self, now: datetime) -> List[UniversalOrderCommand]:
        """
        Main strategy loop — phase-based state machine.

        Returns list of UniversalOrderCommand for OMS routing.
        """
        if self.phase == "EXITED":
            return []

        # ── FORCE EXIT at exit time ──
        if now.time() >= self.exit_time:
            logger.warning(f"TIME EXIT at {now.time()}")
            return self._exit_all("TIME_EXIT")

        # ── Before entry window ──
        if now.time() < self.entry_time:
            return []

        # ── Past entry end time — don't open new ──
        if self.phase == "IDLE" and now.time() > self.entry_end_time:
            return []

        # ── PHASE: IDLE → ENTRY ──
        if self.phase == "IDLE":
            return self._do_entry(now)

        # ── PHASE: ENTERED → wait adjust_wait seconds → ADJUST ──
        if self.phase == "ENTERED" and self.entry_timestamp:
            elapsed = (now - self.entry_timestamp).total_seconds()
            if elapsed >= self.adjust_wait:
                return self._do_adjust(now)
            logger.debug(f"HOLDING entry — {elapsed:.0f}s / {self.adjust_wait}s")
            return []

        # ── PHASE: ADJUSTED → wait exit_wait seconds → EXIT ALL ──
        if self.phase == "ADJUSTED" and self.adjust_timestamp:
            elapsed = (now - self.adjust_timestamp).total_seconds()
            if elapsed >= self.exit_wait:
                return self._exit_all("PLANNED_EXIT")
            logger.debug(f"HOLDING adjusted — {elapsed:.0f}s / {self.exit_wait}s")
            return []

        return []

    def force_exit(self) -> List[UniversalOrderCommand]:
        """Engine-level forced exit."""
        return self._exit_all("FORCE_EXIT")

    def is_active(self) -> bool:
        return self.phase not in ("IDLE", "EXITED")

    def expected_legs(self) -> int:
        count = 0
        if self.ce_leg:
            count += 1
        if self.pe_leg:
            count += 1
        return count

    def get_status(self) -> dict:
        return {
            "state": self.phase,
            "strategy_name": self.strategy_name,
            "ce_leg": self.ce_leg,
            "pe_leg": self.pe_leg,
            "entry_timestamp": (
                self.entry_timestamp.isoformat() if self.entry_timestamp else None
            ),
            "adjust_timestamp": (
                self.adjust_timestamp.isoformat() if self.adjust_timestamp else None
            ),
        }

    # ── Optional callbacks (kept for interface compat) ──

    def on_fill(self, *, symbol, side, price, qty, delta):
        logger.info(f"FILL: {side} {symbol} @ {price} qty={qty}")
        return []

    def on_execution_failed(self, reason: str):
        logger.error(f"Execution failed: {reason}")

    def serialize_state(self) -> dict:
        return self.get_status()

    def restore_state(self, state_dict: dict):
        pass

    # ================================================================
    # ENTRY
    # ================================================================

    def _do_entry(self, now: datetime) -> List[UniversalOrderCommand]:
        """Find CE+PE at target delta, sell both."""
        if not self.option_chain:
            logger.warning("No option chain data — cannot enter")
            return []

        ce_opt = self._find_nearest_delta(self.option_chain, self.target_delta, "CE")
        pe_opt = self._find_nearest_delta(self.option_chain, self.target_delta, "PE")

        if not ce_opt or not pe_opt:
            logger.error("Could not find CE/PE at target delta — skipping entry")
            return []

        ce_sym = ce_opt.get("trading_symbol", "")
        pe_sym = pe_opt.get("trading_symbol", "")
        ce_ltp = float(ce_opt.get("ltp", 0))
        pe_ltp = float(pe_opt.get("ltp", 0))

        logger.info(
            f"ENTRY | CE={ce_sym} (delta={ce_opt.get('delta')}, LTP={ce_ltp}) | "
            f"PE={pe_sym} (delta={pe_opt.get('delta')}, LTP={pe_ltp})"
        )

        self.ce_leg = {"symbol": ce_sym, "entry_ltp": ce_ltp, "option_type": "CE"}
        self.pe_leg = {"symbol": pe_sym, "entry_ltp": pe_ltp, "option_type": "PE"}
        self.entry_timestamp = now
        self.phase = "ENTERED"

        return [
            self._cmd(side="SELL", symbol=ce_sym, tag="ENTRY_CE", ltp=ce_ltp),
            self._cmd(side="SELL", symbol=pe_sym, tag="ENTRY_PE", ltp=pe_ltp),
        ]

    # ================================================================
    # ADJUST — close max-profitable leg, re-short same type
    # ================================================================

    def _do_adjust(self, now: datetime) -> List[UniversalOrderCommand]:
        """Close the most profitable leg and re-short same option type at target delta."""
        if not self.ce_leg or not self.pe_leg:
            logger.warning("Missing legs — skipping adjustment")
            self.phase = "ADJUSTED"
            self.adjust_timestamp = now
            return []

        if not self.option_chain:
            logger.warning("No option chain — skipping adjustment")
            self.phase = "ADJUSTED"
            self.adjust_timestamp = now
            return []

        # Current prices
        ce_now = self._get_current_ltp(self.ce_leg["symbol"])
        pe_now = self._get_current_ltp(self.pe_leg["symbol"])

        # Short PnL = (entry_price - current_price) × qty
        ce_pnl = (self.ce_leg["entry_ltp"] - (ce_now or self.ce_leg["entry_ltp"])) * self.lot_qty
        pe_pnl = (self.pe_leg["entry_ltp"] - (pe_now or self.pe_leg["entry_ltp"])) * self.lot_qty

        logger.info(f"ADJUST check | CE PnL={ce_pnl:.2f}, PE PnL={pe_pnl:.2f}")

        # Close the MORE profitable leg
        if ce_pnl >= pe_pnl:
            close_leg = self.ce_leg
            close_ltp = ce_now or self.ce_leg["entry_ltp"]
        else:
            close_leg = self.pe_leg
            close_ltp = pe_now or self.pe_leg["entry_ltp"]

        close_type = close_leg["option_type"]

        # Find new option of same type at target delta
        new_opt = self._find_nearest_delta(self.option_chain, self.target_delta, close_type)
        if not new_opt:
            logger.error(f"No new {close_type} option found — skipping re-short")
            self.phase = "ADJUSTED"
            self.adjust_timestamp = now
            return []

        new_sym = new_opt.get("trading_symbol", "")
        new_ltp = float(new_opt.get("ltp", 0))

        logger.info(
            f"ADJUST | Close {close_type}={close_leg['symbol']} (BUY @ {close_ltp:.2f}) | "
            f"New {close_type}={new_sym} (SELL @ {new_ltp:.2f}, delta={new_opt.get('delta')})"
        )

        # Update leg
        if close_type == "CE":
            self.ce_leg = {"symbol": new_sym, "entry_ltp": new_ltp, "option_type": "CE"}
        else:
            self.pe_leg = {"symbol": new_sym, "entry_ltp": new_ltp, "option_type": "PE"}

        self.adjust_timestamp = now
        self.phase = "ADJUSTED"

        return [
            self._cmd(side="BUY", symbol=close_leg["symbol"], tag=f"ADJ_CLOSE_{close_type}", ltp=close_ltp),
            self._cmd(side="SELL", symbol=new_sym, tag=f"ADJ_NEW_{close_type}", ltp=new_ltp),
        ]

    # ================================================================
    # EXIT ALL
    # ================================================================

    def _exit_all(self, reason: str) -> List[UniversalOrderCommand]:
        """Buy back all open legs."""
        commands = []

        if self.ce_leg:
            ltp = self._get_current_ltp(self.ce_leg["symbol"])
            commands.append(self._cmd(
                side="BUY", symbol=self.ce_leg["symbol"],
                tag=reason, ltp=ltp,
            ))
            logger.info(f"EXIT CE: {self.ce_leg['symbol']} reason={reason}")

        if self.pe_leg:
            ltp = self._get_current_ltp(self.pe_leg["symbol"])
            commands.append(self._cmd(
                side="BUY", symbol=self.pe_leg["symbol"],
                tag=reason, ltp=ltp,
            ))
            logger.info(f"EXIT PE: {self.pe_leg['symbol']} reason={reason}")

        self.phase = "EXITED"
        self.ce_leg = None
        self.pe_leg = None

        return commands

    # ================================================================
    # HELPERS
    # ================================================================

    def _find_nearest_delta(
        self, chain: list, target_delta: float, option_type: str,
    ) -> Optional[dict]:
        """Find the option closest to target_delta (absolute) for given option_type."""
        candidates = [r for r in chain if r.get("option_type") == option_type]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda r: abs(abs(float(r.get("delta", 0))) - target_delta),
        )

    def _get_current_ltp(self, trading_symbol: str) -> Optional[float]:
        """Lookup current LTP from the cached option chain."""
        for row in self.option_chain:
            if row.get("trading_symbol") == trading_symbol:
                return float(row.get("ltp", 0))
        return None

    def _cmd(
        self, *, side: str, symbol: str, tag: str, ltp: Optional[float] = None,
    ) -> UniversalOrderCommand:
        """Create a UniversalOrderCommand."""
        price = None
        if self.order_type == "LIMIT" and ltp and ltp > 0:
            price = ltp

        return UniversalOrderCommand.new(
            source="STRATEGY",
            user=self.symbol,
            exchange=self.exchange,
            symbol=symbol,
            quantity=self.lot_qty,
            side=side,
            product=self.product,
            order_type=self.order_type,
            price=price,
            strategy_name=self.strategy_name,
            comment=tag,
        )

    @staticmethod
    def _parse_time(val) -> dt_time:
        if isinstance(val, dt_time):
            return val
        if isinstance(val, str):
            parts = val.split(":")
            return dt_time(
                int(parts[0]),
                int(parts[1]),
                int(parts[2]) if len(parts) > 2 else 0,
            )
        return val
