# Shoonya Platform - EC2/Linux Service Installation Guide
==========================================================

## Overview

The platform now runs as a **SINGLE UNIFIED SERVICE** that includes:
- ✅ Execution service (webhook processing)
- ✅ Dashboard (co-hosted on port 8000)
- ✅ Option chain supervisor (background thread)
- ✅ Risk manager (background thread)
- ✅ Order watcher (background thread)

**No need for multiple services** - everything runs in one process.

---

## Installation Steps

### 1. Install Service File

```bash
# Copy service file to systemd
sudo cp ~/shoonya_platform/deployment/shoonya_service.service \
    /etc/systemd/system/shoonya_platform.service

# Reload systemd
sudo systemctl daemon-reload
```

### 2. Enable Auto-Start on Boot

```bash
sudo systemctl enable shoonya_platform
```

### 3. Start Service

```bash
sudo systemctl start shoonya_platform
```

### 4. Check Status

```bash
# View service status
sudo systemctl status shoonya_platform

# View live logs (streaming)
sudo journalctl -u shoonya_platform -f

# View last 100 lines of logs
sudo journalctl -u shoonya_platform -n 100
```

---

## Common Commands

### Service Control

```bash
# Start service
sudo systemctl start shoonya_platform

# Stop service
sudo systemctl stop shoonya_platform

# Restart service
sudo systemctl restart shoonya_platform

# Check if service is running
sudo systemctl is-active shoonya_platform

# View detailed status
sudo systemctl status shoonya_platform
```

### Log Management

```bash
# Follow live logs
sudo journalctl -u shoonya_platform -f

# View logs since boot
sudo journalctl -u shoonya_platform -b

# View logs from last hour
sudo journalctl -u shoonya_platform --since "1 hour ago"

# Export logs to file
sudo journalctl -u shoonya_platform > ~/shoonya_logs.txt
```

### Configuration Changes

After modifying config_env/primary.env:

```bash
# Restart to load new config
sudo systemctl restart shoonya_platform
```

After modifying code:

```bash
# Pull latest code
cd ~/shoonya_platform
git pull

# Clean Python cache
python shoonya_platform/tools/cleanup_shoonya_platform.py

# Restart service
sudo systemctl restart shoonya_platform
```

---

## Service File Location

**Current service file:** `~/shoonya_platform/deployment/shoonya_service.service`
**Installed location:** `/etc/systemd/system/shoonya_platform.service`

### Update Service File

If you modify the service file:

```bash
# Copy updated service file
sudo cp ~/shoonya_platform/deployment/shoonya_service.service \
    /etc/systemd/system/shoonya_platform.service

# Reload systemd
sudo systemctl daemon-reload

# Restart service
sudo systemctl restart shoonya_platform
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check detailed error logs
sudo journalctl -u shoonya_platform -n 50 --no-pager

# Verify config file permissions
ls -la ~/shoonya_platform/config_env/primary.env

# Test manual startup
cd ~/shoonya_platform
source venv/bin/activate
python main.py
```

### Service Keeps Restarting

```bash
# Check restart count
systemctl show shoonya_platform | grep NRestarts

# View failure logs
sudo journalctl -u shoonya_platform --since "10 minutes ago" | grep -i error
```

### Port Already in Use

```bash
# Check what's using port 5001 (execution) or 8000 (dashboard)
sudo lsof -i :5001
sudo lsof -i :8000

# Kill process if needed
sudo kill -9 <PID>
```

---

## Performance Monitoring

### Resource Usage

```bash
# CPU and Memory usage
systemctl status shoonya_platform | grep -E "CPU|Memory"

# Detailed resource stats
sudo systemd-cgtop shoonya_platform.service
```

### File Limits

The service is configured with:
- **Memory Limit:** 2GB
- **CPU Quota:** 80%
- **File Descriptors:** 65536
- **Process Limit:** 8192

---

## Security Notes

The service runs with:
- ✅ User isolation (ec2-user)
- ✅ Private /tmp directory
- ✅ Read-only system files
- ✅ Write access only to logs/ and data/
- ✅ OOM killer protection

---

## Auto-Recovery

The service automatically restarts:
- ✅ On crashes or exceptions
- ✅ On session expiry (exit code 1)
- ✅ On network failures
- ⚠️ Max 5 restarts in 5 minutes (protection against rapid failures)

---

## Uninstallation

```bash
# Stop and disable service
sudo systemctl stop shoonya_platform
sudo systemctl disable shoonya_platform

# Remove service file
sudo rm /etc/systemd/system/shoonya_platform.service

# Reload systemd
sudo systemctl daemon-reload
```

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Start | `sudo systemctl start shoonya_platform` |
| Stop | `sudo systemctl stop shoonya_platform` |
| Restart | `sudo systemctl restart shoonya_platform` |
| Status | `sudo systemctl status shoonya_platform` |
| Logs (live) | `sudo journalctl -u shoonya_platform -f` |
| Enable auto-start | `sudo systemctl enable shoonya_platform` |
| Disable auto-start | `sudo systemctl disable shoonya_platform` |

---

**Documentation Updated:** 2026-02-09
**Service Architecture:** Single unified process (main.py)
**Platform:** Linux/EC2 with systemd
