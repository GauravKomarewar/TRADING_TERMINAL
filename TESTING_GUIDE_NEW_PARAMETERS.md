# TESTING GUIDE - New Parameters
## Quick Reference for both_legs_delta Fix

═══════════════════════════════════════════════════════════════════════

## NEW PARAMETERS USAGE

### 1. both_legs_delta_below ✅

**Use Case**: Check if BOTH legs are below a threshold

**Operators**: `<`, `<=`

**Example**:
```json
{
  "parameter": "both_legs_delta_below",
  "comparator": "<",
  "value": 0.3
}
```

**Logic**: Returns `max(CE_delta, PE_delta)`
- If max < 0.3, then BOTH legs are < 0.3 ✅

**Test Scenarios**:
| CE Delta | PE Delta | Condition | Result | Correct? |
|----------|----------|-----------|--------|----------|
| 0.2      | 0.25     | < 0.3     | TRUE   | ✅       |
| 0.2      | 0.35     | < 0.3     | FALSE  | ✅       |
| 0.4      | 0.5      | < 0.3     | FALSE  | ✅       |

---

### 2. both_legs_delta_above ✅

**Use Case**: Check if BOTH legs are above a threshold

**Operators**: `>`, `>=`

**Example**:
```json
{
  "parameter": "both_legs_delta_above",
  "comparator": ">",
  "value": 0.3
}
```

**Logic**: Returns `min(CE_delta, PE_delta)`
- If min > 0.3, then BOTH legs are > 0.3 ✅

**Test Scenarios**:
| CE Delta | PE Delta | Condition | Result | Correct? |
|----------|----------|-----------|--------|----------|
| 0.4      | 0.5      | > 0.3     | TRUE   | ✅       |
| 0.2      | 0.5      | > 0.3     | FALSE  | ✅       |
| 0.2      | 0.25     | > 0.3     | FALSE  | ✅       |

---

### 3. min_leg_delta ✅

**Use Case**: Get the minimum delta value

**Operators**: Any

**Example**:
```json
{
  "parameter": "min_leg_delta",
  "comparator": ">",
  "value": 0.2
}
```

**Logic**: Returns `min(CE_delta, PE_delta)`
- Use for general minimum delta checks

**Test Scenarios**:
| CE Delta | PE Delta | min_leg_delta | 
|----------|----------|---------------|
| 0.2      | 0.5      | 0.2           |
| 0.5      | 0.3      | 0.3           |
| 0.4      | 0.4      | 0.4           |

---

### 4. max_leg_delta ✅

**Use Case**: Get the maximum delta value

**Operators**: Any

**Example**:
```json
{
  "parameter": "max_leg_delta",
  "comparator": "<",
  "value": 0.5
}
```

**Logic**: Returns `max(CE_delta, PE_delta)`
- Use for general maximum delta checks

**Test Scenarios**:
| CE Delta | PE Delta | max_leg_delta | 
|----------|----------|---------------|
| 0.2      | 0.5      | 0.5           |
| 0.5      | 0.3      | 0.5           |
| 0.4      | 0.4      | 0.4           |

---

### 5. both_legs_delta (DEPRECATED) ⚠️

**Status**: Deprecated but still works

**Warning**: Will show warning message in logs and config validation

**Behavior**: Same as `both_legs_delta_below` (returns max)

**Migration**:
- Replace with `both_legs_delta_below` for `<` comparisons
- Replace with `both_legs_delta_above` for `>` comparisons

═══════════════════════════════════════════════════════════════════════

## MIGRATION EXAMPLES

### Before (WRONG for > operator):
```json
{
  "conditions": [
    {
      "parameter": "both_legs_delta",
      "comparator": ">",
      "value": 0.3,
      "description": "Both legs delta > 0.3"
    }
  ]
}
```
**Problem**: Checks if max(delta) > 0.3, not if BOTH > 0.3 ❌

---

### After (CORRECT):
```json
{
  "conditions": [
    {
      "parameter": "both_legs_delta_above",
      "comparator": ">",
      "value": 0.3,
      "description": "Both legs delta > 0.3"
    }
  ]
}
```
**Fixed**: Checks if min(delta) > 0.3, ensuring BOTH > 0.3 ✅

