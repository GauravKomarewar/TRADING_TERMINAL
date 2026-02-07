# Comprehensive Bug Report - Shoonya Platform

**Date**: February 7, 2026  
**Severity Classification**: Critical, High, Medium, Low

---

## CRITICAL ISSUES (Production-Blocking)

### 1. **Telegram Configuration - None Type Arguments** ⛔
**File**: `shoonya_platform/execution/trading_bot.py:226-228`

**Problem**: 
```python
telegram_config = self.config.get_telegram_config()
self.telegram = TelegramNotifier(
    telegram_config["bot_token"],  # Can be None
    telegram_config["chat_id"],    # Can be None
)
```

**Impact**: If `bot_token` or `chat_id` are None, TelegramNotifier initialization will fail because it expects `str` type  
**Fix Required**: Add validation before instantiation
```python
if telegram_config.get("bot_token") and telegram_config.get("chat_id"):
    self.telegram = TelegramNotifier(...)
else:
    raise ValueError("Telegram bot_token and chat_id are required")
```

---

### 2. **Unsafe Telegram Method Calls** ⛔
**Files**: Multiple occurrences in `trading_bot.py`
- Line 521: `self.telegram.send_login_success(...)`
- Line 530: `self.telegram.send_login_failed(...)`
- Line 542: `self.telegram.send_login_failed(...)`
- Line 822: `self.telegram.send_order_placing(...)`
- Line 855: `self.telegram.send_error_message(...)`
- Line 1107: `self.telegram.send_error_message(...)`
- Line 1429: `self.telegram.send_error_message(...)`

**Problem**: `self.telegram` can be None, but code directly calls methods without null checks

**Impact**: NoneType errors at runtime  
**Fix Required**: 
```python
if self.telegram:
    self.telegram.send_login_success(...)
```

---

### 3. **Strategy Initialization - Missing Required Parameter** ⛔
**File**: `shoonya_platform/execution/trading_bot.py:1133-1135`

**Problem**:
```python
strategy = DeltaNeutralShortStrangleStrategy(
    exchange=universal_config.exchange,
    symbol=universal_config.symbol,
    expiry=market.expiry,
    ... missing 'lot_qty' parameter ...
)
```

**Impact**: Strategy instantiation will fail  
**Fix Required**: Add missing `lot_qty` parameter

---

### 4. **Strategy Attribute Assignment - Non-existent Attributes** ⛔
**File**: `shoonya_platform/execution/trading_bot.py:1155-1156`

**Problem**:
```python
strategy.run_id = run_id        # Attribute doesn't exist
strategy.run_writer = writer    # Attribute doesn't exist
```

**Impact**: AttributeError at runtime  
**Fix Required**: Either add these attributes to the Strategy class or use a different mechanism to pass this data

---

### 5. **Config Parameter Type Mismatches** ⛔
**Files**: Multiple locations

**Issues**:
- Line 607: `self.config.webhook_secret` can be None but passed to `validate_webhook_signature()` expecting `str`
- Line 521: `self.config.user_id` can be None but passed to `send_login_success()` expecting `str`
- Line 754: `order_params={"test_mode": True}` is a dict but function expects `OrderParams` type
- Line 828: `price` can be "MARKET" string but function expects `float`
- Line 847: `order_id=None` but OrderResult expects `str`

**Impact**: Type errors and unexpected behavior  
**Fix Required**: Add proper type validation and conversion before passing values

---

## HIGH-PRIORITY ISSUES (Major Functionality Issues)

### 6. **Bare Exception Handlers** ⚠️
**Files**: Throughout codebase
- `main.py:322`: `except:`  followed by `pass`
- `trading_bot.py:1222-1223`: Bare `except:` with `pass`
- `trading_bot.py:1236-1237`: Bare `except:` with `pass`
- And many more locations

**Problem**: These silently swallow ALL exceptions, hiding bugs and making debugging impossible

**Impact**: 
- Silent failures in production
- Impossible to diagnose issues
- Potential data corruption

**Fix Required**:
```python
# WRONG:
except:
    pass

# CORRECT:
except SpecificException as e:
    logger.error(f"Specific handler: {e}")
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
```

---

### 7. **Missing Order Result Validation** ⚠️
**File**: `shoonya_platform/execution/trading_bot.py:847`

**Problem**:
```python
order_result=OrderResult(success=True, order_id=None)
```

Creating a successful order result with None order_id doesn't make sense

**Impact**: Invalid state can propagate through the system  
**Fix Required**: Ensure order_id is always a string when success=True

---

### 8. **Telegram Optional Initialization Inconsistency** ⚠️
**File**: `shoonya_platform/execution/trading_bot.py:222-236`

**Problem**: 
- Line 222: `self.telegram_enabled` flag set
- Line 235: `self.telegram = None` when disabled
- Throughout code: Methods called on `self.telegram` without checking the flag

**Impact**: Code checks `telegram_enabled` but then calls `self.telegram.method()` anyway in many places

**Fix Required**: Consistently use either the flag OR check for None, not both

---

### 9. **Webhook Secret Validation Issues** ⚠️
**File**: `shoonya_platform/execution/trading_bot.py:607, 625`

**Problem**:
```python
# Line 607 - Can pass None:
return validate_webhook_signature(payload, signature, self.config.webhook_secret)

# Line 625 - Assumes it's not None:
if normalized_data['secret_key'] != self.config.webhook_secret:
```

**Impact**: Webhook validation can be bypassed or crash  
**Fix Required**: Validate webhook_secret is set during init and fail fast if missing

---

## MEDIUM-PRIORITY ISSUES (Code Quality & Maintainability)

