# Operations Guide

> Last verified: 2026-03-01

## Monitoring

### Service Health

```bash
# Systemd service status
sudo systemctl status trading

# Live journal logs
journalctl -u trading -f

# Recent logs (last hour)
journalctl -u trading --since "1 hour ago"

# Timer status
systemctl list-timers --all | grep trading
```

### Application Health Endpoints

```bash
# Execution service health
curl http://localhost:5000/health

# Dashboard status
curl http://localhost:8000/dashboard/home/status

# Bot stats (requires dashboard_session cookie — see below)
curl -b "dashboard_session=<cookie>" http://localhost:8000/dashboard/home/stats
```

> **How to obtain the `dashboard_session` cookie:**
>
> **Option A (Browser):** Log into the dashboard at `http://localhost:8000`, then open
> Developer Tools → Application → Cookies → copy the `dashboard_session` value.
>
> **Option B (Programmatic):**
> ```bash
> # Login and extract the Set-Cookie header:
> curl -c cookies.txt -X POST http://localhost:8000/auth/login \
>   -d "username=admin&password=YOUR_PASSWORD"
> # Use the cookie file in subsequent requests:
> curl -b cookies.txt http://localhost:8000/dashboard/home/stats
> ```

### Log Files

Per-client logs in `logs/<USER_ID>/`:

| Log File | Content |
|----------|---------|
| `trading_bot.log` | Main bot operations, login, startup |
| `dashboard.log` | Dashboard API requests |
| `command_service.log` | Order placement details |
| `order_watcher.log` | Fill monitoring, status updates |
| `strategy_runner.log` | Strategy execution cycles |
| `risk.log` | Risk manager decisions, PnL tracking |

### Telegram Alerts

If configured (`TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID`), the bot sends:
- Startup/shutdown notifications
- Order fills and rejections
- Risk warnings (approaching max loss)
- Daily summary at market close
- Periodic heartbeat (configurable)

---

## Troubleshooting

### Common Issues

#### Bot won't start

```bash
# Check environment file
cat config_env/primary.env | grep -v "^#" | grep -v "^$"

# Verify critical imports
source venv/bin/activate
DASHBOARD_PASSWORD=test python3 -c "
from shoonya_platform.execution.trading_bot import ShoonyaBot
from shoonya_platform.core.config import Config
print('Imports OK')
"

# Check for port conflicts
ss -tlnp | grep -E "5000|8000"
```

#### Dashboard not accessible

```bash
# Check if running
curl -s http://127.0.0.1:8000/auth/status

# Check DASHBOARD_PASSWORD is set
grep DASHBOARD_PASSWORD config_env/primary.env

# For remote access, use SSH tunnel (dashboard binds to 127.0.0.1)
ssh -L 8000:127.0.0.1:8000 ubuntu@your-ec2-ip
```

#### Orders rejected by RMS

Common causes:
1. **Insufficient margin** — Check account funds via dashboard
2. **Position limit exceeded** — Reduce lot size
3. **Market hours** — NSE/NFO: 09:15–15:30 IST, MCX: varies
4. **Product type mismatch** — Options must use NRML for positional

```bash
# Check recent order errors
journalctl -u trading --since "10 min ago" | grep -i "reject\|error\|rms"
```

#### Strategy not executing

```bash
# Check strategy status via API
curl -b "dashboard_session=<cookie>" \
  http://localhost:8000/dashboard/strategy/NIFTY_DNSS/execution-status

# Check strategy config validation
source venv/bin/activate
python3 -c "
import json
from shoonya_platform.strategy_runner.config_schema import validate_config
with open('shoonya_platform/strategy_runner/saved_configs/nifty_dnss_actual.json') as f:
    config = json.load(f)
ok, issues = validate_config(config)
print('Valid:', ok)
for i in issues: print(f'[{i.severity}] {i.message}')
"
```

#### Database locked errors

The platform uses WAL mode to minimize locking. If you still see issues:

```bash
# Check database status
python3 -c "
from shoonya_platform.persistence.database import get_connection
conn = get_connection()
print('WAL mode:', conn.execute('PRAGMA journal_mode').fetchone()[0])
print('Busy timeout:', conn.execute('PRAGMA busy_timeout').fetchone()[0])
conn.close()
"
```

---

## Security Considerations

### Credentials

- All secrets in `config_env/primary.env` — **never commit to git**
- File permissions: `chmod 600 config_env/primary.env`
- TOTP key (`TOKEN`) enables 2FA for broker login
- `WEBHOOK_SECRET_KEY` validates webhook payloads (signature check)

### Dashboard Access

- Protected by `DASHBOARD_PASSWORD` env var
- Cookie-based sessions with configurable TTL
- Binds to `127.0.0.1` by default — not directly accessible from internet
- Use SSH tunnel for remote access

### Execution Service

- Binds to `0.0.0.0:5000` — **restrict with firewall rules**
- Webhook signature validation via HMAC
- Rate limiting recommended (not built-in)

### Systemd Service Hardening

The `trading.service` file enables:
- `PrivateTmp=yes` — isolated /tmp
- `NoNewPrivileges=yes` — can't escalate privileges
- `ProtectKernelTunables=yes` — read-only kernel parameters

---

## Database Maintenance

### Cleanup Old Orders

```python
# Built-in cleanup (runs on schedule)
# Can also trigger manually:
python3 utilities/cleanup.py
```

### Backup Database

```bash
# SQLite backup (safe with WAL mode)
cp shoonya_platform/persistence/data/orders.db /backup/orders_$(date +%Y%m%d).db
```

### Reset Database

```bash
# Stop service first!
sudo systemctl stop trading
rm shoonya_platform/persistence/data/orders.db
# Restart — tables auto-created
sudo systemctl start trading
```

---

## Weekend Market Check

The `scripts/weekend_market_check.py` can be run on weekends to:
- Verify market is actually closed
- Check for special trading sessions (budget day, etc.)
- Log system status for Monday morning checks

---

## Useful Scripts

| Script | Location | Purpose |
|--------|----------|---------|
| `verify_orders.py` | `utilities/` | Cross-reference local DB with broker orders |
| `weekend_market_check.py` | `scripts/` | Weekend market status check |
| `scriptmaster.py` | `scripts/` | ScriptMaster symbol database management |
| `broker_inspect.py` | `shoonya_platform/tools/` | Inspect broker state (positions, orders) |
| `cleanup.py` | `utilities/` | Runtime cleanup (stop service, remove __pycache__) |
| `backup.py` | `utilities/` | ZIP backup of project |
| `bootstrap.py` | `utilities/` | One-stop setup (venv, deps, services) |
