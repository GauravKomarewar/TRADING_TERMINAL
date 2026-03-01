# Deployment Files

This folder contains systemd service and timer configurations for the Shoonya Trading Platform.

---

## 📁 Contents

### `trading.service`
Main systemd service that runs the trading platform.

**Auto-generated** by `bootstrap.py` with correct user/paths for the current system.

**Manual install:**
```bash
sudo cp utilities/deployment/trading.service /etc/systemd/system/trading.service
sudo systemctl daemon-reload
sudo systemctl enable trading
sudo systemctl start trading
```

---

### `systemd/` — Timers

Automated Mon-Fri trading session management:

| File | Purpose |
|------|---------|
| `trading_start.timer` | Triggers at **8:45 AM IST** Mon-Fri |
| `trading_start.service` | Runs `systemctl start trading.service` |
| `trading_stop.timer` | Triggers at **4:00 PM IST** Mon-Fri |
| `trading_stop.service` | Runs `systemctl stop trading.service` |

**Install timers:**
```bash
sudo cp utilities/deployment/systemd/*.service utilities/deployment/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trading_start.timer trading_stop.timer
sudo systemctl start trading_start.timer trading_stop.timer
```

---

## 🚀 Quick Setup (Recommended)

All of the above is handled automatically by `bootstrap.py`:

```bash
git clone https://github.com/GauravKomarewar/TRADING_TERMINAL.git
cd shoonya_platform
python3 utilities/bootstrap.py
```

This will:
1. Create venv at project root
2. Install all Python dependencies
3. Generate & install service + timer files with correct paths
4. Set up shell auto-activation
5. Configure the cleanup utility

---

## 📊 Monitoring

```bash
# Service status
sudo systemctl status trading

# Live logs
journalctl -u trading -f

# Timer status
sudo systemctl list-timers trading_*
```
