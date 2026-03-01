# Feature Reference: Index Tokens & Analytics

> Last verified: 2026-03-01

## Index Tokens Subscriber

**Module:** `shoonya_platform/market_data/feeds/index_tokens_subscriber.py`

Subscribes to real-time index data (NIFTY, BANKNIFTY, India VIX, etc.) via WebSocket.

### Dashboard Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/index-tokens/list` | Available index tokens |
| `GET` | `/dashboard/index-tokens/prices` | Current index LTP/change |

### Strategy Integration

Index data is available in strategy conditions:

```json
{
  "parameter": "index_INDIAVIX_ltp",
  "comparator": ">=",
  "value": 15.0
}
```

Available parameters:
- `index_<NAME>_ltp` — Last traded price
- `index_<NAME>_change_pct` — Percentage change
- `india_vix` — Alias for `index_INDIAVIX_ltp`

---

## Historical Analytics

**Modules:**
- `shoonya_platform/analytics/historical_service.py` — API layer
- `shoonya_platform/analytics/historical_store.py` — Data storage

### Dashboard Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/analytics/history/health` | Analytics system health |
| `GET` | `/dashboard/analytics/history/strategy-samples` | Historical strategy data |
| `GET` | `/dashboard/analytics/history/events` | Historical events |
| `GET` | `/dashboard/analytics/history/index-ticks` | Historical index data |
| `GET` | `/dashboard/analytics/history/option-metrics` | Historical option metrics |

### Dashboard Pages

- `option_chain_analytics.html` — Option chain analytics with charts
- `strategy.html` — Includes Analytics tab for strategy performance

---

## Option Chain System

**Modules:**
- `shoonya_platform/market_data/option_chain/option_chain.py` — Data model
- `shoonya_platform/market_data/option_chain/store.py` — In-memory store
- `shoonya_platform/market_data/option_chain/supervisor.py` — Auto-refresh
- `shoonya_platform/market_data/option_chain/supervisor_monitor.py` — Health monitoring
- `shoonya_platform/market_data/option_chain/db_access.py` — ScriptMaster queries

### Dashboard Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/option-chain/symbols` | Available underlyings |
| `GET` | `/dashboard/option-chain/expiries` | Expiry dates |
| `GET` | `/dashboard/option-chain/chain` | Full option chain |
| `GET` | `/dashboard/option-chain/nearest` | Nearest ATM option |

### Dashboard Page

- `option_chain_dashboard.html` — Live option chain viewer

---

## Market Detection (5-Layer)

The system detects market state through multiple layers:

1. **Exchange Calendar** — NSE/MCX holiday calendar
2. **Time Window** — per-exchange trading hours
3. **WebSocket Status** — live feed connection state
4. **Tick Freshness** — age of last received tick
5. **Weekend Check** — `scripts/weekend_market_check.py` via systemd timer

**Market data flow:**
```
ShoonyaClient (WebSocket) → LiveFeed → tick_data_store → MarketReader → StrategyExecutor
```

---

## Greeks Calculator

**Module:** `shoonya_platform/utils/bs_greeks.py`

Black-Scholes Greeks calculation for options:
- Delta, Gamma, Theta, Vega, IV
- Used by strategy condition engine for delta-based adjustments
- Used by dashboard for position Greeks display
