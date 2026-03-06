# Fyers Broker Integration Guide

This document explains how to wire the Fyers broker (from `option_trading_system_fyers/`) into the shoonya_platform so you can:

1. **Use Fyers as the execution broker** instead of (or alongside) Shoonya.
2. **Use the Fyers data pipeline as a secondary / redundancy market-data source.**

---

## What was created

| File | Purpose |
|------|---------|
| `shoonya_platform/brokers/base.py` | `BrokerInterface` Protocol — the shared contract |
| `shoonya_platform/brokers/fyers/__init__.py` | Package exports |
| `shoonya_platform/brokers/fyers/config.py` | `FyersConfig` — credential loader |
| `shoonya_platform/brokers/fyers/symbol_map.py` | `FyersSymbolMapper` — symbol translation |
| `shoonya_platform/brokers/fyers/client.py` | `FyersBrokerClient` — full broker adapter |
| `shoonya_platform/market_data/feeds/fyers_feed.py` | `FyersLiveFeed` — tick-data adapter |

---

## Architecture overview

```
BrokerInterface (Protocol)
        │
        ├── ShoonyaApiProxy   ← existing (already conforms by duck typing)
        │       └── ShoonyaClient (NorenApi)
        │
        └── FyersBrokerClient ← new adapter
                └── FyersV3Client (from option_trading_system_fyers)


Market data flow
────────────────
Primary:   ShoonyaClient WebSocket  ──→  live_feed.tick_data_store  (Shoonya tokens)
Secondary: FyersBrokerClient WS     ──→  fyers_tick_store            (Fyers symbols)
                                    ──→  tick_data_store (cross_write=True, optional)
```

---

## Quick start — Fyers as execution broker

### 1. Credentials

The Fyers credentials are already in `option_trading_system_fyers/config/credentials.env`.
The `FyersConfig.from_env()` factory auto-discovers that file.  
Alternatively, copy the relevant variables into `shoonya_platform/config_env/fyers.env`:

```env
FYERS_ID=FG0158
FYERS_APP_ID=IQOURN2NSJ-100
FYERS_SECRET_ID=VDJI18IQB2
FYERS_T_OTP_KEY=AUJJZDOIOWOMQDZN7...
FYERS_PIN=2486
FYERS_REDIRECT_URL=http://13.233.165.217/
```

### 2. Standalone usage

```python
from shoonya_platform.brokers.fyers import FyersBrokerClient, FyersConfig

config = FyersConfig.from_env()
broker = FyersBrokerClient(config)

broker.login()                        # TOTP auth, token cached 24h
positions = broker.get_positions()
limits    = broker.get_limits()
info      = broker.get_account_info()

# Place an order (Fyers-native params)
result = broker.place_order({
    "symbol":       "NSE:NIFTY2531024550CE",
    "qty":          50,
    "type":         2,          # MARKET
    "side":         1,          # BUY
    "productType":  "INTRADAY",
    "limitPrice":   0,
    "stopPrice":    0,
    "validity":     "DAY",
    "disclosedQty": 0,
    "offlineOrder": False,
})
print(result.success, result.order_id)
```

### 3. Drop-in replacement in ShoonyaBot

Open `shoonya_platform/shoonya_platform/execution/trading_bot.py` and find the broker
initialisation block (≈ line 220):

```python
# BEFORE
self.api = ShoonyaClient(self.config)
self.api_proxy = ShoonyaApiProxy(self.api)
```

Change to:

```python
# AFTER — broker selected by config
_broker_name = os.getenv("BROKER", "shoonya").lower()
if _broker_name == "fyers":
    from shoonya_platform.brokers.fyers import FyersBrokerClient, FyersConfig
    self.api = FyersBrokerClient(FyersConfig.from_env())
else:
    self.api = ShoonyaClient(self.config)
self.api_proxy = ShoonyaApiProxy(self.api)
```

> **Note:** `ShoonyaApiProxy.__getattr__` delegates everything to `self._client`,
> so `FyersBrokerClient` works as a drop-in without any changes to the proxy.

Set `BROKER=fyers` in your environment / `config_env/primary.env` to switch brokers.

---

## Quick start — Fyers as data source

### Redundancy / secondary feed

```python
from shoonya_platform.brokers.fyers import FyersBrokerClient, FyersConfig
from shoonya_platform.market_data.feeds.fyers_feed import (
    start_fyers_feed,
    get_fyers_tick,
    get_fyers_feed_health,
)

config = FyersConfig.from_env()
fyers_broker = FyersBrokerClient(config)
fyers_broker.login()

symbols = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:NIFTY2531024550CE",
]

# start feed; cross_write=True also pushes ticks into Shoonya tick_data_store
start_fyers_feed(fyers_broker, symbols=symbols, cross_write=True)

# Pull latest tick
tick = get_fyers_tick("NSE:NIFTY50-INDEX")
print(tick)   # {"lp": 24450.45, "pc": 0.15, "v": 1234567, ...}

# Health check
print(get_fyers_feed_health())
```

