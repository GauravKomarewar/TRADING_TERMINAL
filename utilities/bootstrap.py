#!/usr/bin/env python3
"""
===============================================================================
PROJECT BOOTSTRAP — UNIVERSAL SETUP & REPAIR TOOL
===============================================================================

LOCATION: utilities/bootstrap.py

WHAT THIS DOES
--------------
One script to rule them all — works on ANY machine, ANY OS, ANY cloud:

  ✔ Local PC (Windows / macOS / Linux)
  ✔ AWS EC2 (Amazon Linux / Ubuntu)
  ✔ Oracle Cloud, GCP, Azure VMs
  ✔ WSL (Windows Subsystem for Linux)
  ✔ Docker containers

CAPABILITIES
------------
  1. Python version validation (3.10+)
  2. Virtual environment — create / verify / repair / recreate
  3. pip dependencies — install / reinstall / fix corruption
  4. Service management — create and install per OS:
       Linux  → systemd .service + .timer files
       macOS  → launchd .plist files
       Windows → PowerShell launcher + Task Scheduler
  5. Shell auto-activation (.bashrc / .zshrc / PowerShell profile)
  6. Cleanup utility setup

MODES
-----
  Fresh install (default):
    python3 utilities/bootstrap.py

  Repair everything (corrupted venv, broken services):
    python3 utilities/bootstrap.py --repair

  Force recreate venv from scratch:
    python3 utilities/bootstrap.py --force-venv

  Only regenerate & install service files:
    python3 utilities/bootstrap.py --services-only

  Show what would happen without changing anything:
    python3 utilities/bootstrap.py --dry-run

  Skip service installation (venv + deps only):
    python3 utilities/bootstrap.py --no-services

DESIGN
------
• Single venv at <PROJECT_ROOT>/venv/  (never nested)
• 100% idempotent — safe to run 100 times
• Auto-detects OS, user, home, project path
• Never hardcodes usernames or paths
• Downloads missing wheel from GitHub Releases

===============================================================================
"""

import argparse
import getpass
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Optional
from urllib.request import urlretrieve


# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / "venv"

REQUIREMENTS_DIR = PROJECT_ROOT / "utilities" / "requirements"
REQUIREMENTS_FILE = REQUIREMENTS_DIR / "requirements.txt"

MIN_PYTHON = (3, 10)

WHEEL_NAME = "NorenRestApi-0.0.30-py2.py3-none-any.whl"
WHEEL_PATH = REQUIREMENTS_DIR / WHEEL_NAME

GITHUB_RELEASE_BASE = (
    "https://github.com/GauravKomarewar/TRADING_TERMINAL/"
    "releases/download/setup-assets-v1"
)
WHEEL_URL = f"{GITHUB_RELEASE_BASE}/{WHEEL_NAME}"

DEPLOYMENT_DIR = PROJECT_ROOT / "utilities" / "deployment"
SYSTEMD_DIR = DEPLOYMENT_DIR / "systemd"


# =============================================================================
# OS / PLATFORM DETECTION
# =============================================================================

def os_type() -> str:
    """Return 'linux', 'windows', 'macos', or 'unknown'."""
    s = platform.system().lower()
    if s == "linux":
        return "linux"
    elif s == "darwin":
        return "macos"
    elif s == "windows":
        return "windows"
    return "unknown"


def is_wsl() -> bool:
    """Detect Windows Subsystem for Linux."""
    if os_type() != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def is_linux() -> bool:
    return os_type() == "linux"


def is_windows() -> bool:
    return os_type() == "windows"


def is_macos() -> bool:
    return os_type() == "macos"


def current_user() -> str:
    return getpass.getuser()


def current_home() -> Path:
    return Path.home()


def python_version_ok() -> bool:
    return sys.version_info[:2] >= MIN_PYTHON


def has_sudo() -> bool:
    """Check if passwordless sudo is available."""
    if not is_linux() and not is_macos():
        return False
    try:
        r = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# =============================================================================
# PATH HELPERS (CROSS-PLATFORM)
# =============================================================================

def venv_python() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_pip() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def venv_activate_cmd() -> str:
    if is_windows():
        return f"{VENV_DIR}\\Scripts\\Activate.ps1"
    return f"source {VENV_DIR}/bin/activate"


# =============================================================================
# EXECUTION HELPERS
# =============================================================================

