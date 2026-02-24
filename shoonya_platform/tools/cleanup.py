#!/usr/bin/env python3
"""
Shoonya Platform – Clean Runtime Utility (Cross-Platform)
=========================================================

AUTOMATIC SETUP (RECOMMENDED):
    Run bootstrap.py - it automatically configures this utility
run in terminal on ec2 amazon linux:
chmod +x /home/ec2-user/shoonya_platform/shoonya_platform/tools/cleanup.py

sudo ln -sf \
/home/ec2-user/shoonya_platform/shoonya_platform/tools/cleanup.py \
/usr/local/bin/cleanup

MANUAL SETUP:

LINUX/EC2:
    chmod +x ~/shoonya_platform/shoonya_platform/tools/cleanup.py
    sudo ln -sf ~/shoonya_platform/shoonya_platform/tools/cleanup.py \\
        /usr/local/bin/cleanup
    
    Usage: cleanup (from anywhere)

WINDOWS (Option 1 - Batch File):
    cleanup.bat (created by bootstrap.py in project root)
    
    Usage: .\\cleanup.bat

WINDOWS (Option 2 - PowerShell Command):
    .\\setup_powershell_commands.ps1 -Install
    
    Usage: cleanup (from anywhere in PowerShell)

This is a SAFE, OPERATOR-FRIENDLY runtime cleanup tool.

WHAT THIS SCRIPT DOES
---------------------
1. Stops selected systemd services (if running)
2. Removes all __pycache__ directories under the project
3. Removes all compiled .pyc files
4. Starts selected services fresh

WHAT THIS SCRIPT DOES NOT DO
----------------------------
❌ Does NOT touch application logic
❌ Does NOT modify configs or databases
❌ Does NOT auto-restart services without confirmation

SERVICE SELECTION RULES
-----------------------
- Press ENTER → skip service management completely (SAFE DEFAULT)
- Enter `0`     → manage ALL services (stop → clean → start)
- Enter `1,2`   → manage selected services by index

EXAMPLE
-------
👉 Select services to restart: 1
→ stops trading service, cleans files, starts trading service fresh

SAFE TO RUN MULTIPLE TIMES
-------------------------
This script is idempotent and production-safe.
"""

import shutil
import subprocess
import os
from pathlib import Path


# ---------------------------------------------------------------------
# PROJECT CONFIGURATION (CROSS-PLATFORM)
# ---------------------------------------------------------------------

# Auto-detect project root from script location
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Systemd service (Linux/EC2 only)
# Windows users: use run_windows_service.py instead
SERVICES = [
    "trading",  # Service that runs main.py
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
    for dirpath, dirnames, _ in os.walk(root, topdown=True, onerror=lambda _: None):
        if "__pycache__" not in dirnames:
            continue

        pycache_path = Path(dirpath) / "__pycache__"
        try:
            shutil.rmtree(pycache_path, ignore_errors=True)
            count += 1
        except Exception:
            pass

        # Avoid descending into a directory we just removed.
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
    print(f"✅ Removed {count} __pycache__ directories")


def remove_pyc_files(root: Path):
    """
    Remove all compiled .pyc files recursively.
    Safe: ignores permission errors.
    """
    print("🧹 Removing .pyc files...")
    count = 0
    for dirpath, _, filenames in os.walk(root, topdown=True, onerror=lambda _: None):
        for filename in filenames:
            if not filename.endswith(".pyc"):
                continue

            path = Path(dirpath) / filename
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
    Ask operator which services to manage using indexes.

    Rules:
    - ENTER → skip service management
    - 0     → manage all services
    - 1,2   → manage selected services

    Returns:
        list[str]: services to manage (empty = skip)
    """
    print("\n📋 Available services:")
    for i, service in enumerate(SERVICES, start=1):
        print(f"  {i}. {service}")
    print("  0. ALL services")
    print("  ENTER → skip service management")

    raw = input("\n👉 Select services to manage: ").strip()

    # ENTER → skip management entirely
    if not raw:
        print("⏭️ Skipping service management")
        return []

    # 0 → manage all services
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
        print("⚠️ No valid services selected. Skipping service management.")
        return []

    return selected


# ---------------------------------------------------------------------
# SYSTEMD OPERATIONS
# ---------------------------------------------------------------------

def stop_services(services: list[str]):
    """
    Stop selected services.
    Linux/EC2 only - uses sudo.
    """
    import platform
    
    if platform.system() == "Windows":
        print("⚠️  Service stop not available on Windows")
        return
    
    if not services:
        return
        
    print("\n⏹️  Stopping services...")
    for service in services:
        print(f"🛑 Stopping {service}...")
        subprocess.run(
            ["sudo", "systemctl", "stop", service],
            check=False,
        )
    print("✅ Services stopped")


def start_services(services: list[str]):
    """
    Start selected services fresh.
    Linux/EC2 only - uses sudo.
    """
    import platform
    
    if platform.system() == "Windows":
        print("⚠️  Service start not available on Windows")
        return
    
    if not services:
        return
        
    print("\n▶️  Starting services fresh...")
    for service in services:
        print(f"🚀 Starting {service}...")
        subprocess.run(
            ["sudo", "systemctl", "start", service],
            check=False,
        )
    print("✅ Services started fresh")


# ---------------------------------------------------------------------
# MAIN ENTRYPOINT
# ---------------------------------------------------------------------

def main():
    print("🚀 Starting Shoonya clean runtime reset\n")

    if not PROJECT_ROOT.exists():
        raise RuntimeError(f"Project root not found: {PROJECT_ROOT}")

    # Step 1: Ask which services to manage
    services = ask_services_by_index()

    # Step 2: Stop services (if any selected)
    if services:
        stop_services(services)

    # Step 3: Cleanup
    remove_pycache(PROJECT_ROOT)
    remove_pyc_files(PROJECT_ROOT)

    # Step 4: Start services fresh (if any selected)
    if services:
        start_services(services)

    print("\n🎯 Clean runtime reset complete")
    print("👉 Safe to continue operations")


if __name__ == "__main__":
    main()
