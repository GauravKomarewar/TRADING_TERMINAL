#!/usr/bin/env python3
"""
PRODUCTION STRATEGY RUNNER - OMS-COMPLIANT
==========================================
Version: 1.0.0 FROZEN
Status: PRODUCTION READY
Date: 2026-02-06

RESPONSIBILITIES (STRICTLY LIMITED):
✅ Time-driven tick execution
✅ Multi-strategy parallel execution
✅ Passive metrics collection
✅ Error isolation between strategies
✅ Thread-safe strategy management

DOES NOT:
❌ Auto-recovery
❌ Auto-exit
❌ Signal handling
❌ Circuit breakers
❌ Health-based decisions
❌ Market hours enforcement
❌ Lifecycle management

AUTHORITY:
- Runner = CLOCK + DISPATCHER
- OrderWatcher = EXIT authority
- Operator = LIFECYCLE authority
- Strategy = LOGIC only

DESIGN PRINCIPLES:
1. Deterministic execution
2. No hidden behavior
3. Fail-fast on errors
4. Operator-controlled lifecycle
5. OMS-native routing
"""

from __future__ import annotations
import threading
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass, field
from collections import defaultdict

from shoonya_platform.strategies.market_adapter_factory import MarketAdapterFactory
from shoonya_platform.strategies.strategy_logger import get_strategy_logger

logger = logging.getLogger("STRATEGY_RUNNER")


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class StrategyMetrics:
    """Passive metrics - READ ONLY, no decisions"""
    name: str
    
    # Execution counts
    total_ticks: int = 0
    total_commands: int = 0
    total_errors: int = 0
    
    # Timing (passive observation)
    last_tick_time: Optional[datetime] = None
    avg_tick_duration_ms: float = 0.0
    max_tick_duration_ms: float = 0.0
    
    # Registration timestamp
    registered_at: datetime = field(default_factory=datetime.now)
    
    def update_tick_duration(self, duration_ms: float):
        """Update timing stats (passive - no decisions)"""
        if self.total_ticks == 0:
            self.avg_tick_duration_ms = duration_ms
        else:
            # Exponential moving average
            alpha = 0.1
            self.avg_tick_duration_ms = (
                alpha * duration_ms + (1 - alpha) * self.avg_tick_duration_ms
            )
        self.max_tick_duration_ms = max(self.max_tick_duration_ms, duration_ms)


@dataclass
class StrategyContext:
    """Container for strategy instance and dependencies"""
    name: str
    strategy: Any
    market: Any
    market_type: Literal["database_market", "live_feed_market"] = "live_feed_market"
    market_adapter: Optional[Any] = None  # DatabaseMarketAdapter or LiveFeedMarketAdapter
    
    # Thread safety
    lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    
    # Passive metrics
    metrics: StrategyMetrics = field(init=False)
    
    def __post_init__(self):
        self.metrics = StrategyMetrics(name=self.name)


# ============================================================
# STRATEGY RUNNER - CLOCK + DISPATCHER ONLY
# ============================================================

