# File Naming Audit - System Standardization

**Finding**: ✅ 3 `models.py` files with DIFFERENT purposes → Need clear naming

---

## 1. Current Situation - Three Different `models.py` Files

### Problem
```
❌ domain/models.py
❌ execution/models.py  
❌ persistence/models.py

Same name = Confusion about which one to import!
```

### What Each Does

#### A. **domain/models.py** (275 lines)
```python
Exports: TradeRecord, OrderParams, LegData, AlertData, 
         OrderResult, LegResult, AccountInfo, BotStats

Purpose: Business domain layer - what happened in trades
Used by: OMS (trading_bot.py), Dashboard, Reporting
```

#### B. **execution/models.py** (19 lines)
```python
Exports: Intent

Purpose: Simple strategy intent (what to execute)
Structure:
  - action: BUY | SELL
  - symbol: NIFTY
  - qty: 50
  - tag: ENTRY_CE
  - order_type: MKT | LMT
  - price: float

Used by: 
  - strategies/engine/engine.py (executes it)
  - strategies/engine/engine_no_recovery.py (executes it)
  - execution/broker.py (converts to order)
```

#### C. **persistence/models.py** (100+ lines)
```python
Exports: OrderRecord

Purpose: Database persistence model for order storage
Used by: persistence layer (storing to DB)
```

### Additional Problem: Two Different "Command" Classes

#### D. **execution/intent.py** (385 lines)
```python
Exports: UniversalOrderCommand

Purpose: Full-featured order command with all parameters
Structure: Immutable dataclass with:
  - command_id, created_at, source, user
  - exchange, symbol, quantity, side, product
  - order_type, price
  - stop_loss, target, trailing_type, trailing_value
  - broker_order_id, execution_type
  - status, tag, etc.

Used by:
  - strategies/delta_neutral/dnss.py (creates orders)
  - services/recovery_service.py (recovery)
  - services/orphan_position_manager.py (orphan handling)
  - execution/trading_bot.py (main OMS loop)
  - execution/validation.py (validates)
  - execution/order_watcher.py (watches)
  - execution/command_service.py (processes)
```

---

## 2. Naming Issues Identified ✅

### Issue #1: Three `models.py` Files (DIFFERENT purposes)
```
Problem: 
  from shoonya_platform.domain.models import ...
  from shoonya_platform.execution.models import ... 
  from shoonya_platform.persistence.models import ...

Which one are you importing? Confusing!
```

### Issue #2: Intent (models.py) vs UniversalOrderCommand (intent.py)
```
Problem:
  - execution/models.py has Intent class
  - execution/intent.py has UniversalOrderCommand class
  
Both are "intent/command" concepts but:
  - Different names
  - Different purposes
  - Different file locations
  
Confusing which one to use when!
```

---

## 3. Recommended Renaming Strategy

### Step 1: Rename `execution/models.py` → `execution/strategy_intent.py`

**Why:** 
- Makes it CLEAR this is a strategy-level intent
- Separates from business domain models
- Distinguishes from UniversalOrderCommand

**Action:**
```
execution/models.py → execution/strategy_intent.py

Exports:
  class StrategyIntent:  (renamed from Intent)
    action: "BUY" | "SELL"
    symbol: str
    qty: int
    tag: str
    order_type: "MKT" | "LMT"
    price: float
```

**Update Imports (3 files):**
```
strategies/engine/engine.py
  OLD: from shoonya_platform.execution.models import Intent
  NEW: from shoonya_platform.execution.strategy_intent import StrategyIntent

strategies/engine/engine_no_recovery.py  
  OLD: from shoonya_platform.execution.models import Intent
  NEW: from shoonya_platform.execution.strategy_intent import StrategyIntent

execution/broker.py
  OLD: from shoonya_platform.execution.models import Intent
  NEW: from shoonya_platform.execution.strategy_intent import StrategyIntent
```

### Step 2: Rename `domain/models.py` → `domain/business_models.py`

**Why:**
- Clearly identifies as application business domain
- Distinguishes from persistence models
- Avoids confusion with three `models.py` files

