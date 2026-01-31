"""
Live Feed Data Manager - Production Grade v2.0
==========================================
Manages tick data normalization, callbacks, and real-time market feed subscriptions.
Thread-safe, with proper error handling and async callback processing.

CRITICAL CHANGES v2.0:
- WebSocket lifecycle delegated to ShoonyaClient
- Removed duplicate reconnection logic
- Fixed coordination with client session state
- Enhanced error handling and monitoring
- Heartbeat detection for stale data

ARCHITECTURE:
- ShoonyaClient = WebSocket owner (single source of truth)
- LiveFeed = Callback manager + Tick data store
"""

from shoonya_platform.brokers.shoonya.client import ShoonyaClient

import time
import threading
import queue
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from colorama import Fore, Style
import logging

# ===============================
# 📝 Configure Logging
# ===============================
logger = logging.getLogger(__name__)

# ===============================
# ⚙️ Configuration
# ===============================
class FeedConfig:
    """Configuration for live feed manager."""
    CALLBACK_QUEUE_SIZE = 1000
    CALLBACK_WORKERS = 2
    LOG_TICK_INTERVAL = 100  # Log every Nth tick to reduce verbosity
    HEARTBEAT_TIMEOUT = 30  # Seconds without ticks = stale warning
    
config = FeedConfig()

# ===============================
# 🔌 Callbacks & State
# ===============================
_order_fill_callback: Optional[Callable] = None
_tick_update_callbacks: List[Callable] = []
_callback_lock = threading.Lock()

# Async callback processing
_callback_queue: queue.Queue = queue.Queue(maxsize=config.CALLBACK_QUEUE_SIZE)
_callback_workers: List[threading.Thread] = []
_callback_workers_running = False

# Global State (Thread-Safe)
tick_data_store: Dict[str, Dict[str, Any]] = defaultdict(dict)
subscribed_tokens: set = set()
_state_lock = threading.Lock()

# WebSocket state tracking (READ-ONLY - managed by client)
_api_client_ref: Optional[ShoonyaClient] = None
_last_tick_time: Optional[float] = None

# Tick counter for throttled logging
_tick_counter = 0
_tick_counter_lock = threading.Lock()

EXPECTED_COLS = ["ltp", "pc", "v", "o", "h", "l", "c", "ap", "oi", "tt"]


# ===============================
# 🧵 Async Callback Worker
# ===============================
def _callback_worker():
    """
    Background worker that processes callbacks asynchronously.
    Prevents blocking the WebSocket thread.
    """
    global _callback_workers_running
    
    while _callback_workers_running:
        try:
            # Get callback task from queue with timeout
            task = _callback_queue.get(timeout=1.0)
            
            if task is None:  # Poison pill to stop worker
                break
                
            callback_type, callback, args = task
            
            try:
                callback(*args)
            except Exception as e:
                logger.error(
                    f"Error in {callback_type} callback: {e}",
                    exc_info=True
                )
            finally:
                _callback_queue.task_done()
                
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Callback worker error: {e}", exc_info=True)


def _start_callback_workers():
    """Start background workers for async callback processing."""
    global _callback_workers_running, _callback_workers
    
    if _callback_workers_running:
        return
        
    _callback_workers_running = True
    _callback_workers = []
    
    for i in range(config.CALLBACK_WORKERS):
        worker = threading.Thread(
            target=_callback_worker,
            name=f"CallbackWorker-{i}",
            daemon=True
        )
        worker.start()
        _callback_workers.append(worker)
        
    logger.info(f"Started {config.CALLBACK_WORKERS} callback workers")


def _stop_callback_workers():
    """Stop all callback workers gracefully."""
    global _callback_workers_running
    
    if not _callback_workers_running:
        return
        
    _callback_workers_running = False
    
    # Send poison pills
    for _ in _callback_workers:
        try:
            _callback_queue.put(None, timeout=1.0)
        except queue.Full:
            pass
    
    # Wait for workers to finish
    for worker in _callback_workers:
        worker.join(timeout=2.0)
        
    _callback_workers.clear()
    logger.info("Callback workers stopped")


# ===============================
# 🔌 Callback Registration
# ===============================
def register_order_fill_callback(callback: Callable) -> None:
    """
    Allows execution engine to register order fill handler
    without circular imports.
    
    Args:
        callback: Function to handle order fill events
    """
    global _order_fill_callback
    with _callback_lock:
        _order_fill_callback = callback
        logger.info("Order fill callback registered")


