# Understanding "Market" in StrategyRunner + Reorganization Plan

## Part 1: What Is "Market" in StrategyRunner?

### Definition
**Market** = Data provider that gives the strategy real-time market information (prices, Greeks, spot price)

### In Code
```python
# strategy_runner.py
def _execute_strategy(self, context: StrategyContext, now: datetime):
    # 1. Get market snapshot
    snapshot = context.market.snapshot()
    
    # 2. Pass to strategy
    context.strategy.prepare(snapshot)
    
    # 3. Strategy uses it
    intents = context.strategy.on_tick(now)
```

### Current Implementation
```python
from shoonya_platform.execution.db_market import DBBackedMarket

market = DBBackedMarket(
    db_path="shoonya_platform/market_data/option_chain/data/option_chain.db",
    exchange="NFO",
    symbol="NIFTY",
)
```

**DBBackedMarket** = Reads option chain data from SQLite database

### What Market Provides to Strategy
```python
# In DNSS strategy
snapshot = {
    "greeks": pd.DataFrame(...),  # Option Greeks (delta, gamma, theta)
    "spot": 24875.50,              # Spot price
    "timestamp": datetime.now(),
}

# Strategy uses it
self.strategy.prepare(snapshot)
```

### Market Types (Present & Future)
```
Market
├── DBBackedMarket       ← SQLite database (current)
├── LiveMarketFeeder     ← Real broker feed (future)
├── MockMarket          ← Simulated data (testing)
└── BloombergMarket     ← Third-party API (future)
```

---

## Part 2: Current (MESSY) Organization

```
shoonya_platform/
├── execution/               ← MIXED: Execution + Strategy code
│   ├── db_market.py        ❌ STRATEGY (should move)
│   ├── market.py           ❌ STRATEGY (should move)
│   ├── engine.py           ❌ STRATEGY (should move)
│   ├── engine_no_recovery.py ❌ STRATEGY (should move)
│   ├── models.py           ❌ STRATEGY (should move)
│   ├── intent.py           ⚠️ MIXED (moves)
│   ├── intent_tracker.py   ⚠️ SHARED (stays? copies?)
│   ├── execution_guard.py  ❌ STRATEGY (should move)
│   │
│   ├── broker.py           ✅ EXECUTION (stays)
│   ├── trading_bot.py      ✅ EXECUTION (stays)
│   ├── order_watcher.py    ✅ EXECUTION (stays)
│   ├── strategy_control_consumer.py  ✅ EXECUTION (stays)
│   ├── command_service.py  ✅ EXECUTION (stays)
│   ├── position_exit_service.py ✅ EXECUTION (stays)
│   └── ...
│
└── strategies/             ← CLEAN: Strategy code only
    ├── strategy_runner.py
    ├── universal_config/
    ├── delta_neutral/
    └── ...
```

---

## Part 3: PROPOSED (CLEAN) Organization

```
shoonya_platform/
│
├── execution/              ← PURE Execution/OMS only
│   ├── broker.py           ✅ Broker API
│   ├── trading_bot.py      ✅ Main orchestrator
│   ├── order_watcher.py    ✅ Order watching
│   ├── strategy_control_consumer.py  ✅ Event consumer
│   ├── command_service.py  ✅ Commands
│   ├── position_exit_service.py ✅ Exit management
│   ├── recovery.py         ✅ Recovery logic
│   ├── validation.py       ✅ OMS validation
│   ├── trailing.py         ✅ Trailing stops
│   ├── generic_control_consumer.py ✅ Generic consumer
│   └── __init__.py
│
└── strategies/             ← CLEAN: ALL Strategy code only
    ├── market/             ← NEW folder
    │   ├── __init__.py
    │   ├── market.py        (moved from execution/)
    │   ├── db_market.py     (moved from execution/)
    │   └── market_types.py  (new - market interfaces)
    │
    ├── engine/             ← NEW folder
    │   ├── __init__.py
    │   ├── engine.py        (moved from execution/)
    │   ├── engine_no_recovery.py (moved from execution/)
    │   └── engine_interface.py (new - base class)
    │
    ├── models/             ← NEW folder
    │   ├── __init__.py
    │   ├── models.py        (moved from execution/)
    │   ├── execution_guard.py (moved from execution/)
    │   ├── intent.py        (moved from execution/)
    │   └── intent_tracker.py (moved from execution/)
    │
    ├── strategy_runner.py
    ├── universal_config/
    ├── delta_neutral/
    ├── iron_condor/         (future)
    └── __init__.py
```

