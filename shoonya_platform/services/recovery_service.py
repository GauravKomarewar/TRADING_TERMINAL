import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.persistence.database import get_connection

logger = logging.getLogger(__name__)


class RecoveryBootstrap:
    """
    Phase-2 Recovery Bootstrap

    - Runs ONLY on bot startup
    - Fetches broker truth first, then reconciles DB
    - Reconstructs in-memory commands (read-only)
    - Rebuilds ExecutionGuard state
    - Does NOT place orders
    """

    def __init__(self, bot):
        self.bot = bot
        self.repo = OrderRepository(client_id=bot.client_id)
        self.recovery_log = {
            "timestamp": datetime.utcnow().isoformat(),
            "client_id": bot.client_id,
            "broker_positions": [],
            "recovered": [],
            "skipped": [],
            "errors": [],
        }

    # --------------------------------------------------
    # PUBLIC ENTRY
    # --------------------------------------------------
    def run(self):
        logger.warning("♻️ Phase-2 Recovery Bootstrap started")

        # 1️⃣ FETCH BROKER TRUTH FIRST
        try:
            self.bot._ensure_login()
            broker_positions = self.bot.api.get_positions() or []
            broker_orders = self.bot.api.get_order_book() or []
        except Exception as e:
            logger.warning("♻️ Recovery skipped (broker unreachable)")
            logger.warning(str(e))
            return

        # Build broker position map
        broker_pos_map: Dict[str, Dict] = {}
        for p in broker_positions:
            symbol = p.get("tsym")
            try:
                netqty = int(p.get("netqty", 0))
            except Exception:
                netqty = 0

            if netqty == 0:
                continue

            broker_pos_map[symbol] = {
                "exchange": p.get("exch"),
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "product": p.get("prd"),
                "avg_price": float(p.get("avgprc", 0) or 0),
            }

        self.recovery_log["broker_positions"] = list(broker_pos_map.keys())

        logger.info(f"Broker truth: {len(broker_pos_map)} positions")

        # 2️⃣ RECONCILE BROKER ORDERS WITH DB
        for o in broker_orders:
            order_id = o.get("norenordno")
            status = (o.get("status") or "").upper()

            if not order_id:
                continue

            db_record = self.repo.get_by_broker_id(order_id) if hasattr(self.repo, 'get_by_broker_id') else None
            if not db_record:
                continue

            try:
                if status == "COMPLETE" and db_record.status != "EXECUTED":
                    # 🔒 FIX: order_id is broker_order_id (norenordno), NOT command_id
                    self.repo.update_status_by_broker_id(order_id, "EXECUTED")
                elif status in ("CANCELLED", "REJECTED") and db_record.status != "FAILED":
                    self.repo.update_status_by_broker_id(order_id, "FAILED")
            except Exception:
                # Best-effort, continue
                logger.exception("Failed to update DB status for broker order %s", order_id)

        # 3️⃣ DETECT STRATEGIES
        try:
            strategies = self._detect_strategies()
        except Exception as e:
            logger.warning("♻️ Recovery skipped (fresh DB or no schema)")
            logger.warning(str(e))
            return

        if not strategies:
            logger.info("✅ No strategies found for recovery")
            return

        # 4️⃣ RECOVER WITH BROKER VALIDATION
        for strategy_name in strategies:
            try:
                self._recover_strategy(strategy_name, broker_pos_map)
            except Exception as e:
                logger.exception("Error recovering strategy %s: %s", strategy_name, e)
                self.recovery_log["errors"].append({"strategy": strategy_name, "error": str(e)})

        logger.warning(
            f"♻️ Recovery complete | strategies={len(strategies)} | active_commands={len(self.bot.pending_commands)}"
        )

        # Write audit log
        try:
            log_dir = Path("logs/recovery")
            log_dir.mkdir(parents=True, exist_ok=True)

            log_file = log_dir / f"{self.bot.client_id}_{int(time.time())}.json"
            with open(log_file, 'w') as f:
                json.dump(self.recovery_log, f, indent=2)

            logger.info(f"Recovery audit saved: {log_file}")
        except Exception as e:
            logger.error(f"Failed to save recovery audit: {e}")

    # --------------------------------------------------
    # STRATEGY DISCOVERY (BACKWARD-COMPATIBLE)
    # --------------------------------------------------
    def _detect_strategies(self) -> List[str]:
        """
        Strategy ownership is stored in `user` column.
        Recovers ALL active strategies (both pending and filled).
        """
        db = get_connection()
        rows = db.execute(
            """
            SELECT DISTINCT user
            FROM orders
            WHERE status IN ('SENT_TO_BROKER', 'EXECUTED')
              AND user IS NOT NULL
              AND client_id = ?
            """,
            (self.bot.client_id,)
        ).fetchall()
        return [r["user"] for r in rows]

    # --------------------------------------------------
    # STRATEGY RECOVERY
    # --------------------------------------------------
    def _recover_strategy(self, strategy_name: str, broker_pos_map: Dict[str, Dict]):
        db_positions = self.repo.get_open_positions_by_strategy(strategy_name)

        if not db_positions:
            logger.info(f"No DB positions for {strategy_name}")
            return

        logger.info(f"Recovering {strategy_name}: {len(db_positions)} DB positions")

        for db_pos in db_positions:
            symbol = db_pos["symbol"]

            # VALIDATE AGAINST BROKER
            if symbol not in broker_pos_map:
                logger.warning(
                    f"Skipping {symbol} - not in broker positions"
                )
                self.recovery_log["skipped"].append({"strategy": strategy_name, "symbol": symbol, "reason": "not_in_broker"})
                continue

            broker_pos = broker_pos_map[symbol]

            # Validate side
            if db_pos["side"] != broker_pos["side"]:
                logger.error(
                    f"Side mismatch {symbol}: DB={db_pos['side']} Broker={broker_pos['side']}"
                )
                self.recovery_log["skipped"].append({"strategy": strategy_name, "symbol": symbol, "reason": "side_mismatch"})
                continue

            # Use broker quantity (source of truth)
            db_pos["qty"] = broker_pos["qty"]
            db_pos["avg_price"] = broker_pos.get("avg_price")

            # Recover this leg
            self._recover_leg(strategy_name, db_pos)

    # --------------------------------------------------
    # LEG RECOVERY
    # --------------------------------------------------
    def _recover_leg(self, strategy_name: str, pos: dict):
        """Recover individual position leg with validation."""
        symbol = pos["symbol"]

        # Thread-safe duplicate check
        with self.bot._cmd_lock:
            if any(cmd.symbol == symbol for cmd in self.bot.pending_commands):
                logger.warning(f"Duplicate recovery skipped: {symbol}")
                return

            # Fetch original order for full details
            db = get_connection()
            original = db.execute(
                """
                SELECT *
                FROM orders
                WHERE symbol = ?
                  AND user = ?
                  AND client_id = ?
                  AND status IN ('SENT_TO_BROKER', 'EXECUTED')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol, strategy_name, self.bot.client_id)
            ).fetchone()

            if not original:
                logger.error(f"No order record for {symbol}")
                self.recovery_log["errors"].append({"strategy": strategy_name, "symbol": symbol, "reason": "no_db_record"})
                return

            # Build order params from original + broker
            order_params = {
                "exchange": pos["exchange"],
                "symbol": symbol,
                "quantity": pos["qty"],
                "side": pos["side"],
                "product": original.get("product") or "MIS",
                "order_type": original.get("order_type") or "MARKET",
                "price": original.get("price"),
                "stop_loss": original.get("stop_loss"),
                "target": original.get("target"),
                "trailing_type": original.get("trailing_type"),
                "trailing_value": original.get("trailing_value"),
                "strategy_name": strategy_name,
            }

            cmd = UniversalOrderCommand.from_order_params(
                order_params=order_params,
                source="RECOVERY",
                user=strategy_name,
            )

            # Set broker order ID
            if original.get("broker_order_id"):
                object.__setattr__(cmd, "broker_order_id", original.get("broker_order_id"))

            self.bot.pending_commands.append(cmd)

            logger.warning(
                f"♻️ Recovered: {strategy_name} | {symbol} {pos['side']} "
                f"qty={pos['qty']} | broker_id={original.get('broker_order_id')}"
            )

        # Update ExecutionGuard (outside lock)
        try:
            self.bot.execution_guard.confirm_execution(
                strategy_id=strategy_name,
                symbol=symbol,
                direction=pos["side"],
                qty=pos["qty"],
            )
            self.recovery_log["recovered"].append({"strategy": strategy_name, "symbol": symbol})
        except Exception as e:
            logger.exception("Failed to confirm execution guard for %s %s", strategy_name, symbol)
            self.recovery_log["errors"].append({"strategy": strategy_name, "symbol": symbol, "error": str(e)})