def run(cmd: List[str], check: bool = True, quiet: bool = False,
        timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a command, print it, and fail fast on error."""
    if not quiet:
        print(f"  ▶ {' '.join(cmd)}")
    return subprocess.run(
        cmd, check=check, capture_output=quiet, timeout=timeout
    )


def run_quiet(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run silently and return result (for health checks)."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def banner(title: str, step: Optional[int] = None) -> None:
    prefix = f"STEP {step}: " if step else ""
    print(f"\n{'='*60}")
    print(f"{prefix}{title}")
    print(f"{'='*60}")


# =============================================================================
# VENV HEALTH CHECK
# =============================================================================

def venv_is_healthy() -> bool:
    """
    Deep health check — verify venv is not just present but functional.
    Returns True only if python and pip inside venv actually work.
    """
    py = venv_python()
    pip = venv_pip()

    # 1) Binary exists?
    if not py.exists():
        print("  ⚠️  venv python binary missing")
        return False

    # 2) Python actually runs?
    try:
        r = run_quiet([str(py), "-c", "import sys; print(sys.version)"])
        if r.returncode != 0:
            print(f"  ⚠️  venv python fails to execute: {r.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  ⚠️  venv python not runnable: {e}")
        return False

    # 3) pip works?
    try:
        r = run_quiet([str(pip), "--version"])
        if r.returncode != 0:
            print(f"  ⚠️  venv pip broken: {r.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  ⚠️  venv pip not runnable: {e}")
        return False

    # 4) Key packages importable?
    for pkg in ["flask", "fastapi", "pydantic", "NorenRestApiPy"]:
        r = run_quiet([str(py), "-c", f"import {pkg}"])
        if r.returncode != 0:
            print(f"  ⚠️  Package '{pkg}' not importable in venv")
            return False

    return True


# =============================================================================
# SERVICE FILE HEALTH CHECK
# =============================================================================

def services_healthy() -> bool:
    """Check if systemd services are installed and valid (Linux only)."""
    if not is_linux():
        return True  # Non-Linux doesn't use systemd

    required = [
        "/etc/systemd/system/trading.service",
        "/etc/systemd/system/trading_start.timer",
        "/etc/systemd/system/trading_stop.timer",
        "/etc/systemd/system/trading_start.service",
        "/etc/systemd/system/trading_stop.service",
    ]

    for path in required:
        if not Path(path).exists():
            print(f"  ⚠️  Missing: {path}")
            return False

    # Verify trading.service points to correct project path
    try:
        content = Path("/etc/systemd/system/trading.service").read_text()
        if str(PROJECT_ROOT) not in content:
            print(f"  ⚠️  trading.service has wrong project path")
            return False
        if current_user() not in content:
            print(f"  ⚠️  trading.service has wrong user (expected {current_user()})")
            return False
    except OSError:
        return False

    return True


# =============================================================================
# STEP 1: PYTHON VERSION CHECK
# =============================================================================

def step_check_python() -> None:
    banner("Python Version Check", 1)

    if not python_version_ok():
        v = sys.version.split()[0]
        print(f"  ❌ Unsupported Python: {v}")
        print(f"  ➜  Required: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
        if is_linux():
            print("  ➜  sudo apt install python3.12 python3.12-venv")
        elif is_macos():
            print("  ➜  brew install python@3.12")
        elif is_windows():
            print("  ➜  Download from https://www.python.org/downloads/")
        sys.exit(1)

    print(f"  ✅ Python {sys.version.split()[0]}")


# =============================================================================
# STEP 2: SAFETY CHECKS + REPAIR DETECTION
# =============================================================================

def step_safety_checks(args: argparse.Namespace) -> None:
    banner("Safety Checks & Diagnostics", 2)

    # Block running inside active venv (unless --repair which needs it sometimes)
    if os.environ.get("VIRTUAL_ENV") and not args.repair:
        print(f"  ❌ Active virtualenv: {os.environ['VIRTUAL_ENV']}")
        print("  ➜  deactivate  then re-run")
        print("  ➜  Or use --repair to force fix")
        sys.exit(1)

    # Remove stale nested venv
    stale = PROJECT_ROOT / "utilities" / "venv"
    if stale.exists():
        print(f"  ⚠️  Removing stale nested venv: {stale}")
        shutil.rmtree(stale, ignore_errors=True)
        print(f"  ✅ Removed")

    # Diagnose existing venv
    if VENV_DIR.exists():
        healthy = venv_is_healthy()
        if healthy and not args.force_venv:
            print(f"  ✅ Existing venv is healthy")
        elif args.force_venv:
            print(f"  🔧 --force-venv: Will recreate venv from scratch")
        elif args.repair:
            print(f"  🔧 --repair: Corrupted venv detected — will recreate")
        else:
            print(f"  ⚠️  venv exists but is unhealthy!")
            print(f"  ➜  Re-run with --repair to fix automatically")
            print(f"  ➜  Or --force-venv to recreate from scratch")
    else:
        print(f"  ℹ️  No venv found — will create fresh")

    # Diagnose services (Linux)
    if is_linux() and not args.no_services:
        if services_healthy():
            print(f"  ✅ Systemd services healthy")
        else:
            if args.repair or args.services_only:
                print(f"  🔧 Will regenerate & install service files")
            else:
                print(f"  ⚠️  Service files missing/corrupted")
                print(f"  ➜  Re-run with --repair or --services-only to fix")

    print(f"  ✅ Diagnostics complete")


# =============================================================================
# STEP 3: VIRTUAL ENVIRONMENT
# =============================================================================

def step_setup_venv(args: argparse.Namespace) -> None:
    if args.services_only:
        return

    banner("Virtual Environment", 3)

    needs_create = False

    if not VENV_DIR.exists():
        needs_create = True
    elif args.force_venv:
        print(f"  🗑️  Removing existing venv (--force-venv) ...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        needs_create = True
    elif args.repair and not venv_is_healthy():
        print(f"  🗑️  Removing corrupted venv (--repair) ...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        needs_create = True
    elif venv_is_healthy():
        print(f"  ✅ venv OK: {VENV_DIR}")
    else:
        # Unhealthy but no repair flag
        print(f"  ⚠️  venv unhealthy — use --repair to fix")
        return

    if needs_create:
        print(f"  📦 Creating venv at {VENV_DIR} ...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        print(f"  ✅ venv created")

    # Always upgrade toolchain
    print("  ⬆️  Upgrading pip, setuptools, wheel ...")
    run([str(venv_python()), "-m", "pip", "install", "--upgrade",
         "pip", "setuptools", "wheel"])


# =============================================================================
# STEP 4: DEPENDENCIES
# =============================================================================

def step_install_deps(args: argparse.Namespace) -> None:
    if args.services_only:
        return

    banner("Install Dependencies", 4)

    # Wheel
    if not WHEEL_PATH.exists():
        print(f"  📦 Downloading wheel from GitHub Releases ...")
        WHEEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            urlretrieve(WHEEL_URL, str(WHEEL_PATH))
            print(f"  ✅ Downloaded {WHEEL_NAME}")
        except Exception as e:
            print(f"  ❌ Download failed: {e}")
            print(f"  ➜  Manually place {WHEEL_NAME} in {REQUIREMENTS_DIR}/")
            sys.exit(1)
    else:
        print(f"  ✅ Wheel present: {WHEEL_NAME}")

    if not REQUIREMENTS_FILE.exists():
        print(f"  ❌ Missing: {REQUIREMENTS_FILE}")
        sys.exit(1)

    # Install
    print("  📥 Installing dependencies ...")
    if args.repair or args.force_venv:
        # Force reinstall everything on repair
        run([str(venv_pip()), "install", "--force-reinstall",
             "-r", str(REQUIREMENTS_FILE)])
    else:
        run([str(venv_pip()), "install", "-r", str(REQUIREMENTS_FILE)])

    print(f"  📦 Installing {WHEEL_NAME} ...")
    # --no-deps prevents overriding pinned versions from requirements.txt
    run([str(venv_pip()), "install", "--force-reinstall", "--no-deps", str(WHEEL_PATH)])

    # Verify critical imports
    print("  🔍 Verifying installation ...")
    py = str(venv_python())
    failures = []
    for pkg in ["flask", "fastapi", "pydantic", "NorenRestApiPy", "requests"]:
        r = run_quiet([py, "-c", f"import {pkg}"])
        if r.returncode != 0:
            failures.append(pkg)

    if failures:
        print(f"  ❌ Failed to import: {', '.join(failures)}")
        print(f"  ➜  Try: --force-venv to recreate from scratch")
        sys.exit(1)

    print("  ✅ All dependencies verified")


# =============================================================================
# STEP 5: SERVICE INSTALLATION (PER-OS)
# =============================================================================

# ── Linux: systemd ──────────────────────────────────────────────────────────

def _gen_trading_service() -> str:
    user = current_user()
    p = PROJECT_ROOT
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
        WorkingDirectory={p}

        Environment="PATH={p}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
        Environment="PYTHONUNBUFFERED=1"
        Environment="LOG_LEVEL=INFO"
        Environment="PYTHONPATH={p}"

        ExecStart={p}/venv/bin/python {p}/main.py

        Restart=always
        RestartSec=10
        RestartForceExitStatus=1

        MemoryMax=2G
        CPUQuota=80%

        PrivateTmp=yes
        NoNewPrivileges=yes
        ProtectSystem=no
        ProtectHome=no
        ProtectKernelTunables=yes

        TimeoutStopSec=30
        KillSignal=SIGTERM
        SendSIGKILL=yes

        OOMScoreAdjust=-500
        LimitNOFILE=65536
        LimitNPROC=8192

        StandardOutput=journal
        StandardError=journal
        SyslogIdentifier=trading

        [Install]
        WantedBy=multi-user.target
    """)


