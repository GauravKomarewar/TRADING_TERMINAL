# Code Organization - Before & After

## BEFORE: Mixed Architecture ❌

```
execution/ (MESSY - Strategy + OMS code mixed)
├── broker.py              ✅ OMS: Order placement
├── trading_bot.py         ✅ OMS: Main execution loop
├── order_watcher.py       ✅ OMS: Monitor open orders
│
├── market.py              ❌ STRATEGY DATA (doesn't belong here!)
├── db_market.py           ❌ STRATEGY DATA (doesn't belong here!)
├── engine.py              ❌ DNSS-specific (doesn't belong here!)
├── engine_no_recovery.py  ❌ DNSS-specific (doesn't belong here!)
│
├── models.py              ⚠️ SHARED (Intent, ExecutionGuard, etc)
├── intent.py              ⚠️ SHARED
├── execution_guard.py     ⚠️ SHARED
└── [other files]

strategies/ (Disorganized)
├── strategy_runner.py
├── universal_config/
├── delta_neutral/
│   ├── strategy.py
│   ├── adapter.py
│   ├── __main__.py.DEPRECATED  ← Dead code
│   └── __main__.py             ← Separate runner (confusion!)
├── legacy/                     ← Old code still has bad imports
│   ├── run.py              imports from execution.market ❌
│   ├── db_run.py           imports from execution.db_market ❌
│   └── db_based_run.py     imports from execution.db_market ❌
└── [other strategy code]

PROBLEM: 
- Market providers in execution/ (confusion about responsibilty)
- Strategy-specific code mixed with OMS code
- Unclear where data infrastructure belongs
- Multiple runner paths (__main__.py vs strategy_runner.py)
```

---

## AFTER: Clean Architecture ✅

```
execution/ (CLEAN - OMS ONLY)
├── broker.py              ✅ Place orders with broker
├── command_service.py     ✅ Process trading intents
├── trading_bot.py         ✅ Main execution loop
├── strategy_control_consumer.py  ✅ NOW imports from strategies.market
├── order_watcher.py       ✅ Monitor orders
├── recovery.py            ✅ Recovery handling
│
├── models.py              ⚠️ SHARED: Intent, ExecutionGuard
├── intent.py              ⚠️ SHARED: Intent types
├── execution_guard.py     ⚠️ SHARED: Risk checks
├── intent_tracker.py      ⚠️ SHARED: Track intents
└── [other pure OMS]

strategies/ (UNIFIED - ALL STRATEGY CODE)
├── market/                ✅ ← MOVED HERE (was in execution/)
│   ├── market.py          → LiveMarket class
│   ├── db_market.py       → DBBackedMarket class (DNSS reads Greeks from here)
│   └── __init__.py        → Exports: LiveMarket, DBBackedMarket
│
├── strategy_runner.py     ✅ SINGLE UNIFIED EXECUTOR
│   → Polls all strategies every 2 seconds
│   → Thread-safe registration
│   → Error isolation per strategy
│
├── universal_config/      ✅ STANDARD CONFIG FOR ALL STRATEGIES
│   ├── universal_strategy_config.py
│   └── __init__.py
│
├── delta_neutral/         ✅ DNSS STRATEGY
│   ├── strategy.py        → DeltaNeutralShortStrangleStrategy
│   ├── adapter.py         → Convert UniversalStrategyConfig → DNSS config
│   └── [other DNSS components]
│
├── legacy/                ✅ OLD IMPLEMENTATIONS (now using correct imports)
│   ├── run.py             imports from strategies.market ✅
│   ├── db_run.py          imports from strategies.market ✅
│   └── db_based_run.py    imports from strategies.market ✅
│
├── saved_configs/         ✅ Config JSONs
│   └── dnss_nifty.json    → DNSS parameters
│
├── strategy_registry.py   ✅ Strategy registration
└── __init__.py            ✅ Exports: DBBackedMarket, LiveMarket, UniversalStrategyConfig

BENEFITS:
- ✅ Clear responsibility: execution = OMS, strategies = strategy code
- ✅ Single unified executor (no confusing multiple paths)
- ✅ Market providers co-located with strategies (logical grouping)
- ✅ All imports point to correct locations
- ✅ Easy to add new strategies (Iron Condor follows DNSS pattern)
```

---

