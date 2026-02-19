import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any

_AUDIT_DB = Path(__file__).parent / "data" / "audit.db"

def _ensure_audit_table():
    """Create audit_events table if it doesn't exist."""
    _AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_AUDIT_DB))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                client_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                strategy_name TEXT,
                details TEXT,
                success BOOLEAN NOT NULL,
                error_message TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()

def log_audit(
    client_id: str,
    action_type: str,
    strategy_name: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: Optional[str] = None,
):
    """Insert an audit event."""
    _ensure_audit_table()
    conn = sqlite3.connect(str(_AUDIT_DB))
    try:
        conn.execute(
            """
            INSERT INTO audit_events
            (timestamp, client_id, action_type, strategy_name, details, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                client_id,
                action_type,
                strategy_name,
                json.dumps(details) if details else None,
                success,
                error,
            ),
        )
        conn.commit()
    finally:
        conn.close()