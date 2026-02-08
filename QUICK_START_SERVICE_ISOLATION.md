# QUICK START - SERVICE ISOLATION & LOG ROTATION
## 5-Minute Integration Guide

---

## What's Changed?

### Before (Old Way)
```python
# Every file did this
import logging
logger = logging.getLogger(__name__)

# All logs went to single file
logger.info("Something happened")
```

### After (New Way) 
```python
# Import the new function
from shoonya_platform.logging.logger_config import get_component_logger

# Get your service's dedicated logger
logger = get_component_logger('trading_bot')  # Each service gets its own log file

# Use exactly the same
logger.info("Something happened")
```

---

## Log Files Created

When you run the service, you get separate logs in `/opt/shoonya/logs/`:

```
📄 execution_service.log     ← Main webhook service (main.py)
📄 trading_bot.log           ← Bot logic (ShoonyaBot)
📄 command_service.log       ← Order placement (CommandService)
📄 order_watcher.log         ← Order tracking (OrderWatcherEngine)
📄 risk_manager.log          ← Risk checks (SupremeRiskManager)
📄 execution_guard.log       ← Trade guards (ExecutionGuard)
📄 dashboard.log             ← Dashboard API
📄 recovery_service.log      ← Recovery operations
```

Each log file automatically rotates at 50MB. Old files are kept as backups (`trading_bot.log.1`, `.log.2`, etc.)

---

## Running on EC2

### 1. Deploy the Code
```bash
# SSH into EC2
ssh -i key.pem ec2-user@your-ip

# Install (one-time)
cd /opt/shoonya
source venv/bin/activate
pip install -r requirements/requirements.txt
```

### 2. Start the Service
```bash
# Deploy systemd service file
sudo cp shoonya_service.service /etc/systemd/system/shoonya_signal_processor.service

# Enable and start
sudo systemctl enable shoonya_signal_processor
sudo systemctl start shoonya_signal_processor

# Check status
sudo systemctl status shoonya_signal_processor
```

### 3. Verify Logs
```bash
# Check logs are being created
ls -la /opt/shoonya/logs/

# Watch live
tail -f /opt/shoonya/logs/execution_service.log

# Watch all at once (in separate terminal)
tail -f /opt/shoonya/logs/*.log
```

---

## Finding Issues

### Example 1: Bot crashed - Debug it
```bash
# View bot-specific logs
grep "ERROR\|CRITICAL" /opt/shoonya/logs/trading_bot.log

# Get last 20 lines before error (add context)
tail -50 /opt/shoonya/logs/trading_bot.log
```

### Example 2: Order not placed - Where's the issue?
```bash
# Check command service
grep "order_id=12345" /opt/shoonya/logs/command_service.log

# Check if risk blocked it
grep "order_id=12345" /opt/shoonya/logs/risk_manager.log

# Check execution guard
grep "order_id=12345" /opt/shoonya/logs/execution_guard.log

# Check order watcher
grep "order_id=12345" /opt/shoonya/logs/order_watcher.log
```

### Example 3: Service keeps crashing - How often?
```bash
# Count restarts
grep -c "STARTUP\|initialization complete" /opt/shoonya/logs/trading_bot.log

# If > 1, what was the error?
grep "ERROR\|CRITICAL" /opt/shoonya/logs/trading_bot.log
```

---

## Download Logs for Analysis

### Method 1: Using SCP (easiest)
```bash
# From your local machine
scp -i your-key.pem -r ec2-user@your-ip:/opt/shoonya/logs ~/Downloads/shoonya_logs

# View on your machine
cd ~/Downloads/shoonya_logs
grep "ERROR" *.log
```

### Method 2: Create archive first
```bash
# On EC2
cd /opt/shoonya/logs
tar -czf logs_backup.tar.gz *.log

# Download
scp -i your-key.pem ec2-user@your-ip:/opt/shoonya/logs/logs_backup.tar.gz ~/Downloads/

# Extract locally
cd ~/Downloads
tar -xzf logs_backup.tar.gz
```

