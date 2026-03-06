"""
===============================================================================
BROKER INTERFACE v1.0 - Multi-Broker Protocol
===============================================================================

Defines the contract that every broker adapter must satisfy.
Using typing.Protocol for structural subtyping — no forced inheritance,
so existing ShoonyaClient (which extends NorenApi) stays untouched.

ANY object that implements these methods is a valid BrokerInterface:
    - ShoonyaApiProxy (existing, already conforms)
    - FyersBrokerClient (new, explicit protocol implementation)
    - FakeBroker in tests (already conforms by duck typing)

Usage:
    from shoonya_platform.brokers.base import BrokerInterface

    def start_bot(broker: BrokerInterface) -> None:
        broker.login()
        broker.start_websocket(on_tick=handle_tick)
        ...
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from shoonya_platform.domain.business_models import AccountInfo, OrderResult


@runtime_checkable
class BrokerInterface(Protocol):
    """
    Structural protocol for broker adapters.

    Tier-1 (must never silently fail — raise RuntimeError on broker errors):
        login, logout, ensure_session, place_order, modify_order,
        cancel_order, get_positions, get_limits, get_order_book,
        get_account_info, start_websocket

    Tier-2 (informational, may return empty/None gracefully):
        is_logged_in, get_quotes, subscribe, unsubscribe
    """

    # -------------------------------------------------------------------------
    # Session management
    # -------------------------------------------------------------------------

    def login(self) -> bool:
        """
        Authenticate with the broker.

        Returns:
            True on success.
        Raises:
            RuntimeError: if login fails after all retries.
        """
        ...

    def logout(self) -> None:
        """Terminate the broker session and clean up state."""
        ...

    def is_logged_in(self) -> bool:
        """Return True if a valid session is currently active."""
        ...

    def ensure_session(self) -> bool:
        """
        Validate (and recover, if needed) the current session.

        Returns:
            True when session is confirmed valid.
        Raises:
            RuntimeError: if session cannot be recovered.
        """
        ...

    # -------------------------------------------------------------------------
    # WebSocket & subscriptions
    # -------------------------------------------------------------------------

    def start_websocket(
        self,
        on_tick: Callable[[dict], None],
        on_order_update: Optional[Callable[[dict], None]] = None,
        on_open: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Start the real-time WebSocket feed.

        Args:
            on_tick: Called for every market-data tick.
            on_order_update: Called for order status updates (optional).
            on_open: Called when the connection is established (optional).
            on_close: Called when the connection closes (optional).
        """
        ...

    def subscribe(self, tokens: List[str]) -> None:
        """
        Subscribe to market-data for the given tokens.

        Args:
            tokens: Broker-specific token strings.
        """
        ...

    def unsubscribe(self, tokens: List[str]) -> None:
        """Unsubscribe from market-data for the given tokens."""
        ...

    # -------------------------------------------------------------------------
    # Order management (Tier-1 — must raise on failure)
    # -------------------------------------------------------------------------

    def place_order(self, order_params: Any) -> OrderResult:
        """
        Place a new order.

        Args:
            order_params: dict or OrderParams-like object.
        Returns:
            OrderResult with success/failure details.
        """
        ...

    def modify_order(self, order_id: str, modifications: Dict[str, Any]) -> Optional[dict]:
        """
        Modify an existing order.

        Args:
            order_id: Broker order identifier.
            modifications: Fields to modify (qty, price, trigger, etc.).
        Returns:
            Raw broker response dict, or None on error.
        """
        ...

    def cancel_order(self, order_id: str) -> Optional[dict]:
        """
        Cancel a pending order.

        Returns:
            Raw broker response dict, or None on error.
        """
        ...

    # -------------------------------------------------------------------------
    # Account / position queries (Tier-1)
    # -------------------------------------------------------------------------

    def get_positions(self) -> List[dict]:
        """
        Fetch current open positions from the broker.

        Returns:
            List of position dicts (broker-specific schema, normalised by adapter).
        Raises:
            RuntimeError: if the session is invalid or broker is unreachable.
        """
        ...

    def get_limits(self) -> dict:
        """
        Fetch margin / fund limits.

        Returns:
            Dict with at minimum: available_cash, used_margin.
        Raises:
            RuntimeError: if the session is invalid or broker is unreachable.
        """
        ...

    def get_order_book(self) -> List[dict]:
        """
        Fetch today's order book.

        Returns:
            List of order dicts.
        Raises:
            RuntimeError: if the session is invalid or broker is unreachable.
        """
        ...

    def get_account_info(self) -> AccountInfo:
        """
        Fetch consolidated account information.

        Returns:
            AccountInfo dataclass.
        Raises:
            RuntimeError: if the session is invalid or broker is unreachable.
        """
        ...

    # -------------------------------------------------------------------------
    # Tier-2: informational (may return empty/None gracefully)
    # -------------------------------------------------------------------------

    def get_quotes(self, exchange: str, token: str) -> Optional[dict]:
        """
        Fetch a live quote for the given symbol.

        Args:
            exchange: Exchange code (e.g. "NSE", "NFO").
            token: Broker-specific symbol token.
        Returns:
            Quote dict or None if unavailable.
        """
        ...
