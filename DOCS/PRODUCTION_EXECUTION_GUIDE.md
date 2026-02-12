# PRODUCTION EXECUTION GUIDE
**Shoonya Platform - Strategy Runner**  
**Version:** 2.0.0  
**Status:** PRODUCTION READY  
**Last Updated:** 2026-02-06

---

## Quick Start (5 Minutes)

### 1. Create Your Strategy JSON Config

Copy this template and save as `strategies/saved_configs/MY_STRATEGY.json`:

```json
{
  "name": "MY_NIFTY_DNSS",
  "enabled": true,
  "market_config": {
    "market_type": "database_market",
    "exchange": "NFO",
    "symbol": "NIFTY",
    "db_path": "/path/to/your/option_chain.db"
  },
  "entry": {
    "entry_time": "09:30",
    "target_ce_delta": 0.30,
    "target_pe_delta": 0.30,
    "quantity": 10
  },
  "adjustment": {
    "enabled": true,
    "delta_drift_trigger": 0.60,
    "rebalance_target_delta": 0.30
  },
  "exit": {
    "exit_time": "15:30",
    "profit_target": 5000,
    "max_loss": 2000
  },
  "execution": {
    "order_type": "MARKET",
    "product": "NRML"
  }
}
```

### 2. Create a Python Script to Load & Run

```python
#!/usr/bin/env python3
import logging
from shoonya_platform.strategies.delta_neutral.dnss import DNSS
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.execution.broker import ShoonyaBot

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize components
bot = ShoonyaBot()  # Your broker connection
runner = StrategyRunner(bot=bot, poll_interval=2.0)

# Strategy factory
def create_dnss_from_config(config):
    return DNSS(config)

# Load all strategies from JSON
results = runner.load_strategies_from_json(
    config_dir="shoonya_platform/strategies/saved_configs/",
    strategy_factory=create_dnss_from_config
)

# Check results
for name, success in results.items():
    if success:
        print(f"✅ {name} loaded successfully")
    else:
        print(f"❌ {name} failed to load")

# Start runner
runner.start()

# Keep running (this is production - operator controls lifecycle)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    runner.stop()
    logger.info("Shutdown complete")
```

### 3. Run It

```bash
python run_strategies.py
```

---

## Configuration Complete Reference

### Directory Structure

```
shoonya_platform/
├── strategies/
│   ├── find_option.py                    ← Core option lookup
│   ├── strategy_runner.py                ← Runner with JSON loading
│   ├── market_adapter_factory.py         ← Market adapter selection
│   ├── saved_configs/                    ← Your strategy JSON files
│   │   ├── NIFTY_DNSS.json
│   │   ├── BANKNIFTY_DNSS.json
│   │   ├── STRATEGY_CONFIG_SCHEMA.json  ← Schema reference
│   │   └── NIFTY_DNSS_TEMPLATE.json     ← Template to copy from
│   ├── database_market/
│   │   └── adapter.py                   ← SQLite adapter (uses find_option.py)
│   ├── live_feed_market/
│   │   └── adapter.py                   ← WebSocket adapter (uses find_option.py)
│   ├── delta_neutral/
│   │   └── dnss.py                      ← DNSS strategy implementation
│   └── engine/
│       └── engine.py                    ← Execution engine (frozen)
```

---

## Strategy JSON Configuration Reference

### Required Fields

```json
{
  "name": "STRATEGY_IDENTIFIER",           # ✅ Required - unique name
  "enabled": true,                         # ✅ Required - set to true to load
  "market_config": {                       # ✅ Required
    "market_type": "database_market",      # ✅ Required - "database_market" or "live_feed_market"
    "exchange": "NFO",                     # ✅ Required - NFO, MCX, NCDEX, CDSL
    "symbol": "NIFTY",                     # ✅ Required - underlying symbol
    "db_path": "/path/to/db.db"           # ✅ Required if market_type=database_market
  },
  "entry": {                               # ✅ Required
    "entry_time": "HH:MM"                  # ✅ Required - 24-hour format
  },
  "exit": {                                # ✅ Required
    "exit_time": "HH:MM"                   # ✅ Required - 24-hour format
  }
}
```

### Optional Fields