---

## Updating Your Own Modules

If you have other Python files that need logging, follow this pattern:

### Step 1: Import at top of file
```python
from shoonya_platform.logging.logger_config import get_component_logger

# DON'T do this:
# import logging
# logger = logging.getLogger(__name__)
```

### Step 2: Get your logger
```python
# Use one of the built-in component names:
logger = get_component_logger('trading_bot')        # trading_bot.log
logger = get_component_logger('command_service')   # command_service.log
logger = get_component_logger('order_watcher')     # order_watcher.log
logger = get_component_logger('risk_manager')      # risk_manager.log
logger = get_component_logger('execution_guard')   # execution_guard.log
logger = get_component_logger('dashboard')         # dashboard.log
logger = get_component_logger('recovery')          # recovery_service.log
logger = get_component_logger('execution_service') # execution_service.log
```

### Step 3: Use normally
```python
logger.info("Starting operation")
logger.warning("Something unusual")
logger.error("Something went wrong")
logger.debug("Detailed trace info")
```

---

## Health Checks

### Check Overall Status
```bash
sudo systemctl status shoonya_signal_processor

# Output should show:
# Active: active (running) since <timestamp>
# If "failed" or "inactive", something is wrong
```

### Check Boot Messages
```bash
# View service startup
sudo journalctl -u shoonya_signal_processor -n 20

# Or view file logs
head -20 /opt/shoonya/logs/execution_service.log

# Should see initialization messages for all components
grep "STARTUP\|initialization complete" /opt/shoonya/logs/*.log
```

### Check Recent Activity
```bash
# Last 100 lines across all services
for log in /opt/shoonya/logs/*.log; do echo "=== $log ==="; tail -3 "$log"; done
```

---

## Log Levels

### Default: INFO
Shows important events, errors, and status updates

### Change to DEBUG (more verbose)
```bash
# Edit main.py line with setup_application_logging:
setup_application_logging(
    log_dir=str(logs_dir),
    level="DEBUG",  # Change this
)
```

### Change to WARNING (less verbose)
```bash
setup_application_logging(
    log_dir=str(logs_dir),
    level="WARNING",  # Only show warnings and errors
)
```

Restart service after changing: `sudo systemctl restart shoonya_signal_processor`

---

## Common Issues

### Service won't start
```bash
# Check the error
sudo journalctl -u shoonya_signal_processor -n 50

# Try running manually to see traceback
cd /opt/shoonya
source venv/bin/activate
python3 main.py
```

### Logs not being created
```bash
# Verify logs directory exists
ls -la /opt/shoonya/logs/

# If not, create it
mkdir -p /opt/shoonya/logs
sudo chown shoonya:shoonya /opt/shoonya/logs
```

### Logs filling up disk
```bash
# Check size
du -sh /opt/shoonya/logs/

# View per-file
ls -lh /opt/shoonya/logs/*.log*

# Logs auto-rotate at 50MB, but you can manually trigger:
sudo systemctl restart shoonya_signal_processor

# Or delete old backups manually (keep most recent):
cd /opt/shoonya/logs
rm *.log.9 *.log.10  # Keep .1 through .8
```

### Can't find specific log entry
```bash
# Search multiple files at once
grep "INFY" /opt/shoonya/logs/*.log

# Search with context (show 5 lines before/after)
grep -B 5 -A 5 "ERROR" /opt/shoonya/logs/trading_bot.log

# Count occurrences
grep -c "order placed" /opt/shoonya/logs/command_service.log

# Show unique values
grep "status=" /opt/shoonya/logs/command_service.log | sort -u
```

---

## Performance Tips

