#!/usr/bin/env python3
"""
run_strategy.py — Standalone Fresh Strategy Launcher
=====================================================

Runs the fresh_strategy independently of main.py.
Communicates with the trading service via HTTP POST to /webhook.

Usage:
    python run_strategy.py                          # uses example_strategy.json
    python run_strategy.py path/to/my_config.json   # custom config

Environment:
    WEBHOOK_URL  — override webhook target (default: http://127.0.0.1:5000/webhook)
"""

import sys
import os
import signal
import logging
import argparse
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from shoonya_platform.fresh_strategy.runner import FreshStrategyRunner


def setup_logging():
    """Configure console logging."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    parser = argparse.ArgumentParser(description="Fresh Strategy Runner (standalone)")
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to strategy JSON config (default: example_strategy.json)",
    )
    parser.add_argument(
        "--webhook-url",
        default=None,
        help="Override webhook URL (default: http://127.0.0.1:5000/webhook)",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("run_strategy")

    # Resolve config path
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = (
            PROJECT_ROOT
            / "shoonya_platform"
            / "fresh_strategy"
            / "example_strategy.json"
        )

    if not config_path.exists():
        logger.error(f"Config not found: {config_path}")
        sys.exit(1)

    # Set webhook URL if provided
    if args.webhook_url:
        os.environ["WEBHOOK_URL"] = args.webhook_url

    webhook_url = os.environ.get("WEBHOOK_URL", "http://127.0.0.1:5000/webhook")
    logger.info(f"Config : {config_path}")
    logger.info(f"Webhook: {webhook_url}")
    logger.info("=" * 60)

    # Create runner
    runner = FreshStrategyRunner(str(config_path), test_mode=False)

    # Graceful shutdown on Ctrl+C / SIGTERM
    def _shutdown(sig, frame):
        logger.info("Shutdown signal received — stopping strategy")
        runner.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Start (blocking)
    runner.start()

    logger.info("Strategy runner exited.")


if __name__ == "__main__":
    main()