═══════════════════════════════════════════════════════════════════════

## COMPLETE TEST STRATEGY CONFIG

```json
{
  "name": "Test Both Legs Delta Fix",
  "basic": {
    "exchange": "NFO",
    "underlying": "NIFTY",
    "expiry_mode": "weekly_current",
    "lots": 1
  },
  "timing": {
    "entry_time": "09:20",
    "exit_time": "15:20"
  },
  "entry": {
    "rule_type": "if_then",
    "conditions": {
      "operator": "AND",
      "rules": [
        {
          "parameter": "time_current",
          "comparator": ">=",
          "value": "09:20",
          "description": "After 9:20 AM"
        },
        {
          "parameter": "both_legs_delta_below",
          "comparator": "<",
          "value": 0.3,
          "description": "Both legs delta < 0.3"
        }
      ]
    },
    "action": {
      "type": "short_straddle",
      "atm_offset": 0
    }
  },
  "exit": {
    "rule_type": "if_any",
    "conditions": [
      {
        "parameter": "combined_pnl",
        "comparator": ">",
        "value": 5000,
        "description": "Target profit"
      },
      {
        "parameter": "combined_pnl",
        "comparator": "<",
        "value": -2000,
        "description": "Stop loss"
      },
      {
        "parameter": "both_legs_delta_above",
        "comparator": ">",
        "value": 0.5,
        "description": "Both legs delta > 0.5"
      }
    ],
    "action": {
      "type": "close_all_positions"
    }
  },
  "adjustment": {
    "enabled": false
  },
  "market_data": {
    "source": "database",
    "db_path": "/path/to/market_data.db"
  }
}
```

═══════════════════════════════════════════════════════════════════════

## UNIT TEST CASES

### Python Test Code

```python
def test_both_legs_delta_parameters():
    """Test the fixed both_legs_delta parameters."""
    from shoonya_platform.strategy_runner.condition_engine import StrategyState
    
    # Setup state
    state = StrategyState()
    state.ce_delta = 0.2
    state.pe_delta = 0.4
    
    # Test 1: both_legs_delta_below
    result = state.get_param("both_legs_delta_below")
    assert result == 0.4, f"Expected 0.4, got {result}"
    print("✅ Test 1 passed: both_legs_delta_below returns max(0.2, 0.4) = 0.4")
    
    # Test 2: both_legs_delta_above
    result = state.get_param("both_legs_delta_above")
    assert result == 0.2, f"Expected 0.2, got {result}"
    print("✅ Test 2 passed: both_legs_delta_above returns min(0.2, 0.4) = 0.2")
    
    # Test 3: min_leg_delta
    result = state.get_param("min_leg_delta")
    assert result == 0.2, f"Expected 0.2, got {result}"
    print("✅ Test 3 passed: min_leg_delta returns 0.2")
    
    # Test 4: max_leg_delta
    result = state.get_param("max_leg_delta")
    assert result == 0.4, f"Expected 0.4, got {result}"
    print("✅ Test 4 passed: max_leg_delta returns 0.4")
    
    print("\n🎉 All tests passed!")

if __name__ == "__main__":
    test_both_legs_delta_parameters()
```

### Expected Output
```
✅ Test 1 passed: both_legs_delta_below returns max(0.2, 0.4) = 0.4
✅ Test 2 passed: both_legs_delta_above returns min(0.2, 0.4) = 0.2
✅ Test 3 passed: min_leg_delta returns 0.2
✅ Test 4 passed: max_leg_delta returns 0.4

🎉 All tests passed!
```

═══════════════════════════════════════════════════════════════════════

## VALIDATION TEST

### Config Validation Test