```json
{
  "description": "Strategy description",
  "version": "1.0.0",
  
  "entry": {
    "entry_type": "delta_neutral",         # Default: delta_neutral
    "target_ce_delta": 0.30,               # Default: none
    "target_pe_delta": 0.30,               # Default: none
    "delta_tolerance": 0.05,               # Default: 0.05
    "quantity": 10,                        # Default: none (required for actual execution)
    "max_attempts": 3                      # Default: 3
  },
  
  "adjustment": {
    "enabled": true,                       # Default: true
    "adjustment_type": "delta_drift",      # Default: delta_drift
    "delta_drift_trigger": 0.60,           # Default: none
    "rebalance_target_delta": 0.30,        # Default: none
    "cooldown_seconds": 60,                # Default: 60
    "max_adjustments_per_day": 5           # Default: 5
  },
  
  "exit": {
    "exit_type": "profit_target",          # Default: profit_target
    "profit_target": 5000,                 # Default: none
    "max_loss": 2000,                      # Default: none
    "profit_target_percent": 2,            # Alternative to profit_target
    "stop_loss_percent": 1,                # Alternative to max_loss
    "trailing_stop_enabled": false,        # Default: false
    "time_exit_override": true             # Default: true (exit at exit_time regardless)
  },
  
  "execution": {
    "order_type": "MARKET",                # Default: MARKET (LIMIT, STOP, STOP_LIMIT)
    "product": "NRML",                     # Default: NRML (MIS, CNC)
    "price_limit_percent": 1.0,            # Default: 1.0
    "timeout_seconds": 30                  # Default: 30
  },
  
  "risk_management": {
    "max_concurrent_legs": 2,              # Default: 2
    "max_position_size": 20,               # Default: none
    "max_total_loss": 10000,               # Default: none
    "max_daily_loss": 50000,               # Default: none
    "notional_value_limit": 500000,        # Default: none
    "vega_limit": 100,                     # Default: none
    "gamma_limit": 50                      # Default: none
  },
  
  "monitoring": {
    "poll_interval_seconds": 2,            # Default: 2
    "log_enabled": true,                   # Default: true
    "log_file": "logs/MY_STRATEGY.log",    # Default: console only
    "alert_enabled": true,                 # Default: true
    "alert_email": "email@example.com",    # Optional
    "alert_webhook": "https://...",        # Optional
    "metrics_collection": true             # Default: true
  },
  
  "backtesting": {
    "is_backtested": true,
    "backtest_dates": "2026-01-01 to 2026-01-31",
    "backtest_win_rate": 72.5,
    "backtest_avg_profit": 4500,
    "backtest_avg_loss": 1800
  }
}
```

---

## Common Error Prevention

### ✅ DO's

1. **Always validate database path exists**
   ```python
   from pathlib import Path
   db_path = "/path/to/option_chain.db"
   if not Path(db_path).exists():
       raise FileNotFoundError(f"Database not found: {db_path}")
   ```

2. **Check enable flag is true**
   ```json
   {
     "enabled": true  // Must be true to load
   }
   ```

3. **Use exact market_type values**
   ```json
   {
     "market_type": "database_market"   // ✅ Correct
     // "market_type": "websocket"         // ❌ Wrong!
     // "market_type": "live_feed"         // ❌ Wrong!
   }
   ```

4. **Check option returns before using**
   ```python
   option = find_option(field="delta", value=0.3)
   if option:
       delta = option['delta']
   else:
       logger.error("Option not found")
   ```

5. **Use absolute paths for files**
   ```json
   {
     "db_path": "/home/user/data/options.db"   // ✅ Absolute
     // "db_path": "data/options.db"              // ❌ Relative (breaks!)
   }
   ```

### ❌ DON'Ts

1. **Don't hardcode strategies in code**
   ```python
   # ❌ WRONG
   runner.register(name="NIFTY", strategy=dnss_instance, market=my_market)
   
   # ✅ RIGHT - Use JSON
   runner.load_strategies_from_json(config_dir="saved_configs/", strategy_factory=dnss_factory)
   ```

2. **Don't skip strategy.prepare()**
   ```python
   # ❌ WRONG - Direct registration
   runner.register(name="S1", strategy=strategy_instance, market=market)
   
   # ✅ RIGHT - prepare() called automatically by runner
   strategy_instance.prepare()  # Do this first
   ```

3. **Don't use wrong data types**
   ```json
   {
     "entry_time": "9:30"        // ❌ Wrong - must be HH:MM
     "entry_time": "09:30"       // ✅ Correct
   }
   ```

4. **Don't leave required fields empty**
   ```json
   {
     "name": "",               // ❌ Can't be empty
     "market_config": {},      // ❌ Need exchange, symbol, etc
     "exit_time": ""           // ❌ Can't be empty
   }
   ```

5. **Don't modify enabled strategies while running**
   ```python
   # ❌ WRONG - Don't do this
   runner.start()
   time.sleep(5)
   # ... modify JSON file ...
   
   # ✅ RIGHT - Stop, then reload
   runner.stop()
   results = runner.load_strategies_from_json(...)
   runner.start()
   ```