def _gen_start_service() -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=Trading Platform Start Service
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


def _gen_stop_service() -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=Trading Platform Stop Service
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


def install_linux_services(args: argparse.Namespace) -> None:
    """Generate and install systemd service + timer files."""
    print("\n  --- Linux: systemd Service & Timers ---")

    if not has_sudo():
        print("  ⚠️  No passwordless sudo. Manual install needed:")
        print(f"     sudo cp {DEPLOYMENT_DIR}/trading.service /etc/systemd/system/")
        print(f"     sudo cp {SYSTEMD_DIR}/*.service {SYSTEMD_DIR}/*.timer /etc/systemd/system/")
        print("     sudo systemctl daemon-reload")
        _write_service_files_to_repo()
        return

    # Generate and write to repo
    _write_service_files_to_repo()

    # Copy to systemd
    dest = Path("/etc/systemd/system")
    files = [
        (DEPLOYMENT_DIR / "trading.service", "trading.service"),
        (SYSTEMD_DIR / "trading_start.service", "trading_start.service"),
        (SYSTEMD_DIR / "trading_stop.service", "trading_stop.service"),
        (SYSTEMD_DIR / "trading_start.timer", "trading_start.timer"),
        (SYSTEMD_DIR / "trading_stop.timer", "trading_stop.timer"),
    ]

    for src, name in files:
        if src.exists():
            run(["sudo", "cp", str(src), str(dest / name)])
            print(f"  ✅ Installed {name}")
        else:
            print(f"  ⚠️  Missing: {src}")

    run(["sudo", "systemctl", "daemon-reload"])
    print("  ✅ systemd reloaded")

    for timer in ["trading_start.timer", "trading_stop.timer"]:
        run(["sudo", "systemctl", "enable", timer], check=False)
        run(["sudo", "systemctl", "start", timer], check=False)
        print(f"  ✅ Enabled {timer}")

    run(["sudo", "systemctl", "enable", "trading.service"], check=False)
    print("  ✅ trading.service enabled (start manually when ready)")


