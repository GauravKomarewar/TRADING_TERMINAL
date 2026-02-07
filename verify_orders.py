#!/usr/bin/env python3
"""
Order Database Verification Tool
=================================

This script verifies:
1. Orders are written to order.db correctly
2. Status transitions are correct
3. All fields are properly populated
4. No orphaned orders (intent created but not persisted)

Run this to debug order placement issues.
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# Navigate to project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "shoonya_platform" / "persistence" / "data" / "orders.db"

def verify_orders():
    """Run comprehensive order database verification"""
    
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        return False
    
    print(f"🔍 Verifying orders database at {DB_PATH}\n")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # 1. Check total orders
        total = conn.execute("SELECT COUNT(*) as cnt FROM orders").fetchone()["cnt"]
        print(f"📊 Total orders in database: {total}")
        
        if total == 0:
            print("⚠️  No orders found in database!")
            return True
        
        # 2. Count by status
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM orders GROUP BY status"
        ).fetchall()
        
        print("\n📈 Orders by status:")
        status_summary = {}
        for row in status_rows:
            status = row["status"]
            count = row["cnt"]
            status_summary[status] = count
            status_icon = {
                "CREATED": "⚙️",
                "SENT_TO_BROKER": "🚀",
                "EXECUTED": "✅",
                "FAILED": "❌",
            }.get(status, "❓")
            print(f"  {status_icon} {status}: {count}")
        
        # 3. Count by source
        source_rows = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM orders GROUP BY source"
        ).fetchall()
        
        print("\n🎯 Orders by source:")
        for row in source_rows:
            print(f"  {row['source']}: {row['cnt']}")
        
        # 4. Check for data quality issues
        print("\n⚠️  Data Quality Checks:")
        
        # Missing execution_type
        missing_exec = conn.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE execution_type IS NULL"
        ).fetchone()["cnt"]
        if missing_exec > 0:
            print(f"  ❌ {missing_exec} orders missing execution_type")
        else:
            print(f"  ✅ All orders have execution_type")
        
        # SENT_TO_BROKER without broker_order_id
        missing_broker_id = conn.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE status='SENT_TO_BROKER' AND broker_order_id IS NULL"
        ).fetchone()["cnt"]
        if missing_broker_id > 0:
            print(f"  ❌ {missing_broker_id} orders SENT_TO_BROKER but missing broker_order_id")
        else:
            print(f"  ✅ All SENT_TO_BROKER orders have broker_order_id")
        
        # CREATED orders older than 30 seconds
        old_created = conn.execute(
            f"SELECT COUNT(*) as cnt FROM orders WHERE status='CREATED' AND datetime(created_at) < datetime('now', '-30 seconds')"
        ).fetchone()["cnt"]
        if old_created > 0:
            print(f"  ⚠️  {old_created} orders stuck in CREATED for 30+ seconds")
        
        # 5. Show recent orders
        print("\n📝 Last 10 orders:")
        recent = conn.execute(
            "SELECT command_id, symbol, side, quantity, status, broker_order_id, created_at FROM orders ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        
        for row in recent:
            broker_id = row["broker_order_id"] or "-"
            created = row["created_at"].split(".")[0] if row["created_at"] else "-"
            print(f"  {row['command_id'][:12]}... | {row['symbol']:10} {row['side']:4} {row['quantity']:3} | {row['status']:15} | bid={broker_id[:8] if broker_id != '-' else '-'}... | {created}")
        
        # 6. Show failed orders
        failed = conn.execute(
            "SELECT command_id, symbol, side, quantity, created_at, updated_at FROM orders WHERE status='FAILED' ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
        
        if failed:
            print("\n❌ Recent failed orders:")
            for row in failed:
                created = row["created_at"].split(".")[0] if row["created_at"] else "-"
                updated = row["updated_at"].split(".")[0] if row["updated_at"] else "-"
                print(f"  {row['command_id'][:12]}... | {row['symbol']} {row['side']} {row['quantity']} | created={created} | failed={updated}")
        
        # 7. Check for stale SENT_TO_BROKER orders (not updated in 60s)
        stale = conn.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE status='SENT_TO_BROKER' AND datetime(updated_at) < datetime('now', '-60 seconds')"
        ).fetchone()["cnt"]
        if stale > 0:
            print(f"\n⚠️  {stale} orders in SENT_TO_BROKER for 60+ seconds (may indicate broker issue)")
        
        print("\n✅ Verification complete!")
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False
    finally:
        try:
            conn.close()
        except:
            pass


def dump_order_trace(command_id: str):
    """Dump complete trace of a specific order"""
    
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        return
    
    print(f"\n🔍 Order trace for: {command_id}\n")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # Find order
        order = conn.execute(
            "SELECT * FROM orders WHERE command_id = ?",
            (command_id,)
        ).fetchone()
        
        if not order:
            print(f"❌ Order not found in database")
            return
        
        # Pretty print the order
        print("📋 Order Details:")
        print(f"  Command ID: {order['command_id']}")
        print(f"  Symbol: {order['symbol']}")
        print(f"  Side: {order['side']}")
        print(f"  Qty: {order['quantity']}")
        print(f"  Status: {order['status']}")
        print(f"  Broker Order ID: {order['broker_order_id'] or 'NOT SET'}")
        print(f"  Source: {order['source']}")
        print(f"  Execution Type: {order['execution_type']}")
        print(f"  Order Type: {order['order_type']}")
        print(f"  Price: {order['price']}")
        print(f"  Stop Loss: {order['stop_loss']}")
        print(f"  Target: {order['target']}")
        print(f"  Created: {order['created_at']}")
        print(f"  Updated: {order['updated_at']}")
        print(f"  Tag: {order['tag']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        try:
            conn.close()
        except:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].startswith("--order="):
        # Trace specific order
        command_id = sys.argv[1].split("=", 1)[1]
        dump_order_trace(command_id)
    else:
        # Run verification
        verify_orders()
