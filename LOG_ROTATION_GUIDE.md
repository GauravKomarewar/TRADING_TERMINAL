# LOG ROTATION & ANALYSIS GUIDE
### Shoonya Signal Processor (EC2 Deployment)

## Overview
The new logging system provides:
- ✅ **Per-service logs** - dashboard, trading_bot, risk_manager, order_watcher, command_service, execution_guard
- ✅ **Automatic rotation** - 50MB max per file, 10 backups kept (500MB total per service)
- ✅ **Clean separation** - errors in one service don't affect logs of others
- ✅ **Disk-friendly** - old logs automatically removed when backups exceed limit
- ✅ **Easy analysis** - each service has dedicated log file

---

## Log File Layout

After running the service, logs are created in `/opt/shoonya/logs/`:

```
logs/
├── execution_service.log         # Main service & webhook processing
├── execution_service.log.1       # Backup 1 (rotated)
├── execution_service.log.2       # Backup 2 (rotated)
│
├── trading_bot.log               # Bot initialization, alert processing
├── trading_bot.log.1
├── trading_bot.log.2
│
├── command_service.log           # Order placement, command execution
├── command_service.log.1
│
├── order_watcher.log             # Order tracking, recovery
├── order_watcher.log.1
│
├── risk_manager.log              # Risk validation, checks
├── risk_manager.log.1
│
├── execution_guard.log           # Trade execution guard, safety checks
├── execution_guard.log.1
│
├── dashboard.log                 # Dashboard API, UI requests
├── dashboard.log.1
│
└── recovery_service.log          # Recovery & restart operations
    └── recovery_service.log.1
```

### Log File Rotation
- **Trigger**: When a log file reaches 50MB
- **Action**: File is renamed to `.1`, `.1` → `.2`, etc., up to `.10`
- **Cleanup**: Backup `.10` is deleted when limit exceeded
- **Result**: Each service keeps ~500MB of historical logs

---

## Accessing Logs

### On EC2 Instance

#### View tail of current logs (in real-time):
```bash
# Watch execution service logs
tail -f /opt/shoonya/logs/execution_service.log

# Watch trading bot logs
tail -f /opt/shoonya/logs/trading_bot.log

# View all logs at once (split terminal recommended)
tail -f /opt/shoonya/logs/*.log
```

#### View specific errors:
```bash
# Find all ERROR and CRITICAL logs in trading bot
grep -E "ERROR|CRITICAL" /opt/shoonya/logs/trading_bot.log

# Find order execution issues
grep "order" /opt/shoonya/logs/command_service.log -i

# Track risk manager violations
grep "risk" /opt/shoonya/logs/risk_manager.log -i

# Find execution guard flags
grep "guard\|prevented\|rejected" /opt/shoonya/logs/execution_guard.log -i
```

#### Get log file size and line count:
```bash
# Check all log sizes
ls -lh /opt/shoonya/logs/*.log

# Count lines in each service log
wc -l /opt/shoonya/logs/*.log
```

#### Search across all logs for a specific issue:
```bash
# Find all instances of a symbol
grep "INFY" /opt/shoonya/logs/*.log

# Find all order IDs
grep -E "order_id|Order.*[0-9]" /opt/shoonya/logs/*.log

# Find webhook execution logs
grep "webhook\|alert\|signal" /opt/shoonya/logs/execution_service.log -i
```

---

## Downloading Logs for Analysis

### Option 1: Using SCP (from your local machine)
```bash
# Download single log file
scp -i your-ec2-key.pem ec2-user@your-ec2-ip:/opt/shoonya/logs/trading_bot.log ~/Downloads/

# Download all logs
scp -i your-ec2-key.pem -r ec2-user@your-ec2-ip:/opt/shoonya/logs ~/Downloads/shoonya_logs/

# Download only recent main log (not backups)
scp -i your-ec2-key.pem ec2-user@your-ec2-ip:/opt/shoonya/logs/{execution_service,trading_bot,command_service}.log ~/Downloads/
```

### Option 2: Using AWS Systems Manager Session Manager (No SSH Key)
```bash
# Install AWS CLI on EC2:
sudo yum install -y aws-cli

# Start session (requires IAM role with SSM permissions)
aws ssm start-session --target i-xxxxxxxxx

# Then use tar to create archive:
cd /opt/shoonya/logs
tar -czf shoonya_logs_$(date +%Y%m%d).tar.gz *.log
# Download via S3 or direct copy
```

### Option 3: Create log archive for sharing
```bash
# On EC2, create compressed archive (last 7 days + current)
cd /opt/shoonya/logs
tar -czf shoonya_logs_$(date +%Y%m%d_%H%M%S).tar.gz *.log
ls -lh *.tar.gz

# Then download the .tar.gz file using SCP above
```

---

## Log Analysis for Troubleshooting

### 1. **Service Health Check** (every service should have startup line)
```bash
grep "STARTUP\|Service initialization complete" /opt/shoonya/logs/*.log
```