---

## Production Execution Patterns

### Pattern 1: Simple Startup

```python
#!/usr/bin/env python3
"""Simple production startup"""
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.strategies.delta_neutral.dnss import DNSS

runner = StrategyRunner(bot=bot)

# Load all strategies from JSON
results = runner.load_strategies_from_json(
    config_dir="saved_configs/",
    strategy_factory=lambda cfg: DNSS(cfg)
)

# Verify all loaded successfully
if not all(results.values()):
    failed = [k for k,v in results.items() if not v]
    print(f"Warning: {len(failed)} strategies failed to load: {failed}")

# Start execution
runner.start()

# Monitor
while runner.get_status()['running']:
    runner.print_metrics()
    time.sleep(60)
```

### Pattern 2: Gradual Startup with Validation

```python
#!/usr/bin/env python3
"""Careful production startup with validation"""
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.strategies.delta_neutral.dnss import DNSS
from pathlib import Path

def validate_config_file(json_path):
    """Validate before loading"""
    import json
    with open(json_path) as f:
        config = json.load(f)
    
    # Check required fields
    assert config.get("enabled") is not None
    assert config.get("name")
    assert config.get("market_config", {}).get("db_path")
    
    # Validate file exists
    db_path = config["market_config"]["db_path"]
    assert Path(db_path).exists(), f"DB not found: {db_path}"
    
    return True

# Validate all configs first
config_dir = Path("saved_configs")
configs = list(config_dir.glob("*.json"))

for config_file in configs:
    try:
        if validate_config_file(config_file):
            print(f"✅ {config_file.name} - Valid")
    except Exception as e:
        print(f"❌ {config_file.name} - {e}")
        continue

# Safe to load now
runner = StrategyRunner(bot=bot)
results = runner.load_strategies_from_json(
    config_dir="saved_configs/",
    strategy_factory=lambda cfg: DNSS(cfg)
)

# Load report
successful = [k for k,v in results.items() if v]
failed = [k for k,v in results.items() if not v]

print(f"Loaded: {len(successful)}")
print(f"Failed: {len(failed)}")

if successful:
    runner.start()
```

### Pattern 3: Multi-Strategy with Market Type Filtering

```python
#!/usr/bin/env python3
"""Run different strategies with different market types"""
from shoonya_platform.strategies.strategy_runner import StrategyRunner
from shoonya_platform.strategies.delta_neutral.dnss import DNSS
import json
from pathlib import Path

runners = {}

# Group strategies by market type
market_configs = {"database_market": [], "live_feed_market": []}

for config_file in Path("saved_configs").glob("*.json"):
    with open(config_file) as f:
        config = json.load(f)
    
    if config.get("enabled"):
        market_type = config.get("market_config", {}).get("market_type", "database_market")
        market_configs[market_type].append(config_file)

# Create separate runners for each market type
for market_type, configs in market_configs.items():
    if configs:
        runner = StrategyRunner(bot=bot, poll_interval=2.0)
        runner.load_strategies_from_json("saved_configs/", strategy_factory=lambda cfg: DNSS(cfg))
        runners[market_type] = runner
        print(f"Started runner for {market_type} with {len(configs)} strategies")

# Keep all running
for market_type, runner in runners.items():
    runner.start()
```

---

## Error Handling & Recovery

### Handling Load Errors

```python
results = runner.load_strategies_from_json(
    config_dir="saved_configs/",
    strategy_factory=lambda cfg: DNSS(cfg)
)

# Check each strategy
for name, success in results.items():
    if not success:
        print(f"⚠️ {name} failed to load - check logs for details")
        # Could retry or skip
        continue
```

### Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `FileNotFoundError: Database not found` | `db_path` doesn't exist or is wrong | Check path in JSON, ensure file exists |
| `KeyError: 'name'` | JSON missing required field | Use template, add required fields |
| `json.JSONDecodeError` | Invalid JSON syntax | Use JSON validator online |
| `AttributeError: 'NoneType' object has no attribute 'on_tick'` | Strategy factory returned None | Check factory function returns strategy instance |
| `enabled: true` but strategy not loading | Config has `enabled: false` | Check JSON file has `"enabled": true` |
| `No option found for ...` | Database lacks option data | Verify database has data for symbol/exchange |
| `Market adapter creation failed` | Config incomplete or invalid | Verify all market_config fields present |

### Graceful Shutdown

