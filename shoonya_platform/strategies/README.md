# Strategy Management System - Refactored Architecture

## ✅ New Structure

```
shoonya_platform/strategies/
│
├── 📄 Core Production Files (Universal - work with ANY strategy)
│   ├── strategy_runner.py              # CLOCK + DISPATCHER (no logic)
│   ├── strategy_run_writer.py          # DB persistence for runs
│   ├── strategy_reporter.py            # Reporting utility (moved from reporting/)
│   ├── strategy_registry.py            # 🆕 Folder-based discovery
│   └── universal_config/               # Universal config system (instrument-agnostic)
│       └── universal_strategy_config.py
│
├── 📁 User Strategies (each in own folder)
│   ├── delta_neutral/
│   │   ├── dnss.py                      # Delta Neutral Short Strangle implementation
│   │   ├── __init__.py
│   │   └── README.md
│   │
│   ├── iron_condor/
│   │   ├── iron_condor.py               # Iron Condor strategy (when added)
│   │   ├── __init__.py
│   │   └── README.md
│   │
│   └── (other strategies added same way)
│
├── 📦 Legacy / Deprecated Files
│   └── legacy/
│       ├── README.md                    # Migration guide
│       ├── run.py                       # Old runner (deprecated)
│       ├── db_run.py                    # Old DB runner (deprecated)
│       ├── db_based_run.py              # Old runner (deprecated)
│       ├── runner_adv/                  # Advanced runner (deprecated)
│       ├── reporting/                   # Old reporting folder (deprecated)
│       └── delta_neutral/
│           ├── delta_neutral_short_strategy.py  # Old implementation
│           └── configs/                         # Old config system
│
└── __init__.py
```

---

## 🎯 Key Principles

### 1. **Universal Runners**
- `strategy_runner.py` - Clock-based executor, works with ANY strategy
- `strategy_run_writer.py` - Persistence layer, works with ANY strategy
- `strategy_reporter.py` - Reporting utility, works with ANY strategy
- **No hardcoding** to specific strategies

### 2. **Universal Config**
- `universal_config/universal_strategy_config.py` - works with:
  - Options (OPTIDX, OPTSTK)
  - Futures (FUTIDX, FUTSTK)
  - Forex, Commodities (MCX)
  - Stocks (CASH)
- Strategies implement: `prepare()` and `on_tick()` methods
- Config drives WHAT strategy can do, strategy implements HOW

### 3. **Strategy Folders**
Each strategy lives in its own `strategies/<strategy_name>/` folder:
- ✅ `delta_neutral/dnss.py` - DNSS implementation
- ✅ `iron_condor/iron_condor.py` - Iron Condor (future)
- ✅ `butterfly/butterfly.py` - Butterfly (future)
- ✅ Custom strategies follow same pattern

### 4. **Auto-Discovery**
- `strategy_registry.py` - Automatically discovers strategies by folder
- Frontend lists available strategies without hardcoding
- Users can add strategies by creating `strategies/<name>/<name>.py`

---

## 🚀 Frontend Integration

### Strategy Selection (`strategy.html`)
```html
<select id="strategyType" onchange="updateStrategyType()">
  <option value="delta_neutral/dnss">Delta Neutral Short Strangle</option>
  <option value="iron_condor/iron_condor">Iron Condor</option>
  <option value="butterfly/butterfly">Butterfly</option>
  <option value="custom">Custom Entry</option>
</select>
```

### Backend API (`/dashboard/strategies/list`)
```python
GET /dashboard/strategies/list
→ Returns: [
    {"id": "delta_neutral/dnss", "label": "Delta Neutral - Dnss", "module": "..."},
    {"id": "iron_condor/iron_condor", "label": "Iron Condor", "module": "..."},
    ...
]
```

### Strategy Entry Flow
1. User selects strategy from dropdown (auto-populated from `/strategies/list`)
2. User defines: `entry_time`, `exit_time`, `lot_qty`, strategy-specific params
3. Frontend POST to `/intent/strategy/entry` with:
   ```json
   {
     "strategy_name": "NIFTY_DNSS_v1",
     "strategy_version": "1.0.0",
     "exchange": "NFO",
     "symbol": "NIFTY",
     "instrument_type": "OPTIDX",
     "entry_time": "09:20:00",
     "exit_time": "15:30:00",
     "order_type": "LIMIT",
     "product": "NRML",
     "lot_qty": 50,
     "params": {
       "target_entry_delta": 0.4,
       "delta_adjust_trigger": 0.1,
       "max_leg_delta": 0.65,
       "profit_step": 1000
     }
   }
   ```
