# 🐛 STRATEGY SYSTEM BUGS FIXED

## Summary
Fixed **2 critical bugs** in `shoonya_platform/execution/trading_bot.py` that were blocking strategy execution.

---

## Bug #1: Exception Handling Logic Error ⚠️

### Location
[shoonya_platform/execution/trading_bot.py](shoonya_platform/execution/trading_bot.py#L514-L540) - `request_entry()` method
[shoonya_platform/execution/trading_bot.py](shoonya_platform/execution/trading_bot.py#L542-L563) - `request_adjust()` method

### The Problem
The `raise` statement was **OUTSIDE** the `except` block:

```python
def request_entry(self, strategy_name: str):
    with self._live_strategies_lock:
        try:
            strategy, market = self._live_strategies[strategy_name]
        except KeyError:
            logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
            logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
        raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")  # ← ALWAYS RUNS!
    # ...
```

### Why This Breaks
- ✅ If strategy **exists** → line retrieved successfully → code continues → works okay
- ❌ If strategy **doesn't exist** → KeyError caught → logged → raise ALWAYS executes
- ❌ **Even if strategy exists**, the raise is on the wrong indentation level!

This means **ALL calls to `request_entry()` and `request_adjust()` would fail** regardless of whether the strategy existed.

### The Fix
Moved the `raise` **inside** the except block:

```python
def request_entry(self, strategy_name: str):
    with self._live_strategies_lock:
        try:
            strategy, market = self._live_strategies[strategy_name]
        except KeyError:
            logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
            raise RuntimeError(f"Strategy not registered on this bot: {strategy_name}")  # ✅ NOW INSIDE EXCEPT
    # ...
```

---

## Bug #2: Duplicate Error Logging

### Location
Same two methods

### The Problem
Error message was logged **twice**:

```python
except KeyError:
    logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)
    logger.error("Request ENTRY failed: strategy not registered: %s", strategy_name)  # ← DUPLICATE
```

### The Fix
Removed duplicate line

---

## Impact

### What Was Broken
- ❌ Strategy execution via `request_entry()` - **COMPLETELY BROKEN**
- ❌ Strategy adjustments via `request_adjust()` - **COMPLETELY BROKEN**
- ❌ Any external call to execute strategy intents

### What This Fixes
- ✅ Strategy execution calls now work when strategy is registered
- ✅ Strategy adjustment calls now work
- ✅ Test framework can properly test strategy execution
- ✅ Dashboard can call strategy methods without exceptions

---

## Files Changed
- [shoonya_platform/execution/trading_bot.py](shoonya_platform/execution/trading_bot.py)
  - Line 514-540: `request_entry()` method
  - Line 542-563: `request_adjust()` method

---

## How to Verify
```bash
# Run strategy tests
python -m pytest tests/test_strategy_runner.py -v

# Run specific test for execution
python -m pytest tests/test_strategy_runner.py::TestStrategyRunner::test_request_entry -v
```

---

## Related Issues Being Investigated
Based on docs analysis:
- `test_strategy_runner.py` has 13 failing tests (test_execution_results.md)
- Some tests may fail due to MarketAdapterFactory validation
- Need to check if market adapter creation is properly configured

---

## Status
✅ **FIXED** - Code changes applied and committed
