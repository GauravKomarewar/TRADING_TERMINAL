#===================================================================
# database.py is PRODUCTION FROZEN.

# - Orders schema preserved
# - Legacy migrations handled
# - Dashboard control_intents schema aligned
# - No execution-path impact
# - Restart-safe, concurrency-safe

# Any future modification requires full OMS + consumer re-audit.
#===================================================================

import sqlite3
import threading
import os
from pathlib import Path

# ======================================================
# DATABASE PATH (EC2 / WINDOWS / DOCKER SAFE)
# ======================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DB_LOCK = threading.Lock()

# 🔒 MULTI-CLIENT: DB path resolved LAZILY at first get_connection() call.
# This allows load_dotenv() to set ORDERS_DB_PATH before we read it.
# Each client process should set ORDERS_DB_PATH to a unique file in their .env.
# Default: shoonya_platform/persistence/data/orders.db
_DB_PATH = None
_DEFAULT_DB_PATH = (
    _PROJECT_ROOT
    / "shoonya_platform"
    / "persistence"
    / "data"
    / "orders.db"
)


def _resolve_db_path():
    """Resolve DB path lazily (after load_dotenv has run)."""
    global _DB_PATH
    if _DB_PATH is not None:
        return _DB_PATH
    
    _DB_PATH = Path(
        os.environ.get("ORDERS_DB_PATH", str(_DEFAULT_DB_PATH))
    )
    db_parent = _DB_PATH.parent
    db_parent.mkdir(parents=True, exist_ok=True)
    print("DB PATH IN USE:", _DB_PATH)
    return _DB_PATH

def get_connection():
    with _DB_LOCK:
        db_path = _resolve_db_path()
        conn = sqlite3.connect(
            db_path,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row

        # 🔒 CRITICAL: WAL mode for concurrent read/write from multiple threads
        conn.execute("PRAGMA journal_mode=WAL")
        # 🔒 Wait up to 5s for locked DB instead of failing immediately
        conn.execute("PRAGMA busy_timeout=5000")
        
        # Ensure minimal schema exists for tests and runtime
        try:
            # Create orders table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT,
                    command_id TEXT,
                    source TEXT,
                    user TEXT,
                    strategy_name TEXT,

                    exchange TEXT,
                    symbol TEXT,
                    side TEXT,
                    quantity INTEGER,
                    product TEXT,

                    order_type TEXT,
                    price REAL,

                    stop_loss REAL,
                    target REAL,
                    trailing_type TEXT,
                    trailing_value REAL,

                    broker_order_id TEXT,
                    execution_type TEXT,

                    status TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    tag TEXT
                )
                """
            )
            conn.commit()

            # Detect and migrate away from UNIQUE(command_id) if present in older DBs
            try:
                indexes = conn.execute("PRAGMA index_list('orders')").fetchall()
                need_migrate = False
                
                for idx in indexes:
                    if idx[2] == 1:  # unique flag
                        idx_name = idx[1]
                        cols = conn.execute(f"PRAGMA index_info('{idx_name}')").fetchall()
                        for c in cols:
                            # c[2] is column name in pragma index_info
                            if c[2] == 'command_id':
                                need_migrate = True
                                break
                    if need_migrate:
                        break

                if need_migrate:
                    # Recreate table without UNIQUE constraint on command_id
                    conn.execute('BEGIN')
                    conn.execute("ALTER TABLE orders RENAME TO orders_old")
                    conn.execute(
                        """
                        CREATE TABLE orders (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            client_id TEXT,
                            command_id TEXT,
                            source TEXT,
                            user TEXT,
                            strategy_name TEXT,

                            exchange TEXT,
                            symbol TEXT,
                            side TEXT,
                            quantity INTEGER,
                            product TEXT,

                            order_type TEXT,
                            price REAL,

                            stop_loss REAL,
                            target REAL,
                            trailing_type TEXT,
                            trailing_value REAL,

                            broker_order_id TEXT,
                            execution_type TEXT,

                            status TEXT,
                            created_at TEXT,
                            updated_at TEXT,
                            tag TEXT
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO orders (
                            id, client_id, command_id, source, user, strategy_name,
                            exchange, symbol, side, quantity, product,
                            order_type, price, stop_loss, target, trailing_type,
                            trailing_value, broker_order_id, execution_type,
                            status, created_at, updated_at, tag
                        )
                        SELECT id, client_id, command_id, source, user, strategy_name,
                               exchange, symbol, side, quantity, product,
                               order_type, price, stop_loss, target, trailing_type,
                               trailing_value, broker_order_id, execution_type,
                               status, created_at, updated_at, tag
                        FROM orders_old
                        """
                    )
                    conn.execute("DROP TABLE orders_old")
                    conn.commit()
                    
            except Exception:
                # Migration best-effort; fall back to existing table
                conn.rollback()

            # Ensure control_intents table exists (dashboard control plane)
            try:
                cur = conn.cursor()

                # Check existing columns
                cols = cur.execute(
                    "PRAGMA table_info(control_intents)"
                ).fetchall()
                col_names = {c[1] for c in cols}

                required_cols = {
                    "id",
                    "client_id",
                    "parent_client_id",
                    "type",
                    "payload",
                    "source",
                    "status",
                    "created_at",
                }

                if not cols:
                    # Fresh DB → create correct schema
                    cur.execute(
                        """
                        CREATE TABLE control_intents (
                            id TEXT PRIMARY KEY,

                            client_id TEXT NOT NULL,
                            parent_client_id TEXT,

                            type TEXT NOT NULL,
                            payload TEXT NOT NULL,
                            source TEXT NOT NULL,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.commit()

                elif not required_cols.issubset(col_names):
                    # Legacy schema → migrate
                    conn.execute("BEGIN")

                    cur.execute("ALTER TABLE control_intents RENAME TO control_intents_old")

                    cur.execute(
                        """
                        CREATE TABLE control_intents (
                            id TEXT PRIMARY KEY,

                            client_id TEXT NOT NULL,
                            parent_client_id TEXT,

                            type TEXT NOT NULL,
                            payload TEXT NOT NULL,
                            source TEXT NOT NULL,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                        """
                    )

                    # Best-effort copy (legacy rows get client_id='LEGACY')
                    cur.execute(
                        """
                        INSERT INTO control_intents (
                            id, client_id, parent_client_id,
                            type, payload, source, status, created_at
                        )
                        SELECT
                            COALESCE(id, hex(randomblob(16))),
                            'LEGACY',
                            NULL,
                            type,
                            payload,
                            'LEGACY',
                            status,
                            created_at
                        FROM control_intents_old
                        """
                    )

                    cur.execute("DROP TABLE control_intents_old")
                    conn.commit()

            except Exception:
                conn.rollback()

                
        except Exception:
            # Best-effort: if schema creation fails, tests will report error
            conn.rollback()

        return conn