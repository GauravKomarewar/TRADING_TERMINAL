# 🕐 SYSTEMD SCHEDULER SETUP GUIDE

## Overview
Automated service scheduling for Shoonya Platform:
- **Auto-Start**: Monday-Friday at 8:45 AM (before market hours)
- **Auto-Stop**: Daily at 12:00 AM (midnight)

## Quick Install

```bash
chmod +x install_schedulers.sh
./install_schedulers.sh
```

## Manual Installation

### 1. Copy Service Files
```bash
sudo cp systemd/shoonya_start.timer /etc/systemd/system/
sudo cp systemd/shoonya_stop.timer /etc/systemd/system/
sudo cp systemd/shoonya_start.service /etc/systemd/system/
sudo cp systemd/shoonya_stop.service /etc/systemd/system/
```

### 2. Reload Systemd
```bash
sudo systemctl daemon-reload
```

### 3. Enable Timers
```bash
sudo systemctl enable shoonya_start.timer
sudo systemctl enable shoonya_stop.timer
```

### 4. Start Timers
```bash
sudo systemctl start shoonya_start.timer
sudo systemctl start shoonya_stop.timer
```

## Monitor Timers

### List All Timers
```bash
sudo systemctl list-timers shoonya_*
```

### Check Timer Status
```bash
sudo systemctl status shoonya_start.timer
sudo systemctl status shoonya_stop.timer
```

### View Timer Logs
```bash
journalctl -u shoonya_start.service -f
journalctl -u shoonya_stop.service -f
```

## Disable Schedulers

### Temporarily Stop
```bash
sudo systemctl stop shoonya_start.timer
sudo systemctl stop shoonya_stop.timer
```

### Permanently Disable
```bash
sudo systemctl disable shoonya_start.timer
sudo systemctl disable shoonya_stop.timer
```

## How It Works

### Start Timer (shoonya_start.timer)
- **Trigger**: Monday-Friday at 8:45 AM
- **Action**: Starts `shoonya_service.service`
- **Purpose**: Ensure trading system is online before market opens (9:15 AM)

### Stop Timer (shoonya_stop.timer)
- **Trigger**: Daily at 12:00 AM (midnight)
- **Action**: Stops `shoonya_service.service`
- **Purpose**: Clean shutdown after market hours, conserve resources overnight

### Session Validation
The system now includes:
- **Heartbeat Messages**: Every 5 minutes via Telegram
- **Broker Validation**: Checks broker limits to ensure session is alive
- **Auto-Recovery**: If session fails, service will restart automatically
- **Telegram Alerts**: Immediate notification on session issues

## Market Hours Coverage

```
8:45 AM  ─── Service Auto-Start ───> System Ready
9:15 AM  ─── Market Opens        ───> Trading Active
3:30 PM  ─── Market Closes       ───> Monitoring Continues
12:00 AM ─── Service Auto-Stop   ───> Clean Shutdown
```

## Troubleshooting

### Timers Not Firing
```bash
# Check timer syntax
systemctl cat shoonya_start.timer

# Check system time
timedatectl

# Check timer next execution
systemctl list-timers --all
```

### Service Won't Start
```bash
# Check service status
sudo systemctl status shoonya_service.service

# View detailed logs
journalctl -u shoonya_service.service -n 100
```

### Manual Control Override
```bash
# Start service manually (bypasses timer)
sudo systemctl start shoonya_service.service

# Stop service manually
sudo systemctl stop shoonya_service.service

# Restart service
sudo systemctl restart shoonya_service.service
```

## Telegram Integration

With the enhanced telegram integration, you'll receive:

### Regular Heartbeats (Every 5 minutes)
```
💓 SYSTEM HEARTBEAT
⏰ 14:30:15 | 09-Feb-2026
──────────────────
🔐 Session: ✅ Live
💰 Cash: ₹45,087.32
📊 Positions: 2
🤖 Status: Active & Monitoring
```

### Status Reports (Every 10 minutes)
```
📊 BOT STATUS REPORT
📅 2026-02-09 14:32:16
==============================
🤖 BOT STATUS: ✅ Active
🔐 Login Status: ✅ Connected
💰 ACCOUNT LIMITS
   • Available Cash: ₹45,087.32
   • Used Margin: ₹12,450.00
📍 POSITIONS: 2 active
📈 TRADING STATS
   • Today's Trades: 5
   • Total Trades: 127
🛡 RISK MANAGER STATUS
   • Daily PnL: ₹2,340.50
   • Loss Hit Today: NO
```

### Critical Alerts
```
🚨 CRITICAL: SERVICE RESTART REQUIRED
❌ Session recovery failed
🔄 Service will auto-restart in 5 seconds
⏰ Time: 05:23:15
```

## Configuration Files

- `systemd/shoonya_start.timer` - Start timer definition
- `systemd/shoonya_stop.timer` - Stop timer definition
- `systemd/shoonya_start.service` - Start action
- `systemd/shoonya_stop.service` - Stop action
- `shoonya_service.service` - Main trading service

## Notes

- Timers use system local time
- Saturday/Sunday: Service remains off (start timer doesn't trigger)
- Manual overrides work anytime: `sudo systemctl start/stop shoonya_service.service`
- Systemd will restart service automatically on crashes (configured in main service file)
