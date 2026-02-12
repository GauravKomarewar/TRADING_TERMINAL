# DNSS Standalone Execution - Quick Reference

## ⚡ 30-Second Start

```bash
# 1. Create strategy in dashboard OR use example config
# 2. Run standalone:
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_nifty_weekly.json

# Done! Strategy is now trading
```

---

## Configuration Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CREATE STRATEGY IN DASHBOARD                             │
│    (Identity → Entry → Adjustment → Exit → Risk → Schedule) │
│                                                              │
│    Click "Save Strategy"                                    │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. CONFIG SAVED TO DISK                                     │
│    Path: saved_configs/{strategy_name}.json                 │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. RUN STANDALONE                                           │
│    python -m shoonya_platform.strategies.delta_neutral \    │
│      --config ./saved_configs/{strategy_name}.json          │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. STRATEGY EXECUTES EVERY 2 SECONDS                        │
│    • Loads market data                                      │
│    • Checks entry/adjustment/exit conditions               │
│    • Places orders when conditions met                      │
│    • Logs status every 60 ticks (2 minutes)                │
└─────────────────────────────────────────────────────────────┘
```

---

## Command Examples

### Basic Usage
```bash
# Run with default config
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json
```

### Custom Polling Interval
```bash
# Poll every 1 second (more frequent)
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json \
  --poll-interval 1.0

# Poll every 5 seconds (less frequent)
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json \
  --poll-interval 5.0
```

### Limited Duration
```bash
# Run for 30 minutes then exit
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json \
  --duration 30

# Run for 8 hours (trading session)
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json \
  --duration 480
```

### Verbose Logging
```bash
# Enable debug output
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json \
  --verbose
```

### All Options Combined
```bash
python -m shoonya_platform.strategies.delta_neutral \
  --config /path/to/config.json \
  --poll-interval 2.0 \
  --duration 60 \
  --verbose
```

---

## Service Setup

### Windows (PowerShell)

**Option 1: Run Script**
```powershell
# Set config path (optional)
$env:DNSS_CONFIG = ".\saved_configs\my_config.json"

# Run service
.\run_dnss_service.ps1

# Stop with Ctrl+C
```

**Option 2: Windows Service (Task Scheduler)**
```powershell
# Create scheduled task
$taskAction = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -File `"$(Get-Location)\run_dnss_service.ps1`""

$taskTrigger = New-ScheduledTaskTrigger -AtStartup

Register-ScheduledTask `
  -TaskName "DNSS-Strategy-Service" `
  -Action $taskAction `
  -Trigger $taskTrigger `
  -RunLevel Highest

# Start task
Start-ScheduledTask -TaskName "DNSS-Strategy-Service"

# View logs (Event Viewer → Windows Logs → Application)
```

### Linux (Systemd)

**Setup:**
```bash
# Copy service file
sudo cp deployment/dnss.service /etc/systemd/system/

# Edit config path if needed
sudo nano /etc/systemd/system/dnss.service
# Change line: Environment="DNSS_CONFIG=..."

# Enable service (auto-start on boot)
sudo systemctl daemon-reload
sudo systemctl enable dnss

# Start service
sudo systemctl start dnss

# View logs (real-time)
sudo journalctl -u dnss -f

# Stop service
sudo systemctl stop dnss
```

**All Services Commands:**
```bash
# Start
sudo systemctl start dnss

# Stop
sudo systemctl stop dnss

# Restart
sudo systemctl restart dnss

# Status
sudo systemctl status dnss

# Logs (last 50 lines)
sudo journalctl -u dnss -n 50

# Logs (real-time)
sudo journalctl -u dnss -f

# Logs (last hour)
sudo journalctl -u dnss --since "1 hour ago"

# Disable auto-start
sudo systemctl disable dnss
```

---

## Configuration Reference

### Minimal Config (Required Fields)
```json
{
  "name": "My Strategy",
  "identity": {
    "exchange": "NFO",
    "underlying": "NIFTY",
    "instrument_type": "OPTIDX",
    "product_type": "NRML",
    "order_type": "LIMIT"
  },
  "entry": {
    "timing": {
      "entry_time": "09:20",
      "exit_time": "15:15"
    },
    "position": {
      "lots": 1
    },
    "legs": {
      "target_entry_delta": 0.20
    }
  },
  "adjustment": {
    "delta": {
      "trigger": 0.50,
      "target": 0.20,
      "max_leg_delta": 0.65
    },
    "pnl": {
      "profit_lock_trigger": 1500
    },
    "general": {
      "cooldown_seconds": 0
    }
  }
}
```

### Full Config (All Options)
See: `saved_configs/dnss_nifty_weekly.json` or `saved_configs/dnss_example_config.json`

---

## Example Configurations

### NIFTY Daily
```bash
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json  # or dnss_nifty_daily.json
```

### BANKNIFTY Weekly
```json
{
  "name": "DNSS BANKNIFTY Weekly",
  "identity": {
    "underlying": "BANKNIFTY",
    ...
  },
  "entry": {
    "timing": {
      "entry_time": "09:20",
      "exit_time": "15:15"
    },
    "legs": {
      "target_entry_delta": 0.25  // Slightly higher delta for BANKNIFTY
    }
  },
  ...
}
```

### FINNIFTY Daily
```json
{
  "name": "DNSS FINNIFTY Daily",
  "identity": {
    "underlying": "FINNIFTY",
    ...
  },
  "entry": {
    "timing": {
      "entry_time": "09:20",
      "exit_time": "15:15"
    },
    "position": {
      "lots": 2  // Different lot size
    },
    "legs": {
      "target_entry_delta": 0.30
    }
  },
  ...
}
```

---

## Troubleshooting

### ❌ Config file not found
```
❌ Config file not found: ./saved_configs/dnss_nifty_weekly.json
```

**Fix:**
```bash
# Use full path
python -m shoonya_platform.strategies.delta_neutral \
  --config /full/path/to/config.json