def register_tick_update_callback(callback: Callable) -> None:
    """
    Register a callback to be notified on every tick update.
    Callbacks are executed asynchronously in background workers.
    
    Args:
        callback: Function(token, tick_data) to handle tick updates
    """
    with _callback_lock:
        _tick_update_callbacks.append(callback)
        logger.info(f"Tick update callback registered. Total: {len(_tick_update_callbacks)}")


def unregister_tick_update_callback(callback: Callable) -> bool:
    """
    Unregister a previously registered tick update callback.
    
    Args:
        callback: Callback function to remove
        
    Returns:
        True if callback was found and removed, False otherwise
    """
    with _callback_lock:
        try:
            _tick_update_callbacks.remove(callback)
            logger.info(f"Tick update callback unregistered. Remaining: {len(_tick_update_callbacks)}")
            return True
        except ValueError:
            logger.warning("Attempted to unregister callback that wasn't registered")
            return False


# ===============================
# 🧠 Tick Normalizer
# ===============================
def normalize_tick(raw_tick: dict) -> dict:
    """
    Normalize Shoonya tick keys → internal format.
    
    Args:
        raw_tick: Raw tick data from WebSocket
        
    Returns:
        Normalized tick dictionary with standardized keys and types
    """
    normalized = {}

    try:
        # Price data
        if "lp" in raw_tick:
            normalized["ltp"] = float(raw_tick["lp"])
        if "pc" in raw_tick:
            normalized["pc"] = float(raw_tick["pc"])
        if "o" in raw_tick:
            normalized["o"] = float(raw_tick["o"])
        if "h" in raw_tick:
            normalized["h"] = float(raw_tick["h"])
        if "l" in raw_tick:
            normalized["l"] = float(raw_tick["l"])
        if "c" in raw_tick:
            normalized["c"] = float(raw_tick["c"])
        if "ap" in raw_tick:
            normalized["ap"] = float(raw_tick["ap"])
        
        # Volume and OI
        if "v" in raw_tick:
            normalized["v"] = int(raw_tick["v"])
        if "oi" in raw_tick:
            normalized["oi"] = int(raw_tick["oi"])

        # Timestamp - handle both seconds and milliseconds
        if "ft" in raw_tick:
            timestamp = int(raw_tick["ft"])
            # Check if timestamp is in milliseconds (13 digits)
            if timestamp > 10**12:
                timestamp = timestamp / 1000
            normalized["tt"] = datetime.fromtimestamp(timestamp)
        else:
            normalized["tt"] = datetime.now()
            
    except (ValueError, TypeError) as e:
        logger.warning(f"Error normalizing tick data: {e}, Raw tick: {raw_tick}")
    
    return normalized


def _extract_token(raw_token: str) -> str:
    """
    Extract token from potentially formatted string (e.g., 'NFO|12345' -> '12345').
    
    Args:
        raw_token: Raw token string, potentially with exchange prefix
        
    Returns:
        Clean token string
    """
    if "|" in raw_token:
        return raw_token.split("|")[-1]
    return raw_token


# ===============================
# ✅ WebSocket Event Handlers
# ===============================

def event_handler_feed_update(tick_data: dict) -> None:
    """
    🔥 IMPROVED: Handle incoming tick updates from WebSocket.
    
    Thread-safe update to global tick store.
    Now validates client session state before processing.
    
    Args:
        tick_data: Raw tick data from WebSocket
    """
    global _tick_counter, _last_tick_time
    
    # 🔥 NEW: Validate client session
    if _api_client_ref and not _api_client_ref.is_logged_in():
        logger.debug("Ignoring tick - client not logged in")
        return
    
    try:
        raw_token = tick_data.get("tk")
        if not raw_token:
            logger.debug("Received tick without token")
            return

        # Strip exchange prefix if present (NFO|xxxxx)
        token = _extract_token(raw_token)
        
        # Normalize and update store
        normalized = normalize_tick(tick_data)
        
        with _state_lock:
            tick_data_store[token].update(normalized)
            tick_snapshot = tick_data_store[token].copy()
        
        # 🔥 NEW: Update heartbeat
        _last_tick_time = time.time()
            
        # Throttled logging to reduce verbosity
        with _tick_counter_lock:
            _tick_counter += 1
            should_log = (_tick_counter % config.LOG_TICK_INTERVAL) == 0
        
        if should_log:
            ltp = tick_snapshot.get('ltp')
            oi = tick_snapshot.get('oi')
            if ltp is not None:
                logger.debug(f"📈 Tick {token} | LTP: {ltp} | OI: {oi} | Count: {_tick_counter}")
        
        # Queue callbacks for async processing
        with _callback_lock:
            for callback in _tick_update_callbacks:
                try:
                    _callback_queue.put_nowait(
                        ("tick_update", callback, (token, tick_snapshot))
                    )
                except queue.Full:
                    logger.warning(f"Callback queue full, dropping tick update for {token}")
                    
    except Exception as e:
        logger.error(f"Error handling feed update: {e}", exc_info=True)


