#!/usr/bin/env python3
"""
DBBackedMarket (PRODUCTION)
==========================

Market adapter backed by SQLite option-chain snapshots.

Responsibilities:
- Read latest snapshot from OptionChainDB
- Build strategy-compatible greeks DataFrame
- Enforce freshness
- ZERO strategy logic
"""

import pandas as pd
from typing import Dict

from shoonya_platform.market_data.option_chain.db_access import OptionChainDBReader


class DBBackedMarket:
    def __init__(
        self,
        *,
        db_path: str,
        exchange: str,
        symbol: str,
    ):
        self.reader = OptionChainDBReader(db_path)
        self.exchange = exchange
        self.symbol = symbol

    # -------------------------------------------------
    # ENGINE CONTRACT
    # -------------------------------------------------
    def snapshot(self) -> Dict:
        meta, rows = self.reader.read(max_age=2.0)

        df = pd.DataFrame(rows)
        if df.empty:
            return {"greeks": None, "spot": None}

        greeks_df = self._build_greeks_df(df)
        spot = float(meta.get("spot_ltp", 0))

        return {
            "greeks": greeks_df,
            "spot": spot,
        }

    # -------------------------------------------------
    # STRATEGY-COMPATIBLE GREEKS SHAPE
    # -------------------------------------------------
    def _build_greeks_df(self, df: pd.DataFrame) -> pd.DataFrame:
        ce = (
            df[df["option_type"] == "CE"]
            .set_index("strike")
            .sort_index()
        )
        pe = (
            df[df["option_type"] == "PE"]
            .set_index("strike")
            .sort_index()
        )

        # Align on strike (inner join = safest)
        merged = ce.join(
            pe,
            how="inner",
            lsuffix="_CE",
            rsuffix="_PE",
        )

        out = {
            ("Symbol", "CE"): merged["trading_symbol_CE"].values,
            ("Symbol", "PE"): merged["trading_symbol_PE"].values,
            ("Last Price", "CE"): merged["ltp_CE"].values,
            ("Last Price", "PE"): merged["ltp_PE"].values,
            ("Delta", "CE"): merged["delta_CE"].values,
            ("Delta", "PE"): merged["delta_PE"].values,
        }

        greeks_df = pd.DataFrame(out)
        greeks_df.columns = pd.MultiIndex.from_tuples(greeks_df.columns)

        return greeks_df

    # -------------------------------------------------
    # OPTION SELECTOR (DB NATIVE)
    # -------------------------------------------------
    def get_nearest_option(
        self,
        df: pd.DataFrame,
        greek: str,
        target_value: float,
        option_type: str,
    ):
        """
        Drop-in replacement for get_nearest_greek_option()
        """

        col = (greek, option_type)
        sym = ("Symbol", option_type)
        price = ("Last Price", option_type)

        if col not in df.columns:
            return None

        series = df[col].abs()
        idx = (series - abs(target_value)).idxmin()

        return {
            "symbol": df.at[idx, sym],
            "last_price": df.at[idx, price],
            "delta": df.at[idx, col],
        }