# Or create strategy in dashboard first
```

### ❌ Module not found
```
ModuleNotFoundError: No module named 'shoonya_platform'
```

**Fix:**
```bash
# Ensure virtual environment is activated
# Windows:
.\venv\Scripts\Activate.ps1

# Linux/macOS:
source ./venv/bin/activate

# Run bootstrap if needed:
python bootstrap.py
```

### ❌ No strategy called 'dnss'
```
ModuleNotFoundError: No module named 'shoonya_platform.strategies.delta_neutral'
```

**Fix:** Ensure file path is correct: `shoonya_platform/strategies/delta_neutral/__main__.py`

### ❌ Environment configuration missing
```
❌ Failed to load environment: ...
```

**Fix:**
```bash
# Create config_env/primary.env with broker credentials
echo "DASHBOARD_PASSWORD=password" > config_env/primary.env
echo "SHO_USERNAME=username" >> config_env/primary.env
echo "SHO_PASSWORD=password" >> config_env/primary.env
echo "SHO_TWO_FA=2fa_token" >> config_env/primary.env
```

### ❌ Invalid JSON config
```
❌ Invalid JSON: Expecting value: line 1 column 1
```

**Fix:**
```bash
# Validate JSON syntax
python -m json.tool saved_configs/config.json

# Or create via dashboard (guaranteed valid)
```

### ⏱️ Strategy running slow
```
⏱️ Loop overrun: 2.5s > 2.0s interval
```

**Fix:**
```bash
# Increase polling interval
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/config.json \
  --poll-interval 5.0
```

---

## Monitoring

### Real-Time Status
```bash
# Monitor logs in real-time
sudo journalctl -u dnss -f

# Or check Python logs directly
tail -f logs/dnss.log
```

### Log Output Format
```
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | 📂 Loading config...
2026-02-12 10:16:10 | WARNING  | DNSS_STANDALONE  | ⚠️  Strategy generated 2 command(s)
2026-02-12 10:16:10 | INFO     | DNSS_STANDALONE  |    → SELL NIFTY26FEB2650CE qty=50
```

### Dashboard Integration
```
Standalone execution DOES NOT replace dashboard.
Instead:
1. Strategy configured in dashboard
2. Run standalone OR activate via dashboard
3. Dashboard still shows live positions/PnL
4. Real-time data synced through broker API
```

---

## Multi-Strategy Setup

### Running Multiple Strategies Simultaneously

**Option 1: Separate Terminal Windows**
```bash
# Terminal 1: NIFTY
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_nifty_weekly.json

# Terminal 2: BANKNIFTY
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_banknifty_daily.json

# Terminal 3: FINNIFTY
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_finnifty_weekly.json
```

**Option 2: Background Processes (Linux)***
```bash
# Start all in background
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_nifty_weekly.json &
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_banknifty_daily.json &
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_finnifty_weekly.json &

# Check status
jobs

# Kill all
killall python
```

**Option 3: systemd Multiple Instances**
```bash
# Create separate service for each
sudo cp /etc/systemd/system/dnss.service /etc/systemd/system/dnss-nifty.service
sudo cp /etc/systemd/system/dnss.service /etc/systemd/system/dnss-banknifty.service

# Edit each service file with different config path
sudo nano /etc/systemd/system/dnss-nifty.service
# Change: Environment="DNSS_CONFIG=.../dnss_nifty_weekly.json"

# Enable all
sudo systemctl enable dnss-nifty dnss-banknifty
sudo systemctl start dnss-nifty dnss-banknifty

# Monitor
sudo journalctl -u dnss-nifty -u dnss-banknifty -f
```

---

## Performance Tips

1. **Increase polling interval** if system is slow
   ```bash
   --poll-interval 5.0  # Instead of default 2.0
   ```

2. **Run on dedicated machine** for high-frequency strategies

3. **Monitor CPU/Memory** in production
   ```bash
   # Linux
   watch -n 1 'ps aux | grep python'
   
   # Windows (PowerShell)
   Get-Process python -IncludeUserName | Select ProcessName, CPU, WorkingSet
   ```

4. **Use systemd** for auto-restart on crash
   ```bash
   # In service file:
   Restart=on-failure
   RestartSec=10  # Retry every 10 seconds
   ```

---

## File Locations

| File | Purpose |
|------|---------|
| `shoonya_platform/strategies/delta_neutral/__main__.py` | CLI entry point |
| `shoonya_platform/strategies/delta_neutral/dnss.py` | Strategy implementation |
| `shoonya_platform/strategies/saved_configs/` | Strategy JSON configs |
| `config_env/primary.env` | Broker credentials |
| `run_dnss_service.ps1` | Windows service runner |
| `deployment/run_dnss_service.sh` | Linux service runner |
| `deployment/dnss.service` | Systemd service file |
| `logs/` | Execution logs |

---

## Next Steps

1. ✅ **Create** a strategy in dashboard
2. ✅ **Test** standalone: `python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/...`
3. ✅ **Deploy** as service (systemd or Windows Task Scheduler)
4. ✅ **Monitor** via logs: `journalctl -f` or dashboard
5. ✅ **Scale** by running multiple configs simultaneously

---

See [DNSS_STANDALONE_GUIDE.md](DNSS_STANDALONE_GUIDE.md) for comprehensive documentation.
