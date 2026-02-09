#!/usr/bin/env python3
"""
Shoonya Platform – Clean Runtime Utility (Cross-Platform)
=========================================================

AUTOMATIC SETUP (RECOMMENDED):
    Run bootstrap.py - it automatically configures this utility

MANUAL SETUP:

LINUX/EC2:
    chmod +x ~/shoonya_platform/shoonya_platform/tools/cleanup_shoonya_platform.py
    sudo ln -sf ~/shoonya_platform/shoonya_platform/tools/cleanup_shoonya_platform.py \\
        /usr/local/bin/shoonya-clean
    
    Usage: shoonya-clean (from anywhere)

WINDOWS (Option 1 - Batch File):
    shoonya-clean.bat (created by bootstrap.py in project root)
    
    Usage: .\\shoonya-clean.bat

WINDOWS (Option 2 - PowerShell Command):
    .\\setup_powershell_commands.ps1 -Install
    
    Usage: shoonya-clean (from anywhere in PowerShell)

This is a SAFE, OPERATOR-FRIENDLY runtime cleanup tool.

WHAT THIS SCRIPT DOES
---------------------
1. Removes all __pycache__ directories under the project
2. Removes all compiled .pyc files
3. OPTIONALLY reloads systemd
4. OPTIONALLY restarts selected systemd services (index-based)

WHAT THIS SCRIPT DOES NOT DO
----------------------------
❌ Does NOT touch application logic
❌ Does NOT modify configs or databases
❌ Does NOT auto-restart services without confirmation

SERVICE SELECTION RULES
-----------------------
- Press ENTER → skip service restart completely (SAFE DEFAULT)
- Enter `0`     → restart ALL services
- Enter `1,2`   → restart selected services by index

EXAMPLE
-------
👉 Select services to restart: 1,3
→ restarts only the 1st and 3rd services

SAFE TO RUN MULTIPLE TIMES
-------------------------
This script is idempotent and production-safe.
"""

import shutil
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------
# PROJECT CONFIGURATION (CROSS-PLATFORM)
# ---------------------------------------------------------------------

# Auto-detect project root from script location
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Systemd service (Linux/EC2 only)
# Windows users: use run_windows_service.py instead
SERVICES = [
    "shoonya_platform",  # Single unified service (runs main.py)
]


# ---------------------------------------------------------------------
# CLEANUP UTILITIES
# ---------------------------------------------------------------------

def remove_pycache(root: Path):
    """
    Remove all __pycache__ directories recursively.
    Safe: ignores missing or locked directories.
    """
    print("🧹 Removing __pycache__ directories...")
    count = 0
    for path in root.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
        count += 1
    print(f"✅ Removed {count} __pycache__ directories")


def remove_pyc_files(root: Path):
    """
    Remove all compiled .pyc files recursively.
    Safe: ignores permission errors.
    """
    print("🧹 Removing .pyc files...")
    count = 0
    for path in root.rglob("*.pyc"):
        try:
            path.unlink()
            count += 1
        except Exception:
            pass
    print(f"✅ Removed {count} .pyc files")


# ---------------------------------------------------------------------
# SERVICE SELECTION (INDEX-BASED, OPERATOR SAFE)
# ---------------------------------------------------------------------

def ask_services_by_index() -> list[str]:
    """
    Ask operator which services to restart using indexes.

    Rules:
    - ENTER → skip restart
    - 0     → restart all services
    - 1,2   → restart selected services

    Returns:
        list[str]: services to restart (empty = skip)
    """
    print("\n📋 Available services:")
    for i, service in enumerate(SERVICES, start=1):
        print(f"  {i}. {service}")
    print("  0. ALL services")
    print("  ENTER → skip restart")

    raw = input("\n👉 Select services to restart: ").strip()

    # ENTER → skip restart entirely
    if not raw:
        print("⏭️ Skipping service restart")
        return []

    # 0 → restart all services
    if raw == "0":
        return SERVICES.copy()

    selected = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            continue

        idx = int(part)
        if 1 <= idx <= len(SERVICES):
            selected.append(SERVICES[idx - 1])

    if not selected:
        print("⚠️ No valid services selected. Skipping restart.")
        return []

    return selected


# ---------------------------------------------------------------------
# SYSTEMD OPERATIONS
# ---------------------------------------------------------------------

def reload_and_restart_services(services: list[str]):
    """
    Reload systemd and restart selected services.
    Linux/EC2 only - uses sudo.
    Windows users: restart service manually via Services app or run_windows_service.py
    """
    import platform
    
    if platform.system() == "Windows":
        print("⚠️  Service restart not available on Windows")
        print("👉 Manually restart the service or use run_windows_service.py")
        return
    
    print("\n🔄 Reloading systemd...")
    subprocess.run(["sudo", "systemctl", "daemon-reexec"], check=False)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=False)

    for service in services:
        print(f"🔁 Restarting {service}...")
        subprocess.run(
            ["sudo", "systemctl", "restart", service],
            check=False,
        )

    print("✅ systemd reload + service restart complete")


# ---------------------------------------------------------------------
# MAIN ENTRYPOINT
# ---------------------------------------------------------------------

def main():
    print("🚀 Starting Shoonya clean runtime reset\n")

    if not PROJECT_ROOT.exists():
        raise RuntimeError(f"Project root not found: {PROJECT_ROOT}")

    # Step 1: cleanup
    remove_pycache(PROJECT_ROOT)
    remove_pyc_files(PROJECT_ROOT)

    # Step 2: optional systemd + service handling
    services = ask_services_by_index()
    if services:
        reload_and_restart_services(services)

    print("\n🎯 Clean runtime reset complete")
    print("👉 Safe to continue operations")


if __name__ == "__main__":
    main()