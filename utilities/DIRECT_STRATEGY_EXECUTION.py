#!/usr/bin/env python3
"""
Direct strategy_runner execution helper.

This utility replaces legacy direct execution from the old strategy package.
"""

import argparse
import json
from pathlib import Path

from shoonya_platform.strategy_runner.config_schema import validate_config_file


def main():
    parser = argparse.ArgumentParser(description="Validate and stage a strategy_runner config")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to strategy JSON config",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    ok, issues, config = validate_config_file(str(config_path))
    if not ok:
        for issue in issues:
            if issue.severity == "error":
                print(f"ERROR {issue.path}: {issue.message}")
        raise SystemExit("Validation failed")

    saved_dir = Path("shoonya_platform/strategy_runner/saved_configs")
    saved_dir.mkdir(parents=True, exist_ok=True)
    dest = saved_dir / config_path.name
    dest.write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(f"Validated and copied: {dest}")
    print("Start service: python main.py")
    print("Then start strategy from dashboard endpoint:")
    print(f"  POST /dashboard/strategy/{dest.stem}/start-execution")


if __name__ == "__main__":
    main()
