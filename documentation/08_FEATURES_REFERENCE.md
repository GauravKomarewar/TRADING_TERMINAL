# Feature Reference: Index Tokens & Analytics

> Last verified: 2026-03-09

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

**Modules:**
- `shoonya_platform/utils/bs_greeks.py` — Core pricing (`bs_price`, `bs_greeks`, `implied_vol`)
- `shoonya_platform/market_data/option_chain/option_chain.py` — Exchange-aware pipeline

### Models

| Exchange | Model | `q` (dividend yield) | `r` (risk-free) | Spot Source |
|----------|-------|---------------------|-----------------|-------------|
| NFO (NIFTY, BANKNIFTY) | Generalized Black-Scholes | 0.012 | 0.065 | Spot LTP |
| BFO (SENSEX) | Generalized Black-Scholes | 0.012 | 0.065 | Spot LTP |
| MCX (CRUDEOIL, NATGAS, etc.) | Black-76 (`q = r`) | 0.065 | 0.065 | Futures LTP |

**Black-76 for MCX:** Commodity options are on futures contracts, not spot. Setting `q = r` in the generalized Black-Scholes formula reduces it to the Black-76 model — the forward price replaces the spot price, and the dividend yield cancels the risk-free discount.

### Computed Greeks

- **Delta** — First-order price sensitivity to underlying
- **Gamma** — Rate of change of Delta
- **Theta** — Daily time decay (divided by 365)
- **Vega** — Sensitivity to 1% IV change (divided by 100)
- **IV** — Implied volatility via Newton-Raphson on `bs_price`

### None-Safety

All portfolio-level Greeks in `StrategyState` use `(leg.value or 0.0)` guards to handle periods when Greeks haven't been computed yet (e.g., immediately after restart before the first option chain refresh).

### Integration Points

- **Strategy Condition Engine** — `combined_delta`, `leg_delta`, `gamma`, `theta`, `vega`, `iv` parameters
- **Adjustment Engine** — Delta-based rebalancing triggers
- **Dashboard** — Real-time position Greeks display
- **Option Chain** — Auto-refreshes Greeks every ~2 seconds with spot-movement invalidation

---

## Crash Recovery & Auto-Resume

**Modules:**
- `shoonya_platform/services/recovery_service.py` — Phase-2 RecoveryBootstrap
- `shoonya_platform/strategy_runner/strategy_executor_service.py` — Phase-3 `auto_resume_strategies()`
- `shoonya_platform/execution/trading_bot.py` — Startup orchestration

### Recovery Phases

| Phase | Component | Purpose |
|-------|-----------|---------|
| Phase 1 | Service restart (systemd) | Process restarts automatically on crash |
| Phase 2 | `RecoveryBootstrap` | Reconciles broker positions with local DB |
| Phase 3 | `auto_resume_strategies()` | Resumes strategies that were actively running |

### Phase-3 Auto-Resume Logic

On startup, the system scans `strategy_runner/saved_configs/` for strategies eligible to resume. A strategy is eligible when **all** conditions are met:

1. Config JSON has `"status": "RUNNING"`
2. A state file exists (`persistence/data/{name}_state.pkl`)
3. State has at least one active leg with `order_status: FILLED`
4. Entry time is from today (not stale from a previous session)

After re-registration:
- Executor loads the full persisted `StrategyState` (legs, entry prices, PnL history, adjustment counters)
- Broker reconciliation runs to validate positions match what the broker reports
- Normal tick loop resumes — exit, adjustment, and trailing-stop monitoring continue
- Telegram notification sent with recovery details

### State Persistence Lifecycle

| Trigger | When |
|---------|------|
| **Immediate** (after entry) | Right after `_execute_entry()` fills all legs |
| **Immediate** (after exit) | After legs are closed |
| **Immediate** (after adjustment) | After any leg adjustment |
| **Periodic** (every ~30s) | Elapsed-time check via `_last_persist_at` |

State files are JSON at `persistence/data/{name}_state.pkl` containing: legs (with Greeks, PnL, order IDs), spot/ATM data, adjustment history, entry/exit times, trailing stop state.

### Config Status Tracking

The `"status"` field in `saved_configs/{name}.json` tracks lifecycle:

| Status | Meaning |
|--------|---------|
| `RUNNING` | Strategy actively executing — eligible for auto-resume |
| `STOPPED` | User manually stopped — won't auto-resume |
| `COMPLETED` | All exit conditions met, cycle finished |

Updates use atomic `os.replace()` via a temp file to prevent corruption on crash.