Expected output shows each service:
```
execution_service.log: ✅ STARTUP: ...
trading_bot.log: ✅ STARTUP: ...
command_service.log: ✅ STARTUP: ...
```

### 2. **Find the Last 50 Lines Before an Error**
```bash
# Find error timestamp
grep "ERROR" /opt/shoonya/logs/trading_bot.log | head -1

# Once you have timestamp, grep logs around that time
grep "2026-02-08 14:30" /opt/shoonya/logs/trading_bot.log | head -20
```

### 3. **Trace an Order from Entry to Exit**
```bash
# Search across all logs for order ID 12345
grep -r "12345" /opt/shoonya/logs/

# Output shows:
# - command_service.log: Order placed
# - order_watcher.log: Order being tracked
# - risk_manager.log: Risk checks applied
# - execution_guard.log: Safety checks passed/failed
```

### 4. **Check for Restart Loops**
```bash
# Count service startups (should be 1 unless there were crashes)
grep -c "STARTUP" /opt/shoonya/logs/trading_bot.log

# If > 1, check error before each restart
grep "ERROR\|CRITICAL" /opt/shoonya/logs/trading_bot.log

# Check how long service was running before crash
# Look at timestamps between restarts
```

### 5. **Webhook Execution Audit Trail**
```bash
# See all incoming webhooks
grep "webhook\|alert.*received\|signal.*processing" /opt/shoonya/logs/execution_service.log -i

# Check total webhook count
grep -c "webhook\|alert.*received" /opt/shoonya/logs/execution_service.log

# See webhook payloads (if DEBUG level enabled)
grep "payload\|data" /opt/shoonya/logs/execution_service.log -A 5
```

### 6. **Risk Manager Violations**
```bash
# See all risk checks
grep "risk\|violation\|exceeded\|rejected" /opt/shoonya/logs/risk_manager.log -i

# Count violations by type
grep -o "violation.*:" /opt/shoonya/logs/risk_manager.log | sort | uniq -c
```

### 7. **Performance Issues**
```bash
# Long-running operations (timing logs)
grep "execution.*ms\|took.*seconds" /opt/shoonya/logs/*.log -i

# Database query times
grep "db.*query\|latency" /opt/shoonya/logs/*.log -i

# Broker API response times
grep "broker.*response\|api.*delay" /opt/shoonya/logs/*.log -i
```

---

## Systemd Journal Integration

All logs are also captured by systemd journal:

```bash
# View service status and recent logs
sudo systemctl status shoonya_signal_processor

# View last 100 lines of service journal
sudo journalctl -u shoonya_signal_processor -n 100

# View logs since 2 hours ago
sudo journalctl -u shoonya_signal_processor --since "2 hours ago"

# View logs with microsecond precision
sudo journalctl -u shoonya_signal_processor -o short-precise

# Export logs to file
sudo journalctl -u shoonya_signal_processor > shoonya_service.log
```

---

## Setting Log Level

### Temporarily (until service restart):
```bash
# Modify /opt/shoonya/main.py temporarily:
setup_application_logging(
    log_dir=str(logs_dir),
    level="DEBUG",  # Change from "INFO" to "DEBUG"
    ...
)
```

### Permanently (systemd service):
```bash
# Edit service file
sudo systemctl edit shoonya_signal_processor

# Add or modify:
[Service]
Environment="LOG_LEVEL=DEBUG"

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart shoonya_signal_processor
```

---

## Log Cleanup & Maintenance

### Manual rotation trigger:
```bash
# Create a Python script to manually rotate logs:
python3 -c "
from shoonya_platform.logging.logger_config import rotate_logs
result = rotate_logs()
for component, status in result.items():
    print(f'{component}: {status}')
"
```

### Automated cleanup (cron job):
```bash
# Remove logs older than 30 days
0 2 * * * find /opt/shoonya/logs -name "*.log.*" -mtime +30 -delete

# Archive logs monthly
0 0 1 * * tar -czf /opt/shoonya/logs/archive/logs_$(date +\%Y\%m).tar.gz /opt/shoonya/logs/*.log
```

---

## Sharing Logs for Bug Analysis

### Step-by-Step:

1. **Collect logs when issue occurred:**
   ```bash
   # SSH into EC2
   ssh -i key.pem ec2-user@your-ip
   
   # Create archive with timestamp
   cd /opt/shoonya/logs
   tar -czf shoonya_logs_$(date +%Y%m%d_%H%M%S).tar.gz *.log
   ```

2. **Download to your machine:**
   ```bash
   scp -i key.pem ec2-user@your-ip:/opt/shoonya/logs/shoonya_logs_*.tar.gz ~/Downloads/
   ```

3. **Extract and analyze locally:**
   ```bash
   cd ~/Downloads
   tar -xzf shoonya_logs_*.tar.gz
   
   # View each service log
   less trading_bot.log
   less command_service.log
   less execution_service.log
   ```

