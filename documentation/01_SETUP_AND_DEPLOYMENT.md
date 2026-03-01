# Setup & Deployment Guide

> Last verified: 2026-03-01 | Ubuntu 24.04 LTS | Python 3.12.3

## Prerequisites

- **OS:** Ubuntu 22.04+ (EC2 recommended: t3.medium or better)
- **Python:** 3.9+ (system runs 3.12.3)
- **Git:** For repository cloning

---

## 1. Initial Setup

### Clone & Virtual Environment

```bash
cd /home/ubuntu
git clone https://github.com/GauravKomarewar/TRADING_TERMINAL.git shoonya_platform
cd shoonya_platform
python3 -m venv venv
source venv/bin/activate
```

### Install Dependencies

```bash
pip install --upgrade pip
pip install -e .                    # Installs from pyproject.toml
pip install requirements/NorenRestApi-0.0.30-py2.py3-none-any.whl  # Shoonya API client
```

> **Note:** All dependencies are declared in `pyproject.toml`. There is no `requirements.txt`.

### Configure Environment

```bash
cp config_env/primary.env.example config_env/primary.env
nano config_env/primary.env
```

Fill in ALL required variables (see [02_CONFIGURATION_GUIDE.md](02_CONFIGURATION_GUIDE.md)).

### Verify Installation

```bash
source venv/bin/activate
python3 -c "from shoonya_platform.execution.trading_bot import ShoonyaBot; print('OK')"
DASHBOARD_PASSWORD=test python3 -c "from shoonya_platform.api.dashboard.api.router import router; print(f'{len(router.routes)} routes OK')"
python3 -m pytest tests/ -q --tb=no  # Should show 336 passed
```

---

## 2. Running the Platform

### Development / Manual Start

```bash
cd /home/ubuntu/shoonya_platform
source venv/bin/activate
python3 main.py                     # Default: uses config_env/primary.env
python3 main.py --env config_env/custom.env  # Multi-client: custom env file
```

**What starts:**
1. ShoonyaBot initializes, logs into Shoonya API
2. Execution HTTP service on port `5000` (env: `PORT`)
3. Dashboard on port `8000` (env: `DASHBOARD_PORT`)
4. Scheduler for heartbeat, daily summary, cleanup tasks

### Stop Gracefully

```bash
# If running in foreground: Ctrl+C
# If running as service:
sudo systemctl stop trading
```

---

## 3. Systemd Service (Production)

### Install the Service

```bash
# Edit the service file to match your system user and home directory.
# The default is 'ubuntu' — replace with your system user if different.
sudo nano deployment/trading.service
# Update these lines with your username and home path:
#   User=ubuntu          ← replace 'ubuntu' with your system user if different
#   Group=ubuntu         ← replace 'ubuntu' with your system user if different
#   WorkingDirectory=/home/ubuntu/shoonya_platform
#   ExecStart=/home/ubuntu/shoonya_platform/venv/bin/python /home/ubuntu/shoonya_platform/main.py

sudo cp deployment/trading.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trading
sudo systemctl start trading
```

### Service Details

| Setting | Value |
|---------|-------|
| Service name | `trading` |
| ExecStart | `venv/bin/python main.py` |
| Restart policy | Always, 10s delay, max 5 attempts per 300s |
| Memory limit | 2 GB |
| CPU quota | 80% |
| Shutdown timeout | 30 seconds (SIGTERM → SIGKILL) |
| Security | PrivateTmp, NoNewPrivileges, ProtectKernelTunables |

### Service Commands

```bash
sudo systemctl start trading
sudo systemctl stop trading
sudo systemctl restart trading
sudo systemctl status trading
journalctl -u trading -f           # Live logs
journalctl -u trading --since "1 hour ago"  # Recent logs
```

---

## 4. Automatic Scheduling (Systemd Timers)

### Install Timers

```bash
cd /home/ubuntu/shoonya_platform
sudo bash deployment/install_schedulers.sh
```

This installs 3 timers from `deployment/systemd/`:

| Timer | Schedule | Action |
|-------|----------|--------|
| `trading_start.timer` | Mon–Fri 08:45 AM | Starts `trading.service` before market open |
| `trading_stop.timer` | Mon–Fri 04:00 PM | Stops `trading.service` after market close (see note below) |
| `trading_weekend_check.timer` | Sat–Sun 09:00 AM | Runs `scripts/weekend_market_check.py` |

> **Note:** `trading_start.timer` starts the service before market open and `trading_stop.timer` stops it after market close. Adjust `trading_stop.timer`'s `OnCalendar` value in `deployment/systemd/trading_stop.timer` if your trading hours differ.

### Verify Timers

```bash
systemctl list-timers --all | grep trading
```

### Timer Files Reference

```
deployment/systemd/
├── trading_start.service
├── trading_start.timer
├── trading_stop.service
├── trading_stop.timer
├── trading_weekend_check.service
└── trading_weekend_check.timer
```

---

## 5. Full Deployment Script

For a complete deploy (service + timers + restart):

```bash
sudo bash deployment/deploy_improvements.sh
```

This script:
1. Copies `trading.service` to `/etc/systemd/system/`
2. Runs `install_schedulers.sh` (installs all timers)
3. Reloads systemd daemon
4. Restarts the `trading` service
5. Verifies service status and timer activation

---

## 6. Multi-Client Setup

Run multiple bot instances with different accounts:

```bash
# Client 1
python3 main.py --env config_env/client1.env &

# Client 2
python3 main.py --env config_env/client2.env &
```

Each client uses:
- Its own `.env` file (different credentials, ports)
- Its own log directory: `logs/<USER_ID>/`
- Its own SQLite database (configurable via `ORDERS_DB_PATH`)

For systemd, use `deployment/trading@.service` (template unit):

```bash
sudo systemctl start trading@client1
sudo systemctl start trading@client2
```

---

## 7. Log Locations

```
logs/
└── <USER_ID>/
    ├── trading_bot.log        # Main bot operations
    ├── dashboard.log          # Dashboard API requests
    ├── command_service.log    # Order placement details
    ├── order_watcher.log      # Fill monitoring
    ├── strategy_runner.log    # Strategy execution
    └── risk.log               # Risk manager decisions
```

Logs rotate automatically based on size. See `logging/logger_config.py` for configuration.

---

## 8. Firewall / Security

```bash
# Dashboard (local access only — already binds to 127.0.0.1)
# If you need remote access, use SSH tunnel:
ssh -L 8000:127.0.0.1:8000 ubuntu@your-ec2-ip

# Execution service (webhook receiver — binds to 0.0.0.0:5000)
# Restrict to TradingView IPs if possible:
sudo ufw allow from 52.89.214.238 to any port 5000
sudo ufw allow from 34.212.75.30 to any port 5000
sudo ufw allow from 54.218.53.128 to any port 5000
sudo ufw allow from 52.32.178.7 to any port 5000
```