### Cross-write mode (recommended for robustness)

When `cross_write=True` the Fyers feed writes normalised ticks into
`live_feed.tick_data_store` under the mapped Shoonya `"EXCHANGE|TOKEN"` key
**after** the symbol is resolved via `FyersSymbolMapper`.

This means the existing option-chain and strategy code that reads
`tick_data_store` will automatically receive Fyers tick data for any
symbol that can be matched in the scriptmaster — **no strategy changes needed**.

Static index tokens (always available, no scriptmaster needed):

| Fyers symbol | Shoonya key |
|---|---|
| `NSE:NIFTY50-INDEX` | `NSE\|26000` |
| `NSE:NIFTYBANK-INDEX` | `NSE\|26009` |
| `NSE:FINNIFTY-INDEX` | `NSE\|26037` |
| `NSE:MIDCPNIFTY-INDEX` | `NSE\|26074` |
| `BSE:SENSEX-INDEX` | `BSE\|1` |

For option/futures symbols the scriptmaster must be loaded first:
```python
from scripts.scriptmaster import refresh_scriptmaster
refresh_scriptmaster()
```

---

## Option chain data via Fyers API

The `FyersBrokerClient.get_option_chain()` method wraps the Fyers
`optionchain` endpoint directly.

```python
chain = fyers_broker.get_option_chain("NSE:NIFTY50-INDEX", strike_count=10)
# chain["optionsChain"] — list of {strikePrice, callOI, putOI, ...}
# chain["expiryData"]   — list of available expiry dates
```

To write option-chain data into the SQLite store used by the strategy engine:

```python
from shoonya_platform.market_data.option_chain.store import OptionChainStore

store = OptionChainStore()
# Parse chain["optionsChain"] rows and call store.upsert() for each strike
```

The `OptionChainManager` class in `option_trading_system_fyers/core/option_chain_1.py`
already handles all the parsing; use it as the data source and pipe rows to
`OptionChainStore`.

---

## Symbol format reference

| Context | Format | Example |
|---------|--------|---------|
| Fyers index | `EXCHANGE:SYMBOL-INDEX` | `NSE:NIFTY50-INDEX` |
| Fyers equity | `EXCHANGE:SYMBOL-EQ` | `NSE:RELIANCE-EQ` |
| Fyers option | `EXCHANGE:UNDERLYINGYYMMDDSTRIKETYPE` | `NSE:NIFTY2531024550CE` |
| Fyers futures | `EXCHANGE:UNDERLYINGYYMONTHFUT` | `NSE:NIFTY25MARFUT` |
| Shoonya feed key | `EXCHANGE\|TOKEN` | `NFO\|39547` |
| Shoonya trading symbol | Scriptmaster `TradingSymbol` | `NIFTY25MAR24550CE` |

---

## Phased rollout plan

### Phase 1 ✅ (done — this PR)
- `BrokerInterface` Protocol created (non-breaking)
- `FyersBrokerClient` adapter created
- `FyersLiveFeed` adapter created
- `FyersSymbolMapper` created

### Phase 2 — Broker injection in ShoonyaBot (low risk)
- Add `BROKER` env var support in `trading_bot.py` (3-line change shown above)
- Test with `BROKER=fyers` in paper/mock mode before going live

### Phase 3 — Fyers data as redundancy
- Start `start_fyers_feed(..., cross_write=True)` in parallel with the Shoonya feed
- Monitor `get_fyers_feed_health()` via the dashboard
- Strategy engine benefits automatically (reads same `tick_data_store`)

### Phase 4 — Per-client broker config
- Add `broker` key to `config_env/client_routes.json` per client
- Gateway router selects the broker adapter at startup per client session

---

## Testing

```python
# Quick smoke test (no order placement)
from shoonya_platform.brokers.fyers import FyersBrokerClient, FyersConfig
from shoonya_platform.brokers.base import BrokerInterface

config = FyersConfig.from_env()
client = FyersBrokerClient(config)

# Protocol conformance check
assert isinstance(client, BrokerInterface), "FyersBrokerClient must satisfy BrokerInterface"

client.login()
print("Limits:", client.get_limits())
print("Positions:", client.get_positions())
print("Account:", client.get_account_info())
```
