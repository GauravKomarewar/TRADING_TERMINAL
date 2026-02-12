#!/usr/bin/env python3
"""
===============================================================================
PROJECT BOOTSTRAP / ENVIRONMENT SETUP (PRODUCTION – ONE TIME USE)
===============================================================================

PURPOSE
-------
This script bootstraps a clean Python environment for this project.
It is intentionally designed to be:

✔ Deterministic
✔ Re-runnable
✔ Human-readable (even decades later)
✔ Independent of local machine state
✔ Safe for fresh systems (PC / EC2 / VM)

IMPORTANT DESIGN DECISIONS
--------------------------
1. This script MUST NOT be run inside an active virtual environment.
2. Python version is strictly pinned (3.9 / 3.10).
3. Binary artifacts (.whl, installers) are NOT stored in Git history.
4. Required binaries are hosted under GitHub Releases.
5. This script will download missing binaries automatically.

SETUP ASSETS
------------
GitHub Releases (single source of truth for binaries):
    Repository : GauravKomarewar/TRADING_TERMINAL
    Release    : setup-assets-v1

If this script ever fails due to missing assets:
→ Check GitHub Releases first.

===============================================================================
"""

import os
import sys
import subprocess
import platform
from pathlib import Path
from urllib.request import urlretrieve
from typing import List
# =============================================================================
# CONFIGURATION (INTENTIONALLY EXPLICIT)
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent

VENV_DIR = PROJECT_ROOT / "venv"

REQUIREMENTS_FILE = PROJECT_ROOT / "requirements" / "requirements.txt"

# Strict Python compatibility boundary
ALLOWED_PYTHON_VERSIONS = {(3, 9), (3, 10)}

# GitHub Release hosting binary dependencies
GITHUB_RELEASE_BASE = (
    "https://github.com/GauravKomarewar/TRADING_TERMINAL/"
    "releases/download/setup-assets-v1"
)

# External wheel dependency (NOT tracked by Git)
WHEEL_NAME = "NorenRestApi-0.0.30-py2.py3-none-any.whl"
WHEEL_PATH = PROJECT_ROOT / "requirements" / WHEEL_NAME
WHEEL_URL = f"{GITHUB_RELEASE_BASE}/{WHEEL_NAME}"

# =============================================================================
# LOW-LEVEL HELPERS
# =============================================================================

def run(cmd: List[str]) -> None:
    """Run a command and fail fast if it errors."""
    print(f"▶ {' '.join(cmd)}")
    subprocess.check_call(cmd)

def is_windows() -> bool:
    return platform.system().lower() == "windows"

def python_version_ok() -> bool:
    return sys.version_info[:2] in ALLOWED_PYTHON_VERSIONS

# =============================================================================
# MAIN BOOTSTRAP LOGIC
# =============================================================================