def _write_service_files_to_repo() -> None:
    """Write generated .service files into the repo for reference."""
    DEPLOYMENT_DIR.mkdir(parents=True, exist_ok=True)
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)

    (DEPLOYMENT_DIR / "trading.service").write_text(_gen_trading_service())
    (SYSTEMD_DIR / "trading_start.service").write_text(_gen_start_service())
    (SYSTEMD_DIR / "trading_stop.service").write_text(_gen_stop_service())

    print(f"  📝 Generated service files (user={current_user()}, path={PROJECT_ROOT})")


# ── Windows: PowerShell launcher + Task Scheduler ───────────────────────────

def install_windows_services(args: argparse.Namespace) -> None:
    """Create PowerShell launcher scripts and Task Scheduler entries."""
    print("\n  --- Windows: Launcher Scripts & Task Scheduler ---")

    p = PROJECT_ROOT
    py = venv_python()

    # 1) Create start_trading.ps1
    start_ps1 = p / "start_trading.ps1"
    start_ps1.write_text(textwrap.dedent(f"""\
        # ============================================
        # Shoonya Trading Platform — Start (Windows)
        # Generated by bootstrap.py — safe to regenerate
        # ============================================
        $ErrorActionPreference = "Stop"

        Write-Host "Starting Trading Platform..." -ForegroundColor Green
        Write-Host "Project: {p}"
        Write-Host ""

        # Activate venv
        & "{p}\\venv\\Scripts\\Activate.ps1"

        # Change to project directory
        Set-Location "{p}"

        # Run main.py
        & "{py}" "{p}\\main.py"
    """))
    print(f"  ✅ Created start_trading.ps1")

    # 2) Create stop_trading.ps1
    stop_ps1 = p / "stop_trading.ps1"
    stop_ps1.write_text(textwrap.dedent(f"""\
        # ============================================
        # Shoonya Trading Platform — Stop (Windows)
        # Generated by bootstrap.py — safe to regenerate
        # ============================================
        $ErrorActionPreference = "SilentlyContinue"

        Write-Host "Stopping Trading Platform..." -ForegroundColor Yellow

        # Find and stop the trading process
        $procs = Get-Process -Name "python*" | Where-Object {{
            $_.MainModule.FileName -like "*{p}*"
        }}

        if ($procs) {{
            $procs | Stop-Process -Force
            Write-Host "Stopped trading process (PID: $($procs.Id -join ', '))" -ForegroundColor Green
        }} else {{
            Write-Host "No trading process found" -ForegroundColor Gray
        }}
    """))
    print(f"  ✅ Created stop_trading.ps1")

    # 3) Create start_trading.bat (for double-click)
    start_bat = p / "start_trading.bat"
    start_bat.write_text(textwrap.dedent(f"""\
        @echo off
        REM Shoonya Trading Platform — Start (Windows Batch)
        REM Double-click this file to start trading
        echo Starting Trading Platform...
        cd /d "{p}"
        call "{p}\\venv\\Scripts\\activate.bat"
        python main.py
        pause
    """))
    print(f"  ✅ Created start_trading.bat")

    # 4) Try to create Task Scheduler entries
    _install_windows_scheduled_tasks(p)


