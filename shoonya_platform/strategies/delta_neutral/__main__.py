#!/usr/bin/env python3
"""
DNSS Standalone Execution
==========================
Allows running Delta Neutral Short Strangle strategy directly from command line
with a configuration file, without going through the dashboard.

Usage:
  python -m shoonya_platform.strategies.delta_neutral --config /path/to/config.json
  python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_nifty_weekly.json

Requirements:
  - config_env/primary.env must be set up with broker credentials
  - Market data source must be available (SQLite DB or market feed)
"""

from __future__ import annotations
import argparse
import json
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, time as dt_time
from typing import Optional

# Local imports
from .dnss import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig as DnssStrategyConfig,
)

# Market integration
from shoonya_platform.execution.db_market import DBBackedMarket

# Config
from shoonya_platform.core.config import Config

# Logging
logging.basicConfig(
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
)
logger = logging.getLogger("DNSS_STANDALONE")


# ============================================================
# CONFIG CONVERSION
# ============================================================

def convert_dashboard_config_to_execution(config: dict) -> dict:
    """
    Convert dashboard strategy config (from saved JSON) to execution-compatible format
    
    Maps dashboard schema keys to execution schema keys
    """
    identity = config.get("identity", {})
    entry = config.get("entry", {})
    adjustment = config.get("adjustment", {})
    rms = config.get("rms", {})
    
    # Extract core parameters
    return {
        "strategy_name": config.get("name", config.get("id", "DNSS_UNNAMED")),
        "strategy_version": config.get("schema_version", "1.0.0"),
        "exchange": identity.get("exchange", "NFO"),
        "symbol": identity.get("underlying", "NIFTY"),
        "instrument_type": identity.get("instrument_type", "OPTIDX"),
        
        # Timing
        "entry_time": entry.get("timing", {}).get("entry_time", "09:20"),
        "exit_time": entry.get("timing", {}).get("exit_time", "15:15") or config.get("exit", {}).get("time", {}).get("exit_time", "15:15"),
        
        # Execution
        "order_type": identity.get("order_type", "LIMIT"),
        "product": identity.get("product_type", "NRML"),
        "lot_qty": entry.get("position", {}).get("lots", 1),
        
        # Risk & params
        "params": {
            "target_entry_delta": entry.get("legs", {}).get("target_entry_delta", 0.20),
            "delta_adjust_trigger": adjustment.get("delta", {}).get("trigger", 0.50),
            "max_leg_delta": adjustment.get("leg_level", {}).get("per_leg_delta_max", 0.65),
            "profit_step": adjustment.get("pnl", {}).get("profit_lock_trigger", 1500),
            "cooldown_seconds": adjustment.get("general", {}).get("cooldown_seconds", 0),
        },
        
        # Market data expiry
        "expiry_mode": identity.get("expiry_mode", "weekly_current"),
        "expiry_custom": identity.get("expiry_custom"),
    }


def validate_config(execution_config: dict) -> bool:
    """Validate that all required fields are present"""
    required = [
        "strategy_name",
        "exchange",
        "symbol",
        "instrument_type",
        "entry_time",
        "exit_time",
        "order_type",
        "product",
        "lot_qty",
        "params",
    ]
    
    missing = [f for f in required if f not in execution_config or execution_config[f] is None]
    
    if missing:
        logger.error(f"❌ Missing required fields: {missing}")
        return False
    
    return True


def parse_time(time_str: str) -> dt_time:
    """Parse time string HH:MM to datetime.time"""
    try:
        h, m = map(int, time_str.split(":"))
        return dt_time(h, m)
    except (ValueError, IndexError):
        raise ValueError(f"Invalid time format: {time_str}. Use HH:MM")


# ============================================================
# STANDALONE RUNNER
# ============================================================