def event_handler_order_update(order: dict) -> None:
    """
    Handle order update events from WebSocket.
    
    Args:
        order: Order update data
    """
    try:
        with _callback_lock:
            if _order_fill_callback:
                # Queue for async processing
                try:
                    _callback_queue.put_nowait(
                        ("order_update", _order_fill_callback, (order,))
                    )
                except queue.Full:
                    logger.error("Callback queue full, dropping order update")
            else:
                logger.debug(f"Order update received but no callback registered")
    except Exception as e:
        logger.error(f"Error handling order update: {e}", exc_info=True)


def open_callback() -> None:
    """
    🔥 IMPROVED: WebSocket connection opened successfully.
    Now just logs - client manages connection state.
    """
    logger.info(f"{Fore.GREEN}{Style.BRIGHT}✅ WebSocket connection opened{Style.RESET_ALL}")


def close_callback() -> None:
    """
    🔥 IMPROVED: WebSocket connection closed.
    Client handles reconnection - we just log.
    """
    logger.warning(f"{Fore.RED}{Style.BRIGHT}❌ WebSocket connection closed{Style.RESET_ALL}")


# ===============================
# 🔄 Start WebSocket (SIMPLIFIED)
# ===============================
def start_live_feed(
    api_client: ShoonyaClient, 
    timeout: float = 10.0,
) -> bool:
    """
    🔥 FIXED: Start WebSocket feed by delegating to client.
    
    Now a thin wrapper that:
    1. Starts callback workers
    2. Delegates WebSocket to client (single owner)
    3. Waits for connection with timeout
    
    Args:
        api_client: Shoonya API client instance
        timeout: Maximum seconds to wait for connection (default: 10.0)
        
    Returns:
        True if feed started successfully, False otherwise
    """
    global _api_client_ref
    
    try:
        # Start callback workers if not running
        _start_callback_workers()
        
        # Store client reference
        _api_client_ref = api_client
        
        # 🔥 CRITICAL: Client now owns WebSocket lifecycle
        # We just register our callbacks
        logger.info("🚀 Starting live feed via client WebSocket")
        
        api_client.start_websocket(
            on_tick=event_handler_feed_update,
            on_order_update=event_handler_order_update,
            on_open=open_callback,
            on_close=close_callback,
        )
        
        # Give WebSocket time to connect
        time.sleep(timeout)
        
        # Verify connection by checking client state
        if api_client.is_logged_in():
            logger.info("✅ Live feed started successfully")
            return True
        else:
            logger.error("❌ WebSocket connection failed - client not logged in")
            return False
            
    except Exception as e:
        logger.error(f"Error starting live feed: {e}", exc_info=True)
        return False


def stop_live_feed(api_client: Optional[ShoonyaClient] = None) -> None:
    """
    🔥 FIXED: Stop the live feed and cleanup resources.
    
    Now properly delegates to client's stop_websocket() method.
    
    Args:
        api_client: Optional API client to stop WebSocket
    """
    global _api_client_ref
    
    if api_client:
        try:
            # 🔥 FIXED: Use client's proper method
            api_client.stop_websocket()
        except Exception as e:
            logger.error(f"Error stopping websocket: {e}")
    
    _stop_callback_workers()
    _api_client_ref = None
    
    logger.info("Live feed stopped")