```python
runner = StrategyRunner(...)
runner.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Shutting down...")
    runner.stop()  # Graceful stop
    
    # Wait for thread to finish
    if runner._thread:
        runner._thread.join(timeout=5)
    
    # Print final metrics
    runner.print_metrics()
    print("Shutdown complete")
```

---

## Monitoring & Debugging

### Print Real-Time Metrics

```python
runner = StrategyRunner(...)
runner.start()

# Monitor every 60 seconds
for _ in range(60):
    runner.print_metrics()
    time.sleep(60)
```

### Output Example

```
================================================================================
📊 STRATEGY RUNNER METRICS
================================================================================
Global | ticks=120 | commands=45 | errors=0
--------------------------------------------------------------------------------
NIFTY_DNSS          | ticks=  60 | cmds=   22 | errs=  0 | avg=   15.3ms
BANKNIFTY_THETA     | ticks=  60 | cmds=   23 | errs=  0 | avg=   14.2ms
================================================================================
```

### Get Status

```python
status = runner.get_status()
print(f"Running: {status['running']}")
print(f"Total strategies: {status['total_strategies']}")
print(f"Strategy names: {status['strategy_names']}")
```

### Access Metrics Programmatically

```python
metrics = runner.get_metrics()

# Global metrics
print(f"Total ticks: {metrics['global']['total_ticks']}")
print(f"Total errors: {metrics['global']['total_errors']}")

# Per-strategy metrics
for name, m in metrics['strategies'].items():
    print(f"{name}: {m['total_ticks']} ticks, {m['total_errors']} errors")
```

---

## Troubleshooting Guide

### Strategy Not Loading

```
❌ Strategy failed but I don't know why
```

**Solution:** Check logs

```python
import logging
logging.basicConfig(level=logging.DEBUG)  # Enable debug logs
runner = StrategyRunner(...)
results = runner.load_strategies_from_json(...)
# Now check console output for detailed errors
```

### Option Not Found

```
❌ No option found for delta=0.3 CE
```

**Solution:** Database might not have data

```python
from shoonya_platform.strategies.find_option import find_options

# Get all CE options for symbol
all_ce = find_options(field="delta", symbol="NIFTY", limit=10)
print(f"Available CE deltas: {[o['delta'] for o in all_ce]}")

# If empty, database needs data loading
```

### High Error Rate

```
❌ Many errors in metrics
```

**Solution:** Check error logs

```python
# Get individual strategy metrics
metrics = runner.get_metrics()
for name, m in metrics['strategies'].items():
    if m['total_errors'] > 0:
        print(f"⚠️ {name} has {m['total_errors']} errors")
        # Check logs for {name} to see what went wrong
```

### Memory Leak

```
❌ Process memory keeps growing
```

**Solution:** Ensure cleanup on shutdown

```python
runner.stop()     # This must be called
runner._thread.join(timeout=5)

# All connections should be closed now
```

---

## Pre-Production Checklist

- [ ] All JSON configs have `enabled: true` or `enabled: false` (no missing field)
- [ ] All database paths exist and are readable
- [ ] All symbols/exchanges are correct
- [ ] Risk limits are configured appropriately
- [ ] Exit times are before market close
- [ ] Logging is configured (file paths writable)
- [ ] Alerts configured (if using webhooks)
- [ ] Tested with small position sizes first
- [ ] Operator trained on shutdown procedure
- [ ] Monitoring dashboard/script is running
- [ ] Error logs are being captured

---

## Production Deployment Commands

### Start Production

```bash
# Terminal 1 - Run strategy
python production_runner.py

# Terminal 2 - Monitor
python monitor_runner.py
```

### Stop Production

```bash
# Graceful shutdown
Ctrl+C (in Terminal 1)

# OR send signal
kill -TERM <pid>
```

### Restart All Strategies

```bash
# 1. Stop
kill -TERM <pid>

# 2. Wait for graceful shutdown (5 seconds max)
sleep 5

# 3. Restart
python production_runner.py
```

### Emergency Stop (if hung)

```bash
# Force kill (last resort)
kill -9 <pid>

# This may leave positions open!
# Operator must close manually in OMS
```

---

## Summary

✅ **You can now run strategies error-free in production:**

1. Create JSON config in `saved_configs/` directory
2. Load with `runner.load_strategies_from_json()`
3. Start runner with `.start()`
4. Monitor with metrics or logs
5. Stop with `.stop()` or Ctrl+C

**Key Points:**
- All option lookup consolidated to `find_option.py`
- Adapters automatically selected by `market_type` latch
- JSON loading validates config before registration
- Metrics collection is automatic and passive
- No hidden behavior or auto-recovery

**You've got this!** 🚀