```python
def test_deprecated_parameter_warning():
    """Test that deprecated parameter shows warning."""
    from shoonya_platform.strategy_runner.config_schema import validate_config
    
    config = {
        "name": "Test Strategy",
        "basic": {"exchange": "NFO", "underlying": "NIFTY", "lots": 1},
        "timing": {"entry_time": "09:20", "exit_time": "15:20"},
        "entry": {
            "rule_type": "if_then",
            "conditions": {
                "parameter": "both_legs_delta",  # DEPRECATED
                "comparator": ">",
                "value": 0.3
            },
            "action": {"type": "short_straddle"}
        },
        "exit": {
            "rule_type": "if_any",
            "conditions": [],
            "action": {"type": "close_all_positions"}
        },
        "market_data": {"source": "database", "db_path": "/tmp/test.db"}
    }
    
    is_valid, errors = validate_config(config)
    
    # Should have warning about deprecated parameter
    warnings = [e for e in errors if e.severity == "warning"]
    assert len(warnings) > 0, "Expected deprecation warning"
    
    warning_text = str(warnings[0])
    assert "deprecated" in warning_text.lower(), "Warning should mention deprecation"
    assert "both_legs_delta_above" in warning_text, "Warning should suggest alternative"
    
    print("✅ Deprecation warning test passed")
    print(f"   Warning: {warnings[0].message}")

if __name__ == "__main__":
    test_deprecated_parameter_warning()
```

═══════════════════════════════════════════════════════════════════════

## INTEGRATION TEST

### Full Strategy Test

```python
async def test_full_strategy_execution():
    """Test complete strategy with new parameters."""
    from shoonya_platform.strategy_runner.strategy_executor_service import StrategyExecutor
    from shoonya_platform.strategy_runner.config_schema import validate_config
    
    # Load test config
    config = load_test_config()  # Your test config JSON
    
    # Validate
    is_valid, errors = validate_config(config)
    if not is_valid:
        print("❌ Config validation failed:")
        for error in errors:
            if error.severity == "error":
                print(f"   ERROR: {error}")
    
    # Create executor
    executor = StrategyExecutor(bot=mock_bot, db_path="/tmp/test_state.db")
    
    # Register strategy
    await executor.register_strategy(config)
    
    # Simulate market data
    await executor.tick()
    
    # Check state
    state = executor._engine_states.get(config["name"])
    assert state is not None, "Strategy state should exist"
    
    print("✅ Integration test passed")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_full_strategy_execution())
```

═══════════════════════════════════════════════════════════════════════

## QUICK REFERENCE TABLE

| Parameter                | Returns      | Use With | Use Case                    |
|--------------------------|--------------|----------|-----------------------------|
| both_legs_delta_below    | max(CE, PE)  | < <=     | Both legs below threshold   |
| both_legs_delta_above    | min(CE, PE)  | > >=     | Both legs above threshold   |
| min_leg_delta            | min(CE, PE)  | Any      | General minimum delta       |
| max_leg_delta            | max(CE, PE)  | Any      | General maximum delta       |
| any_leg_delta            | max(CE, PE)  | > >=     | At least one leg exceeds    |
| both_legs_delta (⚠️)     | max(CE, PE)  | < only   | DEPRECATED - use above      |

═══════════════════════════════════════════════════════════════════════

## COMMON MISTAKES TO AVOID

### ❌ WRONG: Using both_legs_delta with >
```json
{
  "parameter": "both_legs_delta",
  "comparator": ">",
  "value": 0.3
}
```
This will only check if ANY leg > 0.3, not BOTH!

### ✅ CORRECT: Using both_legs_delta_above with >
```json
{
  "parameter": "both_legs_delta_above",
  "comparator": ">",
  "value": 0.3
}
```
This correctly checks if BOTH legs > 0.3

---

### ❌ WRONG: Using both_legs_delta_above with <
```json
{
  "parameter": "both_legs_delta_above",
  "comparator": "<",
  "value": 0.3
}
```
Wrong semantic - "above" should be used with >, not <

### ✅ CORRECT: Using both_legs_delta_below with <
```json
{
  "parameter": "both_legs_delta_below",
  "comparator": "<",
  "value": 0.3
}
```
Correct semantic - "below" used with <

═══════════════════════════════════════════════════════════════════════

## SUMMARY

**Fixed Parameters**: 5 new parameters added
**Deprecated**: 1 parameter (both_legs_delta) kept for backward compatibility
**Testing**: Use test cases above to verify fixes
**Migration**: Update existing configs to use new parameters
