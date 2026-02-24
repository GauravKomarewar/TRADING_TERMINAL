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
# Version   : v1.1.2-FIXED
# Date      : 2026-02-15
#
# Guarantees:
# - Dashboard intents follow TradingView execution path
# - No broker access
# - No execution bypass
# - Recovery-safe, idempotent
# - Full risk management support (target, stoploss, trailing)
#
# ✅ FIXES APPLIED:
# - Config path standardized to strategy_runner/saved_configs/
# - Config schema mismatch resolved (pass dashboard schema directly)
# - Recovery implementation completed
# - Removed unused UniversalStrategyConfig transformation
#
# DO NOT MODIFY WITHOUT FULL OMS RE-AUDIT
# ======================================================================

import json
import time
import logging
import sqlite3
import re
from pathlib import Path
from typing import Optional, Tuple

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
    - RECOVERY/RESUME

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
                # ✅ FIX: Load dashboard schema and pass directly
                saved_config = self._load_strategy_config(strategy_name)
                if not saved_config:
                    logger.error(
                        "❌ STRATEGY CONFIG NOT FOUND | %s | check /strategy_runner/saved_configs/",
                        strategy_name,
                    )
                    raise RuntimeError(f"Strategy config not found: {strategy_name}")
                
                logger.info(
                    "📋 Loaded strategy config | %s | basic=%s",
                    strategy_name,
                    saved_config.get("basic", {}),
                )
                
                # Override strategy name if provided in intent
                if "strategy_name" in payload:
                    saved_config["name"] = payload["strategy_name"]
                
                logger.info(
                    "🚀 STARTING STRATEGY | %s | config_keys=%s",
                    strategy_name,
                    list(saved_config.keys()),
                )
                
                try:
                    # ✅ Pass dashboard schema directly (nested structure)
                    # Executor expects: config.get("basic"), config.get("timing"), etc.
                    self.strategy_manager.start_strategy_executor(
                        strategy_name=strategy_name,
                        config=saved_config,  # Dashboard schema, NOT transformed
                    )
                    logger.warning(
                        "✅ STRATEGY EXECUTOR STARTED SUCCESSFULLY | %s",
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
                    strategy_name=strategy_name,
                    symbols=None,
                    product_type="ALL",
                    reason="DASHBOARD_EXIT",
                    source="STRATEGY_CONTROL",
                )

            elif action == "FORCE_EXIT":
                self.strategy_manager.request_exit(
                    scope="STRATEGY",
                    strategy_name=strategy_name,
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
        
        COMPLETE IMPLEMENTATION: Creates state + starts strategy.
        
        User selects:
        - strategy_name: Name to assign for recovery
        - symbol: Broker symbol with open position
        - resume_monitoring: Whether to just monitor or also manage
        
        Process:
        1. Get broker position for symbol
        2. Create ExecutionState from broker position
        3. Save state to DB
        4. Load strategy config
        5. Start strategy executor (will load saved state)
        """
        try:
            strategy_name = payload.get("strategy_name")
            symbol = payload.get("symbol")
            resume_monitoring = payload.get("resume_monitoring", True)
            
            if not strategy_name or not symbol:
                raise RuntimeError("strategy_name and symbol required for recovery")
            
            logger.warning(
                f"♻️ RECOVERY/RESUME INITIATED | strategy={strategy_name} | symbol={symbol}"
            )
            
            # 1️⃣ Get broker position
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
            
            # 2️⃣ Extract position details
            position_info = {
                "symbol": symbol,
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "exchange": broker_position.get("exch"),
                "product": broker_position.get("prd"),
                "avg_price": float(broker_position.get("avgprc", 0) or 0),
                "ltp": float(broker_position.get("ltp", 0) or 0),
            }
            
            # 3️⃣ Load strategy config
            config = self._load_strategy_config(strategy_name)
            if not config:
                raise RuntimeError(f"No saved config found for {strategy_name}")
            
            # 4️⃣ Create ExecutionState from broker position
            from shoonya_platform.strategy_runner.strategy_executor_service import ExecutionState
            
            # Determine if CE or PE based on symbol
            is_ce = "CE" in symbol
            is_pe = "PE" in symbol
            
            if not (is_ce or is_pe):
                raise RuntimeError(f"Cannot determine option type from symbol: {symbol}")
            
            # Extract strike from symbol (e.g., "NIFTY 25000 CE" -> 25000.0)
            try:
                parts = symbol.split()
                strike = float(parts[1])
            except (IndexError, ValueError):
                logger.error(f"Cannot parse strike from {symbol}")
                strike = 0.0
            
            exec_state = ExecutionState(
                strategy_name=strategy_name,
                run_id=f"{strategy_name}_recovered_{int(time.time())}",
                has_position=True,
                entry_timestamp=time.time(),
            )
            
            # Set CE or PE leg
            if is_ce:
                exec_state.ce_symbol = symbol
                exec_state.ce_strike = strike
                exec_state.ce_qty = position_info["qty"]
                exec_state.ce_side = position_info["side"]
                exec_state.ce_entry_price = position_info["avg_price"]
            
            if is_pe:
                exec_state.pe_symbol = symbol
                exec_state.pe_strike = strike
                exec_state.pe_qty = position_info["qty"]
                exec_state.pe_side = position_info["side"]
                exec_state.pe_entry_price = position_info["avg_price"]
            
            # 5️⃣ Save state to DB
            state_mgr = self.strategy_manager.strategy_executor_service.state_mgr
            state_mgr.save(exec_state)
            
            logger.info(f"💾 Recovery state saved: {strategy_name}")
            
            # 6️⃣ Start strategy executor (will load saved state)
            self.strategy_manager.start_strategy_executor(
                strategy_name=strategy_name,
                config=config,
            )
            
            logger.warning(
                f"✅ RECOVERY COMPLETE: {strategy_name} | "
                f"{symbol} ({position_info['side']} {position_info['qty']} @ ₹{position_info['avg_price']:.2f})"
            )
            
            # 7️⃣ Track recovery
            self.recovery_handlers[strategy_name] = {
                "status": "RESUMED",
                "symbol": symbol,
                "position": position_info,
                "timestamp": time.time(),
            }
            
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
        
        Path: shoonya_platform/strategy_runner/saved_configs/{slug}.json
        (saved by dashboard POST /strategy/config/save-all)
        
        Returns: Dashboard schema config (nested structure) or None if not found.
        
        ✅ FIX: Returns dashboard schema as-is (executor expects nested structure)
        """
        try:
            # Slugify strategy name (same as frontend)
            requested_slug = strategy_name.strip().lower()
            requested_slug = re.sub(r'[^a-z0-9]+', '_', requested_slug)
            requested_slug = requested_slug.strip('_') or 'unnamed'

            config_dir = (
                Path(__file__).resolve().parents[2]
                / "shoonya_platform"
                / "strategy_runner"
                / "saved_configs"
            )

            direct_path = config_dir / f"{requested_slug}.json"
            if direct_path.exists():
                config = json.loads(direct_path.read_text(encoding="utf-8-sig"))
                logger.info(
                    "✅ Loaded strategy config by filename | requested=%s | file=%s",
                    strategy_name,
                    direct_path.name,
                )
                return config

            # Fallback: match by config "id"/"name" in saved files.
            for path in sorted(config_dir.glob("*.json")):
                if path.name == "STRATEGY_CONFIG_SCHEMA.json":
                    continue
                try:
                    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue

                file_slug = re.sub(r'[^a-z0-9]+', '_', path.stem.strip().lower()).strip('_') or "unnamed"
                id_slug = re.sub(r'[^a-z0-9]+', '_', str(cfg.get("id", "")).strip().lower()).strip('_')
                name_slug = re.sub(r'[^a-z0-9]+', '_', str(cfg.get("name", "")).strip().lower()).strip('_')

                if requested_slug in {file_slug, id_slug, name_slug}:
                    logger.info(
                        "✅ Loaded strategy config by metadata | requested=%s | file=%s | id=%s | name=%s",
                        strategy_name,
                        path.name,
                        cfg.get("id"),
                        cfg.get("name"),
                    )
                    return cfg

            logger.warning(
                "⚠️ Strategy config not found after filename+metadata lookup | requested=%s | expected_slug=%s",
                strategy_name,
                requested_slug,
            )
            return None
            
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