**Action:**
```
domain/models.py → domain/business_models.py

Exports:
  TradeRecord, OrderParams, LegData, AlertData,
  OrderResult, LegResult, AccountInfo, BotStats
```

**Update Imports (2 files):**
```
execution/trading_bot.py
  OLD: from shoonya_platform.domain.models import TradeRecord, AlertData, ...
  NEW: from shoonya_platform.domain.business_models import TradeRecord, AlertData, ...

brokers/shoonya/client.py
  OLD: from shoonya_platform.domain.models import OrderResult, AccountInfo
  NEW: from shoonya_platform.domain.business_models import OrderResult, AccountInfo
```

### Step 3: Rename `persistence/models.py` → `persistence/order_record.py`

**Why:**
- Only exports OrderRecord (single class)
- Better to name after its main export
- Clearer than generic "models.py"

**Action:**
```
persistence/models.py → persistence/order_record.py

Exports:
  OrderRecord (database model for stored orders)
```

**Update Imports (if any use it directly):**
```
Check for any imports and update accordingly
```

---

## 4. Final Result - Clear Naming Convention

```
BEFORE (Confusing):
  ❌ execution/models.py          (Intent class)
  ❌ domain/models.py             (7 business classes)
  ❌ persistence/models.py        (OrderRecord class)

AFTER (Clear):
  ✅ execution/strategy_intent.py (StrategyIntent class - what strategy wants to do)
  ✅ domain/business_models.py    (TradeRecord, BotStats, etc - business records)
  ✅ persistence/order_record.py  (OrderRecord class - stored in DB)
```

### Import Clarity
```
from shoonya_platform.execution.strategy_intent import StrategyIntent
  → Obviously for strategy execution

from shoonya_platform.domain.business_models import TradeRecord
  → Obviously for business domain records

from shoonya_platform.persistence.order_record import OrderRecord
  → Obviously for database persistence
```

---

## 5. Benefits of This Renaming

| Benefit | Before | After |
|---------|--------|-------|
| **Clarity** | Which `models.py`? | File name is self-documenting ✅ |
| **Intent** | Where's the Intent class? | In strategy_intent.py ✅ |
| **Business** | Where's TradeRecord? | In business_models.py ✅ |
| **Persistence** | Where's OrderRecord? | In order_record.py ✅ |
| **Imports** | Need to remember purposes | File name explains purpose ✅ |
| **New developer** | Confusing file names | Obvious from names ✅ |
| **Maintenance** | Hard to find things | Easy to locate ✅ |

---

## 6. Implementation Plan

### Phase 1: Rename Files
```
1. Rename execution/models.py → execution/strategy_intent.py
2. Rename domain/models.py → domain/business_models.py
3. Rename persistence/models.py → persistence/order_record.py
```

### Phase 2: Update Imports (6 files total)
```
1. strategies/engine/engine.py (2 classes)
2. strategies/engine/engine_no_recovery.py (2 classes)
3. execution/broker.py (2 classes)
4. execution/trading_bot.py (2 classes)
5. brokers/shoonya/client.py (2 classes)
6. Any other files importing from these
```

### Phase 3: Verify
```
1. Check all imports resolve
2. Run syntax validation
3. Git commit with clear message
```

---

## 7. Execution Plan Summary

**Files to Rename**: 3
**Classes to Rename**: 1 (Intent → StrategyIntent)
**Files to Update Imports**: 6
**Breaking Changes**: None (internal refactoring)
**Risk Level**: Very Low (simple rename, no logic change)

---

## Key Principle Applied

✅ **"Same name should have same purpose in system"**
- If different purposes → Different names (clear!)
- If same purpose → Merge into one (no duplication!)

This ensures **zero naming confusion** and **clear code organization**.

---

## Should I Proceed?

**Status**: Ready for approval

Do you want me to:
1. ✅ Rename the 3 files?
2. ✅ Update all imports (6 files)?
3. ✅ Rename Intent → StrategyIntent for clarity?
4. ✅ Commit all changes with clear message?

**Recommended**: YES - This will make the system much clearer!
