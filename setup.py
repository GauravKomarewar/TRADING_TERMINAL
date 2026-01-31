import os
import sys
import subprocess
import platform
from pathlib import Path

# ===============================
# CONFIG
# ===============================
VENV_DIR = "venv"
REQUIREMENTS_FILE = Path("requirements") / "requirements.txt"
ALLOWED_VERSIONS = [(3, 9), (3, 10)]

# ===============================
# HELPERS
# ===============================
def run(cmd, shell=False):
    print(f"▶ {cmd}")
    subprocess.check_call(cmd, shell=shell)

def python_version_ok():
    return sys.version_info[:2] in ALLOWED_VERSIONS

def is_windows():
    return platform.system().lower() == "windows"

# ===============================
# MAIN
# ===============================
def main():
    project_dir = Path(__file__).resolve().parent
    os.chdir(project_dir)

    print(f"📂 Project directory: {project_dir}")
    
    if os.environ.get("VIRTUAL_ENV"):
        print("❌ Do not run setup.py inside an active virtual environment")
        sys.exit(1)

    # ---- Python version check ----
    if not python_version_ok():
        print("❌ Unsupported Python version!")
        print(f"👉 Detected: {sys.version.split()[0]}")
        print("👉 Required: Python 3.9 or 3.10")
        sys.exit(1)

    print(f"🐍 Python version OK: {sys.version.split()[0]}")

    # ---- Create venv ----
    if not Path(VENV_DIR).exists():
        print("🐍 Creating virtual environment...")
        run([sys.executable, "-m", "venv", VENV_DIR])
    else:
        print("ℹ️ Virtual environment already exists")

    # ---- Activate paths ----
    if is_windows():
        pip = Path(VENV_DIR) / "Scripts" / "pip.exe"
        activate_hint = f"{VENV_DIR}\\Scripts\\Activate.ps1"
    else:
        pip = Path(VENV_DIR) / "bin" / "pip"
        activate_hint = f"source {VENV_DIR}/bin/activate"

    # ---- Upgrade pip ----
    print("⬆️ Upgrading pip...")
    run([str(pip), "install", "--upgrade", "pip", "setuptools", "wheel"])

    # ---- Install requirements ----
    if not REQUIREMENTS_FILE.exists():
        print(f"❌ Missing {REQUIREMENTS_FILE}")
        sys.exit(1)

    print("📥 Installing dependencies...")
    run([str(pip), "install", "-r", str(REQUIREMENTS_FILE)])

    print("\n✅ Setup complete!")
    print(f"👉 Activate environment with:\n   {activate_hint}")

if __name__ == "__main__":
    main()
