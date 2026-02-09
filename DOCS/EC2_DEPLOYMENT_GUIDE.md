# EC2 DEPLOYMENT GUIDE - SERVICE ISOLATION & LOG ROTATION
## Shoonya Signal Processor Setup on Amazon Linux

---

## Quick Start (5 minutes)

### 1. SSH into your EC2 instance
```bash
ssh -i your-ec2-key.pem ec2-user@your-ec2-ip
```

### 2. Create shoonya user and directories
```bash
# Create dedicated service user
sudo useradd -m -s /bin/bash shoonya
sudo install -d -m 755 -o shoonya -g shoonya /opt/shoonya
sudo install -d -m 755 -o shoonya -g shoonya /opt/shoonya/logs

# Add ec2-user to shoonya group (for easier management)
sudo usermod -aG shoonya ec2-user
```

### 3. Deploy your application
```bash
cd /opt/shoonya

# Clone or copy your repository
git clone <your-repo> .

# Or if using scp:
# scp -r -i key.pem your-local-dir/shoonya_platform ec2-user@your-ip:/opt/shoonya/
```

### 4. Setup Python virtual environment
```bash
cd /opt/shoonya
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements/requirements.txt

# Verify installation
python3 -c "from shoonya_platform.logging.logger_config import setup_application_logging; print('✅ Logging module ready')"
```

### 5. Deploy systemd service
```bash
# Copy service file to systemd directory
sudo cp shoonya_service.service /etc/systemd/system/shoonya_signal_processor.service

# Reload systemd configuration
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable shoonya_signal_processor

# Start the service
sudo systemctl start shoonya_signal_processor

# Verify it's running
sudo systemctl status shoonya_signal_processor
```

### 6. Verify logs are being created
```bash
# Check that log files exist
ls -lh /opt/shoonya/logs/

# You should see:
# - execution_service.log
# - trading_bot.log
# - command_service.log
# - order_watcher.log
# - risk_manager.log
# - execution_guard.log
# - dashboard.log

# Watch live logs
tail -f /opt/shoonya/logs/execution_service.log
```

---

## Verification Steps

### Check Service Status
```bash
sudo systemctl status shoonya_signal_processor

# Expected output:
# ● shoonya_signal_processor.service - Shoonya Signal Processor
#    Loaded: loaded (/etc/systemd/system/shoonya_signal_processor.service)
#    Active: active (running) since [timestamp]
```

### View Recent Logs
```bash
# Recent execution service logs
sudo journalctl -u shoonya_signal_processor -n 20

# File-based logs with tail
tail -20 /opt/shoonya/logs/execution_service.log
```

### Verify All Services Initialized
```bash
# Search for startup messages
grep "STARTUP\|initialization complete" /opt/shoonya/logs/*.log

# Should show one entry for each component
```

### Test Webhook Endpoint
```bash
# Service should be listening on configured port (default 5000)
curl http://localhost:5000/health

# Expected response: OK or status JSON
```

---

## Configuration

### Edit Environment Variables
```bash
# Edit the systemd service file
sudo systemctl edit shoonya_signal_processor

# Add or modify environment variables:
[Service]
Environment="LOG_LEVEL=DEBUG"
Environment="PYTHONUNBUFFERED=1"

# Save and reload
sudo systemctl daemon-reload
sudo systemctl restart shoonya_signal_processor
```

### Update Application Config
```bash
# Edit your config file
nano /opt/shoonya/config_env/primary.env

# Then restart service for changes to take effect
sudo systemctl restart shoonya_signal_processor
```

### Log Rotation Settings
```bash
# To change log rotation parameters, edit main.py:
sudo nano /opt/shoonya/main.py

# Find the setup_application_logging call and modify:
setup_application_logging(
    log_dir=str(logs_dir),
    level="INFO",
    max_bytes=50 * 1024 * 1024,  # Change max file size here
    backup_count=10,              # Change number of backups here
)

# Restart service
sudo systemctl restart shoonya_signal_processor
```

---

## Monitoring & Management

### View Service Logs in Real-Time
```bash
# Watch main service
tail -f /opt/shoonya/logs/execution_service.log

# Watch all logs simultaneously (split your terminal)
for f in /opt/shoonya/logs/*.log; do echo "=== $(basename $f) ==="; tail -n 3 "$f"; done

# Watch specific component
tail -f /opt/shoonya/logs/trading_bot.log
```