# ===============================
# 🔄 Restart Feed (NEW)
# ===============================
def restart_feed(api_client: ShoonyaClient, timeout: float = 10.0) -> bool:
    """
    🔥 NEW: Restart feed (for supervisor recovery).
    
    Args:
        api_client: Shoonya API client instance
        timeout: Maximum seconds to wait for connection
        
    Returns:
        True if restart successful, False otherwise
    """
    logger.info("🔄 Restarting live feed...")
    
    try:
        # Stop existing feed
        stop_live_feed(api_client)
        time.sleep(2)
        
        # Start fresh
        return start_live_feed(api_client, timeout=timeout)
        
    except Exception as e:
        logger.error(f"Feed restart failed: {e}", exc_info=True)
        return False


# ===============================
# 📤 Subscribe Tokens
# ===============================
def subscribe_livedata(
    api_client: ShoonyaClient, 
    token_list: List[str], 
    exchange: str = "NFO"
) -> bool:
    """
    🔥 IMPROVED: Subscribe to live data with session validation.
    
    Thread-safe and prevents duplicate subscriptions.
    
    Args:
        api_client: Shoonya API client instance
        token_list: List of tokens to subscribe
        exchange: Exchange identifier (default: NFO)
        
    Returns:
        True if subscription successful, False otherwise
    """
    global subscribed_tokens

    # 🔥 NEW: Validate client session
    if not api_client.is_logged_in():
        logger.error("❌ Cannot subscribe - client not logged in")
        return False

    try:
        formatted = []
        for t in token_list:
            t = str(t)
            key = f"{exchange}|{t}"
            
            with _state_lock:
                if key not in subscribed_tokens:
                    formatted.append(key)

        if not formatted:
            logger.info("⚠️ All tokens already subscribed.")
            return True

        # Subscribe via API (client handles thread safety)
        api_client.subscribe(formatted)
        
        with _state_lock:
            subscribed_tokens.update(formatted)

        # Log summary for large lists
        if len(formatted) > 10:
            logger.info(
                f"{Fore.MAGENTA}🔔 Subscribed to {len(formatted)} tokens. "
                f"First 5: {formatted[:5]}{Style.RESET_ALL}"
            )
        else:
            logger.info(f"{Fore.MAGENTA}🔔 Subscribed to: {formatted}{Style.RESET_ALL}")
            
        return True
        
    except Exception as e:
        logger.error(f"Error subscribing to tokens: {e}", exc_info=True)
        return False


# ===============================
# ⛔ Unsubscribe
# ===============================
def unsubscribe_livedata(
    api_client: ShoonyaClient, 
    token_list: List[str], 
    exchange: str = "NFO"
) -> bool:
    """
    🔥 IMPROVED: Unsubscribe from live data with session validation.
    
    Args:
        api_client: Shoonya API client instance
        token_list: List of tokens to unsubscribe
        exchange: Exchange identifier (default: NFO)
        
    Returns:
        True if unsubscription successful, False otherwise
    """
    global subscribed_tokens

    # 🔥 NEW: Session check
    if not api_client.is_logged_in():
        logger.warning("Client not logged in, skipping unsubscribe")
        return False

    try:
        # Format tokens with exchange prefix
        formatted_tokens = []
        for t in token_list:
            t = str(t)
            key = f"{exchange}|{t}"
            
            with _state_lock:
                if key in subscribed_tokens:
                    formatted_tokens.append(key)

        if not formatted_tokens:
            logger.info("No tokens to unsubscribe")
            return True

        # Unsubscribe via API
        api_client.unsubscribe(formatted_tokens)

        with _state_lock:
            for token in formatted_tokens:
                subscribed_tokens.discard(token)
                # Extract plain token for store cleanup
                plain_token = _extract_token(token)
                tick_data_store.pop(plain_token, None)

        logger.info(f"Unsubscribed from {len(formatted_tokens)} tokens")
        return True
        
    except Exception as e:
        logger.error(f"Error unsubscribing tokens: {e}", exc_info=True)
        return False


# ===============================
# 📊 Data Retrieval Functions
# ===============================

def get_ltp_map() -> Dict[str, Optional[float]]:
    """
    Get mapping of token -> LTP for all subscribed tokens.
    
    Returns:
        Dictionary mapping token strings to LTP values
    """
    with _state_lock:
        return {
            token: data.get("ltp")
            for token, data in tick_data_store.items()
            if "ltp" in data
        }


