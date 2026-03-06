# Shoonya Trading Platform — Complete Operations Manual

> **Version:** 2.0 &nbsp;|&nbsp; **Last Updated:** 2026-03-06 &nbsp;|&nbsp; **Platform:** Ubuntu 24.04 LTS (EC2)

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Component Reference](#2-component-reference)
3. [Installation & First‑Time Setup](#3-installation--first-time-setup)
4. [Configuration Reference](#4-configuration-reference)
5. [Systemd Services & Timers](#5-systemd-services--timers)
6. [Nginx Reverse Proxy](#6-nginx-reverse-proxy)
7. [Master Account Manager](#7-master-account-manager)
8. [Gateway (Multi‑Client Router)](#8-gateway-multi-client-router)
9. [Copy Trading](#9-copy-trading)
10. [Strategy System Quick Reference](#10-strategy-system-quick-reference)
11. [Dashboard & API](#11-dashboard--api)
12. [Paper Trading Mode](#12-paper-trading-mode)
13. [Daily Operations](#13-daily-operations)
14. [Troubleshooting](#14-troubleshooting)
15. [Security Checklist](#15-security-checklist)

---

## 1. System Architecture

```
                          Internet
                             │
                    ┌────────▼────────┐
                    │  Nginx (80/443) │  TLS termination, HTTP→HTTPS redirect
                    │  /etc/nginx/    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────────┐
              │ / (dashboard)│ /api/ (execution) │
              │ → :8000      │ → :5000           │
              └──────────────┼──────────────────┘
                             │
     ┌───────────────────────┼──────────────────────────┐
     │                       │                          │
┌────▼─────┐          ┌─────▼──────┐            ┌──────▼──────┐
│ Gateway  │          │ Master Mgr │            │  Trading    │
│ Port 7000│          │ Port 9000  │            │  Service    │
│ (FastAPI)│          │ (FastAPI)  │            │  Port 5000  │
│          │          │            │            │  (Flask)    │
│ Routes   │          │ Registry   │            │  + Dashboard│
│ webhooks │          │ Poller     │            │  Port 8000  │
│ per-alias│          │ Copy-trade │            │  (FastAPI)  │
└──────────┘          └────────────┘            └─────────────┘
```

### Single‑Client (Current Setup)

| Component | Port | Purpose |
|-----------|------|---------|
| **Nginx** | 80 → 443 | TLS termination, public entry point |
| **Trading Service** | 5000 | Webhook receiver (Flask + Waitress) |
| **Dashboard** | 8000 | Web UI + REST API (FastAPI, same process as trading) |
| **Gateway** | 7000 | Multi-client webhook router (not required for single-client) |
| **Master Manager** | 9000 | Client registry, health polling, copy-trade control |

### Multi‑Client (Future)

Each additional client adds a `trading@<CLIENT_ID>.service` with unique ports:

| Client | Execution Port | Dashboard Port | Env File |
|--------|---------------|----------------|----------|
| FA14667 | 5001 | 8001 | `config_env/FA14667.env` |
| FA14668 | 5002 | 8002 | `config_env/FA14668.env` |

The **Gateway** routes `/<alias>/webhook` → correct client port.

---

## 2. Component Reference

### Files & Directories

```
shoonya_platform/
├── main.py                    # Entry point for trading service
├── gateway_main.py            # Entry point for gateway
├── master_manager.py          # Entry point for master manager
├── config_env/
│   ├── primary.env            # Client credentials & config
│   ├── gateway.env            # Gateway bind settings
│   ├── master.env             # Master manager credentials
│   ├── client_routes.json     # Gateway routing table
│   └── master_clients.json    # Master client registry
├── shoonya_platform/
│   ├── execution/             # Order execution engine
│   ├── strategy_runner/       # Strategy engine
│   ├── persistence/           # SQLite DB (orders, audit)
│   ├── services/              # Copy trading service
│   ├── api/dashboard/         # Dashboard web UI
│   ├── risk/                  # Risk manager
│   └── core/config.py         # Config loader
├── master/
│   ├── api.py                 # Master FastAPI endpoints
│   ├── registry.py            # Client registry (JSON-backed)
│   └── poller.py              # Health polling engine
├── logs/
│   └── FA14667/               # Per-client rotating logs
└── tests/                     # 333+ tests
```

---

## 3. Installation & First‑Time Setup

### Prerequisites

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv nginx
```

### Clone & Install

```bash
cd /home/ubuntu
git clone https://github.com/GauravKomarewar/TRADING_TERMINAL.git shoonya_platform
cd shoonya_platform
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt  # or: pip install -e .
```

### Configure Environment

```bash
# 1. Copy template and edit with your credentials
cp config_env/primary.env.example config_env/primary.env
nano config_env/primary.env
# Set: USER_NAME, USER_ID, PASSWORD, TOKEN, VC, APP_KEY, WEBHOOK_SECRET_KEY
# Set: DASHBOARD_PASSWORD (min 8 chars, NOT "change_me")
# Set: TRADING_MODE=PAPER  (until you're ready for live)

# 2. Gateway config (already created)
# config_env/gateway.env — GATEWAY_HOST=127.0.0.1, GATEWAY_PORT=7000

# 3. Master manager config
# config_env/master.env — strong passwords, MASTER_HOST=127.0.0.1
```

### Install Systemd Services

```bash
# Services are already installed at /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trading.service gateway.service master.service
sudo systemctl enable trading_start.timer trading_stop.timer
```

### First Start

```bash
# Start all services (gateway first, then master, then trading)
sudo systemctl start gateway.service
sudo systemctl start master.service
sudo systemctl start trading.service

# Verify
sudo systemctl status trading.service gateway.service master.service
```

---

## 4. Configuration Reference

### primary.env — Client Trading Service

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `USER_NAME` | Yes | Shoonya username | `GAURAV_Y_KOMAREWAR` |
| `USER_ID` | Yes | Shoonya client ID | `FA14667` |
| `PASSWORD` | Yes | Shoonya login password | `Algo@240894` |
| `TOKEN` | Yes | TOTP secret key | `6JTYX57J5F...` |
| `VC` | Yes | Vendor code | `FA14667_U` |
| `APP_KEY` | Yes | API app key | `2f48e1a828...` |
| `IMEI` | Yes | Device identifier | `abc1234` |
| `WEBHOOK_SECRET_KEY` | Yes | Shared webhook secret | `GK_TRADINGVIEW_BOT_2408` |
| `DASHBOARD_PASSWORD` | Yes | Dashboard login (min 8 chars) | `MyStr0ngP@ss` |
| `HOST` | No | Bind address (default: 127.0.0.1) | `127.0.0.1` |
| `PORT` | No | Execution port (default: 5000) | `5000` |
| `DASHBOARD_PORT` | No | Dashboard port (default: 8000) | `8000` |
| `THREADS` | No | Waitress threads (default: 4) | `4` |
| `TRADING_MODE` | No | `PAPER` or `LIVE` (default: LIVE) | `PAPER` |
| `RISK_BASE_MAX_LOSS` | Yes | Daily max loss (negative) | `-2500` |
| `RISK_TRAIL_STEP` | No | Trailing stop step | `100` |
| `TELEGRAM_TOKEN` | No | Telegram bot token | `791943...` |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID | `6058616357` |

### gateway.env — Gateway Service

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_HOST` | `127.0.0.1` | Bind address |
| `GATEWAY_PORT` | `7000` | Gateway port |
| `GATEWAY_ROUTES_FILE` | `config_env/client_routes.json` | Route registry file |

### master.env — Master Manager

| Variable | Default | Description |
|----------|---------|-------------|
| `MASTER_NAME` | - | Display name for master |
| `MASTER_ADMIN_PASSWORD` | **REQUIRED** (min 12 chars) | Dashboard login |
| `MASTER_API_TOKEN` | **REQUIRED** (min 12 chars) | Bearer token for API access |
| `MASTER_HOST` | `127.0.0.1` | Bind address |
| `MASTER_PORT` | `9000` | Master API port |
| `MASTER_REGISTRY_FILE` | `config_env/master_clients.json` | Client registry |
| `MASTER_HEALTH_POLL_INTERVAL` | `30` | Health check interval (seconds) |
| `MASTER_AUTO_BLOCK_MISSED_POLLS` | `3` | Auto-block after N misses |

### Copy Trading Variables (in client .env)

| Variable | Default | Description |
|----------|---------|-------------|
| `COPY_TRADING_ROLE` | `standalone` | `standalone`, `master`, or `follower` |
| `COPY_TRADING_SECRET` | - | Shared HMAC-SHA256 secret (required if not standalone) |
| `COPY_TRADING_FOLLOWERS` | `""` | Comma-separated follower URLs (master only) |
| `COPY_TRADING_MASTER_ENDPOINT` | - | Master's URL (follower only) |
| `COPY_TRADING_MODE` | `mirror` | `mirror` (same qty) or `scaled` |
| `COPY_TRADING_SCALE_FACTOR` | `1.0` | Quantity multiplier (if mode=scaled) |

---

## 5. Systemd Services & Timers

### Service Units

| Unit | Type | Description | Auto‑Start |
|------|------|-------------|------------|
| `trading.service` | Long-running | Primary trading client (primary.env) | Via timer |
| `trading@.service` | Template | Multi-client template (`config_env/%i.env`) | Manual |
| `gateway.service` | Long-running | Webhook gateway router | Via timer |
| `master.service` | Long-running | Master account manager | Via timer |
| `trading_start.service` | Oneshot | Starts gateway → master → trading | Via timer |
| `trading_stop.service` | Oneshot | Stops trading → master → gateway | Via timer |

### Timer Units

| Timer | Schedule | Action |
|-------|----------|--------|
| `trading_start.timer` | Mon–Fri 08:45 IST | Start all services |
| `trading_stop.timer` | Mon–Fri 16:00 IST | Stop all services |

### Common Commands

```bash
# Start/stop entire platform
sudo systemctl start trading_start.service    # Starts gateway + master + trading
sudo systemctl start trading_stop.service     # Stops all

# Individual service control
sudo systemctl start trading.service
sudo systemctl stop trading.service
sudo systemctl restart trading.service
sudo systemctl status trading.service

# View logs
journalctl -u trading.service -f              # Follow live logs
journalctl -u trading.service --since "1h ago"
journalctl -u gateway.service -f
journalctl -u master.service -f

# Multi-client (if configured)
sudo systemctl start trading@FA14668.service

# Timer management
systemctl list-timers                         # Show all timer schedules
sudo systemctl enable trading_start.timer     # Enable auto-start
sudo systemctl disable trading_stop.timer     # Disable auto-stop
```

### Service Recovery

All services have `Restart=always` with `RestartSec=10` and `StartLimitBurst=5` in a 300s window. If a service crash-loops 5 times in 5 minutes, systemd stops trying.

To reset after crash-loop:
```bash
sudo systemctl reset-failed trading.service
sudo systemctl start trading.service
```

---

## 6. Nginx Reverse Proxy

### Current Configuration

**File:** `/etc/nginx/sites-available/trading` (symlinked to `sites-enabled/`)

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name 129.154.41.30;
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    server_name 129.154.41.30;

    ssl_certificate /etc/nginx/ssl/nginx.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Dashboard (port 8000)
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Execution API / webhooks (port 5000)
    location /api/ {
        proxy_pass http://127.0.0.1:5000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### How It Works

1. **Port 80** → Redirects all HTTP to HTTPS
2. **Port 443** `/` → Proxies to Dashboard on `127.0.0.1:8000`
3. **Port 443** `/api/` → Proxies to Execution service on `127.0.0.1:5000`
4. Self-signed SSL certificate at `/etc/nginx/ssl/nginx.{crt,key}`

### Nginx Commands

```bash
sudo nginx -t                    # Test config syntax
sudo systemctl reload nginx      # Apply changes (no downtime)
sudo systemctl restart nginx     # Full restart
tail -f /var/log/nginx/error.log # Error logs
```

### Adding Master Dashboard to Nginx (Optional)

To expose the Master Manager dashboard externally:

```nginx
location /master/ {
    proxy_pass http://127.0.0.1:9000/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

## 7. Master Account Manager

The Master Manager is a centralized FastAPI service (port 9000) that manages all trading client instances.

### Features

- **Client Registry** — Register, enable/disable, block/unblock clients
- **Health Polling** — Automatic health checks every 30s, auto-blocks unresponsive clients
- **Copy Trading Control** — Enable/disable roles (master/follower) from one place
- **Systemd Control** — Start/stop/restart client services via API
- **Web Dashboard** — HTML admin panel at `http://127.0.0.1:9000/`

### Accessing the Dashboard

```bash
# Locally on the server
curl http://127.0.0.1:9000/

# Via browser (if exposed through nginx)
# https://129.154.41.30/master/
```

Login with `MASTER_ADMIN_PASSWORD` from `master.env`.

### API Endpoints

All API endpoints require either a session cookie (from login) or `Authorization: Bearer <MASTER_API_TOKEN>`.

#### Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/login` | None | Login form page |
| POST | `/auth/login` | None | Login (form: `password=...`) |
| POST | `/auth/logout` | Session | Logout |

#### Client Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clients` | List all registered clients |
| POST | `/api/clients` | Register or update a client |
| GET | `/api/clients/{id}` | Get client details |
| DELETE | `/api/clients/{id}` | Remove a client |
| GET | `/api/summary` | Platform‑wide summary stats |

#### Service Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| PUT | `/api/clients/{id}/service/enable` | Enable client service |
| PUT | `/api/clients/{id}/service/disable` | Disable client service |
| PUT | `/api/clients/{id}/block` | Block trading (JSON: `{"reason": "..."}`) |
| PUT | `/api/clients/{id}/unblock` | Unblock trading |

#### Systemd Control (from Master)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/clients/{id}/systemd/start` | Start client's systemd service |
| POST | `/api/clients/{id}/systemd/stop` | Stop client's systemd service |
| POST | `/api/clients/{id}/systemd/restart` | Restart client's systemd service |
| GET | `/api/clients/{id}/systemd/status` | Get systemd status output |

#### Copy Trading Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| PUT | `/api/clients/{id}/copy-trading/enable` | Enable copy trading |
| PUT | `/api/clients/{id}/copy-trading/disable` | Disable copy trading |

Enable body (master role):
```json
{"role": "master", "followers": ["http://127.0.0.1:5002", "http://127.0.0.1:5003"]}
```

Enable body (follower role):
```json
{"role": "follower", "master_id": "GAURAV_Y_KOMAREWAR:FA14667"}
```

#### Bot Self‑Registration

Bots call these on startup (using `X-Master-Token` header):

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | Bot registers itself with master |
| GET | `/api/permission/{id}` | Bot polls permissions every N seconds |

Permission response:
```json
{
  "client_id": "FA14667",
  "service_enabled": true,
  "trading_blocked": false,
  "block_reason": null,
  "copy_trading_enabled": false,
  "copy_trading_role": "standalone"
}
```

### Client Registry Fields

Each client in `master_clients.json` tracks:

| Field | Type | Description |
|-------|------|-------------|
| `client_id` | string | Unique ID (e.g., "FA14667") |
| `service_enabled` | bool | Is the service allowed to run? |
| `trading_blocked` | bool | Is trading blocked? |
| `block_reason` | string | Why blocked (if applicable) |
| `copy_trading_role` | string | `standalone`, `master`, or `follower` |
| `copy_trading_enabled` | bool | Is copy trading active? |
| `last_heartbeat` | string | Last health check timestamp |
| `last_health_status` | string | `healthy`, `unreachable`, `http_500` |

### Health Polling

The master polls each enabled client every 30 seconds:

1. Sends GET `{webhook_url}/health` to each client
2. Records status: `healthy` (200), `http_XXX` (error), `unreachable` (timeout)
3. After 3 consecutive misses → **auto-blocks trading** for that client
4. Blocked clients show `block_reason: "Auto-blocked: N missed health checks"`

---

## 8. Gateway (Multi‑Client Router)

The Gateway (port 7000) routes incoming webhooks and dashboard requests to the correct client based on their alias.

### How Routing Works

```
TradingView sends POST to:  /FA14667/webhook
                             ↓
Gateway looks up FA14667 in client_routes.json
                             ↓
Forwards to: http://127.0.0.1:5000/webhook
```

### Route Registry (`config_env/client_routes.json`)

```json
{
  "clients": [
    {
      "alias": "FA14667",
      "display_name": "GAURAV_Y_KOMAREWAR:FA14667",
      "webhook_url": "http://127.0.0.1:5000",
      "dashboard_url": "http://127.0.0.1:8000",
      "enabled": true
    }
  ]
}
```

**Hot-reload:** The gateway checks file modification time on each request. Editing this file takes effect immediately — no restart needed.

### Gateway Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all registered clients |
| GET | `/health` | Gateway health check |
| POST | `/{alias}/webhook` | Forward webhook to client |
| ANY | `/{alias}/dashboard/{path}` | Forward dashboard traffic to client |

### Adding a New Client to Gateway

1. Add entry to `config_env/client_routes.json`
2. The gateway auto-reloads on next request
3. No restart required

---

## 9. Copy Trading

Copy trading allows a **master** bot to replicate its trades to one or more **follower** bots.

### Architecture

```
TradingView → Master Bot (role=master)
                  │
                  ├── Executes trade on master account
                  │
                  └── CopyTradingService.fan_out_alert()
                        │
                        ├── HMAC-SHA256 signs the payload
                        │
                        ├── POST /copy-alert → Follower A
                        ├── POST /copy-alert → Follower B
                        └── POST /copy-alert → Follower C
                              │
                              └── validate_copy_signature()
                                    │ Valid?
                                    └── process_copy_alert()
```

### Setup

**Master Bot** (`config_env/master_bot.env`):
```env
COPY_TRADING_ROLE=master
COPY_TRADING_SECRET=your_shared_secret_min_32_chars
COPY_TRADING_FOLLOWERS=http://127.0.0.1:5002,http://127.0.0.1:5003
COPY_TRADING_MODE=mirror
```

**Follower Bot** (`config_env/follower_bot.env`):
```env
COPY_TRADING_ROLE=follower
COPY_TRADING_SECRET=your_shared_secret_min_32_chars
COPY_TRADING_MASTER_ENDPOINT=http://127.0.0.1:5001
COPY_TRADING_MODE=mirror
```

### Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `mirror` | Same quantity as master | Identical account sizes |
| `scaled` | Quantity × scale_factor | Different capital sizes |

### Circuit Breaker

Each follower has an independent circuit breaker:

- **3 consecutive failures** → Circuit trips (follower skipped)
- **Backoff:** 30s → 60s → 120s → ... → 600s max
- **Recovery:** After backoff expires, follower is retried (half-open)
- **Reset:** On successful delivery, counter resets to 0

Monitor circuit breaker status via `CopyTradingService.circuit_breaker_status`.

### Copy‑Alert Payload Format

```json
{
  "copy_trading": true,
  "master_client_id": "GAURAV_Y_KOMAREWAR:FA14667",
  "master_result_status": "success",
  "copy_mode": "mirror",
  "scale_factor": 1.0,
  "timestamp": "2026-03-06T10:30:45Z",
  "alert": { ... original TradingView alert ... }
}
```

Headers sent to followers:
- `Content-Type: application/json`
- `X-Copy-Signature: <HMAC-SHA256 hex digest>`
- `X-Copy-Master: <master_client_id>`

---

## 10. Strategy System Quick Reference

Strategies are defined as JSON files in `shoonya_platform/strategy_runner/strategies/`. The engine supports:

- **Entry:** ATM/OTM strikes, straddle/strangle/custom, index conditions
- **Exit:** Profit target, stop loss, trailing stop, time-based
- **Adjustment:** Close leg, partial close, convert to spread, reduce by %

See `documentation/03_STRATEGY_SYSTEM.md` for the full strategy JSON schema.

### Key Engine Components

| Component | Purpose |
|-----------|---------|
| `StrategyExecutorService` | Orchestrates strategy lifecycle |
| `EntryEngine` | Evaluates entry conditions, selects strikes |
| `ExitEngine` | Monitors profit/loss/trailing/time exits |
| `AdjustmentEngine` | Evaluates and executes position adjustments |
| `ConditionEngine` | Evaluates conditional rules (spot price, VIX, time) |
| `MarketReader` | Reads option chain from SQLite databases |

---

## 11. Dashboard & API

The dashboard is a FastAPI web application co-hosted in the same process as the trading service.

### Access

- **Local:** `http://127.0.0.1:8000/`
- **Via Nginx:** `https://129.154.41.30/`
- **Login:** Uses `DASHBOARD_PASSWORD` from env

### Key Pages

| Page | URL | Purpose |
|------|-----|---------|
| Login | `/auth/login` | Password authentication |
| Home | `/` | System overview, quick actions |
| Strategies | `/strategies` | List, create, start/stop strategies |
| Strategy Detail | `/strategy/{name}` | Live P&L, legs, adjustments |
| Orders | `/orders` | Order history with status tracking |
| Option Chain | `/option-chain` | Live option chain viewer |
| Risk Dashboard | `/risk` | Daily P&L, max loss, risk state |
| Diagnostics | `/diagnostics` | System health, config validation |

### Key API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Service health check |
| POST | `/webhook` | TradingView webhook receiver |
| GET | `/api/strategies` | List active strategies |
| POST | `/api/strategy/start` | Start a strategy |
| POST | `/api/strategy/stop` | Stop a strategy |
| GET | `/api/orders` | Order history |
| GET | `/api/risk/status` | Risk manager state |

Full API reference in `documentation/API_REFERENCE.json`.

---

## 12. Paper Trading Mode

Set `TRADING_MODE=PAPER` in your client `.env` to block **ALL** real broker submissions.

### How It Works

- Orders go through the full pipeline (validation, risk check, execution guard)
- At the broker submission step, a mock order ID is generated instead
- Orders receive status `PAPER_EXECUTED` instead of being sent to Shoonya
- Logged clearly: `STEP_4_PAPER_MODE | TRADING_MODE=PAPER — broker call blocked`

### Usage

```bash
# Enable paper trading
echo "TRADING_MODE=PAPER" >> config_env/primary.env
sudo systemctl restart trading.service

# Switch to live
# Change TRADING_MODE=LIVE in primary.env
sudo systemctl restart trading.service
```

---

## 13. Daily Operations

### Normal Trading Day

The system auto-starts via timer at **08:45 IST** and auto-stops at **16:00 IST** (Mon–Fri).

**Morning checklist:**
```bash
# 1. Verify services started
sudo systemctl status trading.service gateway.service master.service

# 2. Check broker login succeeded
journalctl -u trading.service --since "today" | grep -i "login"

# 3. Check for errors
journalctl -u trading.service --since "today" | grep -E "ERROR|CRITICAL"
```

**Manual start (if timers are not running):**
```bash
sudo systemctl start trading_start.service
# This starts: gateway → master → trading
```

**Manual stop:**
```bash
sudo systemctl start trading_stop.service
# This stops: trading → master → gateway
```

### Monitoring

```bash
# Live trading logs
journalctl -u trading.service -f

# Application-level logs (rotating, per-client)
tail -f logs/FA14667/trading_bot.log
tail -f logs/FA14667/execution_service.log
tail -f logs/FA14667/risk_manager.log
tail -f logs/FA14667/order_watcher.log

# System health
curl -s http://127.0.0.1:5000/health | python3 -m json.tool
curl -s http://127.0.0.1:9000/health | python3 -m json.tool
curl -s http://127.0.0.1:7000/health | python3 -m json.tool
```

### Audit Log

Every order state change is recorded in the `audit_log` table:

```bash
# View recent audit entries
sqlite3 shoonya_platform/persistence/data/orders.db \
  "SELECT timestamp, action, command_id, new_value FROM audit_log ORDER BY timestamp DESC LIMIT 20;"
```

---

## 14. Troubleshooting

### Service Won't Start

| Symptom | Cause | Fix |
|---------|-------|-----|
| `BROKER_LOGIN_FAILED` | Invalid credentials or broker API down | Check TOTP key, run `sudo chronyc makestep` for clock drift |
| `DASHBOARD_PASSWORD not set` | Missing env var | Add `DASHBOARD_PASSWORD=<strong_pass>` to `.env` |
| `MASTER_ADMIN_PASSWORD... default value` | Weak password in master.env | Set a 12+ char unique password |
| `Start request repeated too quickly` | Crash-loop (5 failures in 5 min) | Check logs: `journalctl -u trading.service -n 50`, fix root cause, then `sudo systemctl reset-failed trading.service` |
| `JSONDecodeError: Expecting value` | Broker API returning empty response | Normal pre-market; broker may be down. Service auto-retries on next timer trigger. |

### Service Keeps Restarting

```bash
# Check failure count
systemctl show trading.service | grep -i restart

# Reset failure counter
sudo systemctl reset-failed trading.service

# View last error
journalctl -u trading.service --since "1h ago" --no-pager | tail -30
```

### Nginx Issues

```bash
# Test config
sudo nginx -t

# Check SSL cert permissions
ls -la /etc/nginx/ssl/   # nginx.key must be readable by root

# Verify upstream is reachable
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:5000/health
```

### Clock Drift (Common on EC2)

If TOTP authentication fails:
```bash
sudo chronyc makestep
# Verify
chronyc tracking | head -5
```

---

## 15. Security Checklist

- [ ] **DASHBOARD_PASSWORD** is strong (min 8 chars, not a default)
- [ ] **MASTER_ADMIN_PASSWORD** is strong (min 12 chars, not a default)
- [ ] **MASTER_API_TOKEN** is a random string (min 12 chars)
- [ ] **WEBHOOK_SECRET_KEY** is unique and strong
- [ ] **COPY_TRADING_SECRET** (if used) is 32+ chars
- [ ] **TRADING_MODE=PAPER** until you've verified the system
- [ ] Nginx uses **TLSv1.2+** only (no TLSv1.0/1.1)
- [ ] Gateway binds to **127.0.0.1** (not 0.0.0.0)
- [ ] Master Manager binds to **127.0.0.1** (not 0.0.0.0)
- [ ] Only Nginx (80/443) is exposed to the internet
- [ ] Firewall blocks direct access to ports 5000, 7000, 8000, 9000
- [ ] Self-signed cert replaced with proper CA cert for production
- [ ] `primary.env`, `master.env` are NOT committed to git (check `.gitignore`)

### Firewall Rules (Recommended)

```bash
# Allow SSH + Nginx only from internet
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw default deny incoming
sudo ufw enable
```

---

## Quick Reference Card

| Action | Command |
|--------|---------|
| Start all services | `sudo systemctl start trading_start.service` |
| Stop all services | `sudo systemctl start trading_stop.service` |
| Restart trading only | `sudo systemctl restart trading.service` |
| View trading logs | `journalctl -u trading.service -f` |
| View master logs | `journalctl -u master.service -f` |
| Check all service status | `systemctl status trading.service gateway.service master.service` |
| Check timer schedule | `systemctl list-timers` |
| Run tests | `cd /home/ubuntu/shoonya_platform && DASHBOARD_PASSWORD=test_pass_123 python -m pytest tests/ -v` |
| Paper trading ON | Set `TRADING_MODE=PAPER` in `.env`, restart |
| Paper trading OFF | Set `TRADING_MODE=LIVE` in `.env`, restart |
| View audit log | `sqlite3 shoonya_platform/persistence/data/orders.db "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 20;"` |
| Master dashboard | `http://127.0.0.1:9000/` |
| Client dashboard | `https://129.154.41.30/` |
