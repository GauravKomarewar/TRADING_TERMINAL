#!/usr/bin/env python3
"""
fake_market_db.py — Synthetic Option Chain Database Generator
=============================================================

Creates realistic SQLite option chain databases with SAFE FAKE EXPIRIES
(year 2099) so they can NEVER be confused with real trading data.

The generated data includes:
- Full option chain with CE + PE at every strike
- Realistic Greeks (delta, gamma, theta, vega, IV)
- Realistic prices using Black-Scholes approximation
- Bid/ask spreads, OI, volume
- Meta table with spot, ATM, fut prices

Usage:
    from tests.fake_market_db import FakeMarketDB

    db = FakeMarketDB(symbol="NIFTY", spot=22500, expiry_tag="10-JAN-2099")
    db.create()                    # Creates the SQLite file
    db.update_prices(spot=22600)   # Simulate price movement
    db.path                        # Returns path to .sqlite file
    db.cleanup()                   # Remove the file

The DB is written to a SEPARATE test directory:
    tests/fake_market_data/  (NOT the real market_data/option_chain/data/)
"""

import math
import os
import random
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any, List


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SAFETY: All fake DBs live in tests/fake_market_data/ — NEVER in real data dir
# SAFETY: All expiries use year 2099 — impossible to match real instruments
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FAKE_DATA_DIR = Path(__file__).resolve().parent / "fake_market_data"

# Lot sizes for common symbols
LOT_SIZES = {
    "NIFTY": 50,
    "BANKNIFTY": 25,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 75,
    "SENSEX": 10,
    "CRUDEOILM": 100,
}

# Strike step sizes
STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
    "CRUDEOILM": 50,
}


def _validate_fake_expiry(expiry_tag: str) -> None:
    """Ensure expiry is in 2099 — safety check against real data."""
    if "2099" not in expiry_tag:
        raise ValueError(
            f"SAFETY: Fake expiry must use year 2099, got '{expiry_tag}'. "
            f"This prevents accidental overlap with real instruments."
        )


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2.0)
    return 0.5 * (1.0 + sign * y)


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _bs_price_greeks(
    spot: float, strike: float, tte: float, iv: float, option_type: str, r: float = 0.07
) -> Dict[str, float]:
    """
    Black-Scholes pricing + Greeks for a European option.
    Returns dict with: ltp, delta, gamma, theta, vega, iv
    """
    if tte <= 0 or iv <= 0:
        intrinsic = max(0, spot - strike) if option_type == "CE" else max(0, strike - spot)
        delta = 1.0 if (option_type == "CE" and spot > strike) else (-1.0 if (option_type == "PE" and spot < strike) else 0.0)
        return {"ltp": intrinsic, "delta": delta, "gamma": 0, "theta": 0, "vega": 0, "iv": iv}

    sigma = iv / 100.0
    sqrt_t = math.sqrt(tte)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * tte) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    if option_type == "CE":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * tte) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        price = strike * math.exp(-r * tte) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0

    gamma = _norm_pdf(d1) / (spot * sigma * sqrt_t)
    theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * sqrt_t)
             - r * strike * math.exp(-r * tte) * _norm_cdf(d2 if option_type == "CE" else -d2)
             * (1 if option_type == "CE" else -1)) / 365.0
    vega = spot * _norm_pdf(d1) * sqrt_t / 100.0  # per 1% IV change

    # Floor price at 0.05 (minimum tick)
    price = max(0.05, price)

    return {
        "ltp": round(price, 2),
        "delta": round(delta, 6),
        "gamma": round(gamma, 8),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "iv": round(iv, 2),
    }