def main() -> None:
    os.chdir(PROJECT_ROOT)
    print(f"📂 Project directory: {PROJECT_ROOT}")

    # -------------------------------------------------------------------------
    # ENSURE REQUIRED WHEEL EXISTS (DOWNLOAD IF MISSING)
    # -------------------------------------------------------------------------
    if not WHEEL_PATH.exists():
        print("📦 Required wheel not found locally.")
        print(f"⬇️ Downloading from GitHub Releases:\n   {WHEEL_URL}")

        WHEEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(WHEEL_URL, WHEEL_PATH)

        print("✅ Download complete")

    else:
        print("ℹ️ Required wheel already present")

    # -------------------------------------------------------------------------
    # SAFETY: refuse to run inside an existing virtual environment
    # -------------------------------------------------------------------------
    if os.environ.get("VIRTUAL_ENV"):
        print("❌ ERROR: Do NOT run this script inside an active virtualenv.")
        print("👉 Deactivate it first, then re-run bootstrap.py")
        sys.exit(1)

    # -------------------------------------------------------------------------
    # PYTHON VERSION GUARD
    # -------------------------------------------------------------------------
    if not python_version_ok():
        print("❌ Unsupported Python version detected")
        print(f"👉 Detected : {sys.version.split()[0]}")
        print("👉 Required : Python 3.9 or 3.10")
        sys.exit(1)

    print(f"🐍 Python OK: {sys.version.split()[0]}")

    # -------------------------------------------------------------------------
    # CREATE VIRTUAL ENVIRONMENT (IDEMPOTENT)
    # -------------------------------------------------------------------------
    if not VENV_DIR.exists():
        print("🐍 Creating virtual environment...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print("ℹ️ Virtual environment already exists")

    # -------------------------------------------------------------------------
    # RESOLVE pip PATH
    # -------------------------------------------------------------------------
    if is_windows():
        pip = VENV_DIR / "Scripts" / "pip.exe"
        activate_hint = f"{VENV_DIR}\\Scripts\\Activate.ps1"
    else:
        pip = VENV_DIR / "bin" / "pip"
        activate_hint = f"source {VENV_DIR}/bin/activate"

    if is_windows():
        python = VENV_DIR / "Scripts" / "python.exe"
    else:
        python = VENV_DIR / "bin" / "python"

    # -------------------------------------------------------------------------
    # UPGRADE TOOLCHAIN (SAFE & REQUIRED)
    # -------------------------------------------------------------------------
    print("⬆️ Upgrading setuptools / wheel (pip-safe)...")
    run([str(python), "-m", "pip", "install", "--upgrade", "setuptools", "wheel"])

    # -------------------------------------------------------------------------
    # INSTALL PYTHON REQUIREMENTS
    # -------------------------------------------------------------------------
    if not REQUIREMENTS_FILE.exists():
        print(f"❌ Missing requirements file: {REQUIREMENTS_FILE}")
        sys.exit(1)

    print("📥 Installing Python dependencies...")
    run([str(pip), "install", "-r", str(REQUIREMENTS_FILE)])

    # -------------------------------------------------------------------------
    # INSTALL WHEEL
    # -------------------------------------------------------------------------
    print(f"📦 Installing wheel: {WHEEL_NAME}")
    run([str(pip), "install", str(WHEEL_PATH)])

    # -------------------------------------------------------------------------
    # SETUP CLEANUP UTILITY (CROSS-PLATFORM)
    # -------------------------------------------------------------------------
    print("\n🧹 Setting up cleanup utility...")
    cleanup_script = PROJECT_ROOT / "shoonya_platform" / "tools" / "cleanup_shoonya_platform.py"
    
    if is_windows():
        # Create batch wrapper for Windows
        batch_wrapper = PROJECT_ROOT / "shoonya-clean.bat"
        batch_content = f'''@echo off
REM Shoonya Platform Cleanup Utility (Windows)
"{python}" "{cleanup_script}" %*
'''
        with open(batch_wrapper, 'w') as f:
            f.write(batch_content)
        print(f"✅ Created Windows batch wrapper: {batch_wrapper.name}")
        print("   👉 Usage: .\\shoonya-clean.bat")
        print("   👉 Or add project root to PATH for 'shoonya-clean' command")
    else:
        # Linux/EC2: Make executable and create symlink
        try:
            # Make script executable
            os.chmod(cleanup_script, 0o755)
            print(f"✅ Made cleanup script executable")
            
            # Try to create symlink (requires sudo, may fail)
            symlink_path = "/usr/local/bin/shoonya-clean"
            try:
                # Check if symlink already exists
                if Path(symlink_path).exists() or Path(symlink_path).is_symlink():
                    print(f"ℹ️  Symlink already exists: {symlink_path}")
                else:
                    # Attempt to create symlink
                    subprocess.run(
                        ["sudo", "ln", "-sf", str(cleanup_script), symlink_path],
                        check=True,
                        capture_output=True
                    )
                    print(f"✅ Created global command: shoonya-clean")
                    print("   👉 Usage: shoonya-clean (from anywhere)")
            except (subprocess.CalledProcessError, PermissionError):
                print("⚠️  Could not create global symlink (sudo required)")
                print("   👉 Run manually to enable global command:")
                print(f"      sudo ln -sf {cleanup_script} /usr/local/bin/shoonya-clean")
                print(f"   👉 Or run directly: python {cleanup_script}")
        except Exception as e:
            print(f"⚠️  Cleanup utility setup skipped: {e}")
            print(f"   👉 Run directly: python {cleanup_script}")

    # -------------------------------------------------------------------------
    # FINAL MESSAGE
    # -------------------------------------------------------------------------
    print("\n✅ SETUP COMPLETE")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("👉 Activate environment with:")
    print(f"   {activate_hint}")
    
    if is_windows():
        print("\n🧹 Cleanup utility available:")
        print("   .\\shoonya-clean.bat")
        print("\n   Optional: Install as PowerShell command:")
        print("   .\\setup_powershell_commands.ps1 -Install")
    else:
        print("\n🧹 Cleanup utility:")
        if Path("/usr/local/bin/shoonya-clean").exists():
            print("   ✅ Global command: shoonya-clean")
        else:
            print("   👉 Enable global command: sudo ln -sf")
            print(f"      {cleanup_script}")
            print("      /usr/local/bin/shoonya-clean")
    
    print("\n🧊 This environment is now production-ready.")

# =============================================================================

if __name__ == "__main__":
    main()