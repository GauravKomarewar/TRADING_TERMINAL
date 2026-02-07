# ===================================================================
# 🔒 PRODUCTION FREEZE
# OrderRepository v1.0.0
# STATUS: PRODUCTION FROZEN
# TENANCY: CLIENT-ISOLATED (SHARED DB)
# DATE: 2026-01-29

# Guarantees:
# - Strict client isolation
# - Broker-safe recovery
# - RMS compatible
# - Copy-trading ready
#
# Recommended Indexes (for scale):
# CREATE INDEX idx_orders_client_status ON orders(client_id, status);
# CREATE INDEX idx_orders_client_updated ON orders(client_id, updated_at);
# ===================================================================

# ===================================================================
# OMS STATUS CONTRACT
#
# CREATED         : OMS intent only (not sent to broker)
# SENT_TO_BROKER  : Broker accepted order, order_id assigned
# EXECUTED        : Filled at broker
# FAILED          : Broker cancelled / rejected / expired
#
# FORBIDDEN: TRIGGERED / EXITED / ambiguous states
# ===================================================================

from datetime import datetime
from typing import List, Optional

from shoonya_platform.persistence.database import get_connection
from shoonya_platform.persistence.models import OrderRecord


class OrderRepository:
    """
    SINGLE SOURCE OF TRUTH for order persistence.

    - No business logic
    - No execution logic
    - Read-only helpers for recovery / reporting
    - Enforces strict client isolation in shared database
    """
    def __init__(self, client_id: str):
        self.client_id = client_id

    # -----------------------------
    # CREATE
    # -----------------------------
    def create(self, record: OrderRecord):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO orders (
                client_id,
                command_id,
                source,
                user,
                strategy_name,

                exchange,
                symbol,
                side,
                quantity,
                product,

                order_type,
                price,

                stop_loss,
                target,
                trailing_type,
                trailing_value,

                broker_order_id,
                execution_type,

                status,
                created_at,
                updated_at,
                tag
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.client_id,
                record.command_id,
                record.source,
                record.user,
                record.strategy_name,

                record.exchange,
                record.symbol,
                record.side,
                record.quantity,
                record.product,

                record.order_type,
                record.price,

                record.stop_loss,
                record.target,
                record.trailing_type,
                record.trailing_value,

                record.broker_order_id,
                record.execution_type,

                record.status,
                record.created_at,
                record.updated_at,
                record.tag,
            ),
        )
        conn.commit()

    # -----------------------------
    # UPDATE
    # -----------------------------
    def update_status(self, command_id: str, status: str):
        conn = get_connection()
        conn.execute(
            """
            UPDATE orders
            SET status = ?, updated_at = ?
            WHERE command_id = ?
            AND client_id = ?
            """,
            (status, datetime.utcnow().isoformat(), command_id, self.client_id),
        )
        conn.commit()

    def update_stop_loss(self, command_id: str, new_sl: float):
        conn = get_connection()
        conn.execute(
            """
            UPDATE orders
            SET stop_loss = ?, updated_at = ?
            WHERE command_id = ?
            AND client_id = ?
            """,
            (new_sl, datetime.utcnow().isoformat(), command_id, self.client_id),
        )
        conn.commit()

    def update_broker_id(self, command_id: str, broker_order_id: str):
        """
        Persist broker order ID after broker acceptance.
        PRODUCTION SAFE — compatibility alias.
        """
        conn = get_connection()
        conn.execute(
            """
            UPDATE orders
            SET broker_order_id = ?, status = ?, updated_at = ?
            WHERE command_id = ?
            AND client_id = ?
            """,
            (
                broker_order_id,
                "SENT_TO_BROKER",
                datetime.utcnow().isoformat(),
                command_id,
                self.client_id,
            ),
        )
        conn.commit()
    # -----------------------------
    # READ
    # -----------------------------
    def get_open_orders(self) -> List[OrderRecord]:
        """
        Orders that must be watched by OrderWatcher.
        """
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE status IN ('CREATED', 'SENT_TO_BROKER')
            AND client_id = ?
            """,
            (self.client_id,),
        ).fetchall()
        records = []
        for r in rows:
            d = dict(r)
            d.pop("id", None)   # 🔒 drop legacy column
            d.pop("client_id", None)  # 🔒 drop client_id (handled by repo)
            records.append(OrderRecord(**d))
        return records


    def get_by_id(self, command_id: str) -> Optional[OrderRecord]:
        conn = get_connection()
        row = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE command_id = ?
            AND client_id = ?
            """,
            (command_id, self.client_id),
        ).fetchone()

        if row is None:
            return None

        data = dict(row)
        data.pop("id", None)
        data.pop("client_id", None)
        return OrderRecord(**data)


    # =====================================================
    # READ-ONLY HELPERS (RECOVERY / REPORTING)
    # =====================================================

    def get_open_orders_by_strategy(self, strategy_name: str) -> List[OrderRecord]:
        """
        Returns all non-closed orders for a strategy.
        Strategy name is stored in `user` column.
        """
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE status IN ('CREATED', 'SENT_TO_BROKER')
              AND user = ?
              AND client_id = ?
            """,
            (strategy_name, self.client_id),
        ).fetchall()

        return [
            OrderRecord(**{k: v for k, v in dict(r).items() if k not in ("id", "client_id")})
            for r in rows
        ]

    def get_last_order_source(self, symbol: str) -> Optional[str]:
        """
        Returns last known source of an order for a symbol.
        ENGINE / STRATEGY / MANUAL
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT source
            FROM orders
            WHERE symbol = ?
            AND client_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (symbol, self.client_id),
        ).fetchone()

        return row["source"] if row else None

    def get_strategy_leg_sources(self, strategy_name: str) -> dict:
        """
        Returns mapping:
        { symbol: source }
        """
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT symbol, source
            FROM orders
            WHERE user = ?
              AND status IN ('CREATED', 'SENT_TO_BROKER')
              AND client_id = ?
            """,
            (strategy_name, self.client_id),
        ).fetchall()

        return {r["symbol"]: r["source"] for r in rows}

    def get_open_leg_count(self, strategy_name: str) -> int:
        """
        Number of open order-legs for a strategy.
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM orders
            WHERE user = ?
              AND status IN ('CREATED', 'SENT_TO_BROKER')
              AND client_id = ?
            """,
            (strategy_name, self.client_id),
        ).fetchone()

        return int(row["cnt"]) if row else 0

    # =====================================================
    # RECOVERY SUPPORT (BROKER-SAFE, SCHEMA-AGNOSTIC)
    # =====================================================
    def get_open_positions_by_strategy(self, strategy_name: str):
        """
        Returns live (non-zero qty) positions.

        NOTE:
        - Does NOT depend on source_strategy column
        - Filters by exchange + symbol pattern
        - Safe for old DB schemas
        """

        conn = get_connection()

        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE status = 'SENT_TO_BROKER'
              AND user = ?
              AND client_id = ?
            """,
            (strategy_name, self.client_id),
        ).fetchall()

        positions = []
        for r in rows:
            positions.append({
                "exchange": r["exchange"],
                "symbol": r["symbol"],
                "product": r.get("product"),
                "qty": int(r["quantity"]),
                "side": r["side"],
                "price": r.get("price"),
                "source": r.get("source"),
                "tag": r.get("tag"),
                "stop_loss": r.get("stop_loss"),
                "target": r.get("target"),
                "trailing_type": r.get("trailing_type"),
                "trailing_value": r.get("trailing_value"),
                "broker_order_id": r.get("broker_order_id"),
            })

        return positions

    def get_last_exit_source(self, symbol: str) -> Optional[str]:
        """
        Returns who exited the last order for a symbol.
        Used to detect MANUAL exits.
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT source
            FROM orders
            WHERE symbol = ?
            AND client_id = ?
            AND status = 'EXECUTED'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (symbol, self.client_id),
        ).fetchone()

        return row["source"] if row else None

    def get_last_exit_tag(self, symbol: str) -> Optional[str]:
        """
        Returns last exit tag for symbol (e.g. MANUAL_EXIT).
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT tag
            FROM orders
            WHERE symbol = ?
            AND client_id = ?
            AND status = 'EXECUTED'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (symbol, self.client_id),
        ).fetchone()

        return row["tag"] if row else None

    def update_status_by_broker_id(self, broker_order_id: str, status: str):
        conn = get_connection()
        conn.execute(
            """
            UPDATE orders
            SET status = ?, updated_at = ?
            WHERE broker_order_id = ?
            AND client_id = ?
            """,
            (status, datetime.utcnow().isoformat(), broker_order_id, self.client_id),
        )
        conn.commit()

    def get_by_broker_id(self, broker_order_id: str) -> Optional[OrderRecord]:
        conn = get_connection()
        row = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE broker_order_id = ?
            AND client_id = ?
            """,
            (broker_order_id, self.client_id),
        ).fetchone()

        if row is None:
            return None   # ✅ orphan broker order → ignored safely
        # return OrderRecord(**dict(row)) if row else None
        data = dict(row)
        data.pop("id", None)
        data.pop("client_id", None)
        return OrderRecord(**data) if row else None

    # =====================================================
    # DASHBOARD READ-ONLY HELPERS
    # =====================================================

    def count_open_orders(self) -> int:
        """
        Number of open OMS orders.
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM orders
            WHERE status IN ('CREATED', 'SENT_TO_BROKER')
            AND client_id = ?
            """,
            (self.client_id,),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def get_last_order_time(self):
        """
        Timestamp of last OMS order update.
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT updated_at
            FROM orders
            WHERE client_id = ?
            ORDER BY datetime(updated_at) DESC
            LIMIT 1
            """,
            (self.client_id,),
        ).fetchone()
        return row["updated_at"] if row else None

    def get_last_alert_time(self):
        """
        Timestamp of last alert-triggered order.
        """
        conn = get_connection()
        row = conn.execute(
            """
            SELECT updated_at
            FROM orders
            WHERE source = 'STRATEGY'
            AND client_id = ?
            ORDER BY datetime(updated_at) DESC
            LIMIT 1
            """,
            (self.client_id,),
        ).fetchone()
        return row["updated_at"] if row else None

    def get_all(self, limit: int = 200):
        """
        Returns latest orders (any status), newest first.
        READ-ONLY helper for dashboard / monitoring.
        """
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE client_id = ?
            ORDER BY datetime(updated_at) DESC
            LIMIT ?
            """,
            (self.client_id, limit),
        ).fetchall()

        records = []
        for r in rows:
            d = dict(r)
            d.pop("id", None)  # legacy safety
            d.pop("client_id", None)  # 🔒 drop client_id (handled by repo)
            records.append(OrderRecord(**d))

        return records

    # =====================================================
    # MAINTENANCE / CLEANUP
    # =====================================================
    def cleanup_old_closed_orders(self, days: int = 3) -> int:
        """
        Delete non-pending orders older than N days.

        Keeps:
        - CREATED
        - SENT_TO_BROKER

        Deletes:
        - EXECUTED
        - FAILED
        - CANCELLED
        - REJECTED
        - EXITED
        """
        conn = get_connection()

        cursor = conn.execute(
            """
            DELETE FROM orders
            WHERE status NOT IN ('CREATED', 'SENT_TO_BROKER')
              AND datetime(updated_at) < datetime('now', ?)
              AND client_id = ?
            """,
            (f"-{days} days", self.client_id),
        )

        deleted = cursor.rowcount
        conn.commit()
        return deleted