4. **Create summary for bug report:**
   ```bash
   # Get error summary
   echo "=== ERRORS ===" > summary.txt
   grep "ERROR\|CRITICAL" *.log >> summary.txt
   
   echo -e "\n=== SERVICE STARTUPS ===" >> summary.txt
   grep "STARTUP\|initialization" *.log >> summary.txt
   
   # Now attach summary.txt and relevant .log files to bug report
   ```

---

## Log Schema (What Each Column Means)

Format: `TIMESTAMP | LEVEL | COMPONENT | MESSAGE`

Example:
```
2026-02-08 14:25:30 | INFO     | TRADING_BOT          | 🚀 STARTUP: Bot initialization started
2026-02-08 14:25:31 | INFO     | COMMAND_SERVICE      | Webhook signal received: INFY Buy Alert
2026-02-08 14:25:31 | INFO     | RISK_MANAGER         | Risk check passed: Exposure 45% < 60% limit
2026-02-08 14:25:32 | INFO     | EXECUTION_GUARD      | Trade approved: BUY 1 INFY @ 1450
2026-02-08 14:25:32 | INFO     | ORDER_WATCHER        | Order 12345 placed, tracking started
2026-02-08 14:25:33 | ERROR    | EXECUTION_GUARD      | ❌ Execution blocked: Daily loss limit exceeded
```

### Levels:
- **DEBUG** - Detailed internal state (enable only when investigating)
- **INFO** - Normal operation milestones
- **WARNING** - Potential issues that don't stop execution
- **ERROR** - Significant problems (check these!)
- **CRITICAL** - Service failure imminent

---

## Monitoring Dashboard (Add to your Grafana/Prometheus)

You can parse logs and expose metrics:

```python
# Example: Count orders by status
import re

with open('/opt/shoonya/logs/command_service.log') as f:
    orders_placed = len(re.findall(r'Order.*placed', f.read()))
    orders_failed = len(re.findall(r'Order.*failed', f.read()))
    
print(f"Orders placed today: {orders_placed}")
print(f"Orders failed today: {orders_failed}")
```

---

## Troubleshooting Common Issues

### Issue: Logs not rotating
**Check:** Is the log file growing beyond 50MB?
```bash
ls -lh /opt/shoonya/logs/trading_bot.log*
# Should see: trading_bot.log (current), trading_bot.log.1, .log.2, etc.
```
**Fix:** Rotate manually or restart service

### Issue: Service keeps restarting
**Check:** 
```bash
grep -c "STARTUP" /opt/shoonya/logs/trading_bot.log
# If > 1: check for errors
grep "ERROR\|CRITICAL" /opt/shoonya/logs/trading_bot.log | tail -5
```

### Issue: Can't find a specific event
**Use grep with context:**
```bash
# Show 10 lines before and after error
grep -B 10 -A 10 "order_id=12345" /opt/shoonya/logs/*.log
```

### Issue: Logs too verbose
**Reduce log level:**
```bash
# In main.py, change:
setup_application_logging(..., level="WARNING")
# Restart service
```

---

## Performance Tips

### 1. **Use grep efficiently:**
```bash
# Fast: single pass
grep "ERROR" /opt/shoonya/logs/trading_bot.log

# Slow: multiple passes
grep "ERROR" /opt/shoonya/logs/trading_bot.log | wc -l
grep "ERROR" /opt/shoonya/logs/trading_bot.log | head -10

# Better (single pass):
grep -c "ERROR" /opt/shoonya/logs/trading_bot.log  # count
grep "ERROR" /opt/shoonya/logs/trading_bot.log -m 10  # first 10
```

### 2. **Large log files:**
```bash
# Use less with indexing (fast navigation)
less /opt/shoonya/logs/execution_service.log

# In less, press '/' then type search term
# Press 'g' to go to start, 'G' to go to end
```

### 3. **Analysis on remote server:**
```bash
# Instead of downloading entire logs, analyze on EC2:
ssh -i key.pem ec2-user@your-ip << 'EOF'
grep "ERROR" /opt/shoonya/logs/*.log | wc -l
grep "order" /opt/shoonya/logs/command_service.log | tail -20
EOF
```

---

## Complete Setup Checklist

- [ ] Systemd service file deployed to `/etc/systemd/system/shoonya_service.service`
- [ ] EC2 instance has IAM role for CloudWatch (optional)
- [ ] Log directory permissions: `sudo chown shoonya:shoonya /opt/shoonya/logs`
- [ ] Service enabled: `sudo systemctl enable shoonya_signal_processor`
- [ ] Service started: `sudo systemctl start shoonya_signal_processor`
- [ ] Check status: `sudo systemctl status shoonya_signal_processor`
- [ ] Verify logs being created: `ls -la /opt/shoonya/logs/`
- [ ] Test log rotation will work (wait for 50MB or restart service)
- [ ] Configure backup strategy (S3, CloudWatch Logs, EBS snapshot)

---

## Questions & Support

For issues with log rotation or service failures:
1. Check relevant `.log` file in `/opt/shoonya/logs/`
2. Look for **ERROR** or **CRITICAL** lines
3. Note the timestamp and search 5 minutes before for root cause
4. Archive logs and share with development team

