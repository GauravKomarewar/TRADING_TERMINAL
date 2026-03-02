#!/usr/bin/env python3
"""
MASTER ACCOUNT MANAGER — ENTRY POINT
======================================

Master account manager service.

Usage:
    python master_manager.py --env config_env/master.env

What it does:
  1. Loads master configuration from env file
  2. Initialises client registry (JSON-backed)
  3. Starts background health poller
  4. Serves the FastAPI control/dashboard app via uvicorn

Ports (from master.env):
  MASTER_PORT           → REST API + admin login  (default 9000)
  MASTER_DASHBOARD_PORT → Dashboard UI            (same process! different bind option)

For simplicity both the REST API and dashboard UI are served on MASTER_PORT.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Ensure project root is on sys.path so `master.*` imports work
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from master.registry import MasterRegistry
from master.poller import HealthPoller
from master.api import create_master_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MASTER] %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("master_manager")


def parse_int_env(name: str, default: int, min_val=None, max_val=None) -> int:
    """Parse an integer environment variable with a helpful error message."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name}={raw!r} is not a valid integer"
        )
    if min_val is not None and value < min_val:
        raise ValueError(
            f"Environment variable {name}={value} is below minimum {min_val}"
        )
    if max_val is not None and value > max_val:
        raise ValueError(
            f"Environment variable {name}={value} exceeds maximum {max_val}"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Shoonya Master Account Manager")
    parser.add_argument(
        "--env",
        default="config_env/master.env",
        help="Path to master env file (default: config_env/master.env)",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------
    env_path = Path(args.env)
    if not env_path.is_absolute():
        env_path = ROOT / env_path

    if env_path.exists():
        load_dotenv(env_path)
        logger.info("Master config loaded from: %s", env_path)
    else:
        logger.warning("Env file not found: %s — using environment defaults", env_path)

    host = os.getenv("MASTER_HOST", "0.0.0.0")
    port = parse_int_env("MASTER_PORT", 9000, min_val=1, max_val=65535)
    registry_file = os.getenv(
        "MASTER_REGISTRY_FILE",
        str(ROOT / "config_env" / "master_clients.json"),
    )
    poll_interval = parse_int_env("MASTER_HEALTH_POLL_INTERVAL", 30, min_val=5)
    auto_block_misses = parse_int_env("MASTER_AUTO_BLOCK_MISSED_POLLS", 3, min_val=1)

    # ------------------------------------------------------------------
    # Registry + Poller
    # ------------------------------------------------------------------
    logger.info("Loading client registry: %s", registry_file)
    registry = MasterRegistry(registry_file)

    poller = HealthPoller(
        registry=registry,
        poll_interval_s=poll_interval,
        auto_block_misses=auto_block_misses,
    )
    poller.start()

    # ------------------------------------------------------------------
    # FastAPI app
    # ------------------------------------------------------------------
    app = create_master_app(registry, poller)

    logger.info("=" * 60)
    logger.info("🛡️  Shoonya Master Account Manager")
    logger.info("   Host         : %s", host)
    logger.info("   Port         : %d", port)
    logger.info("   Dashboard    : http://%s:%d/", host, port)
    logger.info("   API docs     : http://%s:%d/api/docs", host, port)
    logger.info("   Registry     : %s", registry_file)
    logger.info("   Health poll  : every %ds (auto-block after %d misses)", poll_interval, auto_block_misses)
    logger.info("=" * 60)

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=True,
        )
    finally:
        logger.info("Master manager shutting down — stopping health poller")
        poller.stop()


if __name__ == "__main__":
    main()