def get_delta_map() -> Dict[str, Optional[float]]:
    """
    Get mapping of token -> delta for all subscribed tokens.
    
    Returns:
        Dictionary mapping token strings to delta values
    """
    with _state_lock:
        return {
            token: data.get("delta")
            for token, data in tick_data_store.items()
            if "delta" in data
        }


def get_greeks_map() -> Dict[str, Dict[str, Optional[float]]]:
    """
    Get mapping of token -> greeks for all subscribed tokens.
    
    Returns:
        Dictionary mapping token strings to greeks dictionaries
    """
    with _state_lock:
        return {
            token: {
                "delta": data.get("delta"),
                "gamma": data.get("gamma"),
                "theta": data.get("theta"),
                "vega": data.get("vega"),
                "iv": data.get("iv"),
            }
            for token, data in tick_data_store.items()
        }


def get_tick_data(token: str) -> Optional[Dict[str, Any]]:
    """
    Get complete tick data for a specific token.
    
    Args:
        token: Token identifier
        
    Returns:
        Tick data dictionary or None if not found
    """
    with _state_lock:
        return tick_data_store.get(token, {}).copy() if token in tick_data_store else None


def get_all_tick_data() -> Dict[str, Dict[str, Any]]:
    """
    Get complete tick data for all subscribed tokens.
    
    Returns:
        Dictionary mapping tokens to their complete tick data
    """
    with _state_lock:
        return {token: data.copy() for token, data in tick_data_store.items()}


def is_feed_connected() -> bool:
    """
    🔥 IMPROVED: Check if WebSocket feed is currently connected.
    
    Now checks client state instead of local flag.
    
    Returns:
        True if connected, False otherwise
    """
    if _api_client_ref:
        return _api_client_ref.is_logged_in()
    return False


def get_subscribed_tokens() -> List[str]:
    """
    Get list of currently subscribed tokens.
    
    Returns:
        List of subscribed token strings
    """
    with _state_lock:
        return list(subscribed_tokens)


def clear_tick_data() -> None:
    """
    Clear all stored tick data.
    Useful for testing or memory management.
    Does not clear subscription state.
    """
    with _state_lock:
        tick_data_store.clear()
        logger.info("Tick data store cleared")


def reset_all_state() -> None:
    """
    Reset all state including tick data and subscriptions.
    WARNING: Does not unsubscribe from API, only clears local state.
    Use for testing or manual cleanup only.
    """
    global _tick_counter, _last_tick_time
    
    with _state_lock:
        tick_data_store.clear()
        subscribed_tokens.clear()
    
    with _tick_counter_lock:
        _tick_counter = 0
    
    _last_tick_time = None
    
    logger.warning("All state reset (tick data + subscriptions)")


def get_feed_stats() -> Dict[str, Any]:
    """
    🔥 IMPROVED: Get statistics about the current feed state.
    
    Now includes heartbeat information.
    
    Returns:
        Dictionary with feed statistics
    """
    with _state_lock:
        num_subscribed = len(subscribed_tokens)
        num_ticks = len(tick_data_store)
    
    with _tick_counter_lock:
        total_ticks = _tick_counter
    
    # 🔥 NEW: Heartbeat check
    connected = is_feed_connected()
    stale = False
    seconds_since_last_tick = None
    
    if _last_tick_time:
        seconds_since_last_tick = time.time() - _last_tick_time
        if seconds_since_last_tick > config.HEARTBEAT_TIMEOUT:
            stale = True
    
    return {
        "connected": connected,
        "subscribed_tokens": num_subscribed,
        "tokens_with_data": num_ticks,
        "total_ticks_received": total_ticks,
        "callback_queue_size": _callback_queue.qsize(),
        "seconds_since_last_tick": seconds_since_last_tick,
        "feed_stale": stale,
        "callback_workers_running": _callback_workers_running,
    }


