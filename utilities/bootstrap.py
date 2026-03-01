#!/usr/bin/env python3
"""
===============================================================================
PROJECT BOOTSTRAP / ENVIRONMENT SETUP (ONE-STOP SOLUTION)
===============================================================================

LOCATION: utilities/bootstrap.py

PURPOSE
-------
Clone the repo → run this script → everything is ready.

This script handles:
  1. Python version validation (3.10+)
  2. Virtual environment creation at project root (venv/)
  3. pip dependency installation (requirements.txt + NorenRestApi wheel)
  4. Systemd service + timer installation (Linux only)
  5. Cleanup utility setup
  6. .bashrc auto-activation hook (Linux only)

DESIGN DECISIONS
----------------
• Single venv at <PROJECT_ROOT>/venv/ (no nested venv anywhere)
• Re-runnable / idempotent — safe to run multiple times
• Detects current OS user & home directory automatically
• Service files use dynamic paths (never hardcoded ec2-user)
• Python 3.10, 3.11, 3.12, 3.13 supported

USAGE
-----
  cd shoonya_platform
  python3 utilities/bootstrap.py

  (or from anywhere)
  python3 /path/to/shoonya_platform/utilities/bootstrap.py

===============================================================================
"""

import getpass
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List
from urllib.request import urlretrieve


# =============================================================================
# CONFIGURATION
# =============================================================================

# Resolve project root from this script's location: utilities/bootstrap.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Single venv at project root
VENV_DIR = PROJECT_ROOT / "venv"

# Requirements
REQUIREMENTS_DIR = PROJECT_ROOT / "utilities" / "requirements"
REQUIREMENTS_FILE = REQUIREMENTS_DIR / "requirements.txt"

# Python version boundary: 3.10+
MIN_PYTHON = (3, 10)

# Wheel dependency (shipped in repo under utilities/requirements/)
WHEEL_NAME = "NorenRestApi-0.0.30-py2.py3-none-any.whl"
WHEEL_PATH = REQUIREMENTS_DIR / WHEEL_NAME

# GitHub Release fallback for the wheel (if not present locally)
GITHUB_RELEASE_BASE = (
    "https://github.com/GauravKomarewar/TRADING_TERMINAL/"
    "releases/download/setup-assets-v1"
)
WHEEL_URL = f"{GITHUB_RELEASE_BASE}/{WHEEL_NAME}"

# Deployment templates (relative to PROJECT_ROOT)
DEPLOYMENT_DIR = PROJECT_ROOT / "utilities" / "deployment"
SYSTEMD_DIR = DEPLOYMENT_DIR / "systemd"


# =============================================================================
# HELPERS
# =============================================================================

