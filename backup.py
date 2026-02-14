#!/usr/bin/env python3
"""
Shoonya Platform Backup Script
--------------------------------
• Must be placed inside project root (shoonya_platform/)
• Creates ZIP outside project root
• Filename reflects whether config_env is included
• Skips venv, __pycache__, temp, *.pyc, *.pyo, *.tmp
"""

import os
import sys
import zipfile
from datetime import datetime


# ===============================
# 📁 Paths
# ===============================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(PROJECT_ROOT)  # ZIP will be created here


# ===============================
# 📦 Skip Rules
# ===============================

def should_skip(path, skip_config_env):
    skip_dirs = ["venv", "__pycache__", "temp"]

    if skip_config_env:
        skip_dirs.append("config_env")

    for skip_dir in skip_dirs:
        if f"{os.sep}{skip_dir}" in path:
            return True

    if path.endswith((".pyc", ".pyo", ".tmp")):
        return True

    return False


# ===============================
# 🚀 Backup Logic
# ===============================

def create_backup(skip_config_env):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if skip_config_env:
        suffix = "no_config"
    else:
        suffix = "with_config"

    backup_name = f"shoonya_platform_backup_{suffix}_{timestamp}.zip"
    backup_path = os.path.join(PARENT_DIR, backup_name)

    print("\n📦 Creating backup...")
    print(f"📁 Project Root: {PROJECT_ROOT}")
    print(f"📦 Output File : {backup_name}")
    print("--------------------------------------------------")

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_ROOT):

            # Prevent walking into skipped directories
            dirs[:] = [
                d for d in dirs
                if not should_skip(os.path.join(root, d), skip_config_env)
            ]

            for file in files:
                full_path = os.path.join(root, file)

                if should_skip(full_path, skip_config_env):
                    continue

                relative_path = os.path.relpath(full_path, PARENT_DIR)
                zipf.write(full_path, relative_path)

    print("✅ Backup completed successfully.")
    print(f"📦 Saved at: {backup_path}\n")


# ===============================
# 🧠 Main
# ===============================

if __name__ == "__main__":

    print("\nShoonya Platform Backup Utility")
    print("================================")

    choice = input("\nInclude config_env in backup? (y/n): ").strip().lower()

    if choice not in ["y", "n"]:
        print("Invalid input. Please enter y or n.")
        sys.exit(1)

    skip_config_env = False if choice == "y" else True

    create_backup(skip_config_env)
