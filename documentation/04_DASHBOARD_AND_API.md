# Dashboard & API Reference

> Last verified: 2026-03-01 | Source: `api/dashboard/api/router.py` (4081 lines, 97 handlers, 70 routes)

## Dashboard Overview

The dashboard is a FastAPI application served by uvicorn on port `8000` (configurable via `DASHBOARD_PORT`).

- **Authentication:** Cookie-based sessions, single shared password (`DASHBOARD_PASSWORD` env var)
- **Session TTL:** 8 hours (configurable via `DASHBOARD_SESSION_TTL_SEC`)
- **Architecture:** Intent-only control plane — dashboard NEVER accesses broker directly

---

## Web Pages

10 HTML pages in `shoonya_platform/api/dashboard/web/`:

| Page | URL | Description |
|------|-----|-------------|
| `login.html` | `/dashboard/web/login.html` | Authentication page |
| `dashboard.html` | `/dashboard/web/dashboard.html` | Main control panel (positions, PnL, account) |
| `orderbook.html` | `/dashboard/web/orderbook.html` | System + broker order book |
| `place_order.html` | `/dashboard/web/place_order.html` | Manual order placement |
| `strategy.html` | `/dashboard/web/strategy.html` | Strategy management & execution |
| `strategy_builder.html` | `/dashboard/web/strategy_builder.html` | Visual strategy config builder |
| `strategy_logs.html` | `/dashboard/web/strategy_logs.html` | Strategy execution logs |
| `option_chain_dashboard.html` | `/dashboard/web/option_chain_dashboard.html` | Live option chain |
| `option_chain_analytics.html` | `/dashboard/web/option_chain_analytics.html` | Option chain analytics & charts |
| `diagnostics.html` | `/dashboard/web/diagnostics.html` | System diagnostics & order tracing |

---

## Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/login` | Login with `{ password }` → sets `dashboard_session` cookie |
| `POST` | `/auth/logout` | Destroys session |
| `GET` | `/auth/status` | Returns `{ authenticated, client_id }` |

---

## API Endpoints (Grouped)

### System & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/home/status` | Bot health, uptime, connection status |
| `GET` | `/dashboard/home/stats` | Trade counts, PnL summary |
| `GET` | `/dashboard/home/session-info` | Current session details |
| `GET` | `/dashboard/home/account` | Broker account info (funds, margins) |
| `POST` | `/dashboard/home/test-telegram` | Send test Telegram message |
| `POST` | `/dashboard/home/force-login` | Force broker re-login |

### Symbol Search & Instruments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/symbols/search` | Search symbols by query string |
| `GET` | `/dashboard/symbols/exchanges` | List available exchanges |
| `GET` | `/dashboard/symbols/expiries` | Get expiry dates for an underlying |
| `GET` | `/dashboard/symbols/contracts` | Get contracts for a symbol/expiry |

### Order Book

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/orderbook` | System orders from local DB |
| `GET` | `/dashboard/orderbook/broker` | Live orders from broker API |
| `GET` | `/dashboard/trade-history` | Historical trades with pagination |

### Order Operations (Intent-Based)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/dashboard/intent/generic` | Submit generic order intent |
| `POST` | `/dashboard/intent/strategy` | Submit strategy-specific intent |
| `POST` | `/dashboard/intent/advanced` | Advanced order with conditions |
| `POST` | `/dashboard/intent/basket` | Basket (multi-leg) order |
| `POST` | `/dashboard/force-exit` | Force exit specific position |
| `POST` | `/dashboard/cancel-order` | Cancel pending order |
| `POST` | `/dashboard/modify-order` | Modify existing order |

### Strategy Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/strategy/list` | List all saved strategy configs |
| `GET` | `/dashboard/strategy/{name}/load` | Load specific strategy config |
| `POST` | `/dashboard/strategy/save` | Save new/updated strategy config |
| `DELETE` | `/dashboard/strategy/{name}/delete` | Delete strategy config |
| `POST` | `/dashboard/strategy/{name}/rename` | Rename strategy |
| `POST` | `/dashboard/strategy/{name}/clone` | Clone strategy config |
| `POST` | `/dashboard/strategy/{name}/validate` | Validate strategy config |

### Strategy Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/dashboard/strategy/{name}/start-execution` | Start strategy executor |
| `POST` | `/dashboard/strategy/{name}/stop-execution` | Stop strategy executor |
| `POST` | `/dashboard/strategy/{name}/force-exit` | Force exit all strategy positions |
| `GET` | `/dashboard/strategy/{name}/execution-status` | Strategy status, PnL, legs |
| `GET` | `/dashboard/strategy/all-status` | All running strategies status |
| `GET` | `/dashboard/strategy/{name}/logs` | Strategy execution logs |

### Recovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/recovery/list` | List recoverable strategies |
| `POST` | `/dashboard/recovery/{name}/resume` | Resume recovered strategy |

### Orphan Position Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/orphans/list` | List orphan (untracked) positions |
| `GET` | `/dashboard/orphans/summary` | Orphan position summary |
| `GET` | `/dashboard/orphans/rules` | List orphan management rules |
| `POST` | `/dashboard/orphans/rules` | Create orphan management rule |
| `PUT` | `/dashboard/orphans/rules/{id}` | Update orphan rule |
| `DELETE` | `/dashboard/orphans/rules/{id}` | Delete orphan rule |

### Option Chain

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/option-chain/symbols` | Available underlyings |
| `GET` | `/dashboard/option-chain/expiries` | Expiry dates for symbol |
| `GET` | `/dashboard/option-chain/chain` | Full option chain data |
| `GET` | `/dashboard/option-chain/nearest` | Nearest ATM option |

### Position Details & Greeks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/positions/live` | Live positions overview |
| `GET` | `/dashboard/positions/{symbol}/details` | Position details with Greeks |
| `GET` | `/dashboard/positions/legs` | All leg-level data |

### Index Tokens (VIX, etc.)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/index-tokens/list` | Available index tokens |
| `GET` | `/dashboard/index-tokens/prices` | Current index prices |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/analytics/history/health` | Analytics system health |
| `GET` | `/dashboard/analytics/history/strategy-samples` | Historical strategy data |
| `GET` | `/dashboard/analytics/history/events` | Historical events |
| `GET` | `/dashboard/analytics/history/index-ticks` | Historical index data |
| `GET` | `/dashboard/analytics/history/option-metrics` | Historical option metrics |

### Diagnostics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard/diagnostics/orders` | Order diagnostic trace |
| `GET` | `/dashboard/diagnostics/intent-verification` | Verify intent execution |

---

## Execution Service Endpoints (Flask, Port 5000)

From `api/http/execution_app.py`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/webhook` | TradingView/external webhook alerts |
| `GET` | `/health` | Health check |
| `GET` | `/status` | Bot status summary |

Webhook payload is signature-validated against `WEBHOOK_SECRET_KEY`.

---

## Telegram Commands

From `api/http/telegram_controller.py`:

| Command | Description |
|---------|-------------|
| `/status` | Bot status and PnL |
| `/positions` | Current positions |
| `/orders` | Recent orders |
| `/help` | List available commands |

Telegram control requires `TELEGRAM_ALLOWED_USERS` to be configured.