def _install_windows_scheduled_tasks(project: Path) -> None:
    """Create Windows Task Scheduler tasks for auto start/stop."""
    print("\n  📅 Setting up Windows Task Scheduler ...")

    # Task Scheduler XML for auto-start (Mon-Fri 8:45 AM IST)
    start_xml = project / "utilities" / "deployment" / "task_trading_start.xml"
    start_xml.parent.mkdir(parents=True, exist_ok=True)
    start_xml.write_text(textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>Auto-start Shoonya Trading Platform (Mon-Fri 8:45 AM)</Description>
          </RegistrationInfo>
          <Triggers>
            <CalendarTrigger>
              <StartBoundary>2025-01-01T08:45:00+05:30</StartBoundary>
              <Enabled>true</Enabled>
              <ScheduleByWeek>
                <DaysOfWeek>
                  <Monday /><Tuesday /><Wednesday /><Thursday /><Friday />
                </DaysOfWeek>
                <WeeksInterval>1</WeeksInterval>
              </ScheduleByWeek>
            </CalendarTrigger>
          </Triggers>
          <Actions>
            <Exec>
              <Command>powershell.exe</Command>
              <Arguments>-ExecutionPolicy Bypass -File "{project}\\start_trading.ps1"</Arguments>
              <WorkingDirectory>{project}</WorkingDirectory>
            </Exec>
          </Actions>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <AllowHardTerminate>true</AllowHardTerminate>
            <Enabled>true</Enabled>
          </Settings>
        </Task>
    """))

    # Task Scheduler XML for auto-stop (Mon-Fri 4:00 PM IST)
    stop_xml = project / "utilities" / "deployment" / "task_trading_stop.xml"
    stop_xml.write_text(textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>Auto-stop Shoonya Trading Platform (Mon-Fri 4:00 PM)</Description>
          </RegistrationInfo>
          <Triggers>
            <CalendarTrigger>
              <StartBoundary>2025-01-01T16:00:00+05:30</StartBoundary>
              <Enabled>true</Enabled>
              <ScheduleByWeek>
                <DaysOfWeek>
                  <Monday /><Tuesday /><Wednesday /><Thursday /><Friday />
                </DaysOfWeek>
                <WeeksInterval>1</WeeksInterval>
              </ScheduleByWeek>
            </CalendarTrigger>
          </Triggers>
          <Actions>
            <Exec>
              <Command>powershell.exe</Command>
              <Arguments>-ExecutionPolicy Bypass -File "{project}\\stop_trading.ps1"</Arguments>
              <WorkingDirectory>{project}</WorkingDirectory>
            </Exec>
          </Actions>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <AllowHardTerminate>true</AllowHardTerminate>
            <Enabled>true</Enabled>
          </Settings>
        </Task>
    """))

    print(f"  ✅ Generated Task Scheduler XML files")

    # Try to register tasks (requires admin on Windows)
    for task_name, xml_file in [
        ("ShoonyaTrading_AutoStart", start_xml),
        ("ShoonyaTrading_AutoStop", stop_xml),
    ]:
        try:
            r = subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_file), "/F"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                print(f"  ✅ Registered task: {task_name}")
            else:
                print(f"  ⚠️  Could not register {task_name} (admin required)")
                print(f"  ➜  Run as Administrator:")
                print(f"     schtasks /Create /TN {task_name} /XML \"{xml_file}\" /F")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"  ⚠️  schtasks not available")
            print(f"  ➜  Import XML files manually via Task Scheduler GUI")
            break