class FakeMarketDB:
    """
    Creates and manages a synthetic option chain SQLite database.

    SAFETY GUARANTEES:
    - DB file lives in tests/fake_market_data/ (never in real data dir)
    - Expiry is forced to year 2099
    - Trading symbols use "FAKE" prefix
    - lot_size is set to None (matching real DB behavior)
    """

    def __init__(
        self,
        exchange: str = "NFO",
        symbol: str = "NIFTY",
        spot: float = 22500.0,
        expiry_tag: str = "10-JAN-2099",
        num_strikes_each_side: int = 15,
        base_iv: float = 15.0,
        tte_days: float = 5.0,
    ):
        _validate_fake_expiry(expiry_tag)

        self.exchange = exchange.upper()
        self.symbol = symbol.upper()
        self.spot = spot
        self.expiry_tag = expiry_tag
        self.num_strikes = num_strikes_each_side
        self.base_iv = base_iv
        self.tte = tte_days / 365.0
        self.strike_step = STRIKE_STEPS.get(self.symbol, 50)
        self.lot_size = LOT_SIZES.get(self.symbol, 50)
        self._conn: Optional[sqlite3.Connection] = None

        # Derived
        self.atm = round(spot / self.strike_step) * self.strike_step
        self.fut_ltp = round(spot * 1.002, 2)  # Slight futures premium

        # File path — SAFELY in test directory
        FAKE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = FAKE_DATA_DIR / f"{self.exchange}_{self.symbol}_{self.expiry_tag}.sqlite"

    @property
    def path(self) -> Path:
        return self._path

    @property
    def db_dir(self) -> Path:
        return FAKE_DATA_DIR

    def create(self) -> "FakeMarketDB":
        """Create the SQLite database with full option chain."""
        # Remove stale file if exists
        if self._path.exists():
            self._path.unlink()

        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._write_snapshot()
        return self

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            token TEXT,
            trading_symbol TEXT,
            exchange TEXT,
            lot_size INTEGER,
            ltp REAL,
            change_pct REAL,
            volume INTEGER,
            oi INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            bid REAL,
            ask REAL,
            bid_qty INTEGER,
            ask_qty INTEGER,
            last_update REAL,
            iv REAL,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            PRIMARY KEY (strike, option_type)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        self._conn.commit()

    def _generate_chain(self) -> List[tuple]:
        """Generate realistic option chain rows."""
        rows = []
        for i in range(-self.num_strikes, self.num_strikes + 1):
            strike = self.atm + i * self.strike_step

            for opt_type in ("CE", "PE"):
                # IV smile: higher IV for OTM options
                moneyness = abs(strike - self.spot) / self.spot
                iv = self.base_iv + moneyness * 80  # Steeper smile for far OTM

                greeks = _bs_price_greeks(self.spot, strike, self.tte, iv, opt_type)

                # Trading symbol with FAKE prefix for safety
                token = f"FAKE{random.randint(10000, 99999)}"
                tsym = f"{self.symbol}10JAN99{opt_type[0]}{int(strike)}"

                # Realistic bid/ask spread (tighter near ATM)
                spread = max(0.5, greeks["ltp"] * 0.005 + moneyness * 20)
                bid = round(max(0.05, greeks["ltp"] - spread / 2), 2)
                ask = round(greeks["ltp"] + spread / 2, 2)

                # OI and volume: higher near ATM
                base_oi = max(100, int(50000 * math.exp(-moneyness * 15)))
                base_vol = max(10, int(base_oi * random.uniform(0.5, 2.0)))

                ltp = greeks["ltp"]
                rows.append((
                    strike,
                    opt_type,
                    token,
                    tsym,
                    self.exchange,
                    None,  # lot_size is None in real DB (matches real behavior)
                    ltp,
                    round(random.uniform(-5, 5), 2),  # change_pct
                    base_vol,
                    base_oi,
                    round(ltp * random.uniform(0.95, 1.02), 2),  # open
                    round(ltp * random.uniform(1.0, 1.1), 2),    # high
                    round(ltp * random.uniform(0.9, 1.0), 2),    # low
                    round(ltp * random.uniform(0.95, 1.05), 2),  # close
                    bid,
                    ask,
                    random.randint(50, 500) * 50,   # bid_qty
                    random.randint(50, 500) * 50,   # ask_qty
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # last_update
                    greeks["iv"],
                    greeks["delta"],
                    greeks["gamma"],
                    greeks["theta"],
                    greeks["vega"],
                ))
        return rows

    def _write_snapshot(self) -> None:
        """Write full option chain + meta to DB."""
        rows = self._generate_chain()
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM option_chain")
            cur.executemany("""
                INSERT INTO option_chain (
                    strike, option_type,
                    token, trading_symbol, exchange, lot_size,
                    ltp, change_pct, volume, oi,
                    open, high, low, close,
                    bid, ask, bid_qty, ask_qty,
                    last_update,
                    iv, delta, gamma, theta, vega
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

            cur.execute("DELETE FROM meta")
            cur.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [
                    ("exchange", self.exchange),
                    ("symbol", self.symbol),
                    ("expiry", self.expiry_tag),
                    ("atm", str(int(self.atm))),
                    ("spot_ltp", str(self.spot)),
                    ("fut_ltp", str(self.fut_ltp)),
                    ("snapshot_ts", str(time.time())),
                ],
            )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    def update_prices(
        self,
        spot: Optional[float] = None,
        iv_shift: float = 0.0,
        tte_days: Optional[float] = None,
    ) -> None:
        """
        Update the DB with new prices — simulates market movement.
        Call repeatedly to simulate live data even when market is closed.
        """
        if spot is not None:
            self.spot = spot
            self.atm = round(spot / self.strike_step) * self.strike_step
            self.fut_ltp = round(spot * 1.002, 2)
        if tte_days is not None:
            self.tte = tte_days / 365.0
        self.base_iv += iv_shift

        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path))
        self._write_snapshot()

    def simulate_tick(self, volatility: float = 0.3) -> float:
        """
        Simulate one price tick (random walk).
        Returns the new spot price.
        Updates the DB automatically.
        """
        # Geometric Brownian Motion step (1-minute granularity)
        dt = 1.0 / (365 * 375)  # 1 minute in years
        drift = 0.0
        shock = random.gauss(0, 1) * volatility * math.sqrt(dt)
        self.spot *= math.exp(drift + shock)
        self.spot = round(self.spot, 2)

        # Slight IV fluctuation
        iv_shift = random.gauss(0, 0.2)
        self.update_prices(spot=self.spot, iv_shift=iv_shift)
        return self.spot

    def cleanup(self) -> None:
        """Remove the fake database file."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        for suffix in ("", "-shm", "-wal"):
            p = Path(str(self._path) + suffix)
            if p.exists():
                p.unlink()

    def __enter__(self):
        return self.create()

    def __exit__(self, *args):
        self.cleanup()

    def __repr__(self) -> str:
        return (
            f"FakeMarketDB(symbol={self.symbol}, spot={self.spot}, "
            f"expiry={self.expiry_tag}, path={self._path})"
        )


class FakeMarketSimulator:
    """
    Runs continuous market simulation across multiple symbols.
    Generates realistic price movements for testing entries, adjustments, exits.

    Usage:
        sim = FakeMarketSimulator()
        sim.add_symbol("NIFTY", spot=22500)
        sim.add_symbol("BANKNIFTY", spot=48000)
        sim.start()     # Background thread
        sim.stop()

    Or use manually:
        sim.tick()       # Single tick across all symbols
        sim.get_db("NIFTY")  # Get the FakeMarketDB instance
    """

    def __init__(self, base_expiry: str = "10-JAN-2099"):
        _validate_fake_expiry(base_expiry)
        self.base_expiry = base_expiry
        self._dbs: Dict[str, FakeMarketDB] = {}
        self._running = False
        self._thread = None
        self._tick_count = 0
        self._scenarios: List[Dict[str, Any]] = []
        self._scenario_idx = 0

    def add_symbol(
        self,
        symbol: str,
        exchange: str = "NFO",
        spot: float = 22500.0,
        base_iv: float = 15.0,
        tte_days: float = 5.0,
        expiry_tag: Optional[str] = None,
    ) -> FakeMarketDB:
        """Add a symbol to simulate."""
        expiry = expiry_tag or self.base_expiry
        _validate_fake_expiry(expiry)
        db = FakeMarketDB(
            exchange=exchange,
            symbol=symbol,
            spot=spot,
            expiry_tag=expiry,
            base_iv=base_iv,
            tte_days=tte_days,
        )
        db.create()
        self._dbs[symbol.upper()] = db
        return db

    def get_db(self, symbol: str) -> Optional[FakeMarketDB]:
        return self._dbs.get(symbol.upper())

    @property
    def db_dir(self) -> Path:
        return FAKE_DATA_DIR

    def set_scenario(self, scenarios: List[Dict[str, Any]]) -> None:
        """
        Set a scripted scenario for deterministic testing.

        Each scenario step is a dict:
        {
            "symbol": "NIFTY",       # which symbol to move
            "spot_delta": +100,      # absolute change to spot
            "iv_shift": +2.0,        # IV change
            "description": "Gap up"  # for logging
        }
        """
        self._scenarios = scenarios
        self._scenario_idx = 0

    def tick(self, volatility: float = 0.3) -> Dict[str, float]:
        """Single tick across all symbols. Returns {symbol: new_spot}."""
        prices = {}
        self._tick_count += 1

        if self._scenarios and self._scenario_idx < len(self._scenarios):
            # Scripted scenario
            step = self._scenarios[self._scenario_idx]
            self._scenario_idx += 1
            sym = step.get("symbol", "").upper()
            db = self._dbs.get(sym)
            if db:
                new_spot = db.spot + step.get("spot_delta", 0)
                db.update_prices(
                    spot=new_spot,
                    iv_shift=step.get("iv_shift", 0),
                    tte_days=step.get("tte_days"),
                )
                prices[sym] = db.spot
        else:
            # Random walk for all symbols
            for sym, db in self._dbs.items():
                prices[sym] = db.simulate_tick(volatility)

        return prices

    def tick_n(self, n: int, volatility: float = 0.3) -> List[Dict[str, float]]:
        """Run N ticks, returns list of price snapshots."""
        return [self.tick(volatility) for _ in range(n)]

    def start(self, interval_sec: float = 1.0, volatility: float = 0.3) -> None:
        """Start background simulation thread."""
        import threading
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                self.tick(volatility)
                time.sleep(interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True, name="FakeMarketSim")
        self._thread.start()

    def stop(self) -> None:
        """Stop background simulation."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def cleanup_all(self) -> None:
        """Clean up all fake databases."""
        self.stop()
        for db in self._dbs.values():
            db.cleanup()
        self._dbs.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup_all()
