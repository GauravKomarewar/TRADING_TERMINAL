# ARCHITECTURE CLARITY - DNSS Strategy Integration

## ❌ What I Created (WRONG - Creates Confusion)
```
Dashboard Form
    ↓
dnss_nifty.json (custom format)
    ↓
__main__.py (separate DNSS runner)
    ↓
DNSS Strategy directly
```

**Problem**: Separate execution path, doesn't use your existing infrastructure

---

## ✅ What SHOULD Be Done (CORRECT - Uses Your System)

```
Dashboard Form (strategy_new.html)
    ↓
UniversalStrategyConfig (standardized format)
    ↓
strategy_runner.py (universal - runs ANY strategy)
    ↓
Any Strategy (DNSS, IRON_CONDOR, etc.)
```

---

## Your Existing Architecture

### 1. **UniversalStrategyConfig** (Frozen Dataclass)
```python
@dataclass(frozen=True)
class UniversalStrategyConfig:
    strategy_name: str
    exchange: str
    symbol: str
    entry_time: time
    exit_time: time
    order_type: str
    product: str
    lot_qty: int
    params: Dict[str, Any]  # ← Strategy-specific params go here
```

**Location**: `shoonya_platform/strategies/universal_config/universal_strategy_config.py`

### 2. **StrategyRunner** (Universal Executor)
```python
class StrategyRunner:
    def register_strategy(self, universal_config, strategy_instance)
    def execute_tick(self, now: datetime) -> List[Intent]
    def run()  # Main polling loop
```

**Location**: `shoonya_platform/strategies/strategy_runner.py`

### 3. **DNSS Strategy** (Logic Only)
```python
class DeltaNeutralShortStrangleStrategy:
    def __init__(self, config: StrategyConfig, market, get_option_func)
    def prepare(self, market: dict)
    def on_tick(self, now: datetime) -> List[Intent]
```

**Location**: `shoonya_platform/strategies/delta_neutral/dnss.py`

---

## How DNSS Should Flow Through Your System

### Step 1: Dashboard Creates Config
**User creates strategy in dashboard** → Fills 6 sections → Saves

Form data:
```json
{
  "id": "dnss_nifty_v1",
  "name": "NIFTY_DELTA_AUTO_ADJUST",
  "exchange": "NFO",
  "symbol": "NIFTY",
  "entry_time": "09:18",
  "exit_time": "15:28",
  "order_type": "MARKET",
  "lot_qty": 1,
  
  "params": {
    "target_entry_delta": 0.4,
    "delta_adjust_trigger": 0.10,
    "max_leg_delta": 0.65,
    "profit_step": 1000.0,
    "cooldown_seconds": 300
  }
}
```

### Step 2: Dashboard Converts to UniversalStrategyConfig
**API endpoint** (`/strategy/config/save-all` or similar):
```python
universal_config = UniversalStrategyConfig(
    strategy_name="dnss_nifty_v1",
    strategy_version="1.0",
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
        "cooldown_seconds": 300
    }
)

# Save to database or JSON
db.save_config(universal_config)
```

### Step 3: StrategyRunner Uses UniversalStrategyConfig
**Execution service**:
```python
# Load config from database
universal_config = db.load_config("dnss_nifty_v1")

# Create DNSS strategy instance
dnss_config = StrategyConfig(
    entry_time=universal_config.entry_time,
    exit_time=universal_config.exit_time,
    target_entry_delta=universal_config.params["target_entry_delta"],
    delta_adjust_trigger=universal_config.params["delta_adjust_trigger"],
    max_leg_delta=universal_config.params["max_leg_delta"],
    profit_step=universal_config.params["profit_step"],
    cooldown_seconds=universal_config.params["cooldown_seconds"],
)

market = DBBackedMarket(db_path, "NFO", "NIFTY")
dnss_strategy = DeltaNeutralShortStrangleStrategy(
    exchange="NFO",
    symbol="NIFTY",
    expiry="12FEB2026",
    lot_qty=1,
    get_option_func=market.get_nearest_option,
    config=dnss_config,
)

# Register with runner
runner = StrategyRunner()
runner.register_strategy(
    name="dnss_nifty_v1",
    universal_config=universal_config,
    strategy=dnss_strategy,
    market=market,
)

# Run
runner.run()  # Main polling loop - handles ALL strategies
```

### Step 4: StrategyRunner Executes Every 2 Seconds
```python
# strategy_runner.py main loop
while running:
    now = datetime.now()
    
    for strategy_name, context in strategies.items():
        try:
            # 1. Prepare market snapshot
            snapshot = context.market.snapshot()
            context.strategy.prepare(snapshot)
            
            # 2. Execute tick
            intents = context.strategy.on_tick(now)
            
            # 3. Send intents to OrderWatcher/execution
            if intents:
                for intent in intents:
                    order_watcher.process_intent(intent)
        except Exception as e:
            logger.error(f"Error in {strategy_name}: {e}")
    
    time.sleep(2.0)
```

---

## What I Created vs What Should Be Used

| Component | What I Created | What You Should Use |
|-----------|----------------|-------------------|
| **Config Format** | `dnss_nifty.json` (custom) | `UniversalStrategyConfig` |
| **Runner** | `__main__.py` (DNSS-only) | `strategy_runner.py` (universal) |
| **Execution** | Standalone CLI | Integrated with dashboard API |
| **Database** | Sample SQLite | Your existing database |
| **Flow** | Separate path | Dashboard → API → Runner → Strategy |

---

## ACTION: Remove Confusion

### ✅ KEEP:
- `dnss_nifty.json` ← Can be used as reference for params
- `dnss_nifty_precheck.py` ← Database validation is still useful
- `dnss_db_init.py` ← Database creation script is still useful

### ❌ DEPRECATE/REMOVE:
- `shoonya_platform/strategies/delta_neutral/__main__.py` ← Separate runner should NOT exist
- The separate `__main__.py` execution flow

### ✅ USE INSTEAD:
- Dashboard to create config
- Dashboard API to save UniversalStrategyConfig
- `strategy_runner.py` to execute all strategies
- Single unified execution path

---

## Corrected Flow for DNSS

```
1. Dashboard (strategy_new.html)
   ↓
2. Strategy saved as UniversalStrategyConfig
   ↓
3. API endpoint receives config
   ↓
4. Config stored in database
   ↓
5. Execution service loads config via manager
   ↓
6. StrategyRunner instantiates DNSS with config
   ↓
7. StrategyRunner polling loop (main execution)
   ↓
8. DNSS generates intents on each tick
   ↓
9. OrderWatcher processes intents
   ↓
10. Broker execution
```

---

## Summary

**You already have the correct architecture:**
- ✅ `UniversalStrategyConfig` - standardized config format
- ✅ `strategy_runner.py` - universal executor
- ✅ `DNSS strategy` - pluggable logic

**What I created** was an alternative standalone path that bypassed your system.

**The right approach**: Use dashboard → UniversalStrategyConfig → strategy_runner.py to execute DNSS (and any other strategy).

Should I:
1. Remove the `__main__.py` and standalone runner?
2. Show how to integrate DNSS with your existing strategy_runner.py?
3. Create proper UniversalStrategyConfig examples for DNSS?

Which would be most helpful?