class StrategyRunner:
    """
    Production strategy runner - STRICTLY LIMITED SCOPE
    
    DOES:
    - Execute strategies on schedule (clock)
    - Route commands to OMS (dispatcher)
    - Collect passive metrics (observer)
    - Isolate errors between strategies
    
    DOES NOT:
    - Make lifecycle decisions
    - Auto-exit positions
    - Enforce market hours
    - Auto-recover from errors
    - Handle signals
    - Circuit break
    
    ALL AUTHORITY BELONGS TO:
    - OrderWatcher (exits)
    - Operator (lifecycle)
    - Strategy (logic)
    """
    
    def __init__(
        self,
        *,
        bot,
        poll_interval: float = 2.0,
    ):
        """
        Initialize the strategy runner
        
        Args:
            bot: ShoonyaBot instance for OMS routing
            poll_interval: Seconds between execution cycles
        """
        self.bot = bot
        self.poll_interval = poll_interval
        
        # Strategy registry
        self._strategies: Dict[str, StrategyContext] = {}
        self._strategies_lock = threading.RLock()
        
        # Execution control
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        
        # Global counters (passive observation only)
        self._global_ticks = 0
        self._global_commands = 0
        self._global_errors = 0
        
        logger.info(f"🏗️ StrategyRunner initialized | poll_interval={poll_interval}s")
    
    # ========================================================
    # REGISTRATION
    # ========================================================
    
    def register(self, *, name: str, strategy, market) -> bool:
        """
        Register a strategy for execution
        
        Args:
            name: Unique strategy identifier
            strategy: Strategy instance (must implement prepare() and on_tick())
            market: Market data provider
            
        Returns:
            True if registered successfully, False otherwise
        """
        with self._strategies_lock:
            if name in self._strategies:
                logger.error(f"❌ Strategy already registered: {name}")
                return False
            
            # Validate interface
            if not self._validate_strategy(strategy):
                logger.error(f"❌ Strategy {name} missing required methods")
                return False
            
            # Create context
            context = StrategyContext(
                name=name,
                strategy=strategy,
                market=market,
            )
            
            self._strategies[name] = context
            
            # Register with bot (reporting only)
            try:
                self.bot.register_live_strategy(name, strategy, market)
            except Exception as e:
                logger.warning(f"⚠️ Bot registration failed for {name}: {e}")
            
            logger.info(
                f"✅ Strategy registered: {name} | total={len(self._strategies)}"
            )
            
            return True
    
    def register_with_config(
        self,
        *,
        name: str,
        strategy,
        market,
        config: Dict[str, Any],
        market_type: Literal["database_market", "live_feed_market"] = "live_feed_market",
    ) -> bool:
        """
        Register strategy with market adapter selection (latch pattern).
        
        Automatically creates appropriate market adapter based on market_type.
        
        Args:
            name: Unique strategy identifier
            strategy: Strategy instance (must implement prepare() and on_tick())
            market: Market data provider
            config: Strategy configuration with exchange, symbol, db_path, etc.
            market_type: "database_market" or "live_feed_market"
            
        Returns:
            True if registered successfully, False otherwise
        """
        with self._strategies_lock:
            if name in self._strategies:
                logger.error(f"❌ Strategy already registered: {name}")
                return False
            
            # Validate interface
            if not self._validate_strategy(strategy):
                logger.error(f"❌ Strategy {name} missing required methods")
                return False
            
            # Validate config for market type
            is_valid, error = MarketAdapterFactory.validate_config_for_market(
                market_type=market_type,
                config=config,
            )
            if not is_valid:
                logger.error(f"❌ Config validation failed for {name}: {error}")
                logger.error(f"   market_type={market_type}, config keys={list(config.keys())}, db_path={config.get('db_path')}")
                return False
            
            # Create market adapter (latch - selects market backend)
            try:
                logger.info(f"🔄 Creating market adapter for {name} (market_type={market_type}, db_path={config.get('db_path')})...")
                market_adapter = MarketAdapterFactory.create(
                    market_type=market_type,
                    config=config,
                )
                logger.info(f"✓ Market adapter created for {name}")
            except Exception as e:
                logger.error(f"❌ Failed to create market adapter for {name}: {e}", exc_info=True)
                return False
            
            # Create context with adapter
            context = StrategyContext(
                name=name,
                strategy=strategy,
                market=market,
                market_type=market_type,
                market_adapter=market_adapter,
            )
            
            self._strategies[name] = context
            
            # Log to strategy logger
            strategy_logger = get_strategy_logger(name)
            strategy_logger.info(f"Strategy registered - market={market_type}")
            
            # Register with bot (reporting only)
            try:
                self.bot.register_live_strategy(name, strategy, market)
            except Exception as e:
                logger.warning(f"⚠️ Bot registration failed for {name}: {e}")
            
            logger.info(
                f"✅ Strategy registered: {name} | market={market_type} | total={len(self._strategies)}"
            )
            
            return True
    
    def unregister(self, name: str) -> bool:
        """
        Unregister a strategy
        
        NOTE: Does NOT exit positions - operator must do that first
        
        Args:
            name: Strategy identifier
            
        Returns:
            True if unregistered, False if not found
        """
        with self._strategies_lock:
            if name not in self._strategies:
                logger.warning(f"⚠️ Strategy not found: {name}")
                return False
            
            del self._strategies[name]
            
            logger.info(
                f"🗑️ Strategy unregistered: {name} | remaining={len(self._strategies)}"
            )
            
            return True
    
    def _validate_strategy(self, strategy) -> bool:
        """Validate strategy implements required interface"""
        required = ['prepare', 'on_tick']
        
        for method in required:
            if not hasattr(strategy, method):
                logger.error(f"❌ Missing required method: {method}")
                return False
            if not callable(getattr(strategy, method)):
                logger.error(f"❌ Method {method} is not callable")
                return False
        
        return True
    
    # ========================================================
    # JSON CONFIGURATION LOADING
    # ========================================================
    
    def load_strategies_from_json(
        self,
        config_dir: str,
        strategy_factory,
    ) -> Dict[str, bool]:
        """
        Load strategies from JSON configuration files.
        
        Loads all .json files from config_dir directory and registers them.
        Each JSON file must contain strategy configuration.
        
        Args:
            config_dir: Directory containing strategy JSON files (e.g., saved_configs/)
            strategy_factory: Callable that creates strategy instances from config
                             Signature: strategy_factory(config) → strategy_instance
            
        Returns:
            Dict of {strategy_name: success_boolean}
            
        Example:
            results = runner.load_strategies_from_json(
                config_dir="strategies/saved_configs/",
                strategy_factory=lambda cfg: DNSS(cfg)
            )
        """
        import json
        from pathlib import Path
        
        results = {}
        config_path = Path(config_dir)
        
        # Validate directory exists
        if not config_path.exists():
            logger.error(f"❌ Config directory not found: {config_dir}")
            return results
        
        if not config_path.is_dir():
            logger.error(f"❌ Not a directory: {config_dir}")
            return results
        
        # Find all JSON files
        json_files = list(config_path.glob("*.json"))
        if not json_files:
            logger.warning(f"⚠️ No JSON files found in {config_dir}")
            return results
        
        logger.info(f"📖 Loading {len(json_files)} strategy configs from {config_dir}")
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    config = json.load(f)
                
                # Skip template/schema files
                if config.get("name", "").endswith("TEMPLATE") or config.get("name", "").endswith("SCHEMA"):
                    logger.debug(f"⊘ Skipping template: {json_file.name}")
                    continue
                
                # Check if enabled
                if not config.get("enabled", False):
                    logger.info(f"⊘ Strategy disabled in config: {config.get('name', json_file.name)}")
                    results[json_file.stem] = False
                    continue
                
                strategy_name = config.get("name")
                if not strategy_name:
                    logger.error(f"❌ No 'name' field in {json_file.name}")
                    results[json_file.stem] = False
                    continue
                
                # Validate required config fields
                required_fields = ["market_config", "entry", "exit"]
                missing_fields = [f for f in required_fields if f not in config]
                if missing_fields:
                    for f in missing_fields:
                        logger.error(f"❌ Missing required field '{f}' in {strategy_name}")
                    results[strategy_name] = False
                    continue
                
                market_config = config.get("market_config", {})
                market_type = market_config.get("market_type", "database_market")
                
                # Create strategy instance using factory
                try:
                    strategy = strategy_factory(config)
                    if not strategy:
                        logger.error(f"❌ Strategy factory returned None for {strategy_name}")
                        results[strategy_name] = False
                        continue
                except Exception as e:
                    logger.error(f"❌ Failed to create strategy from {json_file.name}: {e}")
                    results[strategy_name] = False
                    continue
                
                # Prepare strategy (initial call with empty market data)
                try:
                    strategy.prepare({})
                except Exception as e:
                    logger.warning(f"⚠️ Strategy prepare() initial call warning for {strategy_name}: {e}")
                    # Don't fail — runner will call prepare() with real data on each tick
                
                # Register with runner
                success = self.register_with_config(
                    name=strategy_name,
                    strategy=strategy,
                    market=None,  # Market is managed via market_adapter
                    config=market_config,
                    market_type=market_type,
                )
                
                results[strategy_name] = success
                
                if success:
                    logger.info(f"✅ Loaded strategy: {strategy_name} from {json_file.name}")
                else:
                    logger.error(f"❌ Failed to register strategy: {strategy_name}")
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ Invalid JSON in {json_file.name}: {e}")
                results[json_file.stem] = False
            except Exception as e:
                logger.error(f"❌ Error loading {json_file.name}: {e}")
                results[json_file.stem] = False
        
        # Summary
        successful = sum(1 for v in results.values() if v)
        logger.info(
            f"📊 Config loading complete: {successful}/{len(results)} strategies loaded"
        )
        
        return results
    
    # ========================================================
    # LIFECYCLE
    # ========================================================
    
    def start(self):
        """Start the execution loop"""
        if self._thread and self._thread.is_alive():
            logger.warning("⚠️ StrategyRunner already running")
            return
        
        self._stop_event.clear()
        
        self._thread = threading.Thread(
            target=self._run_loop,
            name="StrategyRunnerThread",
            daemon=False,  # Non-daemon for clean shutdown
        )
        self._thread.start()
        
        logger.info(
            f"🚀 StrategyRunner started | strategies={len(self._strategies)}"
        )
    
    def stop(self, timeout: int = 30):
        """
        Stop the execution loop
        
        NOTE: Does NOT exit positions - OrderWatcher handles that
        
        Args:
            timeout: Seconds to wait for thread to stop
        """
        logger.warning("🛑 StrategyRunner stop requested")
        
        self._stop_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            
            if self._thread.is_alive():
                logger.error("❌ Runner thread did not stop gracefully")
            else:
                logger.info("✅ Runner thread stopped")
        
        logger.warning("🛑 StrategyRunner stopped")
    
    # ========================================================
    # MAIN EXECUTION LOOP - CLOCK + DISPATCHER
    # ========================================================
    
    def _run_loop(self):
        """
        Main execution loop
        
        RESPONSIBILITIES:
        1. Provide clock (call strategies on schedule)
        2. Dispatch commands to OMS
        3. Collect metrics (passive)
        4. Isolate errors between strategies
        
        DOES NOT:
        - Make decisions based on metrics
        - Exit positions
        - Stop strategies
        - Enforce business rules
        """
        logger.info("🧭 Execution loop started")
        
        while not self._stop_event.is_set():
            try:
                loop_start = time.time()
                now = datetime.now()
                
                # Execute all registered strategies
                self._execute_all_strategies(now)
                
                # Increment global tick counter (passive)
                self._global_ticks += 1
                
                # Sleep until next poll
                elapsed = time.time() - loop_start
                sleep_time = max(0, self.poll_interval - elapsed)
                
                if elapsed > self.poll_interval:
                    logger.warning(
                        f"⏱️ Loop overrun: {elapsed:.2f}s > {self.poll_interval}s"
                    )
                
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.exception("❌ Critical error in main loop")
                self._global_errors += 1
                time.sleep(5)  # Back off on critical error
        
        logger.warning("🛑 Execution loop exited")
    
    def _execute_all_strategies(self, now: datetime):
        """Execute all registered strategies"""
        with self._strategies_lock:
            strategies = list(self._strategies.values())
        
        for context in strategies:
            self._execute_strategy(context, now)
    
    def _execute_strategy(self, context: StrategyContext, now: datetime):
        """
        Execute a single strategy tick
        
        ERROR ISOLATION:
        - Each strategy executes in try-except
        - One strategy crash does NOT affect others
        - Errors are logged and counted (passive)
        - NO auto-recovery or auto-exit
        """
        tick_start = time.time()
        strategy_logger = get_strategy_logger(context.name)
        
        try:
            with context.lock:
                # 1️⃣ Prepare market snapshot
                # Use market_adapter (preferred) or market fallback
                if context.market_adapter is not None:
                    snapshot = context.market_adapter.get_market_snapshot()
                elif context.market is not None and hasattr(context.market, 'get_market_snapshot'):
                    snapshot = context.market.get_market_snapshot()
                elif context.market is not None and hasattr(context.market, 'snapshot'):
                    snapshot = context.market.snapshot()
                else:
                    snapshot = {}
                    strategy_logger.warning("No market source available — empty snapshot")

                context.strategy.prepare(snapshot)
                strategy_logger.debug(f"Market snapshot prepared - {len(snapshot) if isinstance(snapshot, dict) else '?'} items")
                
                # 2️⃣ Execute strategy logic
                commands = context.strategy.on_tick(now) or []
                
                if commands:
                    strategy_logger.info(f"Generated {len(commands)} command(s)")
                
                # 3️⃣ Route commands to OMS (if any)
                if commands:
                    self.bot._process_strategy_intents(
                        strategy_name=context.name,
                        strategy=context.strategy,
                        market=context.market,
                        intents=commands,
                    )
                    
                    # Update metrics (passive)
                    context.metrics.total_commands += len(commands)
                    self._global_commands += len(commands)
                    strategy_logger.info(f"Routed {len(commands)} command(s) to OMS")
                
                # Update metrics - SUCCESS
                tick_duration_ms = (time.time() - tick_start) * 1000
                context.metrics.total_ticks += 1
                context.metrics.last_tick_time = now
                context.metrics.update_tick_duration(tick_duration_ms)
                
                if tick_duration_ms > 100:  # Log slow ticks as warning
                    strategy_logger.warning(f"Slow tick: {tick_duration_ms:.1f}ms")
        
        except Exception as e:
            # Error isolation - log and count (PASSIVE)
            logger.exception(f"❌ {context.name} execution failed")
            strategy_logger.error(f"Execution failed: {str(e)}")
            context.metrics.total_errors += 1
            self._global_errors += 1
            
            # ⚠️ CRITICAL: NO AUTO-RECOVERY
            # ⚠️ CRITICAL: NO AUTO-EXIT
            # ⚠️ CRITICAL: NO AUTO-STOP
            # 
            # Operator must decide what to do via dashboard/logs
    
    # ========================================================
    # METRICS & STATUS (READ-ONLY)
    # ========================================================
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics snapshot (READ-ONLY)
        
        Returns passive observations - NO DECISIONS MADE
        """
        with self._strategies_lock:
            strategy_metrics = {
                name: {
                    "total_ticks": ctx.metrics.total_ticks,
                    "total_commands": ctx.metrics.total_commands,
                    "total_errors": ctx.metrics.total_errors,
                    "avg_tick_duration_ms": round(ctx.metrics.avg_tick_duration_ms, 2),
                    "max_tick_duration_ms": round(ctx.metrics.max_tick_duration_ms, 2),
                    "last_tick_time": (
                        ctx.metrics.last_tick_time.isoformat()
                        if ctx.metrics.last_tick_time else None
                    ),
                    "registered_at": ctx.metrics.registered_at.isoformat(),
                }
                for name, ctx in self._strategies.items()
            }
        
        return {
            "global": {
                "total_ticks": self._global_ticks,
                "total_commands": self._global_commands,
                "total_errors": self._global_errors,
            },
            "strategies": strategy_metrics,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get runner status (READ-ONLY)"""
        is_running = bool(self._thread and self._thread.is_alive())
        
        with self._strategies_lock:
            strategy_count = len(self._strategies)
            strategy_names = list(self._strategies.keys())
        
        return {
            "running": is_running,
            "poll_interval": self.poll_interval,
            "total_strategies": strategy_count,
            "strategy_names": strategy_names,
        }
    
    def print_metrics(self):
        """Print metrics to log (for monitoring)"""
        lines = ["=" * 80, "📊 STRATEGY RUNNER METRICS", "=" * 80]
        lines.append(
            f"Global | "
            f"ticks={self._global_ticks} | "
            f"commands={self._global_commands} | "
            f"errors={self._global_errors}"
        )
        lines.append("-" * 80)
        
        with self._strategies_lock:
            for name, ctx in self._strategies.items():
                m = ctx.metrics
                lines.append(
                    f"{name:20s} | "
                    f"ticks={m.total_ticks:6d} | "
                    f"cmds={m.total_commands:5d} | "
                    f"errs={m.total_errors:3d} | "
                    f"avg={m.avg_tick_duration_ms:6.1f}ms"
                )
        
        lines.append("=" * 80)
        logger.info("\n".join(lines))

