# DNSS Integration with Unified Strategy Runner

## Architecture: SINGLE RUNNER FOR ALL STRATEGIES

```
Dashboard (strategy_new.html)
    ↓
UniversalStrategyConfig (standardized)
    ↓
StrategyRunner (universal executor)
    ├─ DNSS Strategy
    ├─ Iron Condor Strategy
    ├─ Other Strategies
    └─ (all run in parallel, 2s polling)
```

---

## Integration Steps

### Step 1: Create UniversalStrategyConfig for DNSS

Instead of `dnss_nifty.json`, you should use UniversalStrategyConfig:

```python
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig
from datetime import time

# From dashboard form, create config
dnss_config = UniversalStrategyConfig(
    strategy_name="dnss_nifty_v1",
    strategy_version="1.0.0",
    
    exchange="NFO",
    symbol="NIFTY",
    instrument_type="OPTIDX",
    
    entry_time=time(9, 18),
    exit_time=time(15, 28),
    
    order_type="MARKET",
    product="MIS",
    lot_qty=1,
    
    # DNSS-specific parameters
    params={
        "target_entry_delta": 0.4,
        "delta_adjust_trigger": 0.10,
        "max_leg_delta": 0.65,
        "profit_step": 1000.0,
        "cooldown_seconds": 300,
    },
)

# Save to database or JSON
json_str = dnss_config.to_json()
# or
config_dict = dnss_config.to_dict()
```

---

### Step 2: Create DNSS Adapter

**File**: `shoonya_platform/strategies/delta_neutral/adapter.py` (NEW)

```python
"""
DNSS Adapter - Converts UniversalStrategyConfig to Strategy Instance
"""

from datetime import time as dt_time
from typing import Dict, Any, Callable, Optional

from .dnss import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig,
)
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig


def create_dnss_from_universal_config(
    universal_config: UniversalStrategyConfig,
    market,  # DBBackedMarket instance
    get_option_func: Optional[Callable] = None,
    expiry: Optional[str] = None,
) -> DeltaNeutralShortStrangleStrategy:
    """
    Convert UniversalStrategyConfig to DNSS Strategy Instance
    
    Args:
        universal_config: Standard config from dashboard
        market: DBBackedMarket instance for option lookup
        get_option_func: Custom option getter (default: market.get_nearest_option)
        expiry: Manual expiry override (default: auto-calculate from mode)
    
    Returns:
        DeltaNeutralShortStrangleStrategy fully initialized
    """
    
    # Extract DNSS-specific params
    params = universal_config.params
    
    # Create DNSS strategy config
    dnss_config = StrategyConfig(
        entry_time=universal_config.entry_time,
        exit_time=universal_config.exit_time,
        
        target_entry_delta=float(params.get("target_entry_delta", 0.20)),
        delta_adjust_trigger=float(params.get("delta_adjust_trigger", 0.50)),
        max_leg_delta=float(params.get("max_leg_delta", 0.65)),
        
        profit_step=float(params.get("profit_step", 1500)),
        cooldown_seconds=int(params.get("cooldown_seconds", 0)),
    )
    
    # Get option function
    if get_option_func is None:
        get_option_func = market.get_nearest_option
    
    # Calculate expiry if not provided
    if expiry is None:
        expiry = _calculate_expiry(params.get("expiry_mode", "weekly_current"))
    
    # Create and return strategy instance
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=universal_config.exchange,
        symbol=universal_config.symbol,
        expiry=expiry,
        lot_qty=universal_config.lot_qty,
        get_option_func=get_option_func,
        config=dnss_config,
    )
    
    return strategy


def _calculate_expiry(expiry_mode: str) -> str:
    """Calculate current expiry based on mode"""
    from datetime import datetime, date, timedelta
    
    today = date.today()
    
    if expiry_mode == "weekly_current":
        # Find next Thursday (or current if today is Thursday)
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0:
            next_thursday = today
        else:
            next_thursday = today + timedelta(days=days_until_thursday)
        return next_thursday.strftime("%d%b%Y").upper()
    
    elif expiry_mode == "monthly_current":
        # Last Thursday of current month
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
```

---

### Step 3: Use StrategyRunner to Execute DNSS

**File**: Your execution service (e.g., `execution_service.py`)

