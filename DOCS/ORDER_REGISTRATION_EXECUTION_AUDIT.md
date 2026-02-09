# ORDER REGISTRATION & EXECUTION AUDIT
**Date**: 2026-02-09  
**Status**: CRITICAL REVIEW  
**Scope**: Every order from webhook/external/system sources

---

## ✅ DESIRED FLOW (WHAT YOU WANT)

```
┌─────────────────────────────────────────────────────────┐
│ EXTERNAL ORDER SOURCE (Webhook/Dashboard/System)        │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 1. REGISTER TO DB with status=CREATED                   │
│    - Command ID generated                               │
│    - All order details persisted                        │
│    - Immutable record created                           │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 2. SYSTEM BLOCKERS CHECK (Risk/Guard/Duplicate)        │
│    - Risk manager: daily loss, cooldown, max loss       │
│    - Execution guard: strategy rules, cross-strategy    │
│    - Duplicate detect: live orders, positions           │
│                                                         │
│    ❌ IF BLOCKED → Update DB to status=FAILED, tag=reason
│    ✅ IF PASSED  → Continue to step 3                   │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 3. UPDATE TO status=SENT_TO_BROKER                      │
│    - Before broker submission                          │
│    - Signals "about to execute"                         │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 4. EXECUTE ON BROKER                                    │
│    - Place order via API                                │
│    - Capture broker_order_id                            │
│    - Capture result (success/error)                     │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 5. UPDATE DB BASED ON BROKER RESULT                     │
│    ❌ Broker rejected  → status=FAILED, broker_order_id=null
│    ✅ Broker accepted  → status=SENT_TO_BROKER, broker_order_id=xxx
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│ 6. ORDERWATCH POLLS BROKER ("EXECUTED TRUTH")          │
│    - Check order status on broker                       │
│    - If COMPLETE → status=EXECUTED                      │
│    - If REJECTED/CANCELLED/EXPIRED → status=FAILED      │
│    - Clear execution guard on failure                   │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 DATABASE CONTRACT (models.py)

```python
OrderRecord:
  status: CREATED | SENT_TO_BROKER | EXECUTED | FAILED
  tag: optional string (RISK_BLOCKED:reason, GUARD_BLOCKED:reason, etc)
  created_at: timestamp
  updated_at: timestamp
  broker_order_id: null initially, set after SENT_TO_BROKER
```

---

## 🔍 CURRENT STATE ANALYSIS

### ✅ WORKING CORRECTLY

1. **Risk-Blocked Orders** (trading_bot.py)
   - `process_alert()` → risk check fails
   - Calls `_record_blocked_alert(tag=RISK_BLOCKED:<reason>)`
   - Status=CREATED, tag set, no broker submission
   - OrderWatcher marks FAILED
   - ✅ CORRECT FLOW

2. **Guard-Blocked & Duplicate Orders** (trading_bot.py)
   - `process_alert()` → execution guard check fails
   - Calls `_record_blocked_alert(tag=GUARD_BLOCKED:<reason>)`
   - Status=CREATED, tag set, no broker submission
   - OrderWatcher marks FAILED
   - ✅ CORRECT FLOW

### ❌ GAPS IDENTIFIED

#### **GAP 1: Process_leg() Registration Timing**
**Location**: `trading_bot.py:process_leg()`

Current:
```python
# process_leg() calls:
if execution_type == "EXIT":
    self.command_service.register(cmd)  # ← writes CREATED to DB
else:
    self.command_service.register_intent(cmd, execution_type="ENTRY")  # ← writes CREATED to DB
```

Issue: Orders are registered late in the flow (inside process_leg), not at entry point.  
Better: All orders should be registered at `process_alert()` entry point with one unified method.

---

#### **GAP 2: No Status Update to SENT_TO_BROKER Before Broker Submit**
**Location**: `command_service.submit()`

Current:
```python
# command_service.submit():
1. Validate order
2. Persist CREATED to DB
3. Call execute_command()  ← No SENT_TO_BROKER update before this
```

Missing:
```python
# SHOULD BE:
1. Persist CREATED to DB
2. Update to SENT_TO_BROKER
3. Call execute_command()
```

Effect: OrderWatcher may see CREATED and re-execute partial orders.

---

#### **GAP 3: execute_command() Result Not Captured**
**Location**: `trading_bot.py:execute_command()`

Current:
```python
result = self.api.place_order(order_params)
if not result.success:
    self.order_repo.update_status(command.command_id, "FAILED")  # ← Added, good!
else:
    # Missing: update to SENT_TO_BROKER + broker_order_id
    pass
return result
```

Issue: On success, should update `broker_order_id` and keep `SENT_TO_BROKER`.

---

#### **GAP 4: OrderWatcher._process_open_intents() Doesn't Update SENT_TO_BROKER**
**Location**: `order_watcher.py:_process_open_intents()`

Current:
```python
# After successful submit to broker:
self.repo.update_broker_id(cmd.command_id, result.order_id)
# update_broker_id sets status=SENT_TO_BROKER + assigns broker_id
```

Good: This is correct, but depends on execute_command() being called from the right place.

---

#### **GAP 5: Direct EXIT Submissions (command_service.submit for EXIT)**
**Location**: `command_service.submit()`

Current:
```python
if execution_type == "EXIT" or cmd.intent == "EXIT":
    raise RuntimeError("EXIT submission forbidden")