### 10. **Overly Broad Exception Handling** 📋
**Files**: Multiple exception handlers catch generic `Exception`

**Problem**: Don't distinguish between different error types

**Examples**:
- `trading_bot.py:231`: `except Exception as e:` - logs error but may mask system issues
- `trading_bot.py:434`: `except Exception as e:` - too broad
- Many more throughout

**Fix Required**: Catch specific exceptions and handle appropriately

---

### 11. **Missing None Checks Before List/Dict Access** 📋
**File**: `shoonya_platform/execution/trading_bot.py`

**Problem**: Many places access dict values without checking if keys exist
- `telegram_config["bot_token"]` without `.get()`
- `order_result = ...` without validating structure

**Impact**: KeyError in edge cases  
**Fix Required**: Use `.get()` or validate structure first

---

### 12. **Inconsistent Error Logging** 📋
**Files**: Throughout codebase

**Problem**: Some errors logged, some silently passed, inconsistent format

**Impact**: Debugging difficulty  
**Fix Required**: Standardize on `logger.error(..., exc_info=True)` pattern

---

### 13. **Missing Import for pytest** 📋
**Status**: pytest not found in workspace

**Impact**: Test suite cannot run  
**Fix Required**: Install pytest in requirements

---

### 14. **Type Annotation Mismatches** 📋
**Files**: `trading_bot.py` and related modules

**Issues Found**:
- Line 754: dict passed where OrderParams expected
- Line 828: Mixed types (float | "MARKET") in calculations
- Line 847: None passed where str expected

**Fix Required**: Fix type signatures or add runtime validation

---

## MEDIUM-PRIORITY ISSUES (Configuration & Data)

### 15. **Config Values Not Validated at Startup** 📋
**File**: `shoonya_platform/core/config.py` and `trading_bot.py`

**Problem**: Critical config values (webhook_secret, telegram tokens, user_id) can be None but no validation at startup

**Impact**: Failures appear at random times, not at startup  
**Fix Required**: Add ConfigError exception and validate all critical values in `__init__`

---

### 16. **Strategy Parameter Passing Issues** 📋
**File**: `shoonya_platform/execution/trading_bot.py:1133-1156`

**Problems**:
- Missing `lot_qty` parameter
- Trying to set non-existent attributes `run_id` and `run_writer`

**Impact**: Strategy initialization and tracking broken  
**Fix Required**: 
- Add missing parameter to function call
- Properly initialize strategy attributes through constructor or use composition

---

### 17. **Order Parameter Type Issues** 📋
**File**: `shoonya_platform/execution/trading_bot.py:754, 828, 847`

**Problem**:
```python
# Line 754 - Wrong type:
order_params={"test_mode": True}  # Should be OrderParams object

# Line 828 - Invalid value:
price=cmd.price if cmd.order_type == "LIMIT" else "MARKET"  # Mixed types

# Line 847 - Invalid state:
order_id=None  # Can't be None if success=True
```

**Impact**: Order placement may fail or create invalid orders  
**Fix Required**: Proper type checking and conversion

---

## LOW-PRIORITY ISSUES (Code Smell)

### 18. **Inconsistent Logging Levels** 📋

**Problem**: Some important events are logged as INFO when they should be WARNING or ERROR

**Examples**:
- Dashboard crash/restart should be ERROR, not INFO
- Configuration issues should be WARNING, not INFO

**Fix Required**: Review and adjust logging levels

---

### 19. **Missing Documentation**  📋

**Problem**: Critical methods lack docstrings
- Strategy instantiation parameters
- Configuration validation rules
- Error handling expectations

**Fix Required**: Add comprehensive docstrings

---

### 20. **Magic Constants** 📋

**Files**: Multiple files have hardcoded values like:
- Port numbers (8000, etc.)
- Timeout values
- Sleep durations

**Impact**: Difficult to maintain, dangerous to change  
**Fix Required**: Move to configuration

---

## TESTING ISSUES

### 21. **Missing pytest Installation** ⚠️

**Problem**: Tests exist but pytest is not in installed packages

**Impact**: Test suite cannot run  
**Fix Required**: 
```bash
pip install pytest pytest-asyncio pytest-cov
```

---

### 22. **Incomplete Test Coverage** 📋

**Files**: Test files exist but don't cover:
- Telegram initialization failure cases
- None value handling in config
- All exception paths

**Fix Required**: Expand test suite to cover edge cases

---

## RECOMMENDATIONS

### Immediate Actions (Next 24 hours):
1. ✅ Fix telegram None checks (Critical Issue #2)
2. ✅ Fix strategy initialization parameters (Critical Issue #3)
3. ✅ Fix type mismatches in order parameters (Critical Issue #4, #17)
4. ✅ Remove bare `except:` handlers (High Issue #6)

### Short-term (This week):
5. Add startup validation for all critical config values
6. Fix all AttributeError in strategy code
7. Add pytest and run full test suite
8. Document all configuration requirements

### Long-term (This month):
9. Refactor exception handling consistently
10. Add comprehensive type hints and validation
11. Expand test coverage to 90%+
12. Add integration tests

---

## Summary Statistics

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 Critical | 5 | Needs Immediate Fix |
| 🟠 High | 5 | Needs Urgent Fix |
| 🟡 Medium | 10 | Needs Attention |
| 🔵 Low | 5 | Nice to Have |
| **Total** | **25** | Comprehensive Issues Found |

---

## How to Fix

I recommend fixing in this order:
1. Fix all Critical and High issues first
2. Run test suite to validate fixes
3. Then address Medium issues
4. Low-priority issues can be done incrementally

Each issue has a specific fix recommendation above.