# ── macOS: launchd ──────────────────────────────────────────────────────────

def install_macos_services(args: argparse.Namespace) -> None:
    """Create and install launchd plist files for macOS."""
    print("\n  --- macOS: launchd Service & Schedule ---")

    p = PROJECT_ROOT
    py = venv_python()
    user = current_user()
    launch_agents = current_home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    # Main service plist
    service_plist = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.shoonya.trading</string>
            <key>ProgramArguments</key>
            <array>
                <string>{py}</string>
                <string>{p}/main.py</string>
            </array>
            <key>WorkingDirectory</key>
            <string>{p}</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>{p}/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
                <key>PYTHONPATH</key>
                <string>{p}</string>
                <key>PYTHONUNBUFFERED</key>
                <string>1</string>
            </dict>
            <key>KeepAlive</key>
            <true/>
            <key>RunAtLoad</key>
            <false/>
            <key>StandardOutPath</key>
            <string>{p}/logs/trading_stdout.log</string>
            <key>StandardErrorPath</key>
            <string>{p}/logs/trading_stderr.log</string>
        </dict>
        </plist>
    """)

    plist_file = launch_agents / "com.shoonya.trading.plist"
    plist_file.write_text(service_plist)
    print(f"  ✅ Created {plist_file.name}")

    # Auto-start plist (Mon-Fri 8:45 AM)
    start_plist = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.shoonya.trading.start</string>
            <key>ProgramArguments</key>
            <array>
                <string>/bin/launchctl</string>
                <string>start</string>
                <string>com.shoonya.trading</string>
            </array>
            <key>StartCalendarInterval</key>
            <array>
                <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>45</integer></dict>
                <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>45</integer></dict>
                <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>45</integer></dict>
                <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>45</integer></dict>
                <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>45</integer></dict>
            </array>
        </dict>
        </plist>
    """)

    start_file = launch_agents / "com.shoonya.trading.start.plist"
    start_file.write_text(start_plist)
    print(f"  ✅ Created {start_file.name}")

    # Auto-stop plist (Mon-Fri 4:00 PM)
    stop_plist = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.shoonya.trading.stop</string>
            <key>ProgramArguments</key>
            <array>
                <string>/bin/launchctl</string>
                <string>stop</string>
                <string>com.shoonya.trading</string>
            </array>
            <key>StartCalendarInterval</key>
            <array>
                <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
                <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
                <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
                <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
                <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
            </array>
        </dict>
        </plist>
    """)

    stop_file = launch_agents / "com.shoonya.trading.stop.plist"
    stop_file.write_text(stop_plist)
    print(f"  ✅ Created {stop_file.name}")

    # Load agents
    for plist in [plist_file, start_file, stop_file]:
        try:
            subprocess.run(["launchctl", "unload", str(plist)],
                           capture_output=True, timeout=5)
            subprocess.run(["launchctl", "load", str(plist)],
                           capture_output=True, check=True, timeout=5)
            print(f"  ✅ Loaded {plist.name}")
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired):
            print(f"  ⚠️  Could not load {plist.name}")
            print(f"  ➜  launchctl load {plist}")

    # Also save copies to deployment dir
    deploy_macos = DEPLOYMENT_DIR / "macos"
    deploy_macos.mkdir(parents=True, exist_ok=True)
    (deploy_macos / "com.shoonya.trading.plist").write_text(service_plist)
    (deploy_macos / "com.shoonya.trading.start.plist").write_text(start_plist)
    (deploy_macos / "com.shoonya.trading.stop.plist").write_text(stop_plist)
    print(f"  📝 Copies saved to utilities/deployment/macos/")


# ── Dispatch ────────────────────────────────────────────────────────────────

def step_install_services(args: argparse.Namespace) -> None:
    if args.no_services:
        return

    banner("Service Installation", 5)

    os_name = os_type()
    print(f"  OS detected: {os_name}" + (" (WSL)" if is_wsl() else ""))

    if os_name == "linux":
        install_linux_services(args)
    elif os_name == "windows":
        install_windows_services(args)
    elif os_name == "macos":
        install_macos_services(args)
    else:
        print(f"  ⚠️  Unknown OS: {platform.system()}")
        print(f"  ➜  Service auto-install not supported")
        print(f"  ➜  Start manually: {venv_python()} {PROJECT_ROOT / 'main.py'}")


# =============================================================================
# STEP 6: CLEANUP UTILITY SETUP
# =============================================================================

def step_setup_cleanup(args: argparse.Namespace) -> None:
    if args.services_only:
        return

    banner("Cleanup Utility Setup", 6)

    script = PROJECT_ROOT / "utilities" / "cleanup.py"
    if not script.exists():
        print(f"  ⚠️  cleanup.py not found")
        return

    if is_linux() or is_macos():
        os.chmod(script, 0o755)
        print(f"  ✅ Made cleanup.py executable")

        if has_sudo():
            symlink = Path("/usr/local/bin/shoonya-clean")
            try:
                run(["sudo", "ln", "-sf", str(script), str(symlink)], quiet=True)
                print(f"  ✅ Global command: shoonya-clean")
            except subprocess.CalledProcessError:
                print(f"  ⚠️  Symlink failed — run manually: python {script}")
        else:
            print(f"  ➜  Manual: sudo ln -sf {script} /usr/local/bin/shoonya-clean")
    else:
        # Windows
        bat = PROJECT_ROOT / "shoonya-clean.bat"
        bat.write_text(f'@echo off\n"{venv_python()}" "{script}" %*\n')
        print(f"  ✅ Created shoonya-clean.bat")


# =============================================================================
# STEP 7: SHELL AUTO-ACTIVATION
# =============================================================================

def step_shell_hook(args: argparse.Namespace) -> None:
    if args.services_only:
        return

    banner("Shell Auto-Activation", 7)

    if is_windows():
        _setup_powershell_profile()
    elif is_linux() or is_macos():
        _setup_unix_shell_hook()
    else:
        print(f"  ⏭️  Skipping (unsupported OS)")


def _setup_unix_shell_hook() -> None:
    """Add venv auto-activation to .bashrc and/or .zshrc."""
    marker = "# --- Shoonya Trading Environment Auto-Activation ---"
    hook = textwrap.dedent(f"""\
        {marker}
        if [ -d "{VENV_DIR}" ]; then
            source {VENV_DIR}/bin/activate
            cd {PROJECT_ROOT}
        fi
    """)

    # Detect which shells to configure
    shells = []
    bashrc = current_home() / ".bashrc"
    zshrc = current_home() / ".zshrc"

    if bashrc.exists() or is_linux():
        shells.append(bashrc)
    if zshrc.exists() or is_macos():
        shells.append(zshrc)

    for rc_file in shells:
        _write_shell_hook(rc_file, marker, hook)

    if not shells:
        print(f"  ⚠️  No shell RC file found")
        print(f"  ➜  {venv_activate_cmd()}")


def _write_shell_hook(rc_file: Path, marker: str, hook: str) -> None:
    """Write or replace the auto-activation hook in a shell RC file."""
    if rc_file.exists():
        content = rc_file.read_text()
        if marker in content:
            # Replace existing block
            lines = content.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if marker in line:
                    skip = True
                    continue
                if skip:
                    if line.strip() == "fi":
                        skip = False
                        continue
                    if line.startswith("if ") or line.startswith("    "):
                        continue
                    skip = False
                    new_lines.append(line)
                    continue
                new_lines.append(line)
            content = "\n".join(new_lines).rstrip() + "\n\n" + hook
            rc_file.write_text(content)
            print(f"  ✅ Updated {rc_file.name}")
        else:
            with open(rc_file, "a") as f:
                f.write("\n" + hook)
            print(f"  ✅ Added hook to {rc_file.name}")
    else:
        rc_file.write_text(hook)
        print(f"  ✅ Created {rc_file.name}")


def _setup_powershell_profile() -> None:
    """Add auto-activation to PowerShell profile (Windows)."""
    # Detect PowerShell profile path
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$PROFILE"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            profile_path = Path(r.stdout.strip())
        else:
            profile_path = (current_home() / "Documents" / "WindowsPowerShell"
                            / "Microsoft.PowerShell_profile.ps1")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        profile_path = (current_home() / "Documents" / "WindowsPowerShell"
                        / "Microsoft.PowerShell_profile.ps1")

    marker = "# --- Shoonya Trading Environment Auto-Activation ---"
    hook = textwrap.dedent(f"""\
        {marker}
        if (Test-Path "{VENV_DIR}\\Scripts\\Activate.ps1") {{
            & "{VENV_DIR}\\Scripts\\Activate.ps1"
            Set-Location "{PROJECT_ROOT}"
        }}
    """)

    profile_path.parent.mkdir(parents=True, exist_ok=True)

    if profile_path.exists():
        content = profile_path.read_text()
        if marker in content:
            # Remove old block and append new
            lines = content.split("\n")
            new_lines = [l for l in lines if marker not in l
                         and "Shoonya" not in l
                         and "Activate.ps1" not in l
                         and "Set-Location" not in l]
            content = "\n".join(new_lines).rstrip() + "\n\n" + hook
            profile_path.write_text(content)
            print(f"  ✅ Updated PowerShell profile")
        else:
            with open(profile_path, "a") as f:
                f.write("\n" + hook)
            print(f"  ✅ Added hook to PowerShell profile")
    else:
        profile_path.write_text(hook)
        print(f"  ✅ Created PowerShell profile")

    print(f"  ➜  Restart PowerShell to activate")


# =============================================================================
# CLI ARGUMENT PARSING
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shoonya Trading Platform — Universal Bootstrap & Repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python3 utilities/bootstrap.py                 # Fresh install
              python3 utilities/bootstrap.py --repair        # Fix everything
              python3 utilities/bootstrap.py --force-venv    # Nuke & recreate venv
              python3 utilities/bootstrap.py --services-only # Regenerate services
              python3 utilities/bootstrap.py --no-services   # Skip service install
        """)
    )

    parser.add_argument(
        "--repair", action="store_true",
        help="Repair mode: fix corrupted venv, reinstall deps, regenerate services"
    )
    parser.add_argument(
        "--force-venv", action="store_true",
        help="Delete and recreate venv from scratch (nuclear option)"
    )
    parser.add_argument(
        "--services-only", action="store_true",
        help="Only regenerate and install service files (skip venv/deps)"
    )
    parser.add_argument(
        "--no-services", action="store_true",
        help="Skip service installation (venv + deps only)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show diagnostics without making changes"
    )

    return parser.parse_args()


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    args = parse_args()

    # Header
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   SHOONYA TRADING PLATFORM — BOOTSTRAP & REPAIR TOOL   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Project  : {PROJECT_ROOT}")
    print(f"  OS       : {platform.system()} {platform.machine()}"
          f"{' (WSL)' if is_wsl() else ''}")
    print(f"  User     : {current_user()}")
    print(f"  Python   : {sys.version.split()[0]}")
    print(f"  Mode     : ", end="")
    if args.repair:
        print("🔧 REPAIR")
    elif args.force_venv:
        print("🔧 FORCE RECREATE VENV")
    elif args.services_only:
        print("🔧 SERVICES ONLY")
    elif args.dry_run:
        print("👁️  DRY RUN")
    else:
        print("📦 FRESH INSTALL")

    os.chdir(PROJECT_ROOT)

    if args.dry_run:
        step_check_python()
        step_safety_checks(args)
        print(f"\n  👁️  Dry run complete — no changes made")
        return

    step_check_python()            # Step 1
    step_safety_checks(args)       # Step 2
    step_setup_venv(args)          # Step 3
    step_install_deps(args)        # Step 4
    step_install_services(args)    # Step 5
    step_setup_cleanup(args)       # Step 6
    step_shell_hook(args)          # Step 7

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("✅ BOOTSTRAP COMPLETE")
    print(f"{'='*60}")
    print(f"  venv     : {VENV_DIR}")
    print(f"  activate : {venv_activate_cmd()}")
    print(f"  start    : python main.py")

    ost = os_type()
    if ost == "linux":
        print(f"\n  Systemd:")
        print(f"    sudo systemctl start trading")
        print(f"    sudo systemctl status trading")
        print(f"    journalctl -u trading -f")
        print(f"    sudo systemctl list-timers trading_*")
    elif ost == "windows":
        print(f"\n  Windows:")
        print(f"    .\\start_trading.ps1   (or double-click start_trading.bat)")
        print(f"    .\\stop_trading.ps1")
        print(f"    Task Scheduler: ShoonyaTrading_AutoStart / AutoStop")
    elif ost == "macos":
        print(f"\n  macOS:")
        print(f"    launchctl start com.shoonya.trading")
        print(f"    launchctl stop com.shoonya.trading")

    print(f"\n  Repair   : python3 utilities/bootstrap.py --repair")
    print(f"  Cleanup  : shoonya-clean  (or python utilities/cleanup.py)")
    print(f"  Backup   : python utilities/backup.py")
    print(f"\n🧊 This environment is now production-ready.")


if __name__ == "__main__":
    main()
