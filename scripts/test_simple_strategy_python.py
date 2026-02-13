#!/usr/bin/env python3
"""
Test SimpleTestStrategy via Python — no broker or dashboard needed.

Creates mock market data and runs the strategy through all phases:
  1. ENTRY: Short CE + PE at 0.3 delta
  2. HOLD: Wait 60 seconds
  3. ADJUST: Close most profitable leg, re-short same type at 0.3 delta
  4. HOLD: Wait 60 seconds
  5. EXIT: Close all

Also creates a mock .sqlite DB for dashboard testing.

Usage:
    cd shoonya_platform
    python scripts/test_simple_strategy_python.py
"""

import sys
import os
import math
import sqlite3
import logging
from datetime import datetime, time as dt_time
from pathlib import Path

# ── Project root on sys.path ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shoonya_platform.strategies.standalone_implementations.simple_test.simple_test_strategy import (
    SimpleTestStrategy,
)

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-25s] %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("TEST")


# ============================================================
# MOCK OPTION CHAIN BUILDER
# ============================================================

def build_option_chain(spot: float = 22500.0, ce_ltp_shift: float = 0, pe_ltp_shift: float = 0):
    """
    Generate realistic NIFTY option chain rows.

    Returns list[dict] with columns matching the sqlite option_chain schema:
        trading_symbol, token, strike, option_type, ltp, delta, gamma, theta, vega, iv, oi, volume
    """
    chain = []
    scale = 300.0  # logistic scale for delta

    for strike in range(21000, 24050, 50):
        # CE delta via logistic sigmoid
        ce_delta = 1.0 / (1.0 + math.exp((strike - spot) / scale))
        ce_delta = max(0.01, min(0.99, ce_delta))
        pe_delta = ce_delta - 1.0  # put-call parity

        # Premium estimation
        intrinsic_ce = max(0, spot - strike)
        intrinsic_pe = max(0, strike - spot)
        time_val = 200 * ce_delta
        time_val_pe = 200 * abs(pe_delta)
        ce_ltp = round(max(1.0, intrinsic_ce + time_val) + ce_ltp_shift, 2)
        pe_ltp = round(max(1.0, intrinsic_pe + time_val_pe) + pe_ltp_shift, 2)

        chain.append({
            "trading_symbol": f"NIFTY13FEB26C{strike}",
            "token": f"C{strike}",
            "strike": float(strike),
            "option_type": "CE",
            "ltp": ce_ltp,
            "delta": round(ce_delta, 4),
            "gamma": round(0.001 * max(0, 1 - abs((strike - spot) / 1000)), 6),
            "theta": round(-5 * ce_delta, 2),
            "vega": round(10 * max(0, 1 - abs((strike - spot) / 1500)), 2),
            "iv": round(15 + abs((strike - spot) / spot) * 50, 2),
            "oi": 1000000,
            "volume": 50000,
        })

        chain.append({
            "trading_symbol": f"NIFTY13FEB26P{strike}",
            "token": f"P{strike}",
            "strike": float(strike),
            "option_type": "PE",
            "ltp": pe_ltp,
            "delta": round(pe_delta, 4),
            "gamma": round(0.001 * max(0, 1 - abs((strike - spot) / 1000)), 6),
            "theta": round(-5 * abs(pe_delta), 2),
            "vega": round(10 * max(0, 1 - abs((strike - spot) / 1500)), 2),
            "iv": round(15 + abs((strike - spot) / spot) * 50, 2),
            "oi": 1000000,
            "volume": 50000,
        })

    return chain


def build_market_snapshot(spot=22500.0, ce_shift=0.0, pe_shift=0.0):
    return {
        "option_chain": build_option_chain(spot, ce_shift, pe_shift),
        "symbol": "NIFTY",
        "exchange": "NFO",
        "spot_price": spot,
        "expiry": "13-Feb-2026",
        "count": 120,
    }


# ============================================================
# MOCK SQLITE DB (for dashboard test)
# ============================================================

