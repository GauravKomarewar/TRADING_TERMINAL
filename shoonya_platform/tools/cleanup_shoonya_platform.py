#!/usr/bin/env python3
"""
Shoonya Dashboard – Clean Runtime Utility
=========================================
run in terminal
chmod +x /home/ec2-user/shoonya_platform/shoonya_platform/tools/cleanup_shoonya_platform.py

sudo ln -sf \
/home/ec2-user/shoonya_platform/shoonya_platform/tools/cleanup_shoonya_platform.py \
/usr/local/bin/shoonya-clean

now use anywhere just by entering "shoonya-clean" in terminal done.

This script performs a clean runtime reset for the dashboard by:
1. Removing all __pycache__ directories
2. Removing all .pyc files
3. Reloading systemd (daemon-reexec + daemon-reload)

Safe to run multiple times.
No application logic is touched.
"""

import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path("/home/ec2-user/shoonya_platform")


def remove_pycache(root: Path):
    print("🧹 Removing __pycache__ directories...")
    count = 0
    for path in root.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
        count += 1
    print(f"✅ Removed {count} __pycache__ directories")


def remove_pyc_files(root: Path):
    print("🧹 Removing .pyc files...")
    count = 0
    for path in root.rglob("*.pyc"):
        try:
            path.unlink()
            count += 1
        except Exception:
            pass
    print(f"✅ Removed {count} .pyc files")


def reload_systemd():
    print("🔄 Reloading systemd...")
    subprocess.run(["sudo", "systemctl", "daemon-reexec"], check=False)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=False)
    print("✅ systemd reloaded")


def main():
    print("🚀 Starting Shoonya clean runtime reset\n")

    if not PROJECT_ROOT.exists():
        raise RuntimeError(f"Project root not found: {PROJECT_ROOT}")

    remove_pycache(PROJECT_ROOT)
    remove_pyc_files(PROJECT_ROOT)
    reload_systemd()

    print("\n🎯 Clean runtime reset complete")
    print("👉 You can now safely restart Any-shoonya-services")


if __name__ == "__main__":
    main()
