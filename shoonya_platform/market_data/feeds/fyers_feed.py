# 🔌 Fyers Live Feed Adapter v1.0
"""
Fyers Live Feed — parallel market-data feed for shoonya_platform.

Architecture
------------
Shoonya LiveFeed (live_feed.py)  ←──── primary live feed
  └─ tick_data_store: TTLCache       keyed by "EXCHANGE|TOKEN"   (Shoonya tokens)

Fyers LiveFeed  (this module)    ←──── secondary / redundancy feed
  └─ fyers_tick_store: TTLCache      keyed by "NSE:NIFTY50-INDEX" (Fyers symbols)
  └─ also writes to tick_data_store  when a Shoonya token match is found
     (requires scriptmaster to be loaded; silent no-op if not mapped)

Pull interface mirrors live_feed.py:
    from shoonya_platform.market_data.feeds.fyers_feed import (
        start_fyers_feed,
        stop_fyers_feed,
        get_fyers_tick,
        get_all_fyers_ticks,
        subscribe_fyers,
        is_fyers_feed_active,
    )

Redundancy mode (cross-writing to tick_data_store)
---------------------------------------------------
When FYERS_FEED_CROSS_WRITE=True (default: False) ticks are also injected
into the Shoonya tick_data_store under the mapped "EXCHANGE|TOKEN" key.
This means option-chain and strategy code that reads tick_data_store will
automatically benefit from Fyers data as a fallback source.

Enable via:
    start_fyers_feed(broker, cross_write=True)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tick store (Fyers-symbol keyed)
# ---------------------------------------------------------------------------
_FYERS_TICK_TTL_SECONDS = 300   # same as Shoonya tick_data_store
_FYERS_TICK_MAX_TOKENS  = 10_000

fyers_tick_store: TTLCache = TTLCache(
    maxsize=_FYERS_TICK_MAX_TOKENS,
    ttl=_FYERS_TICK_TTL_SECONDS,
)
_fyers_tick_lock = threading.RLock()

# Feed state
_feed_active: bool = False
_last_tick_time: Optional[float] = None
_feed_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_fyers_feed(
    broker,                              # FyersBrokerClient (avoids circular import)
    symbols: Optional[List[str]] = None,
    cross_write: bool = False,
    timeout: float = 10.0,
) -> bool:
    """
    Start the Fyers WebSocket feed.

    Args:
        broker:      FyersBrokerClient instance (already logged in).
        symbols:     Initial list of Fyers symbols to subscribe (e.g.
                     ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"]).
        cross_write: If True, also inject ticks into the Shoonya
                     tick_data_store when the symbol can be mapped.
        timeout:     Seconds to wait for the first tick before returning.

    Returns:
        True if the feed is connected and receiving ticks, False otherwise.
    """
    global _feed_active, _last_tick_time

    from shoonya_platform.brokers.fyers.symbol_map import FyersSymbolMapper
    mapper = FyersSymbolMapper()

    def _on_tick(raw: dict) -> None:
        global _last_tick_time

        # raw may be a single tick dict or a sub-key dict from FyersDataSocket
        ticks: List[dict] = raw if isinstance(raw, list) else [raw]

        for tick in ticks:
            if not isinstance(tick, dict):
                continue
            sym = tick.get("symbol") or tick.get("sym", "")
            if not sym:
                continue

            normalised = mapper.normalize_fyers_tick(tick)

            # Store in fyers_tick_store
            with _fyers_tick_lock:
                fyers_tick_store[sym] = normalised

            # Optionally cross-write to Shoonya tick_data_store
            if cross_write:
                _cross_write_to_shoonya(sym, normalised, mapper)

            _last_tick_time = time.time()

    def _on_open() -> None:
        logger.info("✅ Fyers WebSocket connected")

    def _on_close() -> None:
        global _feed_active
        logger.warning("⚠️  Fyers WebSocket closed")
        _feed_active = False

    try:
        broker.ensure_session()
        broker.start_websocket(on_tick=_on_tick, on_open=_on_open, on_close=_on_close)

        if symbols:
            broker.subscribe(symbols)

        _feed_active = True
        logger.info("⏳ Fyers feed: waiting up to %.1fs for initial ticks...", timeout)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _last_tick_time:
                logger.info("✅ Fyers live feed active — ticks flowing")
                return True
            time.sleep(0.2)

        if broker.is_logged_in():
            logger.warning("Fyers feed connected but no ticks within %.1fs", timeout)
            return True

        logger.error("❌ Fyers feed failed: broker not logged in")
        return False

    except Exception as exc:
        logger.error("start_fyers_feed error: %s", exc, exc_info=True)
        _feed_active = False
        return False


def stop_fyers_feed(broker=None) -> None:
    """Stop the Fyers feed and optionally the underlying WebSocket."""
    global _feed_active
    _feed_active = False
    if broker is not None:
        try:
            broker.stop_websocket()
        except Exception as exc:
            logger.warning("stop_fyers_feed: broker.stop_websocket error: %s", exc)
    logger.info("Fyers live feed stopped")


def subscribe_fyers(broker, symbols: List[str]) -> None:
    """
    Subscribe to additional Fyers symbols at runtime.

    Args:
        broker:  FyersBrokerClient instance.
        symbols: List of Fyers-format symbols.
    """
    try:
        broker.subscribe(symbols)
        logger.debug("Fyers: subscribed %d extra symbols", len(symbols))
    except Exception as exc:
        logger.warning("subscribe_fyers error: %s", exc)


def get_fyers_tick(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Pull the latest tick for a Fyers symbol from fyers_tick_store.

    Args:
        symbol: Fyers-format symbol (e.g. "NSE:NIFTY50-INDEX").

    Returns:
        Normalised tick dict or None if not yet received.
    """
    with _fyers_tick_lock:
        return fyers_tick_store.get(symbol)


def get_all_fyers_ticks() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot of all current Fyers ticks."""
    with _fyers_tick_lock:
        return dict(fyers_tick_store)


def get_fyers_tick_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Pull ticks for a specific list of Fyers symbols."""
    with _fyers_tick_lock:
        return {s: fyers_tick_store[s] for s in symbols if s in fyers_tick_store}


def is_fyers_feed_active() -> bool:
    """Return True if the Fyers feed is running and has received a recent tick."""
    if not _feed_active:
        return False
    if _last_tick_time is None:
        return False
    return (time.time() - _last_tick_time) < 60  # stale after 60s of silence


def get_fyers_feed_health() -> Dict[str, Any]:
    """Return a health status dict for monitoring / dashboard."""
    return {
        "active":         _feed_active,
        "last_tick_ago":  round(time.time() - _last_tick_time, 1) if _last_tick_time else None,
        "symbols_cached": len(fyers_tick_store),
        "healthy":        is_fyers_feed_active(),
    }


# ---------------------------------------------------------------------------
# Internal: cross-write to Shoonya tick_data_store
# ---------------------------------------------------------------------------


def _cross_write_to_shoonya(
    fyers_sym: str,
    normalised_tick: dict,
    mapper,
) -> None:
    """
    Inject a Fyers tick into the Shoonya tick_data_store.

    The tick is stored under the Shoonya "EXCHANGE|TOKEN" key.
    If the symbol cannot be mapped, the write is silently skipped.
    """
    try:
        from shoonya_platform.market_data.feeds.live_feed import (
            tick_data_store,
            _tick_store_lock,
        )
    except ImportError:
        return

    shoonya_key = mapper.fyers_to_shoonya_key(fyers_sym)
    if not shoonya_key:
        return

    # normalised_tick already uses live_feed-compatible keys (ltp, pc, v, o, h, l, c, ap, oi, tt)
    shoonya_tick = {k: normalised_tick[k] for k in
                    ("ltp", "pc", "v", "o", "h", "l", "c", "ap", "oi", "tt",
                     "bp1", "sp1", "bq1", "sq1")
                    if k in normalised_tick}
    shoonya_tick.setdefault("ltp", 0.0)
    shoonya_tick.setdefault("pc",  0.0)
    shoonya_tick.setdefault("v",   0)
    shoonya_tick.setdefault("oi",  0)
    shoonya_tick["_fyers_source"] = True

    try:
        with _tick_store_lock:
            tick_data_store[shoonya_key] = shoonya_tick
    except Exception as exc:
        logger.debug("_cross_write_to_shoonya write error: %s", exc)