## Import Changes Summary

### File: `execution/strategy_control_consumer.py`
```python
# BEFORE ❌
from shoonya_platform.execution.db_market import DBBackedMarket

# AFTER ✅
from shoonya_platform.strategies.market import DBBackedMarket
```

### File: `strategies/legacy/run.py`
```python
# BEFORE ❌
from shoonya_platform.execution.market import LiveMarket

# AFTER ✅
from shoonya_platform.strategies.market import LiveMarket
```

### File: `strategies/legacy/db_run.py`
```python
# BEFORE ❌
from shoonya_platform.execution.db_market import DBBackedMarket

# AFTER ✅
from shoonya_platform.strategies.market import DBBackedMarket
```

### File: `strategies/legacy/db_based_run.py`
```python
# BEFORE ❌
from shoonya_platform.execution.db_market import DBBackedMarket

# AFTER ✅
from shoonya_platform.strategies.market import DBBackedMarket
```

### File: `strategies/delta_neutral/__main__.py.DEPRECATED`
```python
# BEFORE ❌
from shoonya_platform.execution.db_market import DBBackedMarket

# AFTER ✅
from shoonya_platform.strategies.market import DBBackedMarket
```

### File: `strategies/__init__.py`
```python
# BEFORE: Empty
__init__.py (no exports)

# AFTER ✅
from .market import DBBackedMarket, LiveMarket
from .universal_config import UniversalStrategyConfig

__all__ = [
    "DBBackedMarket",
    "LiveMarket",
    "UniversalStrategyConfig",
]
```

---

## Verification Checklist

- ✅ Market files moved: `execution/market.py` → `strategies/market/market.py`
- ✅ Market files moved: `execution/db_market.py` → `strategies/market/db_market.py`
- ✅ Old execution market files deleted
- ✅ All imports updated (7 Python files modified)
- ✅ No old import paths remaining (verified with grep)
- ✅ Python syntax valid (Pylance check passed)
- ✅ strategies/market/__init__.py exports both providers
- ✅ strategies/__init__.py exports market + universal_config
- ✅ execution/ is now OMS-only (no strategy code)
- ✅ strategies/ contains all strategy infrastructure + code

---

## Ready for Commit

```bash
git add -A
git commit -m "refactor(market): Move market data providers from execution/ to strategies/

- Relocate market.py and db_market.py to strategies/market/
- Update all imports in execution/ and legacy strategies
- Delete old market files from execution/ (now clean OMS-only)
- Update strategies/__init__.py with proper exports

Result: Clean architecture with execution=OMS, strategies=all strategy code"
```

---

## Usage After Reorganization

### For Strategy Developers
```python
# Import data providers for new strategy
from shoonya_platform.strategies.market import DBBackedMarket
from shoonya_platform.strategies import UniversalStrategyConfig

# Create adapter.py (like DNSS does)
def create_strategy_from_universal_config(config: UniversalStrategyConfig):
    # Convert universal config to strategy-specific config
    pass

# Register with StrategyRunner automatically
```

### For OMS Code
```python
# execution/ files can import from strategies.market if needed
from shoonya_platform.strategies.market import DBBackedMarket

# Or get it via strategies top-level
from shoonya_platform.strategies import DBBackedMarket
```

### For Tests
```python
# Test strategy execution
from shoonya_platform.strategies.market import DBBackedMarket
from shoonya_platform.strategies import UniversalStrategyConfig

market = DBBackedMarket()
snapshot = market.snapshot("NIFTY", "2025-02-13")
# snapshot = DataFrame with Greeks + spot_price
```

---

## Architecture Principles Enforced

1. **Separation of Concerns** ✅
   - execution/ = Order Management System (no strategy logic)
   - strategies/ = Strategy execution (no OMS logic)
   - Shared = models, intent tracking, risk checks

2. **Single Unified Executor** ✅
   - All strategies use strategy_runner.py
   - No separate __main__.py runners
   - Consistent execution model

3. **Standardized Interfaces** ✅
   - All strategies use UniversalStrategyConfig
   - All get market data via DBBackedMarket.snapshot()
   - All return Intent objects for execution

4. **Scalability** ✅
   - New strategies (Iron Condor, etc) follow same pattern
   - New market providers added to strategies/market/
   - No changes needed to OMS code
