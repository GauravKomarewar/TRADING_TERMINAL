#!/usr/bin/env python3
"""
Simple strategy_runner smoke script.

Legacy simple strategy standalone module was part of the removed strategies folder.
This script now validates a strategy_runner config file and exits.
"""

from pathlib import Path

from shoonya_platform.strategy_runner.config_schema import validate_config_file


def main():
    cfg = Path("shoonya_platform/strategy_runner/saved_configs/simple_test_nifty.json")
    if not cfg.exists():
        print(f"Config not found: {cfg}")
        print("Create a JSON config under shoonya_platform/strategy_runner/saved_configs/")
        return 1

    ok, issues, _ = validate_config_file(str(cfg))
    if not ok:
        print("Validation failed:")
        for issue in issues:
            if issue.severity == "error":
                print(f"  - {issue.path}: {issue.message}")
        return 2

    print("Config is valid for strategy_runner.")
    print("Start service with: python main.py")
    print(f"Then start strategy: POST /dashboard/strategy/{cfg.stem}/start-execution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