### Searching Large Logs
```bash
# FAST: Direct grep
grep "ERROR" /opt/shoonya/logs/trading_bot.log

# SLOWER: Piping through wc
grep "ERROR" /opt/shoonya/logs/trading_bot.log | wc -l

# BETTER: Use grep -c for count
grep -c "ERROR" /opt/shoonya/logs/trading_bot.log

# Slow: Multiple tools
cat /opt/shoonya/logs/trading_bot.log | grep ERROR | head

# Better: Single tool, limit output
grep "ERROR" /opt/shoonya/logs/trading_bot.log -m 10
```

### Working with Big Files
```bash
# DON'T do: cat huge.log
cat /opt/shoonya/logs/execution_service.log

# DO use: less (has paging and search)
less /opt/shoonya/logs/execution_service.log
# In less: press '/' then search, press 'g' for start, 'G' for end

# Or tail for recent lines
tail -100 /opt/shoonya/logs/execution_service.log
```

---

## Cron Jobs (Optional)

### Auto-backup logs daily
```bash
# Add to crontab: sudo crontab -e

0 2 * * * (cd /opt/shoonya/logs && tar -czf /tmp/logs_$(date +\%Y\%m\%d).tar.gz *.log && aws s3 cp /tmp/logs_*.tar.gz s3://your-bucket/logs/)
```

### Auto-cleanup old logs
```bash
# Add to crontab: sudo crontab -e

0 3 * * * find /opt/shoonya/logs -name "*.log.*" -mtime +30 -delete
```

---

## Sharing Logs with Developers

### Step 1: Create focused archive
```bash
cd /opt/shoonya/logs

# Minimal: just the main logs
tar -czf logs_$(date +%Y%m%d).tar.gz execution_service.log trading_bot.log command_service.log

# Complete: everything
tar -czf logs_$(date +%Y%m%d)_full.tar.gz *.log
```

### Step 2: Download
```bash
scp -i key.pem ec2-user@your-ip:/opt/shoonya/logs/logs_*.tar.gz ~/Downloads/
```

### Step 3: Create bug report
```bash
cd ~/Downloads
tar -xzf logs_*.tar.gz

# Create summary
echo "=== Errors ===" > analysis.txt
grep "ERROR\|CRITICAL" *.log >> analysis.txt

echo -e "\n=== Last 50 lines ===" >> analysis.txt
tail -50 *.log >> analysis.txt

# Attach analysis.txt + logs to bug report
```

---

## What Each Log File Contains

| Log File | Purpose | Check For |
|----------|---------|-----------|
| `execution_service.log` | Webhook receiver, main service | Startup/shutdown, webhook processing |
| `trading_bot.log` | Bot initialization, alert parsing | Bot startup, alert processing |
| `command_service.log` | Order placement | "Order placed", "Order failed" |
| `order_watcher.log` | Order tracking, recovery | "Order tracked", "Partial fill" |
| `risk_manager.log` | Risk validation | "Risk check", "Violation", "Exceeded" |
| `execution_guard.log` | Trade safety gate | "Approved", "Prevented", "Rejected" |
| `dashboard.log` | Dashboard API requests | API errors, 404s |
| `recovery_service.log` | Recovery operations | Recovery startup, crash recovery |

---

## Complete One-Time Setup

```bash
# 1. SSH into EC2
ssh -i key.pem ec2-user@your-ip

# 2. Install service
sudo cp shoonya_service.service /etc/systemd/system/shoonya_signal_processor.service
sudo systemctl daemon-reload
sudo systemctl enable shoonya_signal_processor
sudo systemctl start shoonya_signal_processor

# 3. Verify
sudo systemctl status shoonya_signal_processor
ls -la /opt/shoonya/logs/

# 4. Watch live (in separate terminal)
ssh -i key.pem ec2-user@your-ip
tail -f /opt/shoonya/logs/*.log

# Done! ✅
```

---

## Questions?

- **Logs not rotating?** → Check LOG_ROTATION_GUIDE.md
- **Service won't start?** → Check EC2_DEPLOYMENT_GUIDE.md (Troubleshooting section)
- **Need to analyze?** → Search this file for "Finding Issues"
- **How do I integrate my own module?** → See "Updating Your Own Modules" above

