# ✅ DNSS Architecture Unified - Quick Reference

## System Now Uses

```
ONE Runner + ONE Config Format = ALL Strategies
↓
StrategyRunner (universal executor)
  └─ UniversalStrategyConfig (standard format)
    └─ Adapter (creates strategy from config)
      └─ DNSS Strategy (pluggable logic)
```

---

## What Got Changed

| What | Before | After |
|------|--------|-------|
| **Execution** | Separate `__main__.py` for each strategy | Single `StrategyRunner` for ALL strategies |
| **Config** | Custom `dnss_nifty.json` | Standard `UniversalStrategyConfig` |
| **Flow** | Dashboard → Custom → Separate Runner | Dashboard → Standard → Unified Runner |
| **Multi-Strategy** | Not possible | Runs DNSS + Iron Condor + others in parallel |

---

## How to Use DNSS Now

### Step 1: Create UniversalStrategyConfig
```python
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig
from datetime import time

config = UniversalStrategyConfig(
    strategy_name="dnss_nifty_v1",
    exchange="NFO",
    symbol="NIFTY",
    instrument_type="OPTIDX",
    entry_time=time(9, 18),
    exit_time=time(15, 28),
    order_type="MARKET",
    product="MIS",
    lot_qty=1,
    params={
        "target_entry_delta": 0.4,
        "delta_adjust_trigger": 0.10,
        "max_leg_delta": 0.65,
        "profit_step": 1000.0,
        "cooldown_seconds": 300,
    }
)
```

### Step 2: Convert to DNSS Strategy
```python
from shoonya_platform.strategies.delta_neutral import create_dnss_from_universal_config
from shoonya_platform.execution.db_market import DBBackedMarket

market = DBBackedMarket(db_path, "NFO", "NIFTY")
dnss_strategy = create_dnss_from_universal_config(config, market)
```

### Step 3: Register with Runner
```python
from shoonya_platform.strategies.strategy_runner import StrategyRunner

runner = StrategyRunner(bot=bot)
runner.register("dnss_nifty_v1", dnss_strategy, market)
runner.start()
```

---

## Files Changed

### ✅ New
- `shoonya_platform/strategies/delta_neutral/adapter.py` - Config converter

### ✅ Updated
- `shoonya_platform/strategies/delta_neutral/__init__.py` - Exports adapter

### ❌ Deprecated
- `shoonya_platform/strategies/delta_neutral/__main__.py` → `__main__.py.DEPRECATED`

---

## DNSS Parameters in Config

```python
params={
    "target_entry_delta": 0.4,        # Entry delta target
    "delta_adjust_trigger": 0.10,    # Trigger adjustments
    "max_leg_delta": 0.65,           # Emergency exit
    "profit_step": 1000.0,           # Profit tier
    "cooldown_seconds": 300,         # Adjustment cooldown
    "expiry_mode": "weekly_current", # Weekly or monthly
}
```

---

## Key Adapter Functions

### Create Strategy from Config
```python
from shoonya_platform.strategies.delta_neutral import (
    create_dnss_from_universal_config,
)

strategy = create_dnss_from_universal_config(
    universal_config=config,
    market=market,
)
```

### Convert Back to Config
```python
from shoonya_platform.strategies.delta_neutral import dnss_config_to_universal

config = dnss_config_to_universal(
    strategy_name="dnss_nifty",
    exchange="NFO",
    symbol="NIFTY",
    entry_time=time(9, 18),
    exit_time=time(15, 28),
    order_type="MARKET",
    product="MIS",
    lot_qty=1,
    dnss_params={...}
)
```

---

## Multi-Strategy Example

```python
runner = StrategyRunner(bot=bot)

# Strategy 1: DNSS NIFTY
dnss_nifty = create_dnss_from_universal_config(config_nifty, market_nifty)
runner.register("dnss_nifty", dnss_nifty, market_nifty)

# Strategy 2: DNSS BANKNIFTY
dnss_bnf = create_dnss_from_universal_config(config_bnf, market_bnf)
runner.register("dnss_banknifty", dnss_bnf, market_bnf)

# Strategy 3: Iron Condor (future)
ic = create_iron_condor_from_universal_config(config_ic, market_ic)
runner.register("iron_condor", ic, market_ic)

# All run in one runner, 2s polling
runner.start()
```

---

## Why This Architecture?

✅ **Single Source of Truth** - One runner, one config format  
✅ **Scalable** - Add new strateg ies without modifying runner  
✅ **Clean Separation** - Logic separate from execution  
✅ **Dashboard Integration** - Form → API → Config → Runner  
✅ **Parallel Execution** - Multiple strategies at once  
✅ **Error Isolation** - One strategy crash doesn't affect others  
✅ **Unified Monitoring** - Metrics for all strategies  

---

## File Locations

```
shoonya_platform/strategies/
├── strategy_runner.py         ← Use this for ALL strategies
├── universal_config/
│   └── universal_strategy_config.py
└── delta_neutral/
    ├── dnss.py                ← Strategy logic
    ├── adapter.py             ← NEW: Config conversion
    └── __init__.py            ← Exports all
```

---

## Commands

### Precheck Setup
```bash
python dnss_nifty_precheck.py  # Verify all components
```

### Initialize Database
```bash
python dnss_db_init.py  # Create SQLite with sample data
```

### Test Strategy (using runner)
```python
# See full example in DNSS_UNIFIED_FINAL.md
runner.start()
runner.print_metrics()
```

---

**✅ System Ready** - DNSS now integrated with unified StrategyRunner!
