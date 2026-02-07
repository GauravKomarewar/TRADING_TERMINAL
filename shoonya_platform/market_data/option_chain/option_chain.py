"""
===============================================================================
OPTION CHAIN v6.0 - PULL-BASED ARCHITECTURE
===============================================================================

🔥 v6.0 CHANGES (Pull-Based Architecture):
    1. REMOVED: update_tick() callback method
    2. REMOVED: bind_option_chain() dependency
    3. ADDED: pull_latest_ticks() - pull all ticks from feed
    4. ADDED: pull_ticks_efficient() - batch pull for chain tokens only
    5. ADDED: capture_snapshot() - atomic snapshot with fresh data
    6. UPDATED: _auto_greeks_refresher() - pulls before computing Greeks
    
✅ v5.0 IMPROVEMENTS (Still Present):
    1. Thread-safe spot/future price reads
    2. Session validation before all API calls
    3. Shoonya API response validation
    4. WebSocket state coordination
    5. Enhanced error recovery
    6. Proper resource cleanup
    
✅ NEW ARCHITECTURE:
    WebSocket → Feed Store (tick_data_store)
    OptionChain → Pull from feed store on-demand
    
    Benefits:
    - No dropped ticks (no queue overflow)
    - Deterministic updates (pull when ready)
    - Lower latency (no callback buffering)
    - Atomic snapshots (consistent state)
    
✅ COMPATIBILITY:
    - ✅ Requires: live_feed.py v3.0+
    - ✅ Requires: client.py v2.0+
    - ✅ API compatible with v5.0 (except update_tick removed)
    
🔒 PRODUCTION STATUS:
    ✅ Pull-based architecture
    ✅ Thread-safe throughout
    ✅ Session-safe API calls
    ✅ Proper error handling
    ✅ Resource cleanup
    ✅ Production ready
    
===============================================================================
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Literal
import pandas as pd
import threading
import time

from shoonya_platform.market_data.instruments.instruments import get_fno_details, build_option_symbol
from scripts.scriptmaster import SCRIPTMASTER, OPTION_INSTRUMENTS
from shoonya_platform.market_data.feeds.live_feed import (
    start_live_feed,
    subscribe_livedata,
    is_feed_connected,
    check_feed_health,
    get_all_tick_data,      # 🔥 NEW: Pull all ticks
    get_tick_data_batch,    # 🔥 NEW: Efficient batch pull
)
from shoonya_platform.utils.bs_greeks import (
    implied_volatility,
    bs_greeks,
    time_to_expiry_seconds
)
logger = logging.getLogger(__name__)

from dataclasses import dataclass

@dataclass
class GreekConfig:
    min_coverage: float = 0.60
    min_iv: float = 0.01
    max_iv: float = 5.0
    min_price: float = 0.05

GREEK_CONFIG = GreekConfig()

class GreekCoverageError(Exception):
    pass


# ============================================================================
# CORE DATA CLASS
# ============================================================================

class OptionChainData:
    """
    ScriptMaster-based option chain container - v5.0 Hardened.
    Live prices are updated ONLY via WebSocket ticks.
    
    NSE-style format:
    - Centered around ATM strike
    - Equal strikes above and below ATM
    - CE and PE paired for each strike
    
    🔥 v5.0 IMPROVEMENTS:
    - Thread-safe spot/future price reads
    - Feed health monitoring
    - Proper resource cleanup
    - Enhanced error handling
    """

    def __init__(self):
        self._exchange: Optional[str] = None
        self._symbol: Optional[str] = None
        self._expiry: Optional[str] = None
        self._atm: Optional[int] = None
        self._spot_ltp: Optional[float] = None
        self._fut_ltp: Optional[float] = None

        self._df: Optional[pd.DataFrame] = None
        self._token_set: set[str] = set()

        self._last_greek_spot: Optional[float] = None
        self._greeks_ts: Optional[float] = None

        self._spot_token: Optional[str] = None
        self._fut_token: Optional[str] = None

        self._lock = threading.RLock()
        
        # Resource management
        self._cleanup_done = False
        
        # ✅ NEW: Pull statistics
        self._last_pull_time: Optional[float] = None
        self._total_pulls: int = 0
        
        logger.info("OptionChainData v6.0 initialized")

    # ------------------------------------------------------------------
    # BUILD FROM SCRIPTMASTER
    # ------------------------------------------------------------------

    def load_from_scriptmaster(
        self,
        *,
        exchange: str,
        symbol: str,
        expiry: str,
        atm_strike: int,
        count: int = 10,
        spot_ltp: Optional[float] = None,
        fut_ltp: Optional[float] = None,
    ) -> bool:
        """
        🔥 IMPROVED: Build option chain with enhanced validation.
        
        Args:
            exchange: NFO / BFO / MCX
            symbol: Underlying symbol
            expiry: Option expiry (DD-MMM-YYYY)
            atm_strike: ATM strike (spot-based)
            count: strikes on EACH side (default 10 = total 21 strikes with ATM)
            spot_ltp: Current spot price (for reference)
            fut_ltp: Current future price (for reference)

        Returns:
            True if chain built successfully
        """
        exchange = exchange.upper()
        symbol = symbol.upper()

        with self._lock:
            data = SCRIPTMASTER.get(exchange)
            if not data:
                logger.error(f"No ScriptMaster data for {exchange}")
                return False

            # Get valid option instruments for this exchange
            valid_instruments = OPTION_INSTRUMENTS.get(exchange, set())
            if not valid_instruments:
                logger.error(f"No option instruments defined for {exchange}")
                return False

            rows: List[Dict[str, Any]] = []

            for rec in data.values():
                # ✅ FIXED: Check both Symbol and Underlying (critical for BFO)
                symbol_match = (
                    rec.get("Symbol") == symbol 
                    or rec.get("Underlying") == symbol
                )
                
                if not symbol_match:
                    continue

                # Validate option contract
                if (
                    rec.get("Expiry") != expiry
                    or rec.get("Instrument") not in valid_instruments
                    or rec.get("OptionType") not in ("CE", "PE")
                    or rec.get("StrikePrice") is None
                ):
                    continue

                try:
                    strike = int(float(rec["StrikePrice"]))
                    token = str(rec["Token"])

                    rows.append(
                        {
                            "token": token,
                            "trading_symbol": rec["TradingSymbol"],
                            "strike": strike,
                            "option_type": rec["OptionType"],
                            "exchange": exchange,
                            "lot_size": rec.get("LotSize"),

                            # live fields (filled by ticks)
                            "ltp": None,
                            "change_pct": None,
                            "volume": None,
                            "oi": None,
                            "open": None,
                            "high": None,
                            "low": None,
                            "close": None,
                            "bid": None,
                            "ask": None,
                            "bid_qty": None,
                            "ask_qty": None,
                            "last_update": None,
                        }
                    )
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(f"Skipping invalid contract: {e}")
                    continue

            if not rows:
                logger.error(
                    f"No options found for {symbol} {expiry} on {exchange}"
                )
                return False

            df = pd.DataFrame(rows)

            # ------------------------------------------------------
            # NSE-style ATM-centric filtering
            # ------------------------------------------------------
            
            # Get unique strikes sorted
            all_strikes = sorted(df["strike"].unique())
            
            # Find ATM index
            atm_idx = min(
                range(len(all_strikes)),
                key=lambda i: abs(all_strikes[i] - atm_strike)
            )
            
            # Select count strikes on each side (NSE-style)
            start_idx = max(0, atm_idx - count)
            end_idx = min(len(all_strikes), atm_idx + count + 1)
            
            selected_strikes = all_strikes[start_idx:end_idx]
            
            # Filter dataframe to selected strikes
            df = df[df["strike"].isin(selected_strikes)].copy()
            
            # Ensure we have both CE and PE for each strike
            strike_counts = df.groupby("strike")["option_type"].nunique()
            complete_strikes = strike_counts[strike_counts == 2].index
            df = df[df["strike"].isin(complete_strikes)].copy()
            
            # Sort: strike ascending, then CE before PE
            df["_sort_opt"] = df["option_type"].map({"CE": 0, "PE": 1})
            df = df.sort_values(["strike", "_sort_opt"]).drop(columns="_sort_opt")
            df = df.reset_index(drop=True)

            if df.empty:
                logger.error("No complete option pairs found after filtering")
                return False
                
            # ------------------------------------------------------
            # 🚨 STALE SCRIPTMASTER SAFETY CHECK (MANDATORY)
            # ------------------------------------------------------
            median_strike = float(df["strike"].median())
            steps = pd.Series(sorted(df["strike"].unique())).diff().dropna()
            strike_step = int(steps.median()) if not steps.empty else 0

            # Allow max deviation = 2 strike steps
            if strike_step and abs(median_strike - atm_strike) > (2 * strike_step):
                logger.critical(
                    "🚨 STALE SCRIPTMASTER DETECTED 🚨 | "
                    f"ATM={atm_strike}, median_chain_strike={median_strike}, "
                    f"strike_step={strike_step}"
                )
                return False

            # 🔥 NEW: Validate expiry date
            try:
                expiry_dt = datetime.strptime(expiry, "%d-%b-%Y")
                if expiry_dt.date() < datetime.now().date():
                    logger.error("🚨 EXPIRED CONTRACT | expiry=%s", expiry)
                    return False
                
                if expiry_dt.date() == datetime.now().date():
                    logger.warning("⚠️ EXPIRY DAY DETECTED | expiry=%s", expiry)
            except ValueError:
                logger.error("Invalid expiry format: %s", expiry)
                return False

            # Save state
            self._df = df
            # ✅ FIX: Validate tokens (remove empty/None)
            self._token_set = {str(t) for t in df["token"].tolist() if t and str(t).strip()}

            self._exchange = exchange
            self._symbol = symbol
            self._expiry = expiry
            self._atm = atm_strike
            self._spot_ltp = spot_ltp
            self._fut_ltp = fut_ltp

            logger.info(
                f"✅ Option chain loaded | {exchange} {symbol} {expiry} "
                f"| ATM={atm_strike} | Strikes={len(df['strike'].unique())} "
                f"| Contracts={len(df)} | Range=[{df['strike'].min():.0f} - {df['strike'].max():.0f}]"
            )
            return True

    # ------------------------------------------------------------------
    # BUILD FROM SHOONYA OPTION CHAIN (AUTHORITATIVE)
    # ------------------------------------------------------------------    
    def load_from_shoonya_chain(
        self,
        *,
        exchange: str,
        symbol: str,
        expiry: str,
        atm_strike: int,
        spot_ltp: Optional[float],
        fut_ltp: Optional[float],
        chain: Dict[str, Any],
    ) -> bool:
        """
        🔥 IMPROVED: Load option chain with response validation.
        
        Now validates Shoonya API response structure before processing.
        """
        exchange = exchange.upper()
        symbol = symbol.upper()

        # 🔥 NEW: Validate Shoonya response
        if not isinstance(chain, dict):
            logger.error("Invalid chain response type: %s", type(chain))
            return False
        
        if chain.get("stat") == "Not_Ok":
            logger.error("Shoonya API error: %s", chain.get("emsg", "Unknown error"))
            return False

        rows: List[Dict[str, Any]] = []

        values = chain.get("values") or []
        if not values:
            logger.error("Shoonya option chain empty")
            return False

        import re

        for rec in values:
            try:
                tsym = rec.get("tsym", "")
                if not tsym:
                    raise ValueError("Missing tsym")

                tsym = tsym.upper()

                # Infer option type + strike (EXCHANGE SAFE)
                if exchange == "BFO":
                    # Example: SENSEX26JAN84300CE
                    m = re.search(r"(\d+)(CE|PE)$", tsym)
                    if not m:
                        raise ValueError(f"Cannot infer strike from tsym: {tsym}")

                    strike = int(m.group(1))
                    opt = m.group(2)

                else:
                    # NFO + MCX
                    # Example: NIFTY13JAN26C25900
                    m = re.search(r"(C|P)(\d+)$", tsym)
                    if not m:
                        raise ValueError(f"Cannot infer strike from tsym: {tsym}")

                    strike = int(m.group(2))
                    opt = "CE" if m.group(1) == "C" else "PE"

                # Append row
                rows.append(
                    {
                        "token": str(rec["token"]),
                        "trading_symbol": tsym,
                        "strike": strike,
                        "option_type": opt,
                        "exchange": exchange,
                        "lot_size": None,

                        # live fields
                        "ltp": None,
                        "change_pct": None,
                        "volume": None,
                        "oi": None,
                        "open": None,
                        "high": None,
                        "low": None,
                        "close": None,
                        "bid": None,
                        "ask": None,
                        "bid_qty": None,
                        "ask_qty": None,
                        "last_update": None,
                    }
                )

            except Exception as e:
                logger.warning(f"Skipping invalid Shoonya contract: {e}")
                continue

        if not rows:
            logger.error("No valid contracts from Shoonya chain")
            return False

        df = pd.DataFrame(rows)

        # Ensure CE & PE both exist per strike
        cnt = df.groupby("strike")["option_type"].nunique()
        valid_strikes = cnt[cnt == 2].index
        df = df[df["strike"].isin(valid_strikes)].copy()

        if df.empty:
            logger.error("No complete CE/PE pairs after filtering")
            return False

        # Sort NSE-style
        df["_sort"] = df["option_type"].map({"CE": 0, "PE": 1})
        df = (
            df.sort_values(["strike", "_sort"])
            .drop(columns="_sort")
            .reset_index(drop=True)
        )

        # Commit state
        with self._lock:
            self._df = df
            # ✅ FIX: Validate tokens (remove empty/None)
            self._token_set = {str(t) for t in df["token"].astype(str) if t and str(t).strip()}
            self._exchange = exchange
            self._symbol = symbol
            self._expiry = expiry
            self._atm = atm_strike
            self._spot_ltp = spot_ltp
            self._fut_ltp = fut_ltp

        logger.info(
            f"✅ Option chain loaded from Shoonya | {exchange} {symbol} {expiry} "
            f"| ATM={atm_strike} | Strikes={len(df['strike'].unique())} "
            f"| Contracts={len(df)}"
        )

        return True

    # ------------------------------------------------------------------
    # 🔥 v6.0: PULL-BASED TICK UPDATES (REPLACES CALLBACKS)
    # ------------------------------------------------------------------

    def pull_latest_ticks(self) -> int:
        """
        🔥 NEW v6.0: Pull latest tick data from feed store.
        
        This replaces the push-based update_tick() callback.
        Call this method when you want to refresh prices from the feed.
        
        Returns:
            Number of contracts updated
        """
        # Get all current tick data from feed
        all_ticks = get_all_tick_data()
        
        if not all_ticks:
            return 0
        
        updated_count = 0
        
        with self._lock:
            # Update spot price
            if self._spot_token and self._spot_token in all_ticks:
                spot_tick = all_ticks[self._spot_token]
                if "ltp" in spot_tick:
                    self._spot_ltp = spot_tick["ltp"]
                    updated_count += 1
            
            # Update future price
            if self._fut_token and self._fut_token in all_ticks:
                fut_tick = all_ticks[self._fut_token]
                if "ltp" in fut_tick:
                    self._fut_ltp = fut_tick["ltp"]
                    updated_count += 1
            
            # Update option contracts
            if self._df is None:
                return updated_count
            
            # Map tick fields to dataframe columns
            field_mapping = {
                "ltp": "ltp",
                "pc": "change_pct",
                "v": "volume",
                "oi": "oi",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "bp1": "bid",
                "sp1": "ask",
                "bq1": "bid_qty",
                "sq1": "ask_qty",
            }
            
            # ✅ FIX: Build mask lookup and normalize tokens
            token_to_mask = {}
            for token in self._token_set:
                token_to_mask[token] = self._df["token"] == token
            
            # Update each token in the chain
            for returned_token, tick in all_ticks.items():
                # ✅ FIX: Normalize token (handle both plain and prefixed)
                normalized = returned_token.split("|")[-1] if "|" in returned_token else returned_token
                
                if normalized not in token_to_mask:
                    continue
                
                mask = token_to_mask[normalized]
                
                # Update all available fields
                for src, col in field_mapping.items():
                    if src in tick and tick[src] is not None:
                        self._df.loc[mask, col] = tick[src]
                
                # Update timestamp
                if "tt" in tick:
                    self._df.loc[mask, "last_update"] = tick["tt"]
                else:
                    self._df.loc[mask, "last_update"] = datetime.now()
                
                updated_count += 1
        
        return updated_count

    def pull_ticks_efficient(self) -> int:
        """
        🔥 NEW v6.0: Efficient batch pull for option chain tokens.
        
        More efficient than pull_latest_ticks() for large chains
        as it only fetches tokens we care about.
        
        Returns:
            Number of contracts updated
        """
        with self._lock:
            if self._df is None:
                return 0
            
            # Build token list to fetch
            tokens_to_fetch = list(self._token_set)
            if self._spot_token:
                tokens_to_fetch.append(self._spot_token)
            if self._fut_token:
                tokens_to_fetch.append(self._fut_token)
            
            # ✅ FIX: Build reverse lookup for efficiency
            token_to_mask = {}
            for token in self._token_set:
                token_to_mask[token] = self._df["token"] == token
        
        # Batch fetch (more efficient)
        ticks = get_tick_data_batch(tokens_to_fetch)
        
        if not ticks:
            return 0
        
        updated_count = 0
        
        with self._lock:
            # Update spot
            if self._spot_token and self._spot_token in ticks:
                if "ltp" in ticks[self._spot_token]:
                    self._spot_ltp = ticks[self._spot_token]["ltp"]
                    updated_count += 1
            
            # Update future
            if self._fut_token and self._fut_token in ticks:
                if "ltp" in ticks[self._fut_token]:
                    self._fut_ltp = ticks[self._fut_token]["ltp"]
                    updated_count += 1
            
            # Update options
            field_mapping = {
                "ltp": "ltp",
                "pc": "change_pct",
                "v": "volume",
                "oi": "oi",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "bp1": "bid",
                "sp1": "ask",
                "bq1": "bid_qty",
                "sq1": "ask_qty",
            }
            
            for returned_token, tick in ticks.items():
                # ✅ FIX: Normalize token (handle both plain and prefixed)
                normalized = returned_token.split("|")[-1] if "|" in returned_token else returned_token
                
                if normalized not in token_to_mask:
                    continue
                
                mask = token_to_mask[normalized]
                
                for src, col in field_mapping.items():
                    if src in tick and tick[src] is not None:
                        self._df.loc[mask, col] = tick[src]
                
                self._df.loc[mask, "last_update"] = tick.get("tt", datetime.now())
                updated_count += 1
        # ✅ NEW: Track pull statistics
        with self._lock:
            self._last_pull_time = time.time()
            self._total_pulls += 1
            
        return updated_count

    def get_pull_stats(self) -> Dict[str, Any]:
        """
        🔥 NEW v6.0: Get statistics about tick pulls.
        
        Returns:
            Dictionary with pull metrics
        """
        with self._lock:
            return {
                "last_pull_time": self._last_pull_time,
                "seconds_since_pull": (
                    time.time() - self._last_pull_time 
                    if self._last_pull_time else None
                ),
                "total_pulls": self._total_pulls,
                "tokens_subscribed": len(self._token_set),
                "spot_token": self._spot_token,
                "future_token": self._fut_token,
            }

    def capture_snapshot(self) -> Dict[str, Any]:
        """
        🔥 NEW v6.0: Capture atomic snapshot with fresh ticks and Greeks.
        
        This is the recommended way to get consistent option chain state:
        1. Pull latest ticks
        2. Compute Greeks if needed
        3. Return complete snapshot
        
        Returns:
            Dictionary with complete chain state
        """
        # Pull fresh ticks
        updated = self.pull_ticks_efficient()
        
        # Refresh Greeks if we have enough data
        greek_status = "not_attempted"
        if updated >= 4:
            try:
                success = refresh_greeks(self, min_live_contracts=4)
                greek_status = "computed" if success else "insufficient_coverage"
            except Exception as e:
                greek_status = f"failed: {str(e)[:50]}"
        
        # Return atomic snapshot
        with self._lock:
            return {
                "stats": self.get_stats(),
                "dataframe": self.get_dataframe(copy=True),
                "nse_view": self.get_nse_style_view(),
                "greeks": self.get_greeks(),
                "health": self.get_health_status(),
                "timestamp": datetime.now().isoformat(),
                "contracts_updated": updated,
                "greek_status": greek_status,  # ✅ NEW: Visibility into Greek computation
            }
    # ------------------------------------------------------------------
    # ACCESSORS (THREAD-SAFE)
    # ------------------------------------------------------------------

    def get_dataframe(self, copy: bool = True) -> Optional[pd.DataFrame]:
        """
        🔥 IMPROVED: Return dataframe with optional Greek projection.
        
        Thread-safe with proper locking.
        """
        with self._lock:
            if self._df is None:
                return None

            df = self._df.copy() if copy else self._df

            greeks = getattr(self, "_greeks_df", None)
            # ✅ FIX: Add type check to prevent AttributeError
            if greeks is None or not isinstance(greeks, pd.DataFrame) or greeks.empty:
                return df

            # Normalize Greek columns
            g = greeks.copy()

            # Flatten MultiIndex if present
            if isinstance(g.columns, pd.MultiIndex):
                g.columns = [
                    "_".join([str(x) for x in col if x])
                    for col in g.columns
                ]

            # Normalize strike column
            if "Strike Price" in g.columns:
                g = g.rename(columns={"Strike Price": "strike"})

            greek_map = {
                "IV_CE": ("CE", "iv"),
                "IV_PE": ("PE", "iv"),
                "Delta_CE": ("CE", "delta"),
                "Delta_PE": ("PE", "delta"),
                "Gamma_CE": ("CE", "gamma"),
                "Gamma_PE": ("PE", "gamma"),
                "Theta_CE": ("CE", "theta"),
                "Theta_PE": ("PE", "theta"),
                "Vega_CE": ("CE", "vega"),
                "Vega_PE": ("PE", "vega"),
            }

            for col, (opt_type, target_col) in greek_map.items():
                if col not in g.columns:
                    continue

                sub = g[["strike", col]].dropna()
                if sub.empty:
                    continue

                mask = df["option_type"] == opt_type
                df.loc[mask, target_col] = (
                    df.loc[mask, "strike"]
                    .map(sub.set_index("strike")[col])
                )

            return df

    def get_tokens(self) -> List[str]:
        """Get all option tokens in the chain."""
        with self._lock:
            return list(self._token_set)

    def get_calls(self) -> Optional[pd.DataFrame]:
        """Get only CE (Call) options."""
        with self._lock:
            if self._df is None:
                return None
            return self._df[self._df["option_type"] == "CE"].copy()

    def get_puts(self) -> Optional[pd.DataFrame]:
        """Get only PE (Put) options."""
        with self._lock:
            if self._df is None:
                return None
            return self._df[self._df["option_type"] == "PE"].copy()

    def get_strike_row(self, strike: float) -> Optional[pd.DataFrame]:
        """Get both CE and PE for a specific strike."""
        with self._lock:
            if self._df is None:
                return None
            return self._df[self._df["strike"] == strike].copy()

    def get_atm_contracts(self) -> Optional[pd.DataFrame]:
        """Get CE and PE contracts at ATM strike."""
        with self._lock:
            if self._df is None or self._atm is None:
                return None
            return self._df[self._df["strike"] == self._atm].copy()

    def get_stats(self) -> Dict[str, Any]:
        """
        🔥 IMPROVED: Get chain statistics with thread-safe spot reads.
        """
        with self._lock:
            if self._df is None:
                return {"status": "empty"}

            strikes = self._df["strike"].unique()
            
            # 🔥 FIXED: Thread-safe spot/future reads
            spot_ltp = self._spot_ltp
            fut_ltp = self._fut_ltp
            
            return {
                "status": "loaded",
                "exchange": self._exchange,
                "symbol": self._symbol,
                "expiry": self._expiry,
                "atm": self._atm,
                "spot_ltp": spot_ltp,
                "fut_ltp": fut_ltp,
                "contracts": len(self._df),
                "calls": int((self._df["option_type"] == "CE").sum()),
                "puts": int((self._df["option_type"] == "PE").sum()),
                "strikes": len(strikes),
                "strike_range": {
                    "min": float(strikes.min()),
                    "max": float(strikes.max()),
                },
                "has_live_data": self._df["ltp"].notna().any(),
            }

    def get_nse_style_view(self) -> Optional[pd.DataFrame]:
        """
        Compact NSE-style option chain view.
        
        Columns:
        Strike | CE_LTP | PE_LTP | CE_Volume | PE_Volume | CE_OI | PE_OI | CE_Change% | PE_Change%
        """
        with self._lock:
            if self._df is None:
                return None

            ce = self._df[self._df["option_type"] == "CE"]
            pe = self._df[self._df["option_type"] == "PE"]

            ce_view = ce[
                ["strike", "ltp", "volume", "oi", "change_pct"]
            ].rename(
                columns={
                    "ltp": "CE_LTP",
                    "volume": "CE_Volume",
                    "oi": "CE_OI",
                    "change_pct": "CE_Change%",
                }
            )

            pe_view = pe[
                ["strike", "ltp", "volume", "oi", "change_pct"]
            ].rename(
                columns={
                    "ltp": "PE_LTP",
                    "volume": "PE_Volume",
                    "oi": "PE_OI",
                    "change_pct": "PE_Change%",
                }
            )

            df = ce_view.merge(pe_view, on="strike", how="inner")
            df = df.sort_values("strike").reset_index(drop=True)

            # ✅ FORCE NSE COLUMN ORDER
            ordered_cols = [
                "strike",
                "CE_LTP", "PE_LTP",
                "CE_Volume", "PE_Volume",
                "CE_OI", "PE_OI",
                "CE_Change%", "PE_Change%",
            ]

            df = df[ordered_cols]

            return df
            
    def get_nse_style_view_with_greeks(self) -> Optional[pd.DataFrame]:
        """
        NSE-style option chain view enriched with Greeks.

        Columns:
        strike | ATM |
        CE_LTP | CE_Delta | CE_IV | CE_Volume | CE_OI |
        PE_LTP | PE_Delta | PE_IV | PE_Volume | PE_OI
        """

        with self._lock:
            if self._df is None or not hasattr(self, "_greeks_df") or self._greeks_df is None:
                return None

            # Build NSE-style base view INLINE
            ce = self._df[self._df["option_type"] == "CE"]
            pe = self._df[self._df["option_type"] == "PE"]

            ce_view = ce[
                ["strike", "ltp", "volume", "oi"]
            ].rename(columns={
                "ltp": "CE_LTP",
                "volume": "CE_Volume",
                "oi": "CE_OI",
            })

            pe_view = pe[
                ["strike", "ltp", "volume", "oi"]
            ].rename(columns={
                "ltp": "PE_LTP",
                "volume": "PE_Volume",
                "oi": "PE_OI",
            })

            base = (
                ce_view
                .merge(pe_view, on="strike", how="inner")
                .sort_values("strike")
                .reset_index(drop=True)
            )

            base["ATM"] = base["strike"] == self._atm

            # Copy Greeks while holding lock
            greeks = self._greeks_df.copy()

        # Lock released here

        # Normalize Greeks dataframe safely
        if isinstance(greeks.columns, pd.MultiIndex):
            greeks.columns = [
                "_".join([str(x) for x in col if x])
                for col in greeks.columns
            ]

        # Force strike column normalization
        if "Strike Price" in greeks.columns:
            greeks = greeks.rename(columns={"Strike Price": "strike"})
        elif "Strike Price_" in greeks.columns:
            greeks = greeks.rename(columns={"Strike Price_": "strike"})

        # Normalize Greek column names
        greeks = greeks.rename(columns={
            "Delta_CE": "CE_Delta",
            "Delta_PE": "PE_Delta",
            "Gamma_CE": "CE_Gamma",
            "Gamma_PE": "PE_Gamma",
            "Theta_CE": "CE_Theta",
            "Theta_PE": "PE_Theta",
            "Vega_CE": "CE_Vega",
            "Vega_PE": "PE_Vega",
            "IV_CE": "CE_IV",
            "IV_PE": "PE_IV",
        })

        # Merge base view with Greeks
        merged = base.merge(
            greeks[
                [
                    "strike",
                    "CE_Delta", "PE_Delta",
                    "CE_Gamma", "PE_Gamma",
                    "CE_Theta", "PE_Theta",
                    "CE_Vega", "PE_Vega",
                    "CE_IV", "PE_IV",
                ]
            ],
            on="strike",
            how="left",
        )

        # Final NSE-style column order
        ordered_cols = [
            "strike", "ATM",
            "CE_LTP", "CE_Delta", "CE_IV", "CE_Volume", "CE_OI",
            "PE_LTP", "PE_Delta", "PE_IV", "PE_Volume", "PE_OI",
        ]

        merged = merged[ordered_cols]

        # Beautification (round numeric columns)
        num_cols = merged.select_dtypes("number").columns
        merged[num_cols] = merged[num_cols].round(3)

        return merged

    def get_greeks(self) -> Optional[pd.DataFrame]:
        """Get Greeks dataframe if available."""
        return getattr(self, "_greeks_df", None)

    # ------------------------------------------------------------------
    # 🔥 NEW: HEALTH & DIAGNOSTICS
    # ------------------------------------------------------------------

    def get_health_status(self) -> Dict[str, Any]:
        """
        🔥 NEW: Comprehensive health check for this option chain.
        
        Returns:
            Dictionary with health status and metrics
        """
        with self._lock:
            if self._df is None:
                return {
                    "healthy": False,
                    "status": "not_loaded",
                    "issues": ["Chain not loaded"],
                }

            issues = []
            warnings = []
            
            # Check for live data
            live_count = self._df["ltp"].notna().sum()
            total_contracts = len(self._df)
            
            if live_count == 0:
                issues.append("No live price data")
            elif live_count < total_contracts * 0.5:
                warnings.append(f"Only {live_count}/{total_contracts} contracts have prices")
            
            # Check spot/future prices
            if self._spot_ltp is None and self._fut_ltp is None:
                warnings.append("No underlying price available")
            
            # Check Greeks
            has_greeks = hasattr(self, "_greeks_df") and self._greeks_df is not None
            if has_greeks:
                greek_age = time.time() - self._greeks_ts if self._greeks_ts else None
                if greek_age and greek_age > 60:
                    warnings.append(f"Greeks are {greek_age:.0f}s old")
            
            # Check expiry
            try:
                if self._expiry:
                    expiry_dt = datetime.strptime(self._expiry, "%d-%b-%Y")
                    if expiry_dt.date() < datetime.now().date():
                        issues.append("Contract expired")
                    elif expiry_dt.date() == datetime.now().date():
                        warnings.append("Expiry day")
            except:
                pass
            
            healthy = len(issues) == 0
            
            return {
                "healthy": healthy,
                "status": "active" if healthy else "degraded",
                "issues": issues,
                "warnings": warnings,
                "metrics": {
                    "live_data_coverage": live_count / total_contracts if total_contracts > 0 else 0,
                    "has_greeks": has_greeks,
                    "has_spot": self._spot_ltp is not None,
                    "has_future": self._fut_ltp is not None,
                },
                "timestamp": datetime.now().isoformat(),
            }

    def validate_data_freshness(self, max_age_seconds: int = 60) -> bool:
        """
        🔥 NEW: Check if live data is fresh.
        
        Args:
            max_age_seconds: Maximum age for data to be considered fresh
            
        Returns:
            True if data is fresh, False otherwise
        """
        with self._lock:
            if self._df is None:
                return False
            
            # Check last update times
            last_updates = self._df["last_update"].dropna()
            if last_updates.empty:
                return False
            
            latest_update = last_updates.max()
            if not isinstance(latest_update, datetime):
                return False
            
            age = (datetime.now() - latest_update).total_seconds()
            return age <= max_age_seconds

    def cleanup(self) -> None:
        """
        🔥 NEW: Explicit resource cleanup.
        
        Call this when done with the option chain to free resources.
        """
        with self._lock:
            if self._cleanup_done:
                return
            
            # Stop Greek refresher if running
            if hasattr(self, "_stop_event") and self._stop_event:
                self._stop_event.set()
            
            # Clear data
            self._df = None
            self._token_set.clear()
            
            # Clear Greeks
            if hasattr(self, "_greeks_df"):
                self._greeks_df = None
            
            self._cleanup_done = True
            
            logger.info("OptionChainData cleanup complete")

    def __del__(self):
        """Destructor - ensure cleanup on garbage collection."""
        try:
            self.cleanup()
        except:
            pass


# ============================================================================
# FACTORY FUNCTION (PUBLIC API) - ENHANCED
# ============================================================================

def option_chain(
    *,
    api_client,
    exchange: str,
    symbol: str,
    expiry: Optional[str] = None,
    expiry_index: int = 0,
    atm_strike: Optional[int] = None,
    count: int = 10,
) -> OptionChainData:
    """
    🔥 IMPROVED: High-level factory with session validation.

    Auto logic:
    - Expiry → ScriptMaster nearest if not provided
    - ATM → Spot-based ATM if not provided

    Args:
        api_client: Shoonya API client
        exchange: NFO / BFO / MCX
        symbol: Underlying symbol (e.g., NIFTY, SENSEX50)
        expiry: Specific expiry date (DD-MMM-YYYY) or None for auto
        expiry_index: 0=nearest, 1=next (only if expiry=None)
        atm_strike: Specific ATM strike or None for auto
        count: Number of strikes on each side of ATM (default 10)

    Returns:
        OptionChainData (ready for live feed)
        
    Raises:
        RuntimeError: If FNO details cannot be resolved or session invalid
        ValueError: If expiry or ATM cannot be determined
    """
    
    # 🔥 NEW: Validate client session
    if hasattr(api_client, 'is_logged_in') and not api_client.is_logged_in():
        raise RuntimeError("Client session invalid - please login first")

    # Fetch canonical FNO details
    try:
        fno = get_fno_details(
            api_client=api_client,
            exchange=exchange,
            symbol=symbol,
            expiry_index=expiry_index,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to resolve FNO details: {e}")

    if not fno.get("success"):
        raise RuntimeError(f"Failed to resolve FNO details: {fno.get('error', 'Unknown error')}")

    # Resolve expiry
    option_expiry = expiry or fno.get("option_expiry")
    if not option_expiry:
        raise ValueError(
            f"Option expiry could not be resolved for {symbol} on {exchange}"
        )

    # Resolve ATM (prefer spot, fallback to future)
    atm = atm_strike or fno.get("spot_atm") or fno.get("fut_atm")
    if not atm:
        raise ValueError(
            f"ATM strike could not be resolved for {symbol} on {exchange}"
        )

    # LOG ATM RESOLUTION (SAFETY)
    logger.info(
        f"📍 ATM resolved | symbol={symbol} "
        f"| spot_atm={fno.get('spot_atm')} "
        f"| fut_atm={fno.get('fut_atm')} "
        f"| final_atm={atm}"
    )

    # BUILD FULL OPTION SYMBOL USING ATM
    option_symbol = build_option_symbol(
        exchange=exchange,
        symbol=symbol,
        expiry=option_expiry,
        strike=atm,
        opt_type="CE",
    )

    logger.info(
        "📌 get_option_chain INPUT | "
        f"exchange={exchange}, "
        f"tradingsymbol={option_symbol}, "
        f"ATM={atm}, "
        f"count={count}"
    )

    # CALL SHOONYA OPTION CHAIN
    chain = api_client.get_option_chain(
        exchange=exchange,
        tradingsymbol=option_symbol,
        strikeprice=atm,
        count=count,
    )

    if not chain or "values" not in chain:
        raise RuntimeError("Invalid Shoonya option chain response")

    # LOAD FROM SHOONYA
    oc = OptionChainData()
    ok = oc.load_from_shoonya_chain(
        exchange=exchange,
        symbol=symbol,
        expiry=option_expiry,
        atm_strike=atm,
        spot_ltp=fno.get("spot_ltp"),
        fut_ltp=fno.get("fut_ltp"),
        chain=chain,
    )
    
    # Store spot/future tokens
    oc._spot_token = fno.get("spot_token")
    oc._fut_token = fno.get("fut_token")

    if not ok:
        raise RuntimeError(
            f"Failed to build option chain for {symbol} {option_expiry}"
        )

    logger.info(
        f"🎯 Option chain ready | {exchange} {symbol} "
        f"| Expiry={option_expiry} | ATM={atm}"
    )

    return oc


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _normalize_expiry_for_greeks(expiry: str) -> str:
    """Convert expiry to DDMonYY format required by bs_greeks."""
    expiry = expiry.strip().upper()

    # Already correct format
    if "-" not in expiry and len(expiry) == 7:
        return expiry

    try:
        dt = datetime.strptime(expiry, "%d-%b-%Y")
        return dt.strftime("%d%b%y").upper()
    except ValueError:
        raise ValueError(f"Unsupported expiry format for Greeks: {expiry}")

def _prepare_greeks_df(oc) -> pd.DataFrame:
    """Convert OptionChainData dataframe into pivot format for Greek calculation."""
    df = oc.get_dataframe(copy=True)

    if df is None or df.empty:
        raise ValueError("Empty option chain")

    pivot = df.pivot_table(
        index="strike",
        columns="option_type",
        values=["ltp", "token", "trading_symbol"],
        aggfunc="first"
    )

    pivot.rename(columns={
        "ltp": "Last Price",
        "token": "Token",
        "trading_symbol": "Symbol"
    }, inplace=True)

    pivot.reset_index(inplace=True)
    pivot.rename(columns={"strike": "Strike Price"}, inplace=True)

    return pivot

def calculate_greeks(
    *,
    df: pd.DataFrame,
    spot_price: float,
    expiry: str,
    exchange: str,
    risk_free_rate: float = 0.066,
    config: Optional[GreekConfig] = None,
) -> pd.DataFrame:
    """
    Calculate option Greeks on OptionChainData-derived dataframe.
    Requires dataframe returned by _prepare_greeks_df()
    """

    if config is None:
        config = GREEK_CONFIG

    if spot_price <= 0:
        raise ValueError("Invalid spot price")

    market_close = "23:30" if exchange == "MCX" else "15:30"
    expiry_norm = _normalize_expiry_for_greeks(expiry)
    T = max(time_to_expiry_seconds(expiry_norm, market_close), 1e-6)

    df = df.copy()
    eligible = 0
    computed = 0

    for opt in ("CE", "PE"):
        price_col = ("Last Price", opt)
        if price_col not in df.columns:
            continue

        prices = pd.to_numeric(df[price_col], errors="coerce")
        strikes = pd.to_numeric(df["Strike Price"], errors="coerce")

        ivs = [None] * len(df)
        deltas = [None] * len(df)
        gammas = [None] * len(df)
        thetas = [None] * len(df)
        vegas = [None] * len(df)
        rhos = [None] * len(df)

        for i in range(len(df)):
            price = prices.iloc[i]
            strike = strikes.iloc[i]

            if pd.isna(price) or pd.isna(strike) or price < config.min_price:
                continue

            intrinsic = (
                max(spot_price - strike, 0)
                if opt == "CE"
                else max(strike - spot_price, 0)
            )

            if intrinsic > 0 and price <= intrinsic * 1.01:
                continue

            eligible += 1

            try:
                iv_raw = implied_volatility(
                    price, spot_price, strike, T, risk_free_rate, opt
                )
                sigma = iv_raw / 100 if iv_raw > 1 else iv_raw

                if not (config.min_iv <= sigma <= config.max_iv):
                    continue

                greeks = bs_greeks(
                    S=spot_price,
                    K=strike,
                    T=T,
                    r=risk_free_rate,
                    sigma=sigma,
                    opt_type=opt,
                )

                ivs[i] = iv_raw
                deltas[i] = greeks["delta"]
                gammas[i] = greeks["gamma"]
                thetas[i] = greeks["theta"]
                vegas[i] = greeks["vega"]
                rhos[i] = greeks["rho"]

                computed += 1

            except Exception:
                # INTENTIONAL: Bad instruments are expected
                continue

        df[("IV", opt)] = ivs
        df[("Delta", opt)] = deltas
        df[("Gamma", opt)] = gammas
        df[("Theta", opt)] = thetas
        df[("Vega", opt)] = vegas
        df[("Rho", opt)] = rhos

    coverage = computed / eligible if eligible else 0.0

    if eligible == 0:
        raise GreekCoverageError("No eligible options for Greek calculation")

    if coverage < config.min_coverage:
        raise GreekCoverageError(
            f"Greek coverage too low: {coverage:.1%}"
        )

    return df

def refresh_greeks(
    oc: OptionChainData,
    *,
    min_live_contracts: int = 4
) -> bool:
    """
    🔥 IMPROVED: Calculate and refresh Greeks with thread-safe spot reads.

    Design:
    - Safe to call repeatedly
    - Auto-invalidates stale Greeks on large spot move
    - Thread-safe
    - No partial / stale Greek exposure
    """

    # 🔥 FIXED: Thread-safe spot price read
    with oc._lock:
        spot = oc._spot_ltp or oc._fut_ltp
        last_greek_spot = oc._last_greek_spot
        expiry = oc._expiry
        exchange = oc._exchange

    # Guard: Greeks require valid underlying price
    if spot is None or spot <= 0:
        return False

    # Invalidate cached Greeks on large spot movement
    if last_greek_spot and abs(spot - last_greek_spot) / last_greek_spot > 0.0075:
        with oc._lock:
            oc._greeks_df = None
            oc._last_greek_spot = None
            oc._greeks_ts = None
        return False

    # Ensure sufficient live option prices exist
    df = oc.get_dataframe(copy=True)
    if df is None:
        return False

    live_prices = df["ltp"].notna().sum()
    if live_prices < min_live_contracts:
        return False

    # Prepare pivoted dataframe for Greek calculation
    try:
        pivot = _prepare_greeks_df(oc)
    except Exception as e:
        logger.warning("Failed to prepare Greeks df: %s", e)
        return False

    # Calculate Greeks (may raise coverage error)
    try:
        df_greeks = calculate_greeks(
            df=pivot,
            spot_price=spot,
            expiry=expiry,
            exchange=exchange,
        )
    except GreekCoverageError:
        # Low coverage is normal - skip silently
        return False
    except Exception as e:
        logger.warning("Greek calculation failed: %s", e)
        return False

    # Final safety check (spot didn't move mid-calculation)
    with oc._lock:
        current_spot = oc._spot_ltp or oc._fut_ltp
        
        if current_spot and abs(current_spot - spot) / spot > 0.0075:
            logger.warning("Greek calculation invalidated by spot movement")
            return False
        
        # Atomic commit
        oc._greeks_df = df_greeks
        oc._last_greek_spot = spot
        oc._greeks_ts = time.time()

    return True


def display_option_chain(oc: OptionChainData, style: str = "detailed") -> None:
    """
    Display option chain in console (for debugging)
    
    Args:
        oc: OptionChainData instance
        style: 'detailed' or 'nse' (side-by-side view)
    """
    stats = oc.get_stats()
    
    print("\n" + "="*80)
    print(f"OPTION CHAIN: {stats['symbol']} | {stats['exchange']}")
    print(f"Expiry: {stats['expiry']} | ATM: {stats['atm']}")
    print(f"Spot: {stats.get('spot_ltp', 'N/A')} | Future: {stats.get('fut_ltp', 'N/A')}")
    print(f"Strikes: {stats['strikes']} | Contracts: {stats['contracts']}")
    print("="*80)
    
    if style == "nse":
        df = oc.get_nse_style_view()
        if df is not None:
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', None)
            print(df.to_string(index=False))
    else:
        df = oc.get_dataframe()
        if df is not None:
            display_cols = [
                "strike", "option_type", "ltp", "change_pct", 
                "volume", "oi", "trading_symbol"
            ]
            print(df[display_cols].to_string(index=False))
    
    print("="*80 + "\n")

def _auto_greeks_refresher(
    oc,
    stop_event: threading.Event,
    interval: int = 2,
    min_live_contracts: int = 6,
):
    """
    🔥 v6.0: Auto-refresh Greeks with pull-based tick updates.
    """
    consecutive_failures = 0
    max_consecutive_failures = 10
    
    while not stop_event.is_set():
        try:
            # 🔥 Pull latest ticks before computing Greeks
            updated = oc.pull_ticks_efficient()
            
            success = False  # ✅ FIX: Initialize to avoid NameError
            if updated > 0:
                # Compute Greeks with fresh data
                success = refresh_greeks(oc, min_live_contracts=min_live_contracts)
            
            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(
                        "Greek refresh failed %d times consecutively - "
                        "possible data quality issue",
                        consecutive_failures
                    )
                    consecutive_failures = 0  # Reset to avoid spam
        
        except Exception as exc:
            logger.warning("Greek refresh exception: %s", exc, exc_info=True)
            consecutive_failures += 1

        stop_event.wait(interval)


def live_option_chain(
    *,
    api_client,
    exchange: str,
    symbol: str,
    expiry: Optional[str] = None,
    expiry_index: int = 0,
    atm_strike: Optional[int] = None,
    count: int = 10,
    auto_start_feed: bool = True,
    with_greeks: bool = True
) -> OptionChainData:
    """
    🔥 IMPROVED: Build and activate a LIVE option chain with enhanced coordination.

    This function:
    1️⃣ Resolves expiry + ATM via get_fno_details
    2️⃣ Builds OptionChainData (ScriptMaster-only)
    3️⃣ Starts WebSocket (if required and not already started)
    4️⃣ Prepares option chain for pull-based feed access
    5️⃣ Subscribes option tokens

    SAFE:
    - No orders
    - No trading
    - Read-only market data

    Args:
        api_client: Logged-in ShoonyaClient
        exchange: NFO / BFO / MCX
        symbol: Underlying symbol (e.g. NIFTY, BANKNIFTY, SENSEX)
        expiry: Explicit expiry (DD-MMM-YYYY) or None
        expiry_index: 0=nearest, 1=next (used only if expiry=None)
        atm_strike: Manual ATM override (optional)
        count: Strikes on each side of ATM
        auto_start_feed: Start WebSocket automatically (default True)
        with_greeks: Calculate Greeks lazily after ticks arrive

    Returns:
        OptionChainData (LIVE, subscribed, updating)

    Raises:
        RuntimeError / ValueError on failure
    """

    # Build Option Chain (AUTO SAFE)
    oc = option_chain(
        api_client=api_client,
        exchange=exchange,
        symbol=symbol,
        expiry=expiry,
        expiry_index=expiry_index,
        atm_strike=atm_strike,
        count=count,
    )

    logger.info(
        f"📡 Live option chain requested | {exchange} {symbol} | "
        f"Expiry={oc.get_stats()['expiry']} | ATM={oc.get_stats()['atm']}"
    )

    # 🔥 IMPROVED: Check if feed is already connected
    if auto_start_feed:
        if not is_feed_connected():
            logger.info("Starting live feed...")
            started = start_live_feed(api_client)
            if not started:
                raise RuntimeError("Failed to start live feed")
        else:
            logger.info("Live feed already connected")

    # 🔥 v6.0: No binding needed - chain pulls data on-demand
    logger.info("Option chain ready - will pull ticks on-demand (pull-based architecture)")

    # Subscribe Option Tokens
    tokens = oc.get_tokens()
    subscribe_livedata(api_client, tokens, exchange=exchange)

    # 🔴 SUBSCRIBE SPOT & FUTURE
    extra_tokens = []
    if oc._spot_token:
        extra_tokens.append(oc._spot_token)
    if oc._fut_token:
        extra_tokens.append(oc._fut_token)

    if extra_tokens:
        subscribe_livedata(api_client, extra_tokens, exchange=exchange)

    logger.info(
        f"✅ Live option chain ACTIVE | {exchange} {symbol} | "
        f"Tokens={len(tokens)}"
    )
    
    # 🔥 IMPROVED: Greek refresher with proper cleanup
    stop_event = threading.Event()
    oc._stop_event = stop_event

    if with_greeks:
        logger.info("🧮 Auto Greeks refresher started")

        t = threading.Thread(
            target=_auto_greeks_refresher,
            args=(oc, stop_event),
            daemon=True,
        )
        t.start()

    return oc

def get_nearest_premium_option(
    *,
    oc,
    target_premium: float,
    option_type: Literal["CE", "PE"],
) -> Dict:
    """
    🔥 IMPROVED: Find option with premium closest to target.
    
    Now drops NaN prices explicitly before selection.
    """
    
    df = _prepare_greeks_df(oc)

    price_col = ("Last Price", option_type)
    symbol_col = ("Symbol", option_type)
    token_col = ("Token", option_type)

    if price_col not in df.columns:
        raise ValueError("Price column missing")

    # ✅ FIX: Drop NaN prices explicitly
    sub = df.dropna(subset=[price_col]).copy()
    if sub.empty:
        raise ValueError("No live prices available")

    prices = sub[price_col].astype(float)
    diffs = (prices - target_premium).abs()
    idx = diffs.idxmin()
    row = sub.loc[idx]

    return {
        "symbol": row[symbol_col],
        "token": row[token_col],
        "strike_price": float(row["Strike Price"].iloc[0]),
        "last_price": float(row[price_col]),
        "premium_diff": float(row[price_col] - target_premium),
    }

def get_nearest_greek_option(
    *,
    df: pd.DataFrame,
    greek: str,
    target_value: float,
    option_type: Literal["CE", "PE"],
    use_absolute: bool = True,
) -> Dict:
    """
    🔥 IMPROVED: Find option with Greek value closest to target.
    
    Now guards against missing Greeks.
    """
    
    greek = greek.capitalize()
    greek_col = (greek, option_type)
    price_col = ("Last Price", option_type)
    symbol_col = ("Symbol", option_type)
    token_col = ("Token", option_type)

    if greek_col not in df.columns:
        raise ValueError(f"{greek} not found")

    sub = df.dropna(subset=[greek_col, price_col]).copy()
    if sub.empty:
        raise ValueError(f"No {greek} data available")
        
    values = sub[greek_col].astype(float)

    compare = values.abs() if use_absolute else values
    diffs = (compare - abs(target_value)).abs()

    idx = diffs.idxmin()
    row = sub.loc[idx]

    return {
        "symbol": row[symbol_col],
        "token": row[token_col],
        "strike_price": float(row["Strike Price"].iloc[0]),
        "greek": greek,
        "greek_value": float(row[greek_col]),
        "last_price": float(row[price_col]),
    }
