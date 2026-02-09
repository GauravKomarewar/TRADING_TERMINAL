# Shoonya Platform - Utility Commands Reference
================================================

This document lists all utility commands available after running `bootstrap.py`.

---

## 🧹 Cleanup Utility (Cross-Platform)

Removes Python cache files (`__pycache__`, `*.pyc`) and optionally restarts services.

### Linux/EC2

```bash
# If symlink was created successfully during bootstrap:
shoonya-clean

# Alternative (always works):
python shoonya_platform/tools/cleanup_shoonya_platform.py
```

### Windows

```powershell
# Option 1: Batch file (created by bootstrap.py)
.\shoonya-clean.bat

# Option 2: PowerShell command (after running setup)
.\setup_powershell_commands.ps1 -Install
shoonya-clean

# Option 3: Direct execution
python shoonya_platform\tools\cleanup_shoonya_platform.py
```

---

## 🚀 Service Management

### Linux/EC2 (systemd)

```bash
# Start service
sudo systemctl start shoonya_platform

# Stop service
sudo systemctl stop shoonya_platform

# Restart service
sudo systemctl restart shoonya_platform

# View status
sudo systemctl status shoonya_platform

# View logs
sudo journalctl -u shoonya_platform -f
```

See [SERVICE_INSTALLATION_LINUX.md](SERVICE_INSTALLATION_LINUX.md) for complete guide.

### Windows (NSSM)

```powershell
# Start service
nssm start shoonya_platform

# Stop service
nssm stop shoonya_platform

# Restart service
nssm restart shoonya_platform

# View status
nssm status shoonya_platform
```

See [SERVICE_INSTALLATION_WINDOWS.md](SERVICE_INSTALLATION_WINDOWS.md) for complete guide.

### Windows (Development - PowerShell)

```powershell
# Run in foreground
.\run_windows_service.ps1

# Run minimized
Start-Process powershell -ArgumentList "-File .\run_windows_service.ps1" -WindowStyle Minimized
```

---

## 🔧 Common Workflows

### After Git Pull

```bash
# Clean Python cache
shoonya-clean  # or platform-specific alternative

# Restart service (Linux)
sudo systemctl restart shoonya_platform

# Restart service (Windows with NSSM)
nssm restart shoonya_platform
```

### View Logs

```bash
# Linux - systemd journal
sudo journalctl -u shoonya_platform -f

# Windows - application logs
Get-Content .\logs\execution_service.log -Tail 50 -Wait

# Both - all log files
ls logs/*.log
```

### Test Manual Run

```bash
# Activate environment
source venv/bin/activate  # Linux
.\venv\Scripts\Activate.ps1  # Windows

# Run directly
python main.py
```

---

## 📦 Environment Management

### Bootstrap (First Time Setup)

```bash
python bootstrap.py
```

This automatically:
- ✅ Creates virtual environment
- ✅ Installs all dependencies
- ✅ Downloads required wheels from GitHub releases
- ✅ Sets up cleanup utility for your platform
- ✅ Creates Windows batch wrapper or Linux symlink

### Re-bootstrap (Clean Setup)

```bash
# Remove virtual environment
rm -rf venv  # Linux
Remove-Item -Recurse -Force venv  # Windows

# Re-run bootstrap
python bootstrap.py
```

---

## 🔍 Troubleshooting Commands

### Check Service Status

```bash
# Linux
sudo systemctl is-active shoonya_platform
sudo systemctl status shoonya_platform

# Windows
nssm status shoonya_platform
Get-Service shoonya_platform  # If installed as Windows service
```

### Check Port Usage

```bash
# Linux
sudo lsof -i :5001  # Execution service
sudo lsof -i :8000  # Dashboard

# Windows
netstat -ano | findstr :5001
netstat -ano | findstr :8000
```

### View Recent Errors

```bash
# Linux
sudo journalctl -u shoonya_platform --since "10 minutes ago" | grep -i error

# Windows
Get-Content .\logs\execution_service.log -Tail 100 | Select-String -Pattern "ERROR"
```

---

## 🌍 Cross-Platform Command Summary

| Task | Linux/EC2 | Windows |
|------|-----------|---------|
| **Cleanup** | `shoonya-clean` | `.\shoonya-clean.bat` or `shoonya-clean` (PowerShell) |
| **Start Service** | `sudo systemctl start shoonya_platform` | `nssm start shoonya_platform` |
| **Stop Service** | `sudo systemctl stop shoonya_platform` | `nssm stop shoonya_platform` |
| **View Logs** | `sudo journalctl -u shoonya_platform -f` | `Get-Content .\logs\*.log -Tail 50 -Wait` |
| **Activate Venv** | `source venv/bin/activate` | `.\venv\Scripts\Activate.ps1` |
| **Run Manually** | `python main.py` | `python main.py` |

---

## 📚 Additional Resources

- [SERVICE_INSTALLATION_LINUX.md](SERVICE_INSTALLATION_LINUX.md) - Complete Linux/EC2 systemd setup
- [SERVICE_INSTALLATION_WINDOWS.md](SERVICE_INSTALLATION_WINDOWS.md) - Complete Windows NSSM/PowerShell setup
- [bootstrap.py](bootstrap.py) - Environment setup script
- [cleanup_shoonya_platform.py](shoonya_platform/tools/cleanup_shoonya_platform.py) - Cleanup utility source

---

**Last Updated:** 2026-02-09
**Platform Support:** Windows 10/11, Linux (systemd), EC2 Amazon Linux 2