```

Good: EXIT intents cannot be submitted directly.  
But: `command_service.register()` (EXIT path) doesn't execute immediately—it waits for OrderWatcher.

---

## 🎯 CRITICAL RULES TO ENFORCE

### Rule 1: Every Order Must Register First
**When**: `process_alert()` entry point  
**What**: Create OrderRecord in DB immediately with status=CREATED  
**How**: Call unified `_register_order_in_db()` method  
**Guarantee**: Immutable audit trail from the moment order is received

### Rule 2: Blockers Must Update DB, Not Skip Registration
**When**: Risk/Guard/Duplicate blocks trigger  
**What**: Update existing CREATED record with tag and mark as FAILED  
**How**: Set `tag=<BLOCKER>:<reason>`, `status=FAILED`  
**Guarantee**: All orders visible in DB, even if blocked

### Rule 3: SENT_TO_BROKER Update Must Happen Before Submission
**When**: Before `execute_command()` is called  
**What**: Update status from CREATED → SENT_TO_BROKER  
**How**: `order_repo.update_status(command_id, "SENT_TO_BROKER")`  
**Guarantee**: No re-execution risk

### Rule 4: Broker Result Must Update DB
**When**: After broker response received  
**What**: Update broker_order_id and status based on result  
**How**: 
```python
if result.success:
    update_broker_id(cmd.command_id, result.order_id)  # keeps SENT_TO_BROKER
else:
    update_status(cmd.command_id, "FAILED")
```
**Guarantee**: Broker truth reconciliation

### Rule 5: OrderWatcher Only Executes What It Reads from DB
**When**: `OrderWatcherEngine._process_open_intents()`  
**What**: Poll DB for CREATED/SENT_TO_BROKER orders  
**How**: Build execution command from DB record, execute via broker  
**Guarantee**: Single source of truth (DB) for execution

### Rule 6: All Blockers Apply BEFORE Registration or via Tag
**When**: Process_alert execution guard/risk checks  
**What**: Register all orders, mark blocked ones with tag + status=FAILED  
**How**: Unified registration with per-leg or full-batch blocking  
**Guarantee**: No silent order drops, 100% audit trail

---

## 📝 IMPLEMENTATION CHECKLIST

- [ ] Create unified `_register_order_in_db()` method in ShoonyaBot
  - Params: parsed alert, execution_type, strategy_name, exchange, legs
  - Each leg → one OrderRecord with status=CREATED
  - Return: dict of {symbol: command_id}

- [ ] Modify `process_alert()` to register immediately
  - Call `_register_order_in_db()` right after parsing
  - Then apply blockers to update tag/status

- [ ] Modify `command_service.register_intent()` flow
  - Should get command_id from already-registered record
  - Do NOT re-register if already in DB

- [ ] Update `command_service.submit()` to update SENT_TO_BROKER
  - Before calling `execute_command()`

- [ ] Update `execute_command()` to capture broker result
  - On success: update broker_order_id
  - On failure: update status=FAILED

- [ ] Verify `order_watcher.py:_process_open_intents()`
  - Only executes CREATED orders
  - Updates broker_id (which auto-sets SENT_TO_BROKER)

- [ ] Add logging at every status transition
  - CREATED → SENT_TO_BROKER
  - SENT_TO_BROKER → EXECUTED
  - Any → FAILED (with reason)

---

## 🚨 CURRENT ISSUE: Duplicate Registration

**Problem**: Orders get registered twice:
1. In `_record_blocked_alert()` for blocked orders
2. In `command_service.register()` / `register_intent()` for allowed orders

**Solution**: Single registration in `process_alert()` before any checks.

---

## 📊 TEST CASES

1. **Webhook → Registered → Allowed → Executed**
   - ✅ Register with CREATED
   - ✅ Risk check PASS
   - ✅ Guard check PASS
   - ✅ Update to SENT_TO_BROKER
   - ✅ Broker accepts → update broker_id, keep SENT_TO_BROKER
   - ✅ OrderWatcher polls broker → EXECUTED

2. **Webhook → Registered → Risk Blocked → Failed**
   - ✅ Register with CREATED
   - ❌ Risk check FAIL
   - ✅ Update tag=RISK_BLOCKED:<reason>, status=FAILED
   - ✅ OrderWatcher marks FAILED (idempotent)

3. **Webhook → Registered → Guard Blocked → Failed**
   - ✅ Register with CREATED
   - ✅ Risk check PASS
   - ❌ Guard check FAIL
   - ✅ Update tag=GUARD_BLOCKED:<reason>, status=FAILED
   - ✅ OrderWatcher marks FAILED

4. **Webhook → Registered → Sent → Broker Rejects → Failed**
   - ✅ Register with CREATED
   - ✅ All checks PASS
   - ✅ Update to SENT_TO_BROKER
   - ❌ Broker rejects
   - ✅ execute_command() updates status=FAILED
   - ✅ OrderWatcher confirms FAILED from broker

---

## 🔐 INVARIANTS TO PRESERVE

1. **OrderWatcher Authority**: Only OrderWatcherEngine executes from DB
2. **Broker Truth**: Broker is single source for filled/unfilled state
3. **ExecutionGuard Consistency**: Guard state aligns with DB + broker
4. **DB Immutability**: No business logic in updates, only state transitions
5. **Telegram Alerts**: Must include order rejection reason from DB tag

---

## REFERENCES

- [database.py](../shoonya_platform/persistence/database.py) - Schema definition
- [models.py](../shoonya_platform/persistence/models.py) - OrderRecord dataclass
- [repository.py](../shoonya_platform/persistence/repository.py) - DB operations
- [trading_bot.py](../shoonya_platform/execution/trading_bot.py) - process_alert(), process_leg()
- [command_service.py](../shoonya_platform/execution/command_service.py) - register(), submit()
- [order_watcher.py](../shoonya_platform/execution/order_watcher.py) - _process_open_intents()