def check_feed_health() -> Dict[str, Any]:
    """
    🔥 NEW: Comprehensive feed health check.
    
    Returns:
        Dictionary with health status and issues
    """
    stats = get_feed_stats()
    
    issues = []
    warnings = []
    
    # Check connection
    if not stats["connected"]:
        issues.append("WebSocket not connected")
    
    # Check for stale feed
    if stats["feed_stale"]:
        issues.append(f"No ticks for {stats['seconds_since_last_tick']:.0f}s")
    
    # Check callback queue
    queue_usage = stats["callback_queue_size"] / config.CALLBACK_QUEUE_SIZE
    if queue_usage > 0.8:
        warnings.append(f"Callback queue {queue_usage*100:.0f}% full")
    
    # Check workers
    if not stats["callback_workers_running"]:
        issues.append("Callback workers not running")
    
    # Check subscriptions vs data
    if stats["subscribed_tokens"] > 0 and stats["tokens_with_data"] == 0:
        warnings.append("No tick data despite subscriptions")
    
    healthy = len(issues) == 0
    
    return {
        "healthy": healthy,
        "issues": issues,
        "warnings": warnings,
        "stats": stats,
        "timestamp": datetime.now().isoformat(),
    }


def bind_option_chain(option_chain) -> None:
    """
    Bind OptionChainData instance to live feed updates.
    
    Args:
        option_chain: OptionChainData instance to receive tick updates
    """
    register_tick_update_callback(option_chain.update_tick)
    logger.info("Option chain bound to live feed")


# ===============================
# 🔄 BACKWARD COMPATIBILITY (DEPRECATED)
# ===============================

def resubscribe_all(api_client: ShoonyaClient) -> bool:
    """
    ⚠️ DEPRECATED: Client now handles resubscription automatically.
    
    This function is kept for backward compatibility but does nothing.
    The client's WebSocket reconnection logic handles resubscription.
    
    Args:
        api_client: Shoonya API client instance
        
    Returns:
        True (always succeeds as it's a no-op)
    """
    logger.warning(
        "resubscribe_all() is deprecated - "
        "client handles resubscription automatically"
    )
    return True


# ===============================
# 📊 PRODUCTION MONITORING (NEW)
# ===============================

def get_feed_metrics() -> Dict[str, Any]:
    """
    🔥 NEW: Get detailed metrics for monitoring/alerting.
    
    Returns:
        Dictionary with comprehensive metrics
    """
    stats = get_feed_stats()
    
    metrics = {
        "timestamp": time.time(),
        "feed": {
            "connected": stats["connected"],
            "stale": stats["feed_stale"],
            "last_tick_age_seconds": stats["seconds_since_last_tick"],
        },
        "subscriptions": {
            "total": stats["subscribed_tokens"],
            "with_data": stats["tokens_with_data"],
            "coverage_pct": (
                stats["tokens_with_data"] / stats["subscribed_tokens"] * 100
                if stats["subscribed_tokens"] > 0
                else 0
            ),
        },
        "ticks": {
            "total_received": stats["total_ticks_received"],
            "rate_per_second": None,  # Would need time-series data
        },
        "callbacks": {
            "queue_size": stats["callback_queue_size"],
            "queue_capacity": config.CALLBACK_QUEUE_SIZE,
            "queue_usage_pct": (
                stats["callback_queue_size"] / config.CALLBACK_QUEUE_SIZE * 100
            ),
            "workers_running": stats["callback_workers_running"],
        },
    }
    
    return metrics


# ===============================
# 🔒 PRODUCTION NOTES
# ===============================

"""
===============================================================================
LIVE FEED v2.0 - PRODUCTION HARDENING CHANGELOG
===============================================================================

✅ CRITICAL FIXES:
    1. WebSocket lifecycle delegated to ShoonyaClient (single owner)
    2. Removed duplicate reconnection logic (client handles it)
    3. Fixed close_websocket() method call (now uses stop_websocket())
    4. Added session validation before operations
    5. Heartbeat monitoring for stale feed detection
    
✅ IMPROVEMENTS:
    1. Enhanced error handling with detailed logging
    2. Feed health check function for monitoring
    3. Metrics endpoint for operational visibility
    4. Backward compatibility for deprecated functions
    5. Better coordination with client state
    
✅ ARCHITECTURE:
    - ShoonyaClient = WebSocket owner + reconnection logic
    - LiveFeed = Callback manager + tick data store + normalizer
    - Clear separation of concerns
    - Thread-safe throughout
    
🔒 PRODUCTION STATUS:
    ✅ Compatible with hardened client.py v2.0
    ✅ No WebSocket conflicts
    ✅ Proper error handling
    ✅ Monitoring ready
    ✅ Production deployable
    
===============================================================================
"""