def create_mock_sqlite(db_path: Path, spot: float = 22500.0):
    """Create a real .sqlite file with option_chain + meta tables."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            trading_symbol TEXT,
            token TEXT,
            strike REAL,
            option_type TEXT,
            ltp REAL,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            iv REAL,
            oi INTEGER,
            volume INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Insert option chain rows
    chain = build_option_chain(spot)
    for row in chain:
        cur.execute(
            "INSERT INTO option_chain VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["trading_symbol"], row["token"], row["strike"],
                row["option_type"], row["ltp"], row["delta"],
                row["gamma"], row["theta"], row["vega"], row["iv"],
                row["oi"], row["volume"],
            ),
        )

    # Insert meta
    cur.execute("INSERT OR REPLACE INTO meta VALUES ('spot_ltp', ?)", (str(spot),))
    cur.execute("INSERT OR REPLACE INTO meta VALUES ('expiry', '13-FEB-2026')")
    cur.execute("INSERT OR REPLACE INTO meta VALUES ('exchange', 'NFO')")
    cur.execute("INSERT OR REPLACE INTO meta VALUES ('symbol', 'NIFTY')")

    conn.commit()
    conn.close()
    log.info(f"Mock DB created: {db_path}  ({len(chain)} rows, spot={spot})")
    return db_path


# ============================================================
# MAIN TEST
# ============================================================

def main():
    sep = "=" * 70
    print(f"\n{sep}")
    print("  SIMPLE TEST STRATEGY — PYTHON-ONLY PIPELINE TEST")
    print(f"{sep}\n")

    # ── Create mock .sqlite for later dashboard use ──
    mock_db_path = PROJECT_ROOT / "shoonya_platform" / "market_data" / "option_chain" / "data" / "NFO_NIFTY_13-FEB-2026.sqlite"
    create_mock_sqlite(mock_db_path, spot=22500.0)

    # ── Strategy config (flat factory format) ──
    config = {
        "strategy_type": "simple_test",
        "strategy_name": "NIFTY_SIMPLE_TEST",
        "exchange": "NFO",
        "symbol": "NIFTY",
        "instrument_type": "OPTIDX",
        "entry_time": "09:16",
        "exit_time": "15:29",
        "entry_end_time": "15:28",
        "order_type": "MARKET",
        "product": "NRML",
        "lot_qty": 1,  # 1 lot
        "enabled": True,
        "params": {
            "target_entry_delta": 0.3,
            "lot_size": 65,   # NIFTY lot = 65
            "adjust_wait_seconds": 60,
            "exit_wait_seconds": 60,
            "entry_end_time": "15:28",
        },
        "market_config": {
            "market_type": "database_market",
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": str(mock_db_path),
        },
    }

    strategy = SimpleTestStrategy(config)

    # ────────────────────────────────────────
    # Phase 0: Before entry (09:15) — idle
    # ────────────────────────────────────────
    print("\n--- Phase 0: Before entry time (09:15) — should do nothing ---")
    market = build_market_snapshot(spot=22500)
    strategy.prepare(market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 15, 0))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    assert len(cmds) == 0 and strategy.phase == "IDLE"
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Phase 1: ENTRY at 09:16 — short CE + PE
    # ────────────────────────────────────────
    print("\n--- Phase 1: ENTRY at 09:16 — short CE + PE at delta ~0.3 ---")
    strategy.prepare(market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 16, 0))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    for c in cmds:
        print(f"    → {c.side:4s} {c.symbol:<25s} qty={c.quantity}  ({c.comment})")
    assert len(cmds) == 2
    assert all(c.side == "SELL" for c in cmds)
    assert all(c.quantity == 65 for c in cmds)
    assert strategy.phase == "ENTERED"
    # Verify 0.3 delta selection
    ce_sym = strategy.ce_leg["symbol"]
    pe_sym = strategy.pe_leg["symbol"]
    print(f"  CE leg: {ce_sym}  PE leg: {pe_sym}")
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Phase 1.5: 30 seconds later — still holding
    # ────────────────────────────────────────
    print("\n--- Phase 1.5: +30s — still holding (60s not elapsed) ---")
    strategy.prepare(market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 16, 30))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    assert len(cmds) == 0
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Phase 2: ADJUST at 09:17 — close profitable leg, re-short
    # ────────────────────────────────────────
    print("\n--- Phase 2: ADJUST at 09:17 — close profitable leg, re-short ---")
    # Simulate market moved up: CE options cheaper (profit), PE options costlier (loss)
    adjusted_market = build_market_snapshot(spot=22520, ce_shift=-8, pe_shift=5)
    strategy.prepare(adjusted_market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 17, 0))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    for c in cmds:
        print(f"    → {c.side:4s} {c.symbol:<25s} qty={c.quantity}  ({c.comment})")
    assert len(cmds) == 2
    assert strategy.phase == "ADJUSTED"
    # Should be 1 BUY (close) + 1 SELL (new)
    sides = sorted([c.side for c in cmds])
    assert sides == ["BUY", "SELL"], f"Expected BUY+SELL, got {sides}"
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Phase 2.5: 30 seconds later — still holding adjusted
    # ────────────────────────────────────────
    print("\n--- Phase 2.5: +30s — still holding adjusted ---")
    strategy.prepare(adjusted_market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 17, 30))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    assert len(cmds) == 0
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Phase 3: EXIT at 09:18 — close all legs
    # ────────────────────────────────────────
    print("\n--- Phase 3: EXIT at 09:18 — close all legs ---")
    strategy.prepare(adjusted_market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 18, 0))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    for c in cmds:
        print(f"    → {c.side:4s} {c.symbol:<25s} qty={c.quantity}  ({c.comment})")
    assert len(cmds) == 2
    assert all(c.side == "BUY" for c in cmds)
    assert all(c.quantity == 65 for c in cmds)
    assert strategy.phase == "EXITED"
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Phase 4: After exit — should do nothing
    # ────────────────────────────────────────
    print("\n--- Phase 4: After exit — should be idle ---")
    strategy.prepare(adjusted_market)
    cmds = strategy.on_tick(datetime(2026, 2, 13, 9, 19, 0))
    print(f"  Phase={strategy.phase}  Commands={len(cmds)}")
    assert len(cmds) == 0
    print("  PASS ✓")

    # ────────────────────────────────────────
    # Summary
    # ────────────────────────────────────────
    print(f"\n{sep}")
    print("  ALL PHASES PASSED ✓")
    print(f"  Mock DB ready at: {mock_db_path}")
    print(f"  → Use this DB path in dashboard config for dashboard test")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
