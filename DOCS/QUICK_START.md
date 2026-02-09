# 📋 QUICK START GUIDE - System Improvements

## 🎯 What Was Fixed

1. ✅ **Auto-Recovery**: Session failures now trigger automatic service restart
2. ✅ **Telegram Heartbeat**: Get status updates every 5 minutes
3. ✅ **Broker Validation**: Active session checking via broker API
4. ✅ **Auto Scheduling**: Service starts at 8:45 AM (Mon-Fri), stops at 12:00 AM
5. ✅ **Enhanced Messages**: Better telegram notifications

---

## 🚀 One-Command Deployment

```bash
cd /home/ec2-user/shoonya_platform
chmod +x deploy_improvements.sh
./deploy_improvements.sh
```

This will:
- Update systemd service configuration
- Install auto-start/stop timers
- Restart the service
- Verify everything is running

---

## ✅ What You'll See on Telegram

### Every 5 Minutes (Heartbeat)
```
💓 SYSTEM HEARTBEAT
⏰ 14:30:15 | 09-Feb-2026
──────────────────
🔐 Session: ✅ Live
💰 Cash: ₹45,087.32
📊 Positions: 2
🤖 Status: Active & Monitoring
```

### Every 10 Minutes (Full Status)
```
📊 BOT STATUS REPORT
📅 2026-02-09 14:32:16
==============================
🤖 BOT STATUS: ✅ Active
🔐 Login Status: ✅ Connected
💰 ACCOUNT LIMITS
   • Available Cash: ₹45,087.32
... (full report)
```

### On Session Failure (Auto-Restart)
```
🚨 CRITICAL: SERVICE RESTART REQUIRED
❌ Session recovery failed
🔄 Service will auto-restart in 5 seconds
⏰ Time: 05:23:15
```

---

## 📅 Automatic Schedule

```
Monday-Friday:
  8:45 AM  ━━━━━> Service Starts
  9:15 AM  ━━━━━> Market Opens
  3:30 PM  ━━━━━> Market Closes
  
Daily:
  12:00 AM ━━━━━> Service Stops
```

Weekend: Service stays off (no auto-start on Sat/Sun)

---

## 🔍 Monitoring Commands

```bash
# Watch live logs
journalctl -u shoonya_service -f

# Check service status
sudo systemctl status shoonya_service

# View timer schedule
systemctl list-timers shoonya_*

# Manual control (overrides timers)
sudo systemctl start shoonya_service   # Start now
sudo systemctl stop shoonya_service    # Stop now
sudo systemctl restart shoonya_service # Restart now
```

---

## 🛠️ Manual Installation (if deploy script fails)

### Step 1: Update Service File
```bash
sudo cp shoonya_service.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### Step 2: Install Schedulers
```bash
chmod +x install_schedulers.sh
./install_schedulers.sh
```

### Step 3: Restart Service
```bash
sudo systemctl restart shoonya_service
```

---

## ❓ Troubleshooting

### Service Won't Start
```bash
# Check logs
journalctl -u shoonya_service -n 100

# Check service file
systemctl cat shoonya_service

# Verify python path
/home/ec2-user/shoonya_platform/venv/bin/python --version
```

### Heartbeat Not Showing
```bash
# Check if telegram is connected
grep "Telegram" /home/ec2-user/shoonya_platform/trading_bot.log

# Test telegram manually via dashboard
curl http://localhost:8000/test-telegram
```

### Timers Not Firing
```bash
# Check timer status
systemctl list-timers --all

# Check system time
timedatectl

# Enable timers manually
sudo systemctl enable shoonya_start.timer
sudo systemctl enable shoonya_stop.timer
sudo systemctl start shoonya_start.timer
sudo systemctl start shoonya_stop.timer
```

### Session Still Failing
```bash
# Check broker credentials in env file
cat config_env/primary.env | grep USER_ID
cat config_env/primary.env | grep TOTP

# Test login manually
python test2.py
```

---

## 📊 Files Changed

### Modified
- `shoonya_platform/execution/trading_bot.py` (heartbeat + auto-restart)
- `shoonya_platform/risk/supreme_risk.py` (logging fix)
- `notifications/telegram.py` (enhanced messages)
- `shoonya_service.service` (improved restart policy)

### New Files
- `systemd/shoonya_start.timer`
- `systemd/shoonya_stop.timer`
- `systemd/shoonya_start.service`
- `systemd/shoonya_stop.service`
- `install_schedulers.sh`
- `deploy_improvements.sh`
- `SCHEDULER_GUIDE.md`
- `IMPROVEMENTS_SUMMARY.md`
- `QUICK_START.md` (this file)

---

## 📖 More Information

- Full details: [IMPROVEMENTS_SUMMARY.md](IMPROVEMENTS_SUMMARY.md)
- Scheduler guide: [SCHEDULER_GUIDE.md](SCHEDULER_GUIDE.md)

---

## ✅ Verification Checklist

After deployment, verify:

- [ ] Service is running: `sudo systemctl status shoonya_service`
- [ ] Timers are active: `systemctl list-timers shoonya_*`
- [ ] Heartbeat received on telegram (wait 5 min)
- [ ] Status report received on telegram (wait 10 min)
- [ ] Dashboard accessible: `curl http://localhost:8000`
- [ ] Logs show no errors: `journalctl -u shoonya_service -n 50`

---

## 🎉 Done!

Your trading system now:
- ✅ Automatically recovers from session failures
- ✅ Sends heartbeat every 5 minutes
- ✅ Validates broker connection in real-time
- ✅ Starts automatically at 8:45 AM (Mon-Fri)
- ✅ Stops automatically at midnight
- ✅ Keeps you informed with enhanced telegram messages

**Issues?** Check logs: `journalctl -u shoonya_service -f`