```python
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.strategies.delta_neutral.adapter import create_dnss_from_universal_config
from shoonya_platform.execution.db_market import DBBackedMarket
from shoonya_platform.strategies.universal_config import UniversalStrategyConfig


def run_dnss_with_runner(bot, universal_config: UniversalStrategyConfig):
    """
    Run DNSS strategy using unified StrategyRunner
    
    Args:
        bot: ShoonyaBot instance (OMS integration)
        universal_config: Strategy configuration
    """
    
    # 1. Initialize market data provider
    market = DBBackedMarket(
        db_path="shoonya_platform/market_data/option_chain/data/option_chain.db",
        exchange=universal_config.exchange,
        symbol=universal_config.symbol,
    )
    
    # 2. Create DNSS strategy from universal config
    dnss_strategy = create_dnss_from_universal_config(
        universal_config=universal_config,
        market=market,
    )
    
    # 3. Create runner
    runner = StrategyRunner(
        bot=bot,
        poll_interval=2.0,  # Standard 2-second polling
    )
    
    # 4. Register strategy
    runner.register(
        name=universal_config.strategy_name,
        strategy=dnss_strategy,
        market=market,
    )
    
    # 5. Start execution
    runner.start()
    
    # 6. Monitor (optional)
    try:
        while True:
            runner.print_metrics()
            time.sleep(30)  # Print metrics every 30s
    except KeyboardInterrupt:
        runner.stop()
        print("✅ DNSS execution stopped")


# USAGE EXAMPLE:
if __name__ == "__main__":
    from shoonya_platform.core.config import Config
    from shoonya_platform.execution import ShoonyaBot
    
    # Load config
    config = Config()
    
    # Create bot (OMS integration)
    bot = ShoonyaBot(config)
    
    # Load DNSS strategy config from database
    universal_config = UniversalStrategyConfig(
        strategy_name="dnss_nifty_v1",
        strategy_version="1.0.0",
        exchange="NFO",
        symbol="NIFTY",
        instrument_type="OPTIDX",
        entry_time=datetime.time(9, 18),
        exit_time=datetime.time(15, 28),
        order_type="MARKET",
        product="MIS",
        lot_qty=1,
        params={
            "target_entry_delta": 0.4,
            "delta_adjust_trigger": 0.10,
            "max_leg_delta": 0.65,
            "profit_step": 1000.0,
            "cooldown_seconds": 300,
        },
    )
    
    # Run
    run_dnss_with_runner(bot, universal_config)
```

---

## Complete Integration Example

### Scenario: Run DNSS Through Dashboard

**1. User fills strategy form** (strategy_new.html)
- Name: "NIFTY_DELTA_AUTO_ADJUST"
- Entry time: 09:18
- Exit time: 15:28
- Params: delta 0.4, adjust 0.10, etc.

**2. Dashboard API saves config** 
```python
@app.post("/strategy/config/save-all")
def save_all_config(payload):
    # Convert form data to UniversalStrategyConfig
    universal_config = UniversalStrategyConfig(
        strategy_name=payload["name"],
        exchange=payload["exchange"],
        symbol=payload["symbol"],
        entry_time=parse_time(payload["entry_time"]),
        exit_time=parse_time(payload["exit_time"]),
        order_type=payload["order_type"],
        lot_qty=payload["lot_qty"],
        params={
            "target_entry_delta": payload["target_entry_delta"],
            "delta_adjust_trigger": payload["delta_adjust_trigger"],
            "max_leg_delta": payload["max_leg_delta"],
            "profit_step": payload["profit_step"],
            "cooldown_seconds": payload["cooldown_seconds"],
        },
    )
    
    # Save to database
    db.save_strategy_config(universal_config)
    
    return {"status": "saved", "id": universal_config.strategy_name}
```

**3. Execution service loads and runs**
```python
def start_strategy_execution(strategy_id: str):
    # Load config from database
    universal_config = db.load_strategy_config(strategy_id)
    
    # Create runner
    runner = StrategyRunner(bot=bot)
    
    # Register DNSS
    market = DBBackedMarket(..., symbol=universal_config.symbol)
    dnss = create_dnss_from_universal_config(universal_config, market)
    runner.register(
        name=universal_config.strategy_name,
        strategy=dnss,
        market=market,
    )
    
    # Start
    runner.start()
```

---

## What to Remove/Keep

### ✅ KEEP
- `shoonya_platform/strategies/strategy_runner.py` ← Main executor
- `shoonya_platform/strategies/universal_config/` ← Standard config
- `shoonya_platform/strategies/delta_neutral/dnss.py` ← Strategy logic

### ✅ CREATE NEW
- `shoonya_platform/strategies/delta_neutral/adapter.py` ← DNSS adapter
- `shoonya_platform/strategies/delta_neutral/__init__.py` ← Already exists

### ❌ REMOVE/DEPRECATE
- `shoonya_platform/strategies/delta_neutral/__main__.py` ← Separate runner (DELETE this)
- `dnss_nifty.json` in root ← Use UniversalStrategyConfig instead
- Standalone CLI execution

---

## Benefits of Unified Architecture

| Aspect | Benefit |
|--------|---------|
| **Single Runner** | Execute DNSS + Iron Condor + others simultaneously |
| **Standard Config** | Dashboard knows how to save/load any strategy |
| **Clean Separation** | Logic (strategy) separate from Execution (runner) |
| **Error Isolation** | One strategy crash doesn't affect others |
| **Metrics** | Unified monitoring for all strategies |
| **Scalability** | Add new strategies without changing runner |

---

## Next Steps

1. ✅ Create `shoonya_platform/strategies/delta_neutral/adapter.py`
2. ✅ Remove `shoonya_platform/strategies/delta_neutral/__main__.py`
3. ✅ Integrate with existing dashboard API
4. ✅ Test with `strategy_runner.start()`

Would you like me to proceed with these changes?
