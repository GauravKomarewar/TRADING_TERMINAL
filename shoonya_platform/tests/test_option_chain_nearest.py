import sqlite3
import time
from pathlib import Path
from shoonya_platform.api.dashboard.services.option_chain_service import find_nearest_option


def create_test_db(path: Path):
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()

    # meta table
    cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("snapshot_ts", str(time.time())))

    # option_chain table (minimal columns used by reader)
    cur.execute(
        """
        CREATE TABLE option_chain (
            strike REAL,
            option_type TEXT,
            token INTEGER,
            trading_symbol TEXT,
            exchange TEXT,
            lot_size INTEGER,
            ltp REAL,
            iv REAL,
            delta REAL,
            last_update REAL
        )
        """
    )

    # insert sample rows
    rows = [
        (25750, 'CE', 1001, 'NIFTY10FEB26C25750', 'NFO', 50, 120.5, 0.12, 0.5, time.time()),
        (25750, 'PE', 1002, 'NIFTY10FEB26P25750', 'NFO', 50, 118.0, 0.10, -0.12, time.time()),
        (25800, 'CE', 1003, 'NIFTY10FEB26C25800', 'NFO', 50, 130.0, 0.11, 0.4, time.time()),
    ]

    cur.executemany(
        "INSERT INTO option_chain (strike, option_type, token, trading_symbol, exchange, lot_size, ltp, iv, delta, last_update) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )

    conn.commit()
    conn.close()


def test_find_nearest_by_ltp(tmp_path):
    db_file = tmp_path / "test_chain.sqlite"
    create_test_db(db_file)

    res = find_nearest_option(str(db_file), target=119.0, metric="ltp", option_type=None, max_age=5.0)
    assert res["ltp"] in (118.0, 120.5)


def test_find_nearest_filtered_option_type(tmp_path):
    db_file = tmp_path / "test_chain2.sqlite"
    create_test_db(db_file)

    res = find_nearest_option(str(db_file), target=119.0, metric="ltp", option_type="PE", max_age=5.0)
    assert res["option_type"] == "PE"
    assert res["ltp"] == 118.0
