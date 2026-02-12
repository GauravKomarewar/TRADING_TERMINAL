# Standalone Implementations - Quick Reference

## New Location
```
shoonya_platform/strategies/standalone_implementations/
├── delta_neutral/
│   ├── dnss.py               (1036 lines - core strategy logic)
│   ├── adapter.py            (223 lines - UniversalStrategyConfig bridge)
│   └── __init__.py           (clean exports)
└── __init__.py               (package documentation)
```

## Imports

### For Integration with StrategyRunner (Dashboard Path)
```python
from shoonya_platform.strategies.standalone_implementations.delta_neutral import (
    create_dnss_from_universal_config,
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
)
```

### For Direct Use
```python
# All these work independently:
from shoonya_platform.strategies.standalone_implementations.delta_neutral import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
    StrategyState,
    Leg,
    create_dnss_from_universal_config,
    dnss_config_to_universal,
)
```

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `dnss.py` | 1036 | Production-grade DNSS strategy with OMS integration |
| `adapter.py` | 223 | Converts UniversalStrategyConfig ↔ DNSS config |
| `__init__.py` | 35 | Clean exports and module documentation |

## Deleted Files

❌ `__main__.py.DEPRECATED` (465 lines)
- Legacy standalone runner
- Not imported by any system files
- Safe to delete (verified)
- Alternative: Use new unified runner from StrategyRunner

## Dependencies

All imports remain **unchanged** - 100% compatible:
```python
# ✅ These imports still work:
from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig
```

## Migration Path

### Old (Still Works but Outdated)
```
strategies/delta_neutral/     ← OLD LOCATION (now deprecated)
```

### New (Recommended)
```
strategies/standalone_implementations/delta_neutral/   ← NEW LOCATION
```

### Why Migrate References
- Clear organization for multiple strategies
- Better documentation via package structure
- Easier to maintain and extend
- Cleaner codebase (dead code removed)

## System Impact

✅ **StrategyRunner**: No changes needed (generic)
✅ **Dashboard API**: No changes needed (uses UniversalStrategyConfig)
✅ **Execution Guard**: No changes needed (strategy_name based)
✅ **Adapters**: No changes needed (imports are generic)
✅ **Broker Integration**: No changes needed (intent-based)

## How to Use in Code

### Scenario 1: Dashboard Creates Strategy
```python
from shoonya_platform.strategies.standalone_implementations.delta_neutral import (
    create_dnss_from_universal_config
)
from shoonya_platform.strategies.market import DBBackedMarket

# StrategyRunner calls this:
config = UniversalStrategyConfig(...)  # from dashboard/database
market = DBBackedMarket(...)
strategy = create_dnss_from_universal_config(config, market)
```

### Scenario 2: Direct Instantiation
```python
from shoonya_platform.strategies.standalone_implementations.delta_neutral import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
)

config = StrategyConfig(
    entry_time=time(9, 18),
    exit_time=time(15, 28),
    target_entry_delta=0.4,
    delta_adjust_trigger=0.10,
    max_leg_delta=0.65,
    profit_step=1000.0,
    cooldown_seconds=300,
    lot_qty=1,
    order_type="MARKET",
    product="MIS",
)

strategy = DeltaNeutralShortStrangleStrategy(
    exchange="NFO",
    symbol="NIFTY",
    expiry="12FEB2026",
    get_option_func=market.get_nearest_option,
    config=config,
)
```

## Testing the Migration

```python
# Test imports work
from shoonya_platform.strategies.standalone_implementations.delta_neutral import *
print("✅ Migration successful!")

# Test no circular dependencies
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.strategies.strategy_logger import StrategyLogger
print("✅ No import conflicts!")

# Test JSON loading still works
runner = StrategyRunner()
runner.load_strategies_from_json("saved_configs/dnss_nifty.json")
print("✅ Configuration loading works!")
```

## Future Additions

Template for new strategies:

```
standalone_implementations/
├── delta_neutral/          (existing)
├── iron_condor/            (NEW)
│   ├── iron_condor.py
│   ├── adapter.py
│   └── __init__.py
└── butterfly/              (FUTURE)
    ├── butterfly.py
    ├── adapter.py
    └── __init__.py
```

Each needs:
1. Core strategy class with OMS integration (returns `List[UniversalOrderCommand]`)
2. Adapter functions for UniversalStrategyConfig conversion
3. Clean exports via __init__.py

---

**Migration Date**: February 12, 2026  
**Status**: ✅ Complete and Verified
