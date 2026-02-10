# 🔒 PRODUCTION READY - Index Tokens Subscriber
# ===============================================
# Manages subscriptions to index tokens (NIFTY, BANKNIFTY, SENSEX, INDIAVIX, etc.)
# Coordinates with live_feed to maintain real-time index prices

"""
Index Tokens Subscriber - Real-time Index Price Management
============================================================

Purpose:
- Subscribe to major index tokens at market open
- Maintain live index prices in tick_data_store
- Provide convenient access to index data for dashboards and services

CRITICAL NOTES:
- Works WITH live_feed.py (not replacement)
- Uses same tick_data_store for data storage
- Thread-safe via live_feed's state locks
- No callbacks - pull-based like option chain

USAGE:
    from shoonya_platform.market_data.feeds import index_tokens_subscriber
    
    # Subscribe to index tokens
    index_tokens_subscriber.subscribe_index_tokens(api_client)
    
    # Get index data
    data = index_tokens_subscriber.get_index_prices()
    # Returns: {'NIFTY': {'ltp': 25912.5, ...}, 'BANKNIFTY': {...}, ...}
    
    # Get single index
    nifty_data = index_tokens_subscriber.get_index_price('NIFTY')
    # Returns: {'ltp': 25912.5, 'pc': 0.5, 'v': 12345, ...}
"""

import logging
from typing import Dict, Optional, Any, Set, Tuple, List, Union
from shoonya_platform.market_data.feeds.live_feed import (
    subscribe_livedata,
    get_tick_data,
    get_tick_data_batch,
)

logger = logging.getLogger(__name__)

# =============================================================================
# INDEX TOKEN REGISTRY
# =============================================================================
# Key: Index Symbol | Value: (Exchange, Token)
# NOTE: MCX futures tokens change monthly — use resolve_futures_tokens() at
#       startup to dynamically look up the nearest-expiry contract token.
INDEX_TOKENS_REGISTRY = {
    # ===== NSE INDICES (static tokens, never change) =====
    "NIFTY":        ("NSE", "26000"),
    "BANKNIFTY":    ("NSE", "26009"),
    "FINNIFTY":     ("NSE", "26037"),
    "MIDCPNIFTY":   ("NSE", "26074"),
    "NIFTYNXT50":   ("NSE", "26013"),
    "INDIAVIX":     ("NSE", "26017"),

    # ===== BSE INDICES (static tokens) =====
    "SENSEX":       ("BSE", "1"),
    "BANKEX":       ("BSE", "12"),
    "SENSEX50":     ("BSE", "47"),

    # ===== MCX COMMODITIES (tokens resolved at startup) =====
    "CRUDEOIL":     ("MCX", "52929"),
    "CRUDEOILM":    ("MCX", "52929"),
    "GOLD":         ("MCX", "52925"),
    "GOLDM":        ("MCX", "52926"),
    "GOLDPETAL":    ("MCX", None),    # resolved dynamically
    "SILVER":       ("MCX", "52927"),
    "SILVERM":      ("MCX", "52928"),
    "SILVERMIC":    ("MCX", None),    # resolved dynamically
    "NATGASMINI":   ("MCX", None),    # resolved dynamically
}

# ── Futures that need dynamic token resolution via searchscrip ──
# Key: our registry symbol | Value: search text for Shoonya API
MCX_FUTURES_SEARCH = {
    "GOLDPETAL":   "GOLDPETAL",
    "SILVERMIC":   "SILVERMIC",
    "NATGASMINI":  "NATGASMINI",
    "CRUDEOILM":   "CRUDEOILM",
}

# ── Ticker ribbon config (consumed by dashboard frontend) ──
STICKY_SYMBOLS = ["INDIAVIX", "NIFTY"]
TICKER_SYMBOLS = [
    "INDIAVIX", "NIFTY",               # sticky
    "SENSEX", "BANKNIFTY",              # rotating
    "GOLDPETAL", "SILVERMIC",           # rotating
    "NATGASMINI", "CRUDEOILM",         # rotating
    "FINNIFTY",                          # rotating
]

