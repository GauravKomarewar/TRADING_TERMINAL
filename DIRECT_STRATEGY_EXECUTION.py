#!/usr/bin/env python3
"""
DIRECT STRATEGY EXECUTION - RUN FROM STRATEGIES FOLDER

This guide shows how to execute strategies directly with Python
without using the frontend dashboard.

Perfect for:
- Local testing and development
- Automated backtesting
- Direct Python integration
- Debugging strategy behavior
"""

import sys
from pathlib import Path

# Add strategies folder to path
STRATEGIES_ROOT = Path(__file__).parent / "shoonya_platform" / "strategies"
sys.path.insert(0, str(STRATEGIES_ROOT.parent.parent))

print(f"✅ Added to path: {STRATEGIES_ROOT.parent.parent}")

# ═════════════════════════════════════════════════════════════════════════
# EXECUTION MODELS
# ═════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────
# MODEL 1: Run DNSS Strategy with Mock Data (Simplest)
# ─────────────────────────────────────────────────────────────────────────

def example_1_mock_data_execution():
    """
    Run DNSS strategy with mock market data.
    
    Use Case: Testing strategy logic without real market data
    Time: <1 second
    Data: In-memory mock
    """
    print("\n" + "="*70)
    print("MODEL 1: DNSS Strategy with Mock Data (Local Testing)")
    print("="*70)
    
    from unittest.mock import Mock
    from shoonya_platform.strategies.delta_neutral.dnss import (
        DeltaNeutralShortStrangleStrategy,
        DeltaNeutralConfig,
    )
    
    # Step 1: Create config with delta = 0.3
    config = DeltaNeutralConfig(
        target_entry_delta=0.3,
        delta_adjust_trigger=0.6,
        max_leg_delta=0.5,
    )
    print(f"✅ Config created: target_entry_delta={config.target_entry_delta}")
    
    # Step 2: Create strategy instance
    strategy = DeltaNeutralShortStrangleStrategy(
        symbol="NIFTY",
        exchange="NFO",
        config=config,
    )
    print(f"✅ Strategy created: {strategy.__class__.__name__}")
    
    # Step 3: Create mock market data
    mock_market = Mock()
    mock_market.snapshot = Mock(return_value={
        "spot": 23500,
        "ce_delta": 0.30,
        "pe_delta": -0.30,
    })
    print("✅ Mock market data created")
    
    # Step 4: Call prepare() - would find delta 0.3 options
    strategy.market_adapter = Mock()
    strategy.market_adapter.get_nearest_option_by_greek = Mock(
        return_value={
            "symbol": "NIFTY_25FEB_23700_CE",
            "strike_price": 23700,
            "greek_value": 0.30,
            "token": 100001,
        }
    )
    
    # Prepare for entry
    strategy.prepare(mock_market.snapshot())
    print(f"✅ Strategy prepared: active={strategy.state.active}")
    
    if strategy.state.active:
        print(f"   → CE: {strategy.state.ce_leg.symbol} (delta={strategy.state.ce_leg.delta})")
        print(f"   → PE: {strategy.state.pe_leg.symbol} (delta={strategy.state.pe_leg.delta})")


# ─────────────────────────────────────────────────────────────────────────
# MODEL 2: Run Strategy with Real Database Market Data
# ─────────────────────────────────────────────────────────────────────────

def example_2_database_execution(db_path: str = None):
    """
    Run DNSS strategy with real SQLite market data.
    
    Use Case: Testing with actual option chain data
    Time: 2-5 seconds
    Data: SQLite database with historical Greeks
    
    Args:
        db_path: Path to SQLite database with option_chain table
    """
    print("\n" + "="*70)
    print("MODEL 2: DNSS Strategy with SQLite Database")
    print("="*70)
    
    from shoonya_platform.strategies.market_adapter_factory import MarketAdapterFactory
    from shoonya_platform.strategies.delta_neutral.dnss import (
        DeltaNeutralShortStrangleStrategy,
        DeltaNeutralConfig,
    )
    from unittest.mock import Mock
    from datetime import datetime
    
    # If no db_path provided, create sample
    if not db_path:
        print("⚠️  No db_path provided. Using sample data...")
        db_path = create_sample_database()
    
    print(f"✅ Using database: {db_path}")
    
    # Step 1: Create config
    config = DeltaNeutralConfig(
        target_entry_delta=0.3,
        delta_adjust_trigger=0.6,
        max_leg_delta=0.5,
    )
    
    # Step 2: Create market adapter
    adapter_config = {
        "exchange": "NFO",
        "symbol": "NIFTY",
        "db_path": db_path,
    }
    
    adapter = MarketAdapterFactory.create("database_market", adapter_config)
    print(f"✅ Adapter created: {adapter.__class__.__name__}")
    
    # Step 3: Create strategy
    strategy = DeltaNeutralShortStrangleStrategy(
        symbol="NIFTY",
        exchange="NFO",
        config=config,
    )
    
    # Attach adapter (StrategyRunner would do this)
    strategy.market_adapter = adapter
    print(f"✅ Adapter attached to strategy")
    
    # Step 4: Prepare (find delta 0.3 options)
    snapshot = adapter.get_market_snapshot(include_greeks=True)
    strategy.prepare(snapshot)
    
    print(f"✅ Strategy prepared: active={strategy.state.active}")
    
    if strategy.state.active and strategy.state.ce_leg:
        print(f"\n   📊 Entry Legs Found:")
        print(f"   → CE: {strategy.state.ce_leg.symbol}")
        print(f"      Delta: {strategy.state.ce_leg.delta:.4f}")
        print(f"   → PE: {strategy.state.pe_leg.symbol}")
        print(f"      Delta: {strategy.state.pe_leg.delta:.4f}")
        print(f"\n   Total Delta: {strategy.state.total_delta():.4f} (should be ≈0.60)")


