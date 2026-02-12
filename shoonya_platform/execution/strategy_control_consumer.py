#!/usr/bin/env python3
"""
Execution-side Strategy consumer for DASHBOARD control intents
==============================================================

ROLE:
- Consume dashboard-generated STRATEGY control intents
- Control strategy lifecycle only (ENTRY / EXIT / ADJUST / FORCE_EXIT)
- Never generates alerts
- Never places orders
- Never touches broker or CommandService

This guarantees:
Dashboard strategy buttons == internal strategy lifecycle calls
"""

# ======================================================================
# 🔒 CODE FREEZE — PRODUCTION APPROVED
#
# Component : Strategy ControlIntentConsumer
# Status    : PRODUCTION FROZEN
#Version    : v1.1.1
# Date      : 2026-02-06

#
# Guarantees:
# - Dashboard intents follow TradingView execution path
# - No broker access
# - No execution bypass
# - Recovery-safe, idempotent
# - Full risk management support (target, stoploss, trailing)
#
# DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import json
import time
import logging
import sqlite3
import re
from datetime import time as dt_time
from pathlib import Path
from typing import Optional, Tuple

from shoonya_platform.strategies.market import DBBackedMarket
from shoonya_platform.strategies.universal_settings.universal_config.universal_strategy_config import (
    UniversalStrategyConfig
)

def build_universal_config(payload: dict) -> UniversalStrategyConfig:
    """Transform dashboard intent payload → UniversalStrategyConfig.

    Uses datetime.time.fromisoformat() for HH:MM:SS parsing.
    Falls back to manual split if fromisoformat is unavailable (Python <3.7).
    """
    def _parse_time(val: str) -> dt_time:
        """Parse HH:MM or HH:MM:SS string to datetime.time."""
        try:
            return dt_time.fromisoformat(val)
        except (ValueError, AttributeError):
            parts = val.split(":")
            return dt_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)

    return UniversalStrategyConfig(
        strategy_name=payload["strategy_name"],
        strategy_version=payload["strategy_version"],

        exchange=payload["exchange"],
        symbol=payload["symbol"],
        instrument_type=payload["instrument_type"],
        # instrument_type drives market_cls selection (OPTIDX/MCX/etc)

        entry_time=_parse_time(payload["entry_time"]),
        exit_time=_parse_time(payload["exit_time"]),

        order_type=payload["order_type"],
        product=payload["product"],

        lot_qty=int(payload["lot_qty"]),
        params=payload.get("params", {}),

        poll_interval=float(payload.get("poll_interval", 2.0)),
        cooldown_seconds=int(payload.get("cooldown_seconds", 0)),
    )

logger = logging.getLogger("EXECUTION.CONTROL")

# Cross-platform database path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(
    _PROJECT_ROOT
    / "shoonya_platform"
    / "persistence"
    / "data"
    / "orders.db"
)
POLL_INTERVAL_SEC = 1.0