def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, print it, and fail fast on error."""
    print(f"  ▶ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=False)


def is_linux() -> bool:
    return platform.system().lower() == "linux"


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def current_user() -> str:
    return getpass.getuser()


def current_home() -> Path:
    return Path.home()


def python_version_ok() -> bool:
    return sys.version_info[:2] >= MIN_PYTHON


def venv_python() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_pip() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


# =============================================================================
# STEP 1: PYTHON VERSION CHECK
# =============================================================================

def check_python_version() -> None:
    """Ensure Python >= 3.10."""
    print(f"\n{'='*60}")
    print("STEP 1: Python Version Check")
    print(f"{'='*60}")

    if not python_version_ok():
        print(f"  ❌ Unsupported Python version: {sys.version.split()[0]}")
        print(f"  ➜  Required: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
        print(f"  ➜  Install Python 3.12: sudo apt install python3.12 python3.12-venv")
        sys.exit(1)

    print(f"  ✅ Python {sys.version.split()[0]}")


# =============================================================================
# STEP 2: SAFETY CHECKS
# =============================================================================

def safety_checks() -> None:
    """Refuse to run inside an active venv; warn about stale venvs."""
    print(f"\n{'='*60}")
    print("STEP 2: Safety Checks")
    print(f"{'='*60}")

    if os.environ.get("VIRTUAL_ENV"):
        active = os.environ["VIRTUAL_ENV"]
        print(f"  ❌ Active virtualenv detected: {active}")
        print("  ➜  Deactivate it first:  deactivate")
        print("  ➜  Then re-run:  python3 utilities/bootstrap.py")
        sys.exit(1)

    # Warn about stale utilities/venv
    stale_venv = PROJECT_ROOT / "utilities" / "venv"
    if stale_venv.exists():
        print(f"  ⚠️  Stale venv found: {stale_venv}")
        print(f"  ➜  Removing it (single venv should be at {VENV_DIR})")
        shutil.rmtree(stale_venv, ignore_errors=True)
        print(f"  ✅ Removed stale venv")

    print("  ✅ Safety checks passed")


# =============================================================================
# STEP 3: CREATE / VERIFY VIRTUAL ENVIRONMENT
# =============================================================================

def setup_venv() -> None:
    """Create venv at project root if it doesn't exist."""
    print(f"\n{'='*60}")
    print("STEP 3: Virtual Environment")
    print(f"{'='*60}")

    if VENV_DIR.exists() and venv_python().exists():
        print(f"  ✅ venv already exists: {VENV_DIR}")
    else:
        print(f"  📦 Creating venv at {VENV_DIR} ...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        print(f"  ✅ venv created")

    # Upgrade pip + setuptools + wheel inside venv
    print("  ⬆️  Upgrading pip, setuptools, wheel ...")
    run([str(venv_python()), "-m", "pip", "install", "--upgrade",
         "pip", "setuptools", "wheel"])


# =============================================================================
# STEP 4: INSTALL DEPENDENCIES
# =============================================================================

def install_dependencies() -> None:
    """Install requirements.txt and the NorenRestApi wheel."""
    print(f"\n{'='*60}")
    print("STEP 4: Install Dependencies")
    print(f"{'='*60}")

    # Ensure wheel file exists (download if missing)
    if not WHEEL_PATH.exists():
        print(f"  📦 Wheel not found locally — downloading from GitHub Releases ...")
        WHEEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(WHEEL_URL, str(WHEEL_PATH))
        print(f"  ✅ Downloaded {WHEEL_NAME}")
    else:
        print(f"  ✅ Wheel present: {WHEEL_NAME}")

    # Ensure requirements.txt exists
    if not REQUIREMENTS_FILE.exists():
        print(f"  ❌ Missing: {REQUIREMENTS_FILE}")
        sys.exit(1)

    # Install from requirements.txt
    print("  📥 Installing Python dependencies ...")
    run([str(venv_pip()), "install", "-r", str(REQUIREMENTS_FILE)])

    # Install wheel explicitly (in case requirements.txt uses relative path)
    print(f"  📦 Installing {WHEEL_NAME} ...")
    run([str(venv_pip()), "install", "--force-reinstall", str(WHEEL_PATH)])

    print("  ✅ All dependencies installed")


# =============================================================================
# STEP 5: SYSTEMD SERVICE + TIMER INSTALLATION (Linux only)
# =============================================================================

def _generate_trading_service() -> str:
    """Generate trading.service content with correct user/paths."""
    user = current_user()
    project = PROJECT_ROOT

    return textwrap.dedent(f"""\
        [Unit]
        Description=Trading Service
        Documentation=https://github.com/GauravKomarewar/TRADING_TERMINAL
        After=network-online.target
        Wants=network-online.target
        StartLimitIntervalSec=300
        StartLimitBurst=5

        [Service]
        Type=simple
        User={user}
        Group={user}
        WorkingDirectory={project}

        # Environment
        Environment="PATH={project}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
        Environment="PYTHONUNBUFFERED=1"
        Environment="LOG_LEVEL=INFO"
        Environment="PYTHONPATH={project}"

        # Entrypoint
        ExecStart={project}/venv/bin/python {project}/main.py

        # Restart policy
        Restart=always
        RestartSec=10
        RestartForceExitStatus=1

        # Resource limits
        MemoryMax=2G
        CPUQuota=80%

        # Security
        PrivateTmp=yes
        NoNewPrivileges=yes
        ProtectSystem=no
        ProtectHome=no
        ProtectKernelTunables=yes

        # Graceful shutdown
        TimeoutStopSec=30
        KillSignal=SIGTERM
        SendSIGKILL=yes

        # Process limits
        OOMScoreAdjust=-500
        LimitNOFILE=65536
        LimitNPROC=8192

        # Logging
        StandardOutput=journal
        StandardError=journal
        SyslogIdentifier=trading

        [Install]
        WantedBy=multi-user.target
    """)


def _generate_start_service() -> str:
    """Generate trading_start.service with correct paths."""
    return textwrap.dedent(f"""\
        [Unit]
        Description=Trading Platform Start Service
        Documentation=man:systemctl(1)
        After=network.target

        [Service]
        Type=oneshot
        User=root
        WorkingDirectory={PROJECT_ROOT}
        ExecStart=/usr/bin/systemctl start trading.service
        StandardOutput=journal
        StandardError=journal

        [Install]
        WantedBy=multi-user.target
    """)


def _generate_stop_service() -> str:
    """Generate trading_stop.service with correct paths."""
    return textwrap.dedent(f"""\
        [Unit]
        Description=Trading Platform Stop Service
        Documentation=man:systemctl(1)
        After=network.target

        [Service]
        Type=oneshot
        User=root
        WorkingDirectory={PROJECT_ROOT}
        ExecStart=/usr/bin/systemctl stop trading.service
        StandardOutput=journal
        StandardError=journal

        [Install]
        WantedBy=multi-user.target
    """)


def install_systemd_services() -> None:
    """Install trading.service + start/stop timers on Linux."""
    print(f"\n{'='*60}")
    print("STEP 5: Systemd Service & Timer Installation")
    print(f"{'='*60}")

    if not is_linux():
        print("  ⏭️  Skipping (not Linux)")
        return

    # Check for sudo
    result = subprocess.run(["sudo", "-n", "true"], capture_output=True)
    if result.returncode != 0:
        print("  ⚠️  sudo required for systemd installation.")
        print("  ➜  You can install manually later:")
        print(f"     sudo cp {DEPLOYMENT_DIR}/trading.service /etc/systemd/system/")
        print(f"     sudo cp {SYSTEMD_DIR}/*.service {SYSTEMD_DIR}/*.timer /etc/systemd/system/")
        print("     sudo systemctl daemon-reload")
        return

    # 1) Write generated trading.service to deployment dir (for reference)
    trading_service_content = _generate_trading_service()
    trading_service_file = DEPLOYMENT_DIR / "trading.service"
    trading_service_file.write_text(trading_service_content)
    print(f"  📝 Generated {trading_service_file.name} (user={current_user()})")

    # 2) Write generated start/stop services
    start_service_file = SYSTEMD_DIR / "trading_start.service"
    start_service_file.write_text(_generate_start_service())
    print(f"  📝 Generated {start_service_file.name}")

    stop_service_file = SYSTEMD_DIR / "trading_stop.service"
    stop_service_file.write_text(_generate_stop_service())
    print(f"  📝 Generated {stop_service_file.name}")

    # 3) Copy to /etc/systemd/system/
    systemd_dest = Path("/etc/systemd/system")

    files_to_install = [
        (trading_service_file, "trading.service"),
        (start_service_file, "trading_start.service"),
        (stop_service_file, "trading_stop.service"),
        (SYSTEMD_DIR / "trading_start.timer", "trading_start.timer"),
        (SYSTEMD_DIR / "trading_stop.timer", "trading_stop.timer"),
    ]

    for src, name in files_to_install:
        if src.exists():
            run(["sudo", "cp", str(src), str(systemd_dest / name)], check=True)
            print(f"  ✅ Installed {name}")
        else:
            print(f"  ⚠️  Missing: {src}")

    # 4) Reload and enable
    run(["sudo", "systemctl", "daemon-reload"])
    print("  ✅ systemd daemon reloaded")

    # Enable timers
    for timer in ["trading_start.timer", "trading_stop.timer"]:
        run(["sudo", "systemctl", "enable", timer], check=False)
        run(["sudo", "systemctl", "start", timer], check=False)
        print(f"  ✅ Enabled & started {timer}")

    # Enable service (don't start — user should start manually)
    run(["sudo", "systemctl", "enable", "trading.service"], check=False)
    print("  ✅ Enabled trading.service (not started — start manually when ready)")


# =============================================================================
# STEP 6: CLEANUP UTILITY SETUP
# =============================================================================

def setup_cleanup_utility() -> None:
    """Make cleanup.py executable and optionally create a global symlink."""
    print(f"\n{'='*60}")
    print("STEP 6: Cleanup Utility Setup")
    print(f"{'='*60}")

    cleanup_script = PROJECT_ROOT / "utilities" / "cleanup.py"

    if not cleanup_script.exists():
        print(f"  ⚠️  cleanup.py not found at {cleanup_script}")
        return

    if is_linux():
        os.chmod(cleanup_script, 0o755)
        print(f"  ✅ Made cleanup.py executable")

        symlink_path = Path("/usr/local/bin/shoonya-clean")
        try:
            subprocess.run(
                ["sudo", "-n", "ln", "-sf", str(cleanup_script), str(symlink_path)],
                capture_output=True, check=True
            )
            print(f"  ✅ Created global command: shoonya-clean")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"  ⚠️  Could not create symlink (sudo required)")
            print(f"  ➜  Manual: sudo ln -sf {cleanup_script} /usr/local/bin/shoonya-clean")
    else:
        print(f"  ✅ Cleanup utility available at: {cleanup_script}")
        print(f"  ➜  Usage: python {cleanup_script}")