# All indices the system should subscribe to at startup
MAJOR_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "INDIAVIX",
    "FINNIFTY",
    "GOLDPETAL",
    "SILVERMIC",
    "NATGASMINI",
    "CRUDEOILM",
]

# Internal state
_subscribed_indices: Set[str] = set()


# =============================================================================
# DYNAMIC FUTURES TOKEN RESOLUTION
# =============================================================================

def resolve_futures_tokens(api_client: Any) -> int:
    """
    Dynamically resolve MCX futures tokens for the nearest-expiry contract.

    Uses searchscrip() to find the nearest available futures contract for each
    symbol in MCX_FUTURES_SEARCH, then updates INDEX_TOKENS_REGISTRY in-place.

    Call this ONCE at startup, before subscribe_index_tokens().

    Returns:
        Number of tokens successfully resolved.
    """
    global INDEX_TOKENS_REGISTRY
    resolved = 0

    for sym, search_text in MCX_FUTURES_SEARCH.items():
        try:
            result = api_client.searchscrip(exchange="MCX", searchtext=search_text)
            if not result or result.get("stat") != "Ok":
                logger.warning(f"⚠️  searchscrip returned no results for {sym}")
                continue

            values = result.get("values", [])
            if not values:
                logger.warning(f"⚠️  No scrip found for {sym}")
                continue

            # Filter to futures only (instname contains 'FUT' or tsym ends with FUT)
            futures = [
                v for v in values
                if v.get("instname", "").upper() in ("FUTCOM", "FUT")
                or "FUT" in v.get("tsym", "").upper()
            ]

            if not futures:
                # If no explicit FUT filter match, take the first result
                futures = values

            # Sort by expiry (earliest first) — Shoonya returns exd as DD-MMM-YYYY
            def parse_expiry(v):
                """Try to parse expiry date for sorting."""
                exd = v.get("exd", "")
                if not exd:
                    return "9999-99-99"
                try:
                    from datetime import datetime
                    return datetime.strptime(exd, "%d-%b-%Y").strftime("%Y-%m-%d")
                except Exception:
                    return exd

            futures.sort(key=parse_expiry)

            # Take the nearest expiry
            nearest = futures[0]
            token = nearest.get("token", "")
            tsym = nearest.get("tsym", sym)
            exd = nearest.get("exd", "?")

            if token:
                INDEX_TOKENS_REGISTRY[sym] = ("MCX", str(token))
                resolved += 1
                logger.info(f"✅ Resolved {sym} → token={token} tsym={tsym} exp={exd}")
            else:
                logger.warning(f"⚠️  Token missing in scrip result for {sym}")

        except Exception as e:
            logger.warning(f"⚠️  Failed to resolve {sym}: {e}")

    logger.info(f"📊 Resolved {resolved}/{len(MCX_FUTURES_SEARCH)} MCX futures tokens")
    return resolved


# =============================================================================
# SUBSCRIPTION MANAGEMENT
# =============================================================================