# ─────────────────────────────────────────────────────────────────────────
# MODEL 3: Run Via StrategyRunner (Production-like)
# ─────────────────────────────────────────────────────────────────────────

def example_3_strategy_runner_execution(db_path: str = None):
    """
    Run DNSS strategy via StrategyRunner (most production-like).
    
    Use Case: Test full execution flow including runner lifecycle
    Time: 5-10 seconds
    Data: SQLite + mock broker
    """
    print("\n" + "="*70)
    print("MODEL 3: Via StrategyRunner (Production-like)")
    print("="*70)
    
    from shoonya_platform.strategies.strategy_runner import StrategyRunner
    from shoonya_platform.strategies.delta_neutral.dnss import (
        DeltaNeutralShortStrangleStrategy,
        DeltaNeutralConfig,
    )
    from unittest.mock import Mock
    from datetime import datetime
    import time
    
    if not db_path:
        db_path = create_sample_database()
    
    print(f"✅ Using database: {db_path}")
    
    # Step 1: Create mock bot
    mock_bot = Mock()
    mock_bot.execute_command = Mock(return_value=True)
    print("✅ Mock bot created")
    
    # Step 2: Create StrategyRunner
    runner = StrategyRunner(bot=mock_bot)
    print(f"✅ StrategyRunner created")
    
    # Step 3: Create strategy and config
    config = DeltaNeutralConfig(
        target_entry_delta=0.3,
        delta_adjust_trigger=0.6,
        max_leg_delta=0.5,
    )
    
    strategy = DeltaNeutralShortStrangleStrategy(
        symbol="NIFTY",
        exchange="NFO",
        config=config,
    )
    
    # Mock market
    mock_market = Mock()
    mock_market.snapshot = Mock(return_value={"spot": 23500})
    
    # Step 4: Register strategy with runner
    result = runner.register_with_config(
        name="NIFTY_DNSS_TEST",
        strategy=strategy,
        market=mock_market,
        config={
            "exchange": "NFO",
            "symbol": "NIFTY",
            "db_path": db_path,
        },
        market_type="database_market",
    )
    
    print(f"✅ Strategy registered: {result}")
    
    # Step 5: Access registered strategy
    context = runner._strategies["NIFTY_DNSS_TEST"]
    print(f"\n   📊 Registered Strategy Context:")
    print(f"   → Name: {context.name}")
    print(f"   → Market Type: {context.market_type}")
    print(f"   → Adapter: {context.market_adapter.__class__.__name__}")
    print(f"   → Metrics: {context.metrics.total_ticks} ticks")


# ─────────────────────────────────────────────────────────────────────────
# MODEL 4: Run Multiple Strategies (Parallel Testing)
# ─────────────────────────────────────────────────────────────────────────

