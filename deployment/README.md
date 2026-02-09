# Deployment Files

This folder contains all deployment-related configuration files for the Shoonya Platform.

---

## 📁 Contents

### Service Files

#### `trading.service`
**Purpose:** Systemd service definition for Linux/EC2 deployment

**Installation:**
```bash
sudo cp trading.service /etc/systemd/system/trading.service
sudo systemctl daemon-reload
sudo systemctl enable trading
sudo systemctl start trading
```

**Documentation:** See [DOCS/SERVICE_INSTALLATION_LINUX.md](../DOCS/SERVICE_INSTALLATION_LINUX.md)

---

### Systemd Timers (`systemd/` folder)

Automated trading session management using systemd timers:

#### Start Timer
- `shoonya_start.service` - Starts trading at 9:14 AM
- `shoonya_start.timer` - Timer trigger

#### Stop Timer  
- `shoonya_stop.service` - Stops trading at 3:31 PM
- `shoonya_stop.timer` - Timer trigger

#### Weekend Check
- `shoonya_weekend_check.service` - Checks if market is open on weekends
- `shoonya_weekend_check.timer` - Runs every Saturday/Sunday

**Installation:**
```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable shoonya_start.timer
sudo systemctl enable shoonya_stop.timer
sudo systemctl enable shoonya_weekend_check.timer
```

---

### Deployment Scripts

#### `install_schedulers.sh`
**Purpose:** Automated installation script for systemd timers

**Usage:**
```bash
chmod +x deployment/install_schedulers.sh
sudo ./deployment/install_schedulers.sh
```

**What it does:**
- Copies all timer/service files to `/etc/systemd/system/`
- Enables timers
- Shows timer status

#### `deploy_improvements.sh`
**Purpose:** Deployment helper script for applying improvements

**Usage:**
```bash
chmod +x deployment/deploy_improvements.sh
./deployment/deploy_improvements.sh
```

---

## 🚀 Quick Deployment Guide

### EC2/Linux Production Deployment

```bash
# 1. Clone repository
git clone <repo-url>
cd shoonya_platform

# 2. Run bootstrap
python bootstrap.py

# 3. Configure credentials
nano config_env/primary.env

# 4. Install service
sudo cp deployment/trading.service /etc/systemd/system/trading.service
sudo systemctl daemon-reload
sudo systemctl enable trading
sudo systemctl start trading

# 5. (Optional) Install timers for auto-start/stop
cd deployment
chmod +x install_schedulers.sh
sudo ./install_schedulers.sh
```

### Windows Development

See [DOCS/SERVICE_INSTALLATION_WINDOWS.md](../DOCS/SERVICE_INSTALLATION_WINDOWS.md) for NSSM/PowerShell setup.

---

## 📚 Related Documentation

- [SERVICE_INSTALLATION_LINUX.md](../DOCS/SERVICE_INSTALLATION_LINUX.md) - Complete Linux/EC2 guide
- [SERVICE_INSTALLATION_WINDOWS.md](../DOCS/SERVICE_INSTALLATION_WINDOWS.md) - Complete Windows guide
- [UTILITY_COMMANDS.md](../DOCS/UTILITY_COMMANDS.md) - Command reference
- [EC2_DEPLOYMENT_GUIDE.md](../DOCS/EC2_DEPLOYMENT_GUIDE.md) - EC2-specific deployment

---

**Last Updated:** 2026-02-09