### Check Disk Usage
```bash
# Total logs size
du -sh /opt/shoonya/logs/

# Per-service size
ls -lh /opt/shoonya/logs/*.log | awk '{print $5, $9}'
```

### Search for Issues
```bash
# Find all errors
grep -r "ERROR\|CRITICAL" /opt/shoonya/logs/

# Find specific timestamp
grep "2026-02-08 14:30" /opt/shoonya/logs/*.log

# Find order execution trace
grep "12345" /opt/shoonya/logs/*.log
```

### Force Log Rotation
```bash
# Restart service to trigger rotation
sudo systemctl restart shoonya_signal_processor

# Or wait for 50MB threshold to be reached
```

---

## Troubleshooting

### Service Won't Start
```bash
# Check for Python errors
sudo systemctl status shoonya_signal_processor -l

# View full error in journal
sudo journalctl -u shoonya_signal_processor -n 50 --no-pager

# Test Python code directly
cd /opt/shoonya
source venv/bin/activate
python3 main.py

# This will show the actual error
```

### Permission Denied Errors
```bash
# Fix log directory permissions
sudo chown -R shoonya:shoonya /opt/shoonya
sudo chmod 755 /opt/shoonya
sudo chmod 755 /opt/shoonya/logs

# Verify
ls -la /opt/shoonya/logs/
```

### Logs Not Rotating
```bash
# Check current log size
ls -lh /opt/shoonya/logs/execution_service.log

# If it's huge but not rotating, restart service
sudo systemctl restart shoonya_signal_processor

# Verify rotation happened
ls -lh /opt/shoonya/logs/execution_service.log*
# Should now see .log, .log.1, .log.2, etc.
```

### Out of Disk Space
```bash
# Check total disk usage
df -h /

# Find large log files
find /opt/shoonya/logs -name "*.log*" -size +100M -exec ls -lh {} \;

# Manually rotate and clean old logs
cd /opt/shoonya/logs
# Keep only last 5 backups
ls -t *.log.* | tail -n +6 | xargs rm -f

# Or delete logs older than 7 days
find . -name "*.log.*" -mtime +7 -delete
```

### Service Crashes Immediately
```bash
# 1. Check for config errors
source /opt/shoonya/venv/bin/activate
python3 -c "from shoonya_platform.core.config import Config; Config()"

# 2. Check for missing dependencies
python3 -c "from shoonya_platform.execution.trading_bot import ShoonyaBot"

# 3. View startup logs
tail -50 /opt/shoonya/logs/execution_service.log

# 4. Run with debug mode to see full traceback
cd /opt/shoonya
python3 main.py 2>&1 | head -100
```

---

## Backup & Recovery

### Daily Log Backup to S3
```bash
#!/bin/bash
# Save as /opt/shoonya/backup_logs.sh

DATE=$(date +%Y%m%d)
LOGS_DIR="/opt/shoonya/logs"
S3_BUCKET="your-s3-bucket"

# Archive logs
tar -czf /tmp/shoonya_logs_${DATE}.tar.gz -C ${LOGS_DIR} .

# Upload to S3
aws s3 cp /tmp/shoonya_logs_${DATE}.tar.gz s3://${S3_BUCKET}/logs/ \
    --sse AES256 \
    --metadata "hostname=$(hostname),date=${DATE}"

# Clean up
rm /tmp/shoonya_logs_${DATE}.tar.gz

# Clean up old backups locally (older than 7 days)
find ${LOGS_DIR}/*.log.* -mtime +7 -delete
```

Install as cron job:
```bash
# Add to crontab
sudo crontab -e

# Add line:
0 2 * * * /opt/shoonya/backup_logs.sh >> /var/log/shoonya_backup.log 2>&1
```

### Restore from Backup
```bash
# Download from S3
aws s3 cp s3://your-bucket/logs/shoonya_logs_20260208.tar.gz .

# Extract
cd /opt/shoonya/logs
tar -xzf shoonya_logs_20260208.tar.gz
```

---

## Performance Tuning