4. Backend:
   - Creates `UniversalStrategyConfig` from request
   - Instantiates strategy (e.g., `DeltaNeutralShortStrangleStrategy`)
   - Registers with `StrategyRunner` (clock-based)
   - Returns intent_id to frontend

---

## 📝 Creating New Strategies

### Step 1: Create Folder
```bash
mkdir shoonya_platform/strategies/my_strategy
touch shoonya_platform/strategies/my_strategy/__init__.py
```

### Step 2: Implement Strategy Class
File: `shoonya_platform/strategies/my_strategy/my_strategy.py`

```python
class MyCustomStrategy:
    def __init__(self, exchange, symbol, expiry, get_option_func, config):
        self.exchange = exchange
        self.symbol = symbol
        self.expiry = expiry
        self.get_option = get_option_func
        self.config = config  # UniversalStrategyConfig
        
    def prepare(self):
        """Initialize strategy state"""
        pass
    
    def on_tick(self, market_state) -> list:
        """Execute strategy logic on each tick"""
        # Return list of UniversalOrderCommand objects
        # Or empty list if no action
        return []
```

### Step 3: Add Configuration
File: `shoonya_platform/strategies/my_strategy/configs.py` (optional)

```python
from pathlib import Path
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig

def get_config_for_symbol(symbol: str) -> UniversalStrategyConfig:
    return UniversalStrategyConfig(
        strategy_name=f"{symbol}_MY_STRATEGY",
        strategy_version="1.0.0",
        exchange="NFO",
        symbol=symbol,
        instrument_type="OPTIDX",
        entry_time=time(9, 20),
        exit_time=time(15, 30),
        order_type="LIMIT",
        product="NRML",
        lot_qty=50,
        params={
            "custom_param_1": "value",
            "custom_param_2": 123,
        }
    )
```

### Step 4: Strategy appears in UI
- Restart backend
- `/dashboard/strategies/list` returns your new strategy
- Frontend automatically shows in dropdown
- Users can select and configure via UI

---

## 🔼 Migration From Legacy

If you were using old runners:

**Old Way:**
```python
from shoonya_platform.strategies.run import main
main("delta_neutral.configs.nifty")
```

**New Way:**
```python
# Via Frontend:
# 1. Go to Strategy page
# 2. Select "Delta Neutral Short Strangle"
# 3. Enter params
# 4. Click "Start Strategy"

# Via Intent API:
POST /dashboard/intent/strategy/entry
{
  "strategy_name": "NIFTY_DNSS",
  "strategy_version": "1.0.0",
  ...
}
```

---

## 📚 Important Files

### Production Files (DO NOT DELETE)
- `strategy_runner.py` - Core runner (universal)
- `strategy_run_writer.py` - DB writer (universal)
- `strategy_reporter.py` - Reporting (universal)
- `universal_config/` - Config system (universal)
- `strategy_registry.py` - Discovery system (universal)

### Legacy Files (Deprecated but preserved)
- Everything in `legacy/` folder
- Use for reference only

### User Strategies
- `delta_neutral/dnss.py` - Production DNSS implementation
- Add new strategies in same format

---

## 🧪 Testing Strategies

### Unit Test
```python
from shoonya_platform.strategies.delta_neutral.dnss import DeltaNeutralShortStrangleStrategy
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig

config = UniversalStrategyConfig(...)
strategy = DeltaNeutralShortStrangleStrategy(..., config=config)
strategy.prepare()
commands = strategy.on_tick(market_state)
```

### Integration Test (via API)
```bash
curl -X POST http://localhost:8000/dashboard/intent/strategy/entry \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "TEST_DNSS",
    "strategy_version": "1.0.0",
    "exchange": "NFO",
    "symbol": "NIFTY",
    ...
  }'
```

---

**Last Updated:** 2026-02-09  
**Architecture:** Universal, Folder-Based, Auto-Discoverable
