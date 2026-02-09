# Legacy Strategy Runners

This folder contains **DEPRECATED** strategy runner files that are no longer in active use.

## ⚠️ Do NOT Use These Files

These files are kept for historical reference only. They contain outdated approaches and have been replaced by better implementations.

---

## Legacy Files

### `run.py`
- **Status:** Deprecated
- **Replaced by:** [strategy_runner.py](../strategy_runner.py)
- **Reason:** Old runner without proper OMS compliance and thread safety

### `db_run.py`
- **Status:** Deprecated  
- **Replaced by:** [strategy_runner.py](../strategy_runner.py) + [strategy_run_writer.py](../strategy_run_writer.py)
- **Reason:** Mixed database logic with strategy execution

### `db_based_run.py`
- **Status:** Deprecated
- **Replaced by:** [strategy_runner.py](../strategy_runner.py) + [strategy_run_writer.py](../strategy_run_writer.py)
- **Reason:** Similar to db_run.py, mixed concerns

---

## ✅ Current Production Files

Use these files instead (located in parent `strategies/` folder):

### **strategy_runner.py**
Production-ready strategy runner with:
- ✅ OMS-compliant order placement via execution service
- ✅ Multi-strategy parallel execution
- ✅ Thread-safe strategy management
- ✅ Proper error handling and logging
- ✅ DB persistence integration

### **strategy_run_writer.py**
Database writer for strategy runs:
- ✅ Strategy run tracking
- ✅ Event logging
- ✅ Performance metrics
- ✅ Separate from execution logic

### **delta_neutral/**
Active delta neutral short strategy:
- ✅ Production-ready implementation
- ✅ Configuration-driven
- ✅ Works with strategy_runner.py

---

## Migration Notes

If you have code referencing the legacy files:

1. **Replace imports:**
   ```python
   # OLD
   from shoonya_platform.strategies.run import ...
   
   # NEW
   from shoonya_platform.strategies.strategy_runner import StrategyRunner
   ```

2. **Use OMS-compliant execution:**
   ```python
   # OLD - Direct broker API calls
   broker.place_order(...)
   
   # NEW - Via execution service
   execution_client.submit_intent(...)
   ```

3. **Separate DB concerns:**
   ```python
   # OLD - Mixed in runner
   runner.run_and_save_to_db()
   
   # NEW - Separate writer
   writer = StrategyRunWriter()
   writer.write_run_start(...)
   ```

---

**Last Updated:** 2026-02-09  
**Moved to legacy:** 2026-02-09
