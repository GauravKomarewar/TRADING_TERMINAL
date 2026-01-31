import sqlite3
import threading
import os
from pathlib import Path

_DB_LOCK = threading.Lock()
# Use workspace-relative path if the default path doesn't exist
_DB_PATH = "/home/ec2-user/shoonya_platform/shoonya_platform/persistence/data/orders.db"
_DB_PATH = os.environ.get("SHOONYA_ORDERS_DB", _DB_PATH)

# Ensure parent directory exists
db_parent = Path(_DB_PATH).parent
db_parent.mkdir(parents=True, exist_ok=True)

print("DB PATH IN USE:", _DB_PATH)

def get_connection():
    with _DB_LOCK:
        conn = sqlite3.connect(
            _DB_PATH,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        # Ensure minimal schema exists for tests and runtime
        try:
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
        except Exception:
            # Best-effort: if schema creation fails, tests will report error
            pass

        return conn