def subscribe_index_tokens(
    api_client: Any,  # ShoonyaClient or ShoonyaApiProxy
    indices: Optional[list] = None,
    auto_start: bool = True,
) -> Tuple[int, List[str]]:
    """
    Subscribe to index tokens via live_feed.
    
    Args:
        api_client: ShoonyaClient instance (must be logged in)
        indices: List of index names (e.g., ['NIFTY', 'BANKNIFTY'])
                 If None, subscribes to MAJOR_INDICES
        auto_start: Whether to start live feed if not already running
        
    Returns:
        (count_subscribed, list_of_symbols)
        
    Example:
        count, symbols = subscribe_index_tokens(api_client, ['NIFTY', 'BANKNIFTY'])
        print(f"Subscribed to {count} indices: {symbols}")
    """
    global _subscribed_indices
    
    if not api_client.is_logged_in():
        logger.error("❌ Cannot subscribe - api_client not logged in")
        return 0, []
    
    # Default to major indices if not specified
    if indices is None:
        indices = MAJOR_INDICES
    
    # Validate and collect tokens
    tokens_to_subscribe = []
    valid_symbols = []
    
    for symbol in indices:
        symbol = symbol.upper()
        
        if symbol not in INDEX_TOKENS_REGISTRY:
            logger.warning(f"⚠️  Index '{symbol}' not in registry - skipping")
            continue
        
        exchange, token = INDEX_TOKENS_REGISTRY[symbol]
        if not token:
            logger.warning(f"⚠️  Token not resolved for '{symbol}' — skipping (run resolve_futures_tokens first)")
            continue
        tokens_to_subscribe.append(token)
        valid_symbols.append(symbol)
        _subscribed_indices.add(symbol)
    
    if not tokens_to_subscribe:
        logger.warning("No valid indices to subscribe")
        return 0, []
    
    # Subscribe via live_feed
    try:
        # Determine exchanges (most will be NSE, some BSE, some MCX)
        # Real API would need per-token exchange - we'll use NFO as default
        # and individual exchanges for each
        exchanges = set()
        for symbol in valid_symbols:
            exc, _ = INDEX_TOKENS_REGISTRY[symbol]
            exchanges.add(exc)
        
        # Subscribe each exchange's tokens
        for exc in exchanges:
            exc_tokens = [
                INDEX_TOKENS_REGISTRY[s][1]
                for s in valid_symbols
                if INDEX_TOKENS_REGISTRY[s][0] == exc
            ]
            
            if exc_tokens:
                success = subscribe_livedata(
                    api_client,
                    exc_tokens,
                    exchange=exc
                )
                
                if not success:
                    logger.warning(f"⚠️  Failed to subscribe {exc} tokens")
                    continue
        
        logger.info(
            f"✅ Subscribed to {len(valid_symbols)} index tokens: {valid_symbols}"
        )
        return len(valid_symbols), valid_symbols
        
    except Exception as e:
        logger.error(f"❌ Error subscribing to index tokens: {e}", exc_info=True)
        return 0, []


def get_subscribed_indices() -> List[str]:
    """
    Get list of currently subscribed index symbols.
    
    Returns:
        List of subscribed index names (e.g., ['NIFTY', 'BANKNIFTY', 'SENSEX'])
    """
    global _subscribed_indices
    return sorted(list(_subscribed_indices))


# =============================================================================
# DATA RETRIEVAL (PULL-BASED FROM TICK_DATA_STORE)
# =============================================================================