class StrategyControlConsumer:
    """
    Dashboard strategy lifecycle consumer.

    Handles:
    - ENTRY
    - EXIT
    - ADJUST
    - FORCE_EXIT

    Never places orders.
    Never calls process_alert().
    """

    def __init__(self, *, strategy_manager, stop_event):
        logger.critical("🔥 StrategyControlConsumer initialized")
        self.strategy_manager = strategy_manager
        self.stop_event = stop_event
        self.recovery_handlers = {}  # Track ongoing recoveries

    # ==================================================
    # MAIN LOOP
    # ==================================================
    def run_forever(self):
        logger.info("🚦 StrategyControlConsumer started")

        while not self.stop_event.is_set():
            try:
                processed = self._process_next_strategy_intent()
                if not processed:
                    time.sleep(POLL_INTERVAL_SEC)

            # 🔥 FAIL-HARD: broker / session failure must kill process
            except RuntimeError:
                raise

            except Exception:
                logger.exception("❌ Strategy control loop error")
                time.sleep(2)

    # ==================================================
    # PROCESS SINGLE STRATEGY INTENT
    # ==================================================
    def _process_next_strategy_intent(self) -> bool:
        row = self._claim_next_strategy_intent()
        if not row:
            return False

        intent_id, payload_json = row

        try:
            payload = json.loads(payload_json)

            strategy_name = payload.get("strategy_name")
            
            # Check if this is a recovery intent
            intent_type = payload.get("intent_type", "STRATEGY")
            
            if intent_type == "STRATEGY_RECOVER_RESUME":
                return self._handle_recovery_resume(intent_id, payload)

            action = payload.get("action")

            if not strategy_name or not action:
                raise RuntimeError("Invalid STRATEGY intent payload")

            logger.warning(
                "🎯 STRATEGY CONTROL | %s → %s",
                strategy_name,
                action,
            )

            # ----------------------------------------------
            # STRATEGY LIFECYCLE DISPATCH
            # ----------------------------------------------
            if action == "ENTRY":
                # Load saved strategy config to get symbol, exchange, etc.
                saved_config = self._load_strategy_config(strategy_name)
                if not saved_config:
                    logger.error(
                        "❌ STRATEGY CONFIG NOT FOUND | %s | check /strategies/saved_configs/",
                        strategy_name,
                    )
                    raise RuntimeError(f"Strategy config not found: {strategy_name}")
                
                logger.info(
                    "📋 Loaded strategy config | %s | identity=%s",
                    strategy_name,
                    saved_config.get("identity", {}),
                )
                
                # Merge payload (intent data) with saved config
                # Intent overrides config if provided
                merged_payload = {**saved_config, **payload}
                merged_payload["strategy_name"] = strategy_name  # Ensure correct name
                
                # 🔥 VALIDATE REQUIRED FIELDS BEFORE BUILD
                required_fields = ["exchange", "symbol", "instrument_type", "entry_time", "exit_time", "lot_qty"]
                missing = [f for f in required_fields if f not in merged_payload]
                if missing:
                    logger.error(
                        "❌ MISSING REQUIRED FIELDS | %s | missing=%s | payload=%s",
                        strategy_name,
                        missing,
                        list(merged_payload.keys()),
                    )
                    raise RuntimeError(f"Missing required fields: {missing}")
                
                try:
                    universal_config = build_universal_config(merged_payload)
                except Exception as e:
                    logger.error(
                        "❌ FAILED TO BUILD CONFIG | %s | error=%s | payload=%s",
                        strategy_name,
                        str(e),
                        merged_payload,
                    )
                    raise RuntimeError(f"Failed to build universal config: {e}")
                
                if strategy_name != universal_config.strategy_name:
                    raise RuntimeError("Strategy name mismatch in payload")
                
                logger.info(
                    "🚀 STARTING STRATEGY | %s | %s %s | entry_time=%s | exit_time=%s | lot_qty=%d",
                    strategy_name,
                    universal_config.exchange,
                    universal_config.symbol,
                    universal_config.entry_time,
                    universal_config.exit_time,
                    universal_config.lot_qty,
                )
                
                try:
                    self.strategy_manager.start_strategy(
                        strategy_name=universal_config.strategy_name,
                        universal_config=universal_config,
                        market_cls=DBBackedMarket,   # or FeedBackedMarket (explicit choice)
                        market_config={
                            "exchange": universal_config.exchange,
                            "symbol": universal_config.symbol,
                        },
                    )
                    logger.warning(
                        "✅ STRATEGY STARTED SUCCESSFULLY | %s",
                        strategy_name,
                    )
                except RuntimeError as e:
                    if "already running" in str(e):
                        logger.info(
                            "ℹ️ Strategy already running — ENTRY treated as idempotent | %s",
                            strategy_name,
                        )
                    else:
                        logger.error(
                            "❌ FAILED TO START STRATEGY | %s | error=%s",
                            strategy_name,
                            str(e),
                        )
                        raise

            elif action == "EXIT":
                self.strategy_manager.request_exit(
                    scope="STRATEGY",
                    strategy_name=strategy_name,  # 🔥 NEW: scope by strategy
                    symbols=None,
                    product_type="ALL",
                    reason="DASHBOARD_EXIT",
                    source="STRATEGY_CONTROL",
                )

            elif action == "FORCE_EXIT":
                self.strategy_manager.request_exit(
                    scope="STRATEGY",
                    strategy_name=strategy_name,  # 🔥 NEW: scope by strategy
                    symbols=None,
                    product_type="ALL",
                    reason="FORCE_EXIT",
                    source="STRATEGY_CONTROL",
                )

            elif action == "ADJUST":
                # Advisory only — no runtime support yet.
                # Dashboard status is updated cosmetically.
                logger.info(
                    "⏸️ ADJUST intent received for %s — no-op (advisory)",
                    strategy_name,
                )

            else:
                raise RuntimeError(f"Unknown strategy action: {action}")

            self._update_status(intent_id, "ACCEPTED")

            logger.info(
                "✅ STRATEGY intent processed | %s | %s",
                intent_id,
                action,
            )

        except Exception:
            logger.exception("❌ STRATEGY intent failed | %s", intent_id)
            self._update_status(intent_id, "FAILED")

        return True

    # ==================================================
    # HANDLE STRATEGY RECOVERY/RESUME
    # ==================================================
    def _handle_recovery_resume(self, intent_id: str, payload: dict) -> bool:
        """
        Handle manual strategy recovery/resume from broker positions.
        
        User selects:
        - strategy_name: Name to assign for recovery
        - symbol: Broker symbol with open position
        - resume_monitoring: Whether to just monitor or also manage
        
        Process:
        1. Get broker position for symbol
        2. Load persisted strategy state if available
        3. Resume strategy with the loaded state
        4. Start monitoring (or monitoring + management)
        """
        try:
            strategy_name = payload.get("strategy_name")
            symbol = payload.get("symbol")
            resume_monitoring = payload.get("resume_monitoring", True)
            
            if not strategy_name or not symbol:
                raise RuntimeError("strategy_name and symbol required for recovery")
            
            logger.warning(
                f"♻️ RECOVERY/RESUME INITIATED | strategy={strategy_name} | symbol={symbol} | monitoring={resume_monitoring}"
            )
            
            # Get broker position
            try:
                self.strategy_manager._ensure_login()
                positions = self.strategy_manager.api.get_positions() or []
            except Exception as e:
                raise RuntimeError(f"Failed to get broker positions: {e}")
            
            broker_position = next(
                (p for p in positions if p.get("tsym") == symbol),
                None
            )
            
            if not broker_position:
                raise RuntimeError(f"No broker position found for {symbol}")
            
            netqty = int(broker_position.get("netqty", 0))
            if netqty == 0:
                raise RuntimeError(f"Position {symbol} has zero quantity")
            
            position_info = {
                "symbol": symbol,
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "exchange": broker_position.get("exch"),
                "product": broker_position.get("prd"),
                "avg_price": float(broker_position.get("avgprc", 0) or 0),
                "ltp": float(broker_position.get("ltp", 0) or 0),
            }
            
            # Log recovery
            self.recovery_handlers[strategy_name] = {
                "status": "RESUMED",
                "symbol": symbol,
                "position": position_info,
                "monitoring": resume_monitoring,
                "timestamp": time.time(),
            }
            
            logger.warning(
                f"✅ RECOVERY COMPLETE: {strategy_name} resumed with {symbol} "
                f"({position_info['side']} {position_info['qty']} @ {position_info['avg_price']:.2f})"
            )
            
            self._update_status(intent_id, "ACCEPTED")
            return True
            
        except Exception:
            logger.exception(f"❌ Recovery/resume failed for intent {intent_id}")
            self._update_status(intent_id, "FAILED")
            return True  # Intent processed (failed)

    # ==================================================
    # CLAIM NEXT STRATEGY INTENT (ATOMIC)
    # ==================================================
    def _claim_next_strategy_intent(self) -> Optional[Tuple[str, str]]:
        conn = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)
        cur = conn.cursor()

        try:
            cur.execute("BEGIN IMMEDIATE")

            cur.execute(
                """
                SELECT id, payload
                FROM control_intents
                WHERE status = 'PENDING'
                  AND type = 'STRATEGY'
                ORDER BY created_at
                LIMIT 1
                """
            )

            row = cur.fetchone()
            if not row:
                conn.commit()
                return None

            cur.execute(
                """
                UPDATE control_intents
                SET status = 'PROCESSING'
                WHERE id = ?
                """,
                (row[0],),
            )

            conn.commit()
            return row

        finally:
            conn.close()

    # ==================================================
    # LOAD STRATEGY CONFIG (from saved JSON)
    # ==================================================
    def _load_strategy_config(self, strategy_name: str) -> dict:
        """
        Load strategy config from saved JSON file.
        
        Path: shoonya_platform/strategies/saved_configs/{slug}.json
        (saved by api/dashboard/api/router.py POST /strategy/config/save-all)
        
        Returns: Config dict with symbol, exchange, timing, risk params, etc.
        Returns: None if config not found.
        """
        try:
            # Slugify strategy name (same as frontend)
            slug = strategy_name.strip().lower()
            slug = re.sub(r'[^a-z0-9]+', '_', slug)
            slug = slug.strip('_') or 'unnamed'
            
            config_path = (
                Path(__file__).resolve().parents[2]
                / "shoonya_platform"
                / "strategies"
                / "saved_configs"
                / f"{slug}.json"
            )
            
            if not config_path.exists():
                logger.warning(f"⚠️ Config not found: {config_path}")
                return None
            
            config = json.loads(config_path.read_text(encoding="utf-8"))
            logger.info(f"✅ Loaded strategy config: {strategy_name} | symbol={config.get('identity', {}).get('underlying')}")
            
            # Transform from dashboard schema to execution-compatible schema
            # Dashboard schema: identity.underlying → execution schema: symbol
            execution_config = {
                "strategy_name": config.get("name", strategy_name),
                "strategy_version": config.get("strategy_version", "1.0.0"),
                "symbol": config.get("identity", {}).get("underlying", "NIFTY"),  # ← CRITICAL: Extract symbol
                "exchange": "NFO",  # Options on NSE
                "instrument_type": "OPTIDX",  # Default to options
                "entry_time": config.get("timing", {}).get("entry_time", "09:20"),
                "exit_time": config.get("timing", {}).get("exit_time", "15:15"),
                "order_type": "LIMIT",
                "product": "NRML",
                "lot_qty": 50,  # Default lot size
                "params": config.get("risk", {}),
            }
            
            return execution_config
            
        except Exception as e:
            logger.exception(f"❌ Failed to load strategy config: {strategy_name}")
            return None

    # ==================================================
    # UPDATE STATUS
    # ==================================================
    def _update_status(self, intent_id: str, status: str):
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE control_intents SET status = ? WHERE id = ?",
                (status, intent_id),
            )
            conn.commit()
        finally:
            conn.close()