### Memory Settings
```bash
# Increase if service uses large buffers
sudo systemctl edit shoonya_signal_processor

[Service]
MemoryLimit=4G  # Increase from 2G if needed

# Restart
sudo systemctl daemon-reload
sudo systemctl restart shoonya_signal_processor
```

### CPU Settings
```bash
# Increase if CPU-bound operations
sudo systemctl edit shoonya_signal_processor

[Service]
CPUQuota=150%  # Allow 1.5 cores (was 80%)
```

### File Descriptor Limits
```bash
# View current limits
ulimit -n

# Edit if needed
sudo systemctl edit shoonya_signal_processor

[Service]
LimitNOFILE=131072  # Increase from 65536
```

---

## Security Hardening

### SELinux Configuration (if enabled)
```bash
# Check if SELinux is active
getenforce

# Create policy for shoonya service
sudo semanage port -a -t http_port_t -p tcp 5000

# Apply firewall rules
sudo firewall-cmd --add-service=http --permanent
sudo firewall-cmd --reload
```

### Restrict Log Access
```bash
# Only shoonya user can read logs
sudo chmod 750 /opt/shoonya/logs
sudo chmod 640 /opt/shoonya/logs/*.log
```

### TLS for Webhook Endpoint
```python
# In main.py, enable HTTPS
serve(
    flask_app,
    host="0.0.0.0",
    port=5000,
    certfile="/path/to/cert.pem",
    keyfile="/path/to/key.pem",
)
```

---

## Monitoring Integration

### CloudWatch Logs (AWS)
```bash
# Install CloudWatch agent
sudo yum install -y amazon-cloudwatch-agent

# Configure to ship logs
sudo nano /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

# Add log files section:
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/opt/shoonya/logs/execution_service.log",
            "log_group_name": "/shoonya/execution",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  }
}

# Start agent
sudo systemctl restart amazon-cloudwatch-agent
```

### DataDog Integration
```bash
# Install agent
DD_AGENT_MAJOR_VERSION=7 DD_API_KEY=your-key \
  DD_SITE="datadoghq.com" bash -c "$(curl -L https://s3.amazonaws.com/dd-agent/scripts/install_script.sh)"

# Configure log shipping
echo 'logs:
  - type: file
    path: /opt/shoonya/logs/
    service: shoonya
    source: python
    sourcecategory: bot' | sudo tee -a /etc/datadog-agent/datadog.yaml

# Restart agent
sudo systemctl restart datadog-agent
```

---

## Maintenance Schedule

### Daily
- [ ] Check service status: `systemctl status shoonya_signal_processor`
- [ ] Monitor disk usage: `du -sh /opt/shoonya/logs/`
- [ ] Review recent errors: `grep ERROR /opt/shoonya/logs/*.log`

### Weekly
- [ ] Archive logs to S3
- [ ] Review error trends
- [ ] Update application if patches available

### Monthly
- [ ] Clean old log backups (older than 30 days)
- [ ] Review and adjust log rotation settings
- [ ] Verify backup/recovery process works

---

## Getting Help

**Service won't start?**
```bash
sudo journalctl -u shoonya_signal_processor --no-pager | tail -100
```

**Need to investigate bug?**
```bash
# Download logs
scp -r -i key.pem ec2-user@your-ip:/opt/shoonya/logs ~/Downloads/

# Analyze locally
grep ERROR ~/Downloads/logs/*.log
grep "2026-02-08 14:25" ~/Downloads/logs/*.log  # specific timestamp
```

**Need to debug live?**
```bash
# SSH in and watch logs
ssh -i key.pem ec2-user@your-ip
tail -f /opt/shoonya/logs/*.log
```

---

## Complete EC2 Setup Checklist

- [ ] EC2 instance running Amazon Linux 2
- [ ] Python 3.8+ installed
- [ ] Shoonya user created with proper permissions
- [ ] Virtual environment set up
- [ ] Dependencies installed
- [ ] Configuration files in place
- [ ] Systemd service file deployed
- [ ] Service enabled and started
- [ ] Log files being created
- [ ] S3 bucket created for log backups
- [ ] CloudWatch/monitoring configured
- [ ] Security groups configured for webhook port
- [ ] Firewall rules configured (if applicable)
- [ ] Team has access to logs via S3/CloudWatch
- [ ] Backup strategy documented and tested

