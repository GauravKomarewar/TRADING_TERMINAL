# Shoonya Platform - Windows Service Installation Guide
========================================================

## Overview

The platform runs as a **background service** on Windows using:
- Option 1: **NSSM (Recommended)** - Non-Sucking Service Manager
- Option 2: **Python Script** - Built-in service wrapper

---

## Method 1: NSSM (Recommended for Production)

### Installation

1. **Download NSSM**
   - Visit: https://nssm.cc/download
   - Download the latest version (e.g., nssm-2.24.zip)
   - Extract to `C:\nssm` (or any folder in PATH)

2. **Open PowerShell as Administrator**

   ```powershell
   # Navigate to project directory
   cd C:\Users\<your_username>\shoonya_platform

   # Install service
   C:\nssm\nssm.exe install shoonya_platform
   ```

3. **Configure Service in NSSM GUI**

   NSSM will open a configuration window. Fill in:

   **Application Tab:**
   - Path: `C:\Users\<your_username>\shoonya_platform\venv\Scripts\python.exe`
   - Startup directory: `C:\Users\<your_username>\shoonya_platform`
   - Arguments: `main.py`

   **Details Tab:**
   - Display name: `Shoonya Trading Platform`
   - Description: `Automated trading execution service with dashboard`
   - Startup type: `Automatic`

   **I/O Tab:**
   - Output (stdout): `C:\Users\<your_username>\shoonya_platform\logs\service_stdout.log`
   - Error (stderr): `C:\Users\<your_username>\shoonya_platform\logs\service_stderr.log`

   **Environment Tab:**
   - Add: `PYTHONUNBUFFERED=1`

4. **Start Service**

   ```powershell
   # Start service
   nssm start shoonya_platform

   # Check status
   nssm status shoonya_platform
   ```

### NSSM Commands

```powershell
# Start service
nssm start shoonya_platform

# Stop service
nssm stop shoonya_platform

# Restart service
nssm restart shoonya_platform

# Check status
nssm status shoonya_platform

# Edit configuration
nssm edit shoonya_platform

# View service details
nssm get shoonya_platform *

# Uninstall service
nssm remove shoonya_platform confirm
```

---

## Method 2: PowerShell Script Runner (Development)

For development or quick testing, use the provided PowerShell script:

### Setup

1. **Create Windows service runner script**

   Already created at: `run_windows_service.ps1`

2. **Run in development mode**

   ```powershell
   # Run in foreground (console)
   .\run_windows_service.ps1

   # Run minimized
   Start-Process powershell -ArgumentList "-File .\run_windows_service.ps1" -WindowStyle Minimized
   ```

---

## Service Management via Windows Services

Once installed (via NSSM), you can manage the service through:

### Services GUI

1. Press `Win + R`
2. Type `services.msc` and press Enter
3. Find "Shoonya Trading Platform"
4. Right-click to Start/Stop/Restart

### PowerShell Commands

```powershell
# Start service
Start-Service shoonya_platform

# Stop service
Stop-Service shoonya_platform

# Restart service
Restart-Service shoonya_platform

# Check status
Get-Service shoonya_platform

# View detailed properties
Get-Service shoonya_platform | Format-List *
```

---

## Auto-Start on Windows Boot

The service will automatically start on boot if configured correctly:

1. Open Services (`services.msc`)
2. Find "Shoonya Trading Platform"
3. Right-click → Properties
4. Set **Startup type** to **Automatic**

---

## Viewing Logs

### Service Logs (NSSM)

```powershell
# View stdout log
Get-Content -Path "C:\Users\<username>\shoonya_platform\logs\service_stdout.log" -Tail 50 -Wait

# View stderr log
Get-Content -Path "C:\Users\<username>\shoonya_platform\logs\service_stderr.log" -Tail 50 -Wait
```

### Application Logs

```powershell
# View execution service log
Get-Content -Path ".\logs\execution_service.log" -Tail 50 -Wait

# View trading bot log
Get-Content -Path ".\logs\trading_bot.log" -Tail 50 -Wait

# View all recent logs
Get-ChildItem -Path ".\logs\*.log" | ForEach-Object {
    Write-Host "=== $($_.Name) ===" -ForegroundColor Cyan
    Get-Content $_.FullName -Tail 10
}
```

---

## Troubleshooting

### Service Won't Start

1. **Check logs**
   ```powershell
   # View error log
   Get-Content ".\logs\service_stderr.log" -Tail 50
   ```

2. **Test manual startup**
   ```powershell
   # Activate venv and run manually
   .\venv\Scripts\Activate.ps1
   python main.py
   ```

3. **Verify config**
   ```powershell
   # Check if config_env/primary.env exists
   Test-Path ".\config_env\primary.env"
   ```

### Service Keeps Restarting

```powershell
# View Windows Event Viewer
eventvwr.msc
# Navigate to: Windows Logs → Application
# Filter by source: nssm or shoonya_platform
```

### Port Already in Use

```powershell
# Check what's using port 5001 or 8000
netstat -ano | findstr :5001
netstat -ano | findstr :8000

# Kill process by PID
Stop-Process -Id <PID> -Force
```

---

## Performance Monitoring

### Task Manager

1. Open Task Manager (`Ctrl + Shift + Esc`)
2. Go to "Details" tab
3. Find `python.exe` (service process)
4. Monitor CPU and Memory usage

### Resource Monitor

```powershell
# Open Resource Monitor
perfmon /res
```

---

## Updating Service After Code Changes

```powershell
# Stop service
nssm stop shoonya_platform

# Pull latest code
git pull

# Clean Python cache
python shoonya_platform\tools\cleanup_shoonya_platform.py

# Restart service
nssm restart shoonya_platform
```

---

## Security Considerations

### Running as Different User

To run service as a specific user (recommended for production):

```powershell
# Edit service
nssm edit shoonya_platform

# In "Log on" tab:
# Select "This account"
# Enter username and password
```

### Firewall Rules

If accessing dashboard from network:

```powershell
# Allow inbound on port 8000
New-NetFirewallRule -DisplayName "Shoonya Dashboard" `
    -Direction Inbound `
    -LocalPort 8000 `
    -Protocol TCP `
    -Action Allow
```

---

## Uninstallation

### Remove NSSM Service

```powershell
# Stop service
nssm stop shoonya_platform

# Remove service
nssm remove shoonya_platform confirm
```

---

## Quick Reference Card

| Task | PowerShell Command |
|------|-------------------|
| Install | `nssm install shoonya_platform` |
| Start | `nssm start shoonya_platform` |
| Stop | `nssm stop shoonya_platform` |
| Restart | `nssm restart shoonya_platform` |
| Status | `nssm status shoonya_platform` |
| Logs | `Get-Content .\logs\service_stdout.log -Tail 50 -Wait` |
| Edit Config | `nssm edit shoonya_platform` |
| Uninstall | `nssm remove shoonya_platform confirm` |

---

## Alternative: Task Scheduler (Simple Auto-Start)

If you don't need full service features:

```powershell
# Create scheduled task to run on startup
$trigger = New-ScheduledTaskTrigger -AtStartup
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-File C:\Users\<username>\shoonya_platform\run_windows_service.ps1"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest

Register-ScheduledTask -TaskName "Shoonya Platform" `
    -Trigger $trigger `
    -Action $action `
    -Principal $principal `
    -Description "Shoonya Trading Platform Auto-Start"
```

---

**Documentation Updated:** 2026-02-09
**Service Architecture:** Single unified process (main.py)
**Platform:** Windows 10/11 with NSSM or PowerShell