def get_index_price(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get latest price data for a single index.
    
    Args:
        symbol: Index symbol (e.g., 'NIFTY', 'BANKNIFTY')
        
    Returns:
        Dict with latest tick data or None if not available
        
    Example:
        data = get_index_price('NIFTY')
        if data:
            print(f"NIFTY LTP: {data.get('ltp')}, Change: {data.get('pc')}%")
    """
    symbol = symbol.upper()
    
    if symbol not in INDEX_TOKENS_REGISTRY:
        logger.debug(f"Symbol '{symbol}' not in registry")
        return None
    
    exchange, token = INDEX_TOKENS_REGISTRY[symbol]
    
    if not token:
        logger.debug(f"Token not resolved for {symbol}")
        return None
    
    # Pull from tick_data_store via live_feed
    tick_data = get_tick_data(token)
    
    if not tick_data:
        logger.debug(f"No tick data for {symbol} ({exchange}:{token})")
        return None
    
    # Enrich with symbol info
    tick_data['symbol'] = symbol
    tick_data['exchange'] = exchange
    tick_data['token'] = token
    
    return tick_data


def get_index_prices(
    indices: Optional[list] = None,
    include_missing: bool = False,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Get latest price data for multiple indices efficiently.
    
    Args:
        indices: List of index symbols. If None, returns all subscribed.
        include_missing: If True, include indices with no data. If False, omit.
        
    Returns:
        Dict mapping symbol → tick_data or None
        
    Example:
        data = get_index_prices(['NIFTY', 'BANKNIFTY', 'INDIAVIX'])
        print(data['NIFTY']['ltp'])  # Get NIFTY LTP
        print(data['INDIAVIX']['ltp'])  # Get VIX level
    """
    global _subscribed_indices
    
    if indices is None:
        indices = get_subscribed_indices()
    
    if not indices:
        logger.debug("No indices to fetch")
        return {}
    
    result = {}
    
    # Collect all tokens to fetch
    tokens = []
    symbol_map = {}  # token → symbol
    
    for symbol in indices:
        symbol = symbol.upper()
        if symbol not in INDEX_TOKENS_REGISTRY:
            continue
        
        exchange, token = INDEX_TOKENS_REGISTRY[symbol]
        if not token:
            continue  # token not resolved yet
        tokens.append(token)
        symbol_map[token] = (symbol, exchange)
    
    if not tokens:
        return {}
    
    # Batch fetch from tick_data_store
    batch_data = get_tick_data_batch(tokens)
    
    # Reorganize by symbol
    for symbol in indices:
        symbol = symbol.upper()
        if symbol not in INDEX_TOKENS_REGISTRY:
            if include_missing:
                result[symbol] = None
            continue
        
        exchange, token = INDEX_TOKENS_REGISTRY[symbol]
        
        if token in batch_data:
            data = batch_data[token].copy()
            data['symbol'] = symbol
            data['exchange'] = exchange
            data['token'] = token
            result[symbol] = data
        elif include_missing:
            result[symbol] = None
        # else: omit this symbol
    
    return result


def get_index_ltp_map() -> Dict[str, Optional[float]]:
    """
    Quick access to just LTP (last traded price) for all subscribed indices.
    Useful for dashboards that only need prices, not full tick details.
    
    Returns:
        Dict mapping symbol → LTP (float or None)
        
    Example:
        prices = get_index_ltp_map()
        print(f"NIFTY at {prices.get('NIFTY', 'N/A')}")
    """
    data = get_index_prices()
    return {
        symbol: (tick.get('ltp') if tick else None)
        for symbol, tick in data.items()
    }


# =============================================================================
# METADATA HELPERS
# =============================================================================

_FRIENDLY_NAMES = {
    "NIFTY": "Nifty 50",
    "BANKNIFTY": "Nifty Bank",
    "FINNIFTY": "Nifty Financial",
    "MIDCPNIFTY": "Nifty Midcap 50",
    "NIFTYNXT50": "Nifty Next 50",
    "INDIAVIX": "India VIX",
    "SENSEX": "BSE Sensex",
    "BANKEX": "BSE Bankex",
    "SENSEX50": "BSE Sensex 50",
    "CRUDEOIL": "Crude Oil",
    "CRUDEOILM": "Crude Oil Mini",
    "GOLD": "Gold",
    "GOLDM": "Gold Mini",
    "GOLDPETAL": "Gold Petal",
    "SILVER": "Silver",
    "SILVERM": "Silver Mini",
    "SILVERMIC": "Silver Micro",
    "NATGASMINI": "Natural Gas Mini",
}


def get_index_metadata(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get metadata about an index (exchange, token, full name).
    
    Args:
        symbol: Index symbol (e.g., 'NIFTY')
        
    Returns:
        Dict with exchange, token, or None if not found
    """
    symbol = symbol.upper()
    
    if symbol not in INDEX_TOKENS_REGISTRY:
        return None
    
    exchange, token = INDEX_TOKENS_REGISTRY[symbol]
    
    # Friendly names
    return {
        "symbol": symbol,
        "exchange": exchange,
        "token": token,
        "name": _FRIENDLY_NAMES.get(symbol, symbol),
    }


def is_index_available(symbol: str) -> bool:
    """
    Check if an index is available in registry and has live data.
    
    Args:
        symbol: Index symbol
        
    Returns:
        True if index has live tick data available
    """
    data = get_index_price(symbol)
    return data is not None and len(data) > 0


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

def reset_subscriptions():
    """
    Clear internal subscription state.
    Use after unsubscribing from live_feed.
    """
    global _subscribed_indices
    _subscribed_indices.clear()
    logger.info("Index subscriptions reset")


def get_all_available_indices() -> Dict[str, str]:
    """
    Get all indices available in registry.
    
    Returns:
        Dict mapping symbol → friendly name
    """
    return {
        symbol: _FRIENDLY_NAMES.get(symbol, symbol)
        for symbol in INDEX_TOKENS_REGISTRY.keys()
    }
