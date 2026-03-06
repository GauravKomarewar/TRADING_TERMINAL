"""
===============================================================================
FYERS BROKER CLIENT v1.0 - BrokerInterface Adapter
===============================================================================

Wraps FyersV3Client (from option_trading_system_fyers) and presents it
through the shoonya_platform BrokerInterface protocol.

Key design choices:
  ✅ Thread-safe via RLock (mirrors ShoonyaClient pattern)
  ✅ Returns OrderResult / AccountInfo domain objects (same as ShoonyaClient)
  ✅ Fail-hard on Tier-1 operations (raises RuntimeError on broker errors)
  ✅ Graceful fallback on Tier-2 informational endpoints
  ✅ Fyers uses its own WebSocket (FyersDataSocket); ticks are dispatched
     through the same on_tick callback contract as ShoonyaClient.start_websocket()

Usage
-----
    from shoonya_platform.brokers.fyers import FyersBrokerClient, FyersConfig

    config = FyersConfig.from_env()          # reads credentials.env / env vars
    broker = FyersBrokerClient(config)
    broker.login()
    broker.start_websocket(on_tick=my_handler)
    broker.subscribe(["NSE:NIFTY50-INDEX", "NSE:NIFTY2531024550CE"])

Wire into ShoonyaBot:
    # In trading_bot.py — replace the hard-coded ShoonyaClient block:
    if config.broker == "fyers":
        from shoonya_platform.brokers.fyers import FyersBrokerClient, FyersConfig
        raw_client = FyersBrokerClient(FyersConfig.from_env())
    else:
        raw_client = ShoonyaClient(config)
    self.api_proxy = ShoonyaApiProxy(raw_client)   # works unchanged
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from threading import RLock

from shoonya_platform.brokers.base import BrokerInterface          # noqa: F401 (used as Protocol)
from shoonya_platform.brokers.fyers.config import FyersConfig
from shoonya_platform.domain.business_models import AccountInfo, OrderResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import of FyersV3Client (lives in option_trading_system_fyers project)
# ---------------------------------------------------------------------------

def _import_fyers_client():
    """
    Import FyersV3Client from the sister fyers project.

    We resolve the path dynamically so the shoonya_platform package does
    not need the fyers project on its sys.path at install time.
    """
    # Try direct import first (if PYTHONPATH includes the fyers project)
    try:
        from core.fyers_final import FyersV3Client  # type: ignore
        return FyersV3Client
    except ImportError:
        pass

    # Resolve relative path: shoonya_platform/ → ../option_trading_system_fyers/
    fyers_root = Path(__file__).resolve().parents[5] / "option_trading_system_fyers"
    if fyers_root.exists() and str(fyers_root) not in sys.path:
        sys.path.insert(0, str(fyers_root))

    try:
        from core.fyers_final import FyersV3Client  # type: ignore
        return FyersV3Client
    except ImportError as exc:
        raise ImportError(
            f"Cannot import FyersV3Client. Ensure option_trading_system_fyers is at "
            f"{fyers_root} or on PYTHONPATH. Original error: {exc}"
        ) from exc


def _import_fyers_data_socket():
    """Lazy import of FyersDataSocket."""
    try:
        from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket  # type: ignore
        return FyersDataSocket
    except ImportError as exc:
        raise ImportError(
            "fyers-apiv3 is not installed. Run: pip install fyers-apiv3>=3.1.11"
        ) from exc


# ---------------------------------------------------------------------------
# FyersBrokerClient
# ---------------------------------------------------------------------------


class FyersBrokerClient:
    """
    BrokerInterface adapter for the Fyers broker (API v3).

    Implements the same method signatures as ShoonyaApiProxy so it can be
    dropped in wherever a proxy object is expected.
    """

    def __init__(self, config: FyersConfig) -> None:
        self._config = config
        self._lock = RLock()
        self._logged_in = False

        # Underlying FyersV3Client — imported lazily
        FyersV3Client = _import_fyers_client()
        self._fyers_client = FyersV3Client(
            fyers_id=config.fyers_id,
            totp_key=config.totp_key,
            pin=config.pin,
            redirect_url=config.redirect_url,
            app_id=config.app_id,
            secret_id=config.secret_id,
            token_file=config.token_file,
        )

        # WebSocket state
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_callbacks: dict = {}
        self._fyers_ws = None
        self._subscribed_symbols: set = set()

        logger.info("FyersBrokerClient initialised (user: %s)", config.fyers_id)

    # =========================================================================
    # Session management
    # =========================================================================

    def login(self) -> bool:
        """
        Authenticate with Fyers (TOTP flow, with token caching).

        Returns True on success, raises RuntimeError on failure.
        """
        with self._lock:
            try:
                self._fyers_client.connect()
                self._logged_in = bool(self._fyers_client.fyers)
                if self._logged_in:
                    logger.info("✅ Fyers login successful (user: %s)", self._config.fyers_id)
                    return True
                raise RuntimeError("Fyers login returned no fyers model instance")
            except Exception as exc:
                logger.error("❌ Fyers login failed: %s", exc)
                self._logged_in = False
                raise RuntimeError(f"FYERS_LOGIN_FAILED: {exc}") from exc

    def logout(self) -> None:
        """Terminate Fyers session and stop WebSocket."""
        self.stop_websocket()
        with self._lock:
            self._logged_in = False
            self._fyers_client.fyers = None
            self._fyers_client.access_token = None
        logger.info("Fyers session terminated")

    def is_logged_in(self) -> bool:
        return self._logged_in

    def ensure_session(self) -> bool:
        """
        Validate session; re-login if token has expired (Fyers tokens last 24h).

        Raises RuntimeError if session cannot be recovered.
        """
        with self._lock:
            if self._logged_in and not self._fyers_client._is_token_expired():
                return True
            logger.info("Fyers session expired or not active — re-logging in")
            return self.login()

    # =========================================================================
    # WebSocket
    # =========================================================================

    def start_websocket(
        self,
        on_tick: Callable[[dict], None],
        on_order_update: Optional[Callable[[dict], None]] = None,
        on_open: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Start Fyers WebSocket feed.

        Ticks are dispatched via on_tick (same contract as ShoonyaClient).
        Note: Fyers does not push order updates via the market-data socket;
        on_order_update is accepted for API compatibility but never called.
        """
        self.ensure_session()

        self._ws_callbacks = {
            "on_tick": on_tick,
            "on_open": on_open,
            "on_close": on_close,
        }

        access_token = f"{self._config.app_id}:{self._fyers_client.access_token}"
        FyersDataSocket = _import_fyers_data_socket()

        def _on_message(msg: dict) -> None:
            if not isinstance(msg, dict):
                return
            # Fyers sends a list of ticks OR a single dict
            ticks = msg if isinstance(msg, list) else [msg]
            for tick in ticks:
                if isinstance(tick, dict) and tick.get("ltp"):
                    try:
                        on_tick(tick)
                    except Exception as exc:
                        logger.warning("on_tick error: %s", exc)

        def _on_connect(msg: dict) -> None:
            logger.info("Fyers WebSocket connected")
            # Re-subscribe to any symbols registered before connect
            if self._subscribed_symbols:
                self._fyers_ws.subscribe(
                    symbols=list(self._subscribed_symbols),
                    data_type="SymbolUpdate",
                )
            if on_open:
                try:
                    on_open()
                except Exception as exc:
                    logger.warning("on_open callback error: %s", exc)

        def _on_error(msg: dict) -> None:
            logger.error("Fyers WebSocket error: %s", msg)

        def _on_close(msg: dict) -> None:
            logger.warning("Fyers WebSocket closed: %s", msg)
            if on_close:
                try:
                    on_close()
                except Exception as exc:
                    logger.warning("on_close callback error: %s", exc)

        self._fyers_ws = FyersDataSocket(
            access_token=access_token,
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=_on_connect,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        # Run WebSocket in a daemon thread
        self._ws_thread = threading.Thread(
            target=self._fyers_ws.connect,
            name="FyersWebSocket",
            daemon=True,
        )
        self._ws_thread.start()
        logger.info("Fyers WebSocket thread started")

    def stop_websocket(self) -> None:
        """Stop the Fyers WebSocket connection."""
        if self._fyers_ws is not None:
            try:
                self._fyers_ws.close_connection()
            except Exception as exc:
                logger.warning("Error stopping Fyers WebSocket: %s", exc)
            self._fyers_ws = None

    def subscribe(self, tokens: List[str]) -> None:
        """
        Subscribe to market data.

        Args:
            tokens: Fyers-format symbols, e.g. ["NSE:NIFTY50-INDEX", "NSE:NIFTY2531024550CE"]
                    OR Shoonya-format keys that will be translated via FyersSymbolMapper.
        """
        fyers_symbols = self._to_fyers_symbols(tokens)
        self._subscribed_symbols.update(fyers_symbols)

        if self._fyers_ws is not None:
            try:
                self._fyers_ws.subscribe(
                    symbols=fyers_symbols,
                    data_type="SymbolUpdate",
                )
                logger.debug("Fyers: subscribed %d symbols", len(fyers_symbols))
            except Exception as exc:
                logger.warning("Fyers subscribe error: %s", exc)

    def unsubscribe(self, tokens: List[str]) -> None:
        """Unsubscribe from market data."""
        fyers_symbols = self._to_fyers_symbols(tokens)
        self._subscribed_symbols.difference_update(fyers_symbols)

        if self._fyers_ws is not None:
            try:
                self._fyers_ws.unsubscribe(symbols=fyers_symbols)
            except Exception as exc:
                logger.warning("Fyers unsubscribe error: %s", exc)

    # =========================================================================
    # Order management
    # =========================================================================

    def place_order(self, order_params: Any) -> OrderResult:
        """
        Place an order with Fyers.

        Accepts either a plain dict using Fyers API keys or a normalised
        dict using Shoonya-style keys (auto-translated).

        Fyers order keys:
            symbol      : "NSE:NIFTY2531024550CE"
            qty         : 50
            type        : 1 (LIMIT) / 2 (MARKET) / 3 (SL) / 4 (SL-M)
            side        : 1 (BUY) / -1 (SELL)
            productType : "INTRADAY" / "MARGIN" / "CNC" / "BO" / "CO"
            limitPrice  : 0 (for market)
            stopPrice   : 0
            validity    : "DAY" / "IOC"
            disclosedQty: 0
            offlineOrder: False
        """
        self.ensure_session()

        params = self._normalize_order_params(order_params)
        try:
            resp = self._fyers_client.fyers.place_order(data=params)
            return self._parse_order_result(resp)
        except Exception as exc:
            logger.error("Fyers place_order failed: %s", exc)
            return OrderResult(success=False, error_message=str(exc))

    def modify_order(self, order_id: str, modifications: Dict[str, Any]) -> Optional[dict]:
        """Modify an existing Fyers order."""
        self.ensure_session()
        data = {"id": order_id, **modifications}
        try:
            resp = self._fyers_client.fyers.modify_order(data=data)
            if isinstance(resp, dict) and resp.get("s") == "ok":
                return resp
            logger.warning("Fyers modify_order non-ok response: %s", resp)
            return resp
        except Exception as exc:
            logger.error("Fyers modify_order failed: %s", exc)
            return None

    def cancel_order(self, order_id: str) -> Optional[dict]:
        """Cancel a Fyers order."""
        self.ensure_session()
        try:
            resp = self._fyers_client.fyers.cancel_order(data={"id": order_id})
            return resp
        except Exception as exc:
            logger.error("Fyers cancel_order failed: %s", exc)
            return None

    # =========================================================================
    # Account / position queries (Tier-1)
    # =========================================================================

    def get_positions(self) -> List[dict]:
        """
        Fetch current positions from Fyers.

        Returns a list of position dicts with BOTH Fyers-native keys and
        Shoonya-compatible aliases so all existing consumer code works:
            tsym / tradingsymbol  — trading symbol
            netqty / qty          — net quantity
            exch / exchange       — exchange
            prd                   — product type (MIS/NRML/CNC)
            rpnl / realised_pnl   — realised P&L
            urmtom / unrealised_pnl — unrealised P&L
        """
        self.ensure_session()
        resp = self._fyers_client.fyers.positions()
        if not isinstance(resp, dict) or resp.get("s") != "ok":
            logger.error("get_positions: bad Fyers response: %s", resp)
            raise RuntimeError(f"FYERS_API_ERROR: get_positions returned {resp}")
        raw_list = resp.get("netPositions") or resp.get("positions", [])
        return [self._normalise_position(p) for p in (raw_list or [])]

    def get_limits(self) -> dict:
        """
        Fetch Fyers fund / margin limits.

        Returns a minimal dict compatible with the shoonya_platform usage:
            available_cash, used_margin, total_balance
        """
        self.ensure_session()
        resp = self._fyers_client.fyers.funds()
        if not isinstance(resp, dict) or resp.get("s") != "ok":
            raise RuntimeError(f"FYERS_API_ERROR: get_limits returned {resp}")
        fund_limit = resp.get("fund_limit") or []
        # Fyers returns a list of {title, equityAmount} dicts
        lookup = {item.get("title", ""): item.get("equityAmount", 0.0)
                  for item in fund_limit if isinstance(item, dict)}
        return {
            "available_cash":  lookup.get("Available Balance", 0.0),
            "used_margin":     lookup.get("Utilised Amount", 0.0),
            "total_balance":   lookup.get("Total Balance", 0.0),
            "_raw":            resp,
        }

    def get_order_book(self) -> List[dict]:
        """
        Fetch today's order book from Fyers, normalised to Shoonya-compatible schema.

        Key mappings so OrderWatcher works without changes:
            norenordno  ← Fyers "id"  (Shoonya order-book ID field)
            status      ← Fyers numeric status → string (COMPLETE/REJECTED/CANCELLED/PENDING)
        """
        self.ensure_session()
        resp = self._fyers_client.fyers.orderbook()
        if not isinstance(resp, dict) or resp.get("s") != "ok":
            raise RuntimeError(f"FYERS_API_ERROR: get_order_book returned {resp}")
        raw_orders = resp.get("orderBook") or []
        return [self._normalise_order(o) for o in raw_orders]

    def get_account_info(self) -> AccountInfo:
        """Fetch consolidated account info."""
        self.ensure_session()
        limits = self.get_limits()
        positions = self.get_positions()
        total_pnl = sum(float(p.get("pnl", 0)) for p in positions)
        return AccountInfo(
            available_cash=float(limits.get("available_cash", 0)),
            used_margin=float(limits.get("used_margin", 0)),
            positions=positions,
        )

    def get_holdings(self) -> List[dict]:
        """Fetch equity holdings from Fyers (Tier-2 informational)."""
        try:
            resp = self._fyers_client.fyers.holdings()
            if isinstance(resp, dict) and resp.get("s") == "ok":
                return resp.get("holdings") or []
        except Exception as exc:
            logger.warning("get_holdings error: %s", exc)
        return []

    def get_session_info(self) -> dict:
        """
        Return basic session information (Tier-2 informational).

        Fyers does not expose a session-info endpoint; we return a
        compatible dict so bot_status_scheduling.get_session_info() works.
        """
        profile = {}
        try:
            resp = self._fyers_client.fyers.get_profile()
            if isinstance(resp, dict) and resp.get("s") == "ok":
                d = resp.get("data", {})
                profile = {
                    "name": d.get("name", ""),
                    "email": d.get("email_id", ""),
                    "broker": "Fyers",
                    "uid": d.get("fy_id", ""),
                }
        except Exception as exc:
            logger.debug("get_session_info profile fetch error: %s", exc)
        return {
            "logged_in": self._logged_in,
            "broker": "fyers",
            "userid": self._config.fyers_id,
            "profile": profile,
            "token_expired": self._fyers_client._is_token_expired(),
        }

    def searchscrip(self, exchange: str, searchtext: str) -> Optional[dict]:
        """
        Symbol search stub (used by MCX futures token resolver).

        Fyers does not expose a symbol-search REST endpoint equivalent to
        Shoonya's searchscrip. Returns None gracefully so callers handle it.
        """
        logger.debug(
            "searchscrip called for exchange=%s text=%s — not supported on Fyers",
            exchange,
            searchtext,
        )
        return None

    # =========================================================================
    # Tier-2: informational
    # =========================================================================

    def get_quotes(self, exchange: str, token: str) -> Optional[dict]:
        """
        Fetch a live quote.

        Accepts either:
          - Fyers format: exchange="NSE", token="NIFTY50-INDEX"  → "NSE:NIFTY50-INDEX"
          - Fyers full symbol: exchange="NSE:NIFTY50-INDEX", token="" (ignored)
        """
        if ":" in exchange:
            sym = exchange  # full symbol passed as first arg
        else:
            sym = f"{exchange}:{token}"

        try:
            resp = self._fyers_client.fyers.quotes(data={"symbols": sym})
            if isinstance(resp, dict) and resp.get("s") == "ok":
                d = resp.get("d") or []
                return d[0] if d else None
        except Exception as exc:
            logger.warning("get_quotes(%s) error: %s", sym, exc)
        return None

    # =========================================================================
    # Direct Fyers-specific helpers (not part of BrokerInterface)
    # =========================================================================

    def get_option_chain(self, symbol: str, strike_count: int = 10) -> dict:
        """
        Fetch the Fyers option chain for an index symbol.

        Args:
            symbol: Fyers index symbol, e.g. "NSE:NIFTY50-INDEX"
            strike_count: Number of strikes on each side.
        Returns:
            Raw Fyers optionchain response dict (or empty dict on error).
        """
        self.ensure_session()
        try:
            resp = self._fyers_client.fyers.optionchain(data={
                "symbol": symbol,
                "strikecount": strike_count,
                "timestamp": "",
            })
            if isinstance(resp, dict) and resp.get("s") == "ok":
                return resp
            logger.warning("get_option_chain non-ok: %s", resp)
            return {}
        except Exception as exc:
            logger.warning("get_option_chain error: %s", exc)
            return {}

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _to_fyers_symbols(self, tokens: List[str]) -> List[str]:
        """
        Ensure tokens are in Fyers format.

        If a token already contains ":" it is assumed to be a Fyers symbol.
        Shoonya-style "EXCHANGE|TOKEN" strings are passed through a symbol
        mapper (requires scriptmaster to be loaded for dynamic lookup).
        """
        from shoonya_platform.brokers.fyers.symbol_map import FyersSymbolMapper  # noqa
        mapper = FyersSymbolMapper()
        result = []
        for t in tokens:
            if ":" in t:
                result.append(t)
            else:
                fyers_sym = mapper.shoonya_key_to_fyers(t)
                if fyers_sym:
                    result.append(fyers_sym)
                else:
                    logger.debug("Cannot map Shoonya token %s to Fyers symbol — skipping", t)
        return result

    def _normalize_order_params(self, order_params: Any) -> dict:
        """Normalise order_params to a Fyers API-compatible dict."""
        if isinstance(order_params, dict):
            params = dict(order_params)
        elif hasattr(order_params, "to_dict") and callable(order_params.to_dict):
            params = order_params.to_dict()
        elif hasattr(order_params, "__dict__"):
            params = dict(order_params.__dict__)
        else:
            raise TypeError(f"Unsupported order_params type: {type(order_params)}")

        # If params uses Shoonya-style keys, translate common ones to Fyers
        if "tradingsymbol" in params or "transactiontype" in params:
            params = self._translate_shoonya_order_to_fyers(params)

        return {k: v for k, v in params.items() if v is not None}

    @staticmethod
    def _translate_shoonya_order_to_fyers(p: dict) -> dict:
        """
        Best-effort translation of Shoonya order dict keys to Fyers API keys.

        This is a convenience helper for callers that currently build
        Shoonya-style dicts. Not all combinations are supported.
        """
        # Transaction type: B/BUY → 1, S/SELL → -1
        tx = str(p.get("transactiontype", "B")).upper()
        side = 1 if tx in ("B", "BUY") else -1

        # Order type: LMT/LIMIT → 1, MKT/MARKET → 2, SL-LMT → 3, SL-MKT → 4
        ot = str(p.get("prctyp", "MKT")).upper()
        type_map = {"MKT": 2, "MARKET": 2, "LMT": 1, "LIMIT": 1,
                    "SL-LMT": 3, "SL-MKT": 4}
        order_type = type_map.get(ot, 2)

        # Product type
        prod = str(p.get("prd", "I")).upper()
        prod_map = {"I": "INTRADAY", "M": "MARGIN", "C": "CNC",
                    "INTRADAY": "INTRADAY", "MARGIN": "MARGIN"}
        product_type = prod_map.get(prod, "INTRADAY")

        # Symbol: use as-is if it contains ":", otherwise assume NFO and
        # you will need to supply the Fyers symbol directly.
        sym = p.get("tradingsymbol", "") or p.get("symbol", "")

        return {
            "symbol":       sym,
            "qty":          int(p.get("qty", 0)),
            "type":         order_type,
            "side":         side,
            "productType":  product_type,
            "limitPrice":   float(p.get("prc", 0) or 0),
            "stopPrice":    float(p.get("trgprc", 0) or 0),
            "validity":     "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }

    @staticmethod
    def _parse_order_result(resp: Any) -> OrderResult:
        """Convert a Fyers place_order response to an OrderResult."""
        if isinstance(resp, dict):
            if resp.get("s") == "ok":
                return OrderResult(
                    success=True,
                    order_id=str(resp.get("id", "")),
                    status="ok",
                    response_data=resp,
                )
            return OrderResult(
                success=False,
                status=resp.get("s", "error"),
                error_message=resp.get("message", str(resp)),
                response_data=resp,
            )
        return OrderResult(success=False, error_message=f"Unexpected response: {resp}")

    @staticmethod
    def _normalise_position(raw: dict) -> dict:
        """
        Normalise a Fyers position dict.

        Emits BOTH Fyers-native keys AND Shoonya-compatible aliases so
        existing consumer code (bot_execution, position_exit_service,
        bot_status_scheduling) works without modification.

        Shoonya ↔ Fyers field map:
            tsym       ← symbol       (Shoonya trading symbol field)
            netqty     ← netQty       (net quantity used by OrderWatcher/exits)
            exch       ← segment/exchange
            prd        ← productType  (MIS / NRML / CNC)
            rpnl       ← realized_profit
            urmtom     ← unrealized_profit
        """
        # Derive Shoonya-style product code
        fyers_prod = str(raw.get("productType") or raw.get("type") or "").upper()
        prod_map = {"INTRADAY": "MIS", "MARGIN": "NRML", "CNC": "CNC", "BO": "MIS", "CO": "MIS"}
        prd = prod_map.get(fyers_prod, "MIS")

        # Symbol: strip exchange prefix if present ("NSE:NIFTY25.." → "NIFTY25..")
        raw_sym = raw.get("symbol", "")
        tsym = raw_sym.split(":", 1)[-1] if ":" in raw_sym else raw_sym

        # Exchange: derive from segment or raw symbol prefix
        raw_exch = raw.get("exchange", "") or raw.get("segment", "")
        if not raw_exch and ":" in raw_sym:
            raw_exch = raw_sym.split(":")[0]

        net_qty = int(raw.get("netQty", 0))
        realised  = float(raw.get("realized_profit",   raw.get("rpnl",   0)) or 0)
        unrealised = float(raw.get("unrealized_profit", raw.get("urmtom", 0)) or 0)

        return {
            # ---- Shoonya-compatible keys (used by all existing consumers) ----
            "tsym":           tsym,
            "netqty":         net_qty,
            "exch":           raw_exch,
            "prd":            prd,
            "rpnl":           realised,
            "urmtom":         unrealised,
            # ---- Fyers / common keys ------------------------------------
            "symbol":         raw_sym,
            "tradingsymbol":  tsym,
            "exchange":       raw_exch,
            "qty":            net_qty,
            "buy_avg":        float(raw.get("buyAvg",  0) or 0),
            "sell_avg":       float(raw.get("sellAvg", 0) or 0),
            "pnl":            realised + unrealised,
            "realised_pnl":   realised,
            "unrealised_pnl": unrealised,
            "day_buy_qty":    int(raw.get("buyQty",  0)),
            "day_sell_qty":   int(raw.get("sellQty", 0)),
            "_raw":           raw,
        }

    @staticmethod
    def _normalise_order(raw: dict) -> dict:
        """
        Normalise a Fyers order dict to Shoonya-compatible schema.

        Critical mappings for OrderWatcher:
            norenordno  ← id       (Shoonya's order ID field name)
            status      ← numeric status → COMPLETE/REJECTED/CANCELLED/PENDING

        Fyers order status codes:
            1  = Validation pending
            2  = Traded (Filled)     → COMPLETE
            4  = Cancelled           → CANCELLED
            5  = Cancelled (partial) → CANCELLED
            6  = Traded partially    → PENDING  (still open)
            7  = Rejected            → REJECTED
        """
        _FYERS_STATUS_MAP = {
            1: "PENDING",
            2: "COMPLETE",
            4: "CANCELLED",
            5: "CANCELLED",
            6: "PENDING",
            7: "REJECTED",
        }
        raw_status = raw.get("status", 0)
        # status may already be a string (e.g. in paper mode)
        if isinstance(raw_status, str):
            status_str = raw_status.upper()
        else:
            status_str = _FYERS_STATUS_MAP.get(int(raw_status), "PENDING")

        return {
            # ---- Shoonya-compatible keys (used by OrderWatcher) ----
            "norenordno":  str(raw.get("id", "")),
            "status":      status_str,
            "tsym":        raw.get("symbol", ""),
            "qty":         raw.get("qty", 0),
            "prc":         raw.get("limitPrice", 0),
            "trgprc":      raw.get("stopPrice", 0),
            "transactiontype": "B" if raw.get("side", 1) == 1 else "S",
            "prd":         raw.get("productType", ""),
            "exch":        raw.get("exchange", ""),
            "rejreason":   raw.get("message", ""),
            # ---- Fyers native keys (preserved) ----
            "id":          raw.get("id", ""),
            "_raw":        raw,
        }
