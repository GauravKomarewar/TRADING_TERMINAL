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
INDEX_TOKENS_REGISTRY = {
    # ===== NSE INDICES =====
    "NIFTY":        ("NSE", "26000"),
    "BANKNIFTY":    ("NSE", "26009"),
    "FINNIFTY":     ("NSE", "26037"),
    "MIDCPNIFTY":   ("NSE", "26074"),
    "NIFTYNXT50":   ("NSE", "26013"),
    "INDIAVIX":     ("NSE", "26017"),

    # ===== BSE INDICES =====
    "SENSEX":       ("BSE", "1"),
    "BANKEX":       ("BSE", "12"),
    "SENSEX50":     ("BSE", "47"),

    # ===== MCX COMMODITIES (Popular) =====
    "CRUDEOIL":     ("MCX", "52929"),
    "CRUDEOILM":    ("MCX", "52929"),
    "GOLD":         ("MCX", "52925"),
    "GOLDM":        ("MCX", "52926"),
    "SILVER":       ("MCX", "52927"),
    "SILVERM":      ("MCX", "52928"),
}

# Subset of most-watched indices (for quick subscription)
MAJOR_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "INDIAVIX",  # Volatility index
]

# Internal state
_subscribed_indices: Set[str] = set()


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
    friendly_names = {
        "NIFTY": "Nifty 50",
        "BANKNIFTY": "Nifty Bank",
        "FINNIFTY": "Nifty Financial",
        "MIDCPNIFTY": "Nifty Midcap 50",
        "NIFTYNXT50": "Nifty Next 50",
        "INDIAVIX": "India VIX",
        "SENSEX": "BSE Sensex",
        "BANKEX": "BSE Bankex",
        "SENSEX50": "BSE Sensex 50",
    }
    
    return {
        "symbol": symbol,
        "exchange": exchange,
        "token": token,
        "name": friendly_names.get(symbol, symbol),
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
    friendly_names = {
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
        "SILVER": "Silver",
        "SILVERM": "Silver Mini",
    }
    
    return {
        symbol: friendly_names.get(symbol, symbol)
        for symbol in INDEX_TOKENS_REGISTRY.keys()
    }
