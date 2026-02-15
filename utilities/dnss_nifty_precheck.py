#!/usr/bin/env python3
"""
DNSS NIFTY pre-flight checks for strategy_runner architecture.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from shoonya_platform.strategy_runner.config_schema import validate_config_file


def check_config_file():
    config_path = Path("shoonya_platform/strategy_runner/saved_configs/dnss_nifty.json")
    if not config_path.exists():
        return False, f"Config file not found: {config_path}"

    is_valid, issues, _ = validate_config_file(str(config_path))
    if not is_valid:
        errors = [f"{i.path}: {i.message}" for i in issues if i.severity == "error"]
        return False, f"Config validation failed: {errors}"
    return True, f"Config file valid: {config_path}"


def check_database():
    db_path = Path("shoonya_platform/market_data/option_chain/data/option_chain.db")
    if not db_path.exists():
        return False, f"Option-chain DB not found: {db_path}"
    return True, f"Database found: {db_path}"


def check_environment():
    env_path = Path("config_env/primary.env")
    if not env_path.exists():
        return False, f"Environment file not found: {env_path}"
    return True, f"Environment file present: {env_path}"


def check_executor_modules():
    required = [
        Path("shoonya_platform/strategy_runner/strategy_executor_service.py"),
        Path("shoonya_platform/strategy_runner/config_schema.py"),
        Path("shoonya_platform/strategy_runner/condition_engine.py"),
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        return False, f"Missing modules: {missing}"
    return True, "Strategy runner modules are present"


def print_summary(results):
    print("\n" + "=" * 70)
    print("DNSS NIFTY PRE-FLIGHT CHECK (strategy_runner)")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")

    passed = sum(1 for success, _ in results.values() if success)
    total = len(results)
    for check_name, (success, message) in results.items():
        print(f"{check_name:30} -> {message}")

    print("\n" + "=" * 70)
    print(f"RESULT: {passed}/{total} checks passed")
    if passed == total:
        print("\nAll checks passed. Start service with:")
        print("  python main.py")
        print("Then register/start strategy via dashboard runner endpoints.")
        return 0
    print(f"\n{total - passed} checks failed.")
    return 1


def main():
    results = {
        "Config File": check_config_file(),
        "SQLite Database": check_database(),
        "Environment": check_environment(),
        "Executor Modules": check_executor_modules(),
    }
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