class DNSSStandaloneRunner:
    """Simple standalone runner for DNSS strategy"""
    
    def __init__(self, config_path: str, poll_interval: float = 2.0):
        """
        Initialize standalone runner
        
        Args:
            config_path: Path to strategy config JSON
            poll_interval: Polling interval in seconds
        """
        self.config_path = Path(config_path)
        self.poll_interval = poll_interval
        
        self.strategy: Optional[DeltaNeutralShortStrangleStrategy] = None
        self.market: Optional[DBBackedMarket] = None
        self.execution_config: Optional[dict] = None
        
        self._tick_count = 0
        self._error_count = 0
        self._running = False
    
    def load_config(self) -> bool:
        """Load and validate config from JSON file"""
        logger.info(f"📂 Loading config from: {self.config_path}")
        
        if not self.config_path.exists():
            logger.error(f"❌ Config file not found: {self.config_path}")
            return False
        
        try:
            with open(self.config_path, "r") as f:
                dashboard_config = json.load(f)
            
            logger.info(f"✅ Config loaded: {dashboard_config.get('name', 'UNNAMED')}")
            
            # Convert to execution format
            self.execution_config = convert_dashboard_config_to_execution(dashboard_config)
            
            # Validate
            if not validate_config(self.execution_config):
                return False
            
            logger.info(f"✅ Config validated | {self.execution_config['symbol']} | "
                       f"Entry: {self.execution_config['entry_time']} | "
                       f"Exit: {self.execution_config['exit_time']}")
            
            return True
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to load config: {e}")
            return False
    
    def initialize(self) -> bool:
        """Initialize market and strategy instances"""
        logger.info("🔧 Initializing market and strategy...")
        
        try:
            # Ensure config loaded
            if not self.execution_config:
                if not self.load_config():
                    return False
            
            cfg = self.execution_config
            assert cfg is not None  # Type guard for type checking
            
            # 1️⃣ Get database path
            db_path = str(
                Path(__file__).resolve().parents[3]
                / "shoonya_platform"
                / "market_data"
                / "option_chain"
                / "data"
                / "option_chain.db"
            )
            
            # 2️⃣ Initialize market data provider
            logger.info(f"📊 Creating DBBackedMarket | {cfg['exchange']} {cfg['symbol']}")
            self.market = DBBackedMarket(
                db_path=db_path,
                exchange=cfg['exchange'],
                symbol=cfg['symbol'],
            )
            
            # 3️⃣ Get expiry from database or use from config
            # For now, use from config or a reasonable default
            expiry = cfg.get('expiry_custom') or self._get_current_expiry(cfg['expiry_mode'])
            
            # 4️⃣ Create strategy config
            dnss_config = DnssStrategyConfig(
                entry_time=parse_time(cfg['entry_time']),
                exit_time=parse_time(cfg['exit_time']),
                
                target_entry_delta=float(cfg['params'].get('target_entry_delta', 0.20)),
                delta_adjust_trigger=float(cfg['params'].get('delta_adjust_trigger', 0.50)),
                max_leg_delta=float(cfg['params'].get('max_leg_delta', 0.65)),
                
                profit_step=float(cfg['params'].get('profit_step', 1500)),
                cooldown_seconds=int(cfg['params'].get('cooldown_seconds', 0)),
                lot_qty=int(cfg['lot_qty']),
                
                order_type=cfg['order_type'],
                product=cfg['product'],
            )
            
            # 5️⃣ Initialize strategy
            logger.info(f"🚀 Creating DNSS strategy | {cfg['symbol']}")
            self.strategy = DeltaNeutralShortStrangleStrategy(
                exchange=cfg['exchange'],
                symbol=cfg['symbol'],
                expiry=expiry,
                get_option_func=self.market.get_nearest_option,
                config=dnss_config,
            )
            
            logger.info(f"✅ Strategy initialized | Expiry: {expiry}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_current_expiry(self, expiry_mode: str) -> str:
        """Get current expiry based on mode"""
        from datetime import datetime, timedelta, date
        
        today = date.today()
        
        if expiry_mode == "weekly_current":
            # Find next Thursday (or current if today is Thursday)
            days_until_thursday = (3 - today.weekday()) % 7
            if days_until_thursday == 0 and today.weekday() == 3:
                # Today is Thursday
                next_thursday = today
            else:
                next_thursday = today + timedelta(days=(3 - today.weekday()) % 7)
            return next_thursday.strftime("%d%b%Y").upper()
        
        elif expiry_mode == "monthly_current":
            # Last Thursday of current month
            # Find last day of month, then work backwards to Thursday
            next_month = today.replace(day=28) + timedelta(days=4)
            last_day = (next_month - timedelta(days=next_month.day)).day
            for day in range(last_day, 0, -1):
                candidate = today.replace(day=day)
                if candidate.weekday() == 3:  # Thursday
                    return candidate.strftime("%d%b%Y").upper()
        
        # Default: closest weekly Thursday
        days_until_thursday = (3 - today.weekday()) % 7
        next_thursday = today + timedelta(days=days_until_thursday)
        return next_thursday.strftime("%d%b%Y").upper()
    
    def run(self, duration_minutes: Optional[int] = None):
        """
        Run the strategy polling loop
        
        Args:
            duration_minutes: Run for this many minutes, then exit (None = infinite)
        """
        if not self.strategy or not self.market:
            logger.error("❌ Strategy not initialized. Call initialize() first.")
            return False
        
        self._running = True
        start_time = time.time()
        max_duration = (duration_minutes * 60) if duration_minutes else None
        
        logger.info(f"▶️ Starting execution loop | poll_interval={self.poll_interval}s")
        if duration_minutes:
            logger.info(f"⏱️ Will run for {duration_minutes} minutes")
        
        try:
            while self._running:
                # Check duration
                if max_duration and (time.time() - start_time) > max_duration:
                    logger.info(f"⏱️ Duration limit reached ({duration_minutes}m)")
                    break
                
                # Execute tick
                now = datetime.now()
                self._execute_tick(now)
                
                # Sleep
                time.sleep(self.poll_interval)
        
        except KeyboardInterrupt:
            logger.info("⏹️ Interrupted by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self._running = False
            self._print_summary()
        
        return True
    
    def _execute_tick(self, now: datetime):
        """Execute a single strategy tick"""
        # Type guard for type checking
        if not self.strategy or not self.market:
            logger.error("❌ Strategy or market not initialized")
            return
        
        try:
            # 1️⃣ Prepare market snapshot
            snapshot = self.market.snapshot()
            self.strategy.prepare(snapshot)
            
            # 2️⃣ Execute strategy logic
            commands = self.strategy.on_tick(now) or []
            
            # Log if commands generated
            if commands:
                logger.warning(f"⚠️ Strategy generated {len(commands)} command(s)")
                for cmd in commands:
                    logger.info(f"   → {cmd.side} {cmd.symbol} qty={cmd.quantity}")
            
            # 3️⃣ Update metrics
            self._tick_count += 1
            
            # Log status occasionally
            if self._tick_count % 60 == 0:  # Every 60 ticks (2 min at 2s interval)
                status = self.strategy.get_status()
                logger.info(f"📊 Strategy Status | Ticks: {self._tick_count} | "
                           f"State: {status['state']} | "
                           f"PnL: {status['unrealized_pnl']:.2f}")
        
        except Exception as e:
            logger.error(f"❌ Tick execution failed: {e}")
            self._error_count += 1
            import traceback
            traceback.print_exc()
    
    def _print_summary(self):
        """Print execution summary"""
        logger.info("=" * 70)
        logger.info(f"EXECUTION SUMMARY")
        logger.info(f"  Ticks executed: {self._tick_count}")
        logger.info(f"  Errors: {self._error_count}")
        
        if self.strategy:
            status = self.strategy.get_status()
            logger.info(f"  Final State: {status['state']}")
            logger.info(f"  Unrealized PnL: {status['unrealized_pnl']:.2f}")
            logger.info(f"  Realized PnL: {status['realized_pnl']:.2f}")
        
        logger.info("=" * 70)


# ============================================================
# CLI INTERFACE
# ============================================================

def main():
    """Command-line entry point"""
    parser = argparse.ArgumentParser(
        description="Run DNSS strategy from JSON config file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m shoonya_platform.strategies.delta_neutral --config saved_configs/dnss_nifty_weekly.json
  python -m shoonya_platform.strategies.delta_neutral --config ./config.json --duration 30
        """,
    )
    
    parser.add_argument(
        "--config",
        required=True,
        help="Path to strategy config JSON file",
    )
    
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Run for this many minutes (default: infinite)",
    )
    
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds (default: 2.0)",
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load environment
    logger.info("🔐 Loading environment configuration...")
    try:
        config = Config()
        logger.info("✅ Environment loaded")
    except Exception as e:
        logger.error(f"❌ Failed to load environment: {e}")
        return 1
    
    # Create and run runner
    runner = DNSSStandaloneRunner(
        config_path=args.config,
        poll_interval=args.poll_interval,
    )
    
    if not runner.initialize():
        logger.error("❌ Failed to initialize runner")
        return 1
    
    if not runner.run(duration_minutes=args.duration):
        logger.error("❌ Strategy execution failed")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
