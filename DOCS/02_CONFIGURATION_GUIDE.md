# Configuration Guide

> Last verified: 2026-03-01 | Source: `config_env/primary.env.example` and `core/config.py`

## Environment File

All configuration is loaded from a `.env` file. Default: `config_env/primary.env`.

```bash
cp config_env/primary.env.example config_env/primary.env
nano config_env/primary.env
```

Override with `--env` flag: `python3 main.py --env config_env/custom.env`

---

## Required Variables

### Shoonya Credentials

| Variable | Description | Example |
|----------|-------------|---------|
| `USER_NAME` | Shoonya login username | `FA12345` |
| `USER_ID` | Shoonya user/client ID | `FA12345` |
| `PASSWORD` | Shoonya login password | `yourpassword` |
| `TOKEN` | TOTP key for 2FA (base32) | `JBSWY3DPEHPK3PXP` |
| `VC` | Vendor code from Shoonya | `FA12345_U` |
| `APP_KEY` | API key from Shoonya | `abc123def456...` |
| `IMEI` | Device identifier | `abc123` |

### Webhook Security

| Variable | Description | Example |
|----------|-------------|---------|
| `WEBHOOK_SECRET_KEY` | Shared secret for webhook signature validation | `mysecretkey123` |

### Dashboard

| Variable | Description | Example |
|----------|-------------|---------|
| `DASHBOARD_PASSWORD` | Password for dashboard login (required at startup) | `strongpassword` |

### Risk Management

| Variable | Description | Default |
|----------|-------------|---------|
| `RISK_BASE_MAX_LOSS` | Maximum allowed loss (₹, negative) | `-15` |
| `RISK_TRAIL_STEP` | Trailing profit-lock step (₹) | `1` |

---

## Optional Variables

### Server Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Execution service bind address | `127.0.0.1` |
| `PORT` | Execution service port | `5000` |
| `DASHBOARD_PORT` | Dashboard port | `8000` |
| `THREADS` | Waitress worker threads | `4` |

### Telegram Notifications

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_TOKEN` | Bot token from @BotFather | *(disabled if empty)* |
| `TELEGRAM_CHAT_ID` | Chat/group ID for notifications | *(disabled if empty)* |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated user IDs for Telegram control | *(empty)* |

### Database

| Variable | Description | Default |
|----------|-------------|---------|
| `ORDERS_DB_PATH` | Custom path for SQLite database | `persistence/data/orders.db` |

### Risk Fine-Tuning

| Variable | Description | Default |
|----------|-------------|---------|
| `RISK_WARNING_THRESHOLD` | Warning at this % of max loss | `0.80` |
| `RISK_MAX_CONSECUTIVE_LOSS_DAYS` | Kill switch after N consecutive loss days | `3` |
| `RISK_STATUS_UPDATE_MIN` | Risk status update interval (minutes) | `30` |
| `RISK_STATE_FILE` | Path to risk state persistence file | *(auto)* |
| `RISK_PNL_RETENTION_1M` | 1-minute PnL samples retention (days) | `3` |
| `RISK_PNL_RETENTION_5M` | 5-minute PnL samples retention (days) | `7` |
| `RISK_PNL_RETENTION_1D` | Daily PnL retention (days) | `30` |

### Retry & Reporting

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_RETRY_ATTEMPTS` | Order retry attempts | `3` |
| `RETRY_DELAY` | Delay between retries (seconds) | `1` |
| `REPORT_FREQUENCY_MINUTES` | Auto-report interval | `10` |

---

## Strategy Configuration (JSON)

Strategy configs are JSON files in `shoonya_platform/strategy_runner/saved_configs/`.

### Schema Version 4.0 — Required Sections

```json
{
  "schema_version": "4.0",
  "name": "NIFTY_DNSS",
  "identity": {
    "exchange": "NFO",
    "underlying": "NIFTY",
    "product_type": "NRML",
    "order_type": "MARKET"
  },
  "timing": {
    "entry_window_start": "09:20",
    "entry_window_end": "15:20",
    "eod_exit_time": "15:15"
  },
  "schedule": {
    "expiry_mode": "weekly_current",
    "active_days": ["mon", "tue", "wed", "thu", "fri"]
  },
  "entry": {
    "global_conditions": [],
    "legs": [
      {
        "tag": "CE_SELL",
        "side": "SELL",
        "option_type": "CE",
        "lots": 1,
        "strike_mode": "standard",
        "strike_selection": "ATM"
      }
    ]
  },
  "adjustment": { "rules": [] },
  "exit": {}
}
```

### Config Validation

```python
from shoonya_platform.strategy_runner.config_schema import validate_config
import json

with open("strategy_runner/saved_configs/nifty_dnss_actual.json") as f:
    config = json.load(f)

is_valid, issues = validate_config(config)
for issue in issues:
    print(f"[{issue.severity}] {issue.message}")
```

### Valid Values

| Field | Valid Options |
|-------|-------------|
| `exchange` | `NFO`, `MCX`, `NSE`, `BSE`, `CDS`, `BFO` |
| `product_type` | `NRML`, `MIS`, `CNC`, `CO`, `BO` |
| `order_type` | `MARKET`, `LIMIT`, `SL`, `SL-M` |
| `side` | `BUY`, `SELL` |
| `option_type` | `CE`, `PE` |
| `instrument` | `OPT`, `FUT` |
| `strike_mode` | `standard`, `exact`, `atm_points`, `atm_pct`, `match_leg` |
| `expiry_mode` | `weekly_current`, `weekly_next`, `monthly_current`, `monthly_next` |

### Available Strategy Configs

| File | Description |
|------|-------------|
| `nifty_dnss_actual.json` | NIFTY delta-neutral short straddle |
| `crudeoilm_dnss_actual.json` | CrudeOilM delta-neutral short straddle |
| `crudeoilm_test_all.json` | CrudeOilM test configuration |
| `strategy_config.schema.json` | JSON Schema definition |

---

## Hardcoded Constants

These are set in code, not configurable via environment:

| Constant | Value | Location |
|----------|-------|----------|
| Shoonya API host | `https://api.shoonya.com/NorenWClientTP/` | `core/config.py` |
| Shoonya WebSocket | `wss://api.shoonya.com/NorenWSTP/` | `core/config.py` |
| Dashboard session TTL | 8 hours (env: `DASHBOARD_SESSION_TTL_SEC`) | `api/dashboard/auth.py` |
| Order DB default path | `persistence/data/orders.db` | `persistence/database.py` |
| Shutdown timeout | 30 seconds | `main.py` |