---

## Part 4: File-by-File Movement Plan

### TO MOVE TO `strategies/market/`
```
execution/market.py             → strategies/market/market.py
execution/db_market.py          → strategies/market/db_market.py
(new file)                      → strategies/market/__init__.py
```

### TO MOVE TO `strategies/engine/`
```
execution/engine.py             → strategies/engine/engine.py
execution/engine_no_recovery.py → strategies/engine/engine_no_recovery.py
(new file)                      → strategies/engine/__init__.py
```

### TO MOVE TO `strategies/models/`
```
execution/models.py             → strategies/models/models.py
execution/execution_guard.py    → strategies/models/execution_guard.py
execution/intent.py             → strategies/models/intent.py
execution/intent_tracker.py     → strategies/models/intent_tracker.py
(new file)                      → strategies/models/__init__.py
```

### TO KEEP IN `execution/` (Pure OMS)
```
execution/broker.py             ✅ STAYS
execution/trading_bot.py        ✅ STAYS (routes to strategy_runner)
execution/order_watcher.py      ✅ STAYS
execution/strategy_control_consumer.py ✅ STAYS
execution/command_service.py    ✅ STAYS
execution/position_exit_service.py ✅ STAYS
execution/recovery.py           ✅ STAYS
execution/trailing.py           ✅ STAYS
execution/validation.py         ✅ STAYS
execution/generic_control_consumer.py ✅ STAYS
execution/__init__.py           ✅ STAYS
```

---

## Part 5: Import Changes Required

### BEFORE (Scattered)
```python
from shoonya_platform.execution.db_market import DBBackedMarket
from shoonya_platform.execution.engine import StrategyEngine
from shoonya_platform.execution.models import UniversalStrategyConfig
from shoonya_platform.execution.intent import Intent
```

### AFTER (Organized)
```python
from shoonya_platform.strategies.market import DBBackedMarket
from shoonya_platform.strategies.engine import StrategyEngine
from shoonya_platform.strategies.models import UniversalStrategyConfig, Intent
```

---

## Part 6: Clean Separation of Concerns

### Execution Folder = OMS Authority
```
Responsibility: Execute orders, manage broker connection, watch fills
Authority: Broker API, OrderWatcher, Position management
Knows about: Orders, fills, positions, broker state
Doesn't know about: Strategy logic, Greeks, option chains
```

### Strategies Folder = Strategy Authority
```
Responsibility: Generate trading signals, manage strategy logic
Authority: Strategy logic, market data, configuration
Knows about: Greeks, options, entry/exit conditions
Doesn't know about: Broker internals, position management
```

---

## Part 7: Folder Structure After Reorganization

```
shoonya_platform/
│
├── execution/                  ← CLEAN: Only OMS/Broker/Execution
│   ├── broker.py
│   ├── trading_bot.py
│   ├── order_watcher.py
│   ├── strategy_control_consumer.py
│   ├── command_service.py
│   ├── position_exit_service.py
│   ├── recovery.py
│   ├── trailing.py
│   ├── validation.py
│   ├── generic_control_consumer.py
│   └── __init__.py
│
├── strategies/                 ← CLEAN: Only Strategy Code
│   ├── market/                 ← NEW
│   │   ├── __init__.py
│   │   ├── market.py           (moved from execution/)
│   │   ├── db_market.py        (moved from execution/)
│   │   └── market_types.py     (new)
│   │
│   ├── engine/                 ← NEW
│   │   ├── __init__.py
│   │   ├── engine.py           (moved from execution/)
│   │   ├── engine_no_recovery.py (moved from execution/)
│   │   └── engine_interface.py (new)
│   │
│   ├── models/                 ← NEW
│   │   ├── __init__.py
│   │   ├── models.py           (moved from execution/)
│   │   ├── execution_guard.py  (moved from execution/)
│   │   ├── intent.py           (moved from execution/)
│   │   └── intent_tracker.py   (moved from execution/)
│   │
│   ├── strategy_runner.py      (already here)
│   ├── universal_config/       (already here)
│   ├── delta_neutral/          (already here)
│   │   ├── adapter.py          (already here)
│   │   ├── dnss.py             (already here)
│   │   └── ...
│   │
│   └── __init__.py
│
└── <other folders>
```