# =============================================================================
# STEP 7: BASHRC AUTO-ACTIVATION (Linux only)
# =============================================================================

def setup_bashrc_hook() -> None:
    """Add venv auto-activation to .bashrc (Linux only)."""
    print(f"\n{'='*60}")
    print("STEP 7: Shell Auto-Activation")
    print(f"{'='*60}")

    if not is_linux():
        print("  ⏭️  Skipping (not Linux)")
        if is_windows():
            print(f"  ➜  Activate manually: {VENV_DIR}\\Scripts\\Activate.ps1")
        return

    bashrc = current_home() / ".bashrc"
    marker = "# --- Shoonya Trading Environment Auto-Activation ---"

    # The hook we want
    hook_block = textwrap.dedent(f"""\
        {marker}
        if [ -d "{VENV_DIR}" ]; then
            source {VENV_DIR}/bin/activate
            cd {PROJECT_ROOT}
        fi
    """)

    if bashrc.exists():
        content = bashrc.read_text()
        if marker in content:
            # Replace existing block (between marker and the fi line)
            lines = content.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if marker in line:
                    skip = True
                    continue
                if skip:
                    # Skip until we hit a line that's not part of the hook
                    if line.strip() == "fi":
                        skip = False
                        continue
                    if line.startswith("if ") or line.startswith("    "):
                        continue
                    skip = False
                    new_lines.append(line)
                    continue
                new_lines.append(line)

            content = "\n".join(new_lines).rstrip() + "\n\n" + hook_block
            bashrc.write_text(content)
            print("  ✅ Updated .bashrc hook (replaced old block)")
        else:
            with open(bashrc, "a") as f:
                f.write("\n" + hook_block)
            print("  ✅ Added venv auto-activation to .bashrc")
    else:
        bashrc.write_text(hook_block)
        print("  ✅ Created .bashrc with venv auto-activation")

    print(f"  ➜  Run: source ~/.bashrc  (to apply now)")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     SHOONYA TRADING PLATFORM — BOOTSTRAP SETUP         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Project root : {PROJECT_ROOT}")
    print(f"  OS           : {platform.system()} {platform.machine()}")
    print(f"  User         : {current_user()}")
    print(f"  Python       : {sys.version.split()[0]}")

    os.chdir(PROJECT_ROOT)

    check_python_version()       # Step 1
    safety_checks()              # Step 2
    setup_venv()                 # Step 3
    install_dependencies()       # Step 4
    install_systemd_services()   # Step 5
    setup_cleanup_utility()      # Step 6
    setup_bashrc_hook()          # Step 7

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("✅ BOOTSTRAP COMPLETE")
    print(f"{'='*60}")
    print(f"  venv     : {VENV_DIR}")
    print(f"  activate : source {VENV_DIR}/bin/activate")
    print(f"  start    : python main.py")

    if is_linux():
        print(f"\n  Systemd commands:")
        print(f"    sudo systemctl start trading")
        print(f"    sudo systemctl status trading")
        print(f"    journalctl -u trading -f")
        print(f"\n  Timers (auto start/stop Mon-Fri):")
        print(f"    sudo systemctl list-timers trading_*")

    print(f"\n  Cleanup  : shoonya-clean  (or python utilities/cleanup.py)")
    print(f"  Backup   : python utilities/backup.py")
    print(f"\n🧊 This environment is now production-ready.")


# =============================================================================

if __name__ == "__main__":
    main()