def example_4_multiple_strategies(db_path: str = None):
    """
    Run multiple DNSS strategies with different configurations.
    
    Use Case: Test strategy behavior across instruments
    Time: 10-15 seconds
    Data: Multiple databases/strategies
    """
    print("\n" + "="*70)
    print("MODEL 4: Multiple Strategies (Parallel)")
    print("="*70)
    
    from shoonya_platform.strategies.strategy_runner import StrategyRunner
    from shoonya_platform.strategies.delta_neutral.dnss import (
        DeltaNeutralShortStrangleStrategy,
        DeltaNeutralConfig,
    )
    from unittest.mock import Mock
    
    if not db_path:
        db_path = create_sample_database()
    
    # Create runner
    mock_bot = Mock()
    runner = StrategyRunner(bot=mock_bot)
    
    # Register multiple strategies
    strategies = [
        {
            "name": "NIFTY_DELTA_LOW",
            "delta": 0.25,
            "trigger": 0.50,
        },
        {
            "name": "NIFTY_DELTA_MID",
            "delta": 0.30,
            "trigger": 0.60,
        },
        {
            "name": "NIFTY_DELTA_HIGH",
            "delta": 0.35,
            "trigger": 0.70,
        },
    ]
    
    print(f"📋 Registering {len(strategies)} strategies...\n")
    
    for strat_config in strategies:
        config = DeltaNeutralConfig(
            target_entry_delta=strat_config["delta"],
            delta_adjust_trigger=strat_config["trigger"],
            max_leg_delta=0.5,
        )
        
        strategy = DeltaNeutralShortStrangleStrategy(
            symbol="NIFTY",
            exchange="NFO",
            config=config,
        )
        
        mock_market = Mock()
        result = runner.register_with_config(
            name=strat_config["name"],
            strategy=strategy,
            market=mock_market,
            config={
                "exchange": "NFO",
                "symbol": "NIFTY",
                "db_path": db_path,
            },
            market_type="database_market",
        )
        
        status = "✅" if result else "❌"
        print(f"{status} {strat_config['name']}")
        print(f"   → Delta Target: {strat_config['delta']}")
        print(f"   → Adjustment Trigger: {strat_config['trigger']}")
    
    print(f"\n✅ Registered: {len(runner._strategies)} strategies")
    print(f"   → Total Metrics: {sum(ctx.metrics.total_ticks for ctx in runner._strategies.values())}")


# ─────────────────────────────────────────────────────────────────────────
# HELPER: Create Sample Database
# ─────────────────────────────────────────────────────────────────────────

def create_sample_database() -> str:
    """Create temporary database with sample option chain data"""
    import sqlite3
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    
    conn = sqlite3.connect(db_path)
    
    # Create schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            symbol TEXT,
            strike_price REAL,
            token INTEGER,
            delta_ce REAL,
            delta_pe REAL,
            gamma REAL,
            theta REAL,
            vega REAL
        )
    """)
    
    # Insert sample options with delta ≈ 0.3
    sample_data = [
        ("NIFTY_25FEB_23600_CE", 23600, 100003, 0.45, -0.55, 0.005, -0.3, 0.12),
        ("NIFTY_25FEB_23700_CE", 23700, 100004, 0.30, -0.70, 0.006, -0.25, 0.15),  # ← TARGET
        ("NIFTY_25FEB_23800_CE", 23800, 100005, 0.15, -0.85, 0.004, -0.15, 0.10),
        ("NIFTY_25FEB_23600_PE", 200003, 23600, 0.55, -0.45, 0.005, -0.3, 0.12),
        ("NIFTY_25FEB_23700_PE", 200004, 23700, 0.70, -0.30, 0.006, -0.25, 0.15),  # ← TARGET
        ("NIFTY_25FEB_23800_PE", 200005, 23800, 0.85, -0.15, 0.004, -0.15, 0.10),
    ]
    
    for row in sample_data:
        conn.execute(
            "INSERT INTO option_chain VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            row
        )
    
    conn.commit()
    conn.close()
    
    return db_path


# ═════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🚀 DIRECT STRATEGY EXECUTION - PYTHON GUIDE")
    print("="*70)
    
    print("""
    Choose an execution model:
    
    1. Mock Data (Local testing)
       → Fast, in-memory, no dependencies
       → Use for: Logic validation, CI/CD tests
    
    2. Database (Real option data)
       → Uses SQLite with Greeks
       → Use for: Development, backtesting
    
    3. StrategyRunner (Production-like)
       → Full execution flow
       → Use for: Integration testing
    
    4. Multiple Strategies (Parallel)
       → Test multiple configurations
       → Use for: Comparative analysis
    """)
    
    # Run examples
    example_1_mock_data_execution()
    example_2_database_execution()
    example_3_strategy_runner_execution()
    example_4_multiple_strategies()
    
    print("\n" + "="*70)
    print("✅ ALL EXAMPLES COMPLETED")
    print("="*70)
    
    print("""
    📚 NEXT STEPS:
    
    1. Run tests:
       pytest shoonya_platform/tests/strategies/test_delta_greek_selection.py -v
    
    2. Test directly:
       python -m shoonya_platform.strategies.run_direct strategy_config.json
    
    3. Integration:
       from shoonya_platform.strategies.delta_neutral import DeltaNeutralShortStrangleStrategy
       # Use as shown in examples above
    
    4. Production:
       Use main.py with config from saved_configs/
       Execution service will handle the rest
    """)