---

## Part 8: Benefits of This Reorganization

| Benefit | Impact |
|---------|--------|
| **Single Folder** | "I want to fix strategy" → Go to `strategies/` |
| **Clear Intent** | Developer immediately knows what's strategy vs execution |
| **No Confusion** | No more "is db_market execution or strategy?" |
| **Imports Easy** | All strategy stuff in one namespace |
| **Testing Easy** | Mock entire strategies folder without touching execution |
| **Maintenance** | Finding strategy bugs = search `strategies/` only |
| **Scaling** | Add Iron Condor, other strategies without execution changes |

---

## Part 9: Migration Checklist

### Phase 1: Create New Folder Structure
- [ ] Create `strategies/market/` 
- [ ] Create `strategies/engine/`
- [ ] Create `strategies/models/`

### Phase 2: Copy Files to New Locations
- [ ] Copy `execution/market.py` → `strategies/market/market.py`
- [ ] Copy `execution/db_market.py` → `strategies/market/db_market.py`
- [ ] Copy `execution/engine.py` → `strategies/engine/engine.py`
- [ ] Copy `execution/engine_no_recovery.py` → `strategies/engine/engine_no_recovery.py`
- [ ] Copy `execution/models.py` → `strategies/models/models.py`
- [ ] Copy `execution/execution_guard.py` → `strategies/models/execution_guard.py`
- [ ] Copy `execution/intent.py` → `strategies/models/intent.py`
- [ ] Copy `execution/intent_tracker.py` → `strategies/models/intent_tracker.py`

### Phase 3: Update All Imports
- [ ] Find all `from shoonya_platform.execution.market import`
- [ ] Change to `from shoonya_platform.strategies.market import`
- [ ] Find all `from shoonya_platform.execution.db_market import`
- [ ] Change to `from shoonya_platform.strategies.market import`
- [ ] (repeat for engine, models, intent)

### Phase 4: Update `__init__.py` Files
- [ ] Create `strategies/market/__init__.py` with exports
- [ ] Create `strategies/engine/__init__.py` with exports
- [ ] Create `strategies/models/__init__.py` with exports
- [ ] Update `strategies/__init__.py` with all exports

### Phase 5: Test & Validate
- [ ] Run precheck script
- [ ] Verify all imports work
- [ ] Run strategy with runner
- [ ] Check no import errors

### Phase 6: Delete Old Files from execution/
- [ ] Delete `execution/market.py`
- [ ] Delete `execution/db_market.py`
- [ ] Delete `execution/engine.py`
- [ ] Delete `execution/engine_no_recovery.py`
- [ ] Delete `execution/models.py`
- [ ] Delete `execution/execution_guard.py`
- [ ] Delete `execution/intent.py`
- [ ] Delete `execution/intent_tracker.py`

### Phase 7: Commit to Git
- [ ] `git add -A`
- [ ] `git commit -m "refactor: Consolidate all strategy code to strategies/ folder"`

---

## Part 10: Example After Reorganization

### Current (Before)
```python
# Scattered imports
from shoonya_platform.execution.db_market import DBBackedMarket
from shoonya_platform.execution.engine import StrategyEngine
from shoonya_platform.execution.models import UniversalStrategyConfig
from shoonya_platform.execution.intent import Intent
from shoonya_platform.execution.execution_guard import ExecutionGuard

# Confusing - where is strategy code?
```

### After Clean Reorganization
```python
# Clean: All strategy code imported from one place
from shoonya_platform.strategies.market import DBBackedMarket
from shoonya_platform.strategies.engine import StrategyEngine
from shoonya_platform.strategies.models import (
    UniversalStrategyConfig,
    Intent,
    ExecutionGuard,
)

# Clear: Looking for strategy code? → strategies/ folder
```

---

## Summary

**MARKET** = Data provider (prices, Greeks) for strategies

**REORGANIZATION** = Move all strategy-related files to `strategies/` folder:
- `market/` - Market data providers (db_market, market)
- `engine/` - Strategy engines
- `models/` - Data models (config, intent, guard)

**BENEFIT** = Single folder for all strategy concerns, execution folder stays clean

**Next**: Should I proceed with the reorganization?
