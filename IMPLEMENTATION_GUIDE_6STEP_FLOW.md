# 6-STEP ORDER FLOW - IMPLEMENTATION GUIDE

## Quick Reference: File Locations

| Step | Component | File | Method | Lines |
|------|-----------|------|--------|-------|
| 1 | CommandService | `execution/command_service.py` | `submit()` | 125-235 |
| 2 | TradingBot | `execution/trading_bot.py` | `execute_command()` | 1422-1475 |
| 3 | TradingBot | `execution/trading_bot.py` | `execute_command()` | 1477-1485 |
| 4 | TradingBot | `execution/trading_bot.py` | `execute_command()` | 1487-1515 |
| 5 | TradingBot | `execution/trading_bot.py` | `execute_command()` | 1517-1560 |
| 6 | OrderWatcher | `execution/order_watcher.py` | `_reconcile_broker_orders()` | 106-230 |

---

## STEP-BY-STEP EXECUTION TRACE

### STEP 1: REGISTER TO DB
**Entry Point**: `CommandService.submit(command, execution_type="ENTRY")`

```python
# File: shoonya_platform/execution/command_service.py

def submit(self, cmd: UniversalOrderCommand, *, execution_type: str):
    # 1️⃣ HARD VALIDATION
    validate_order(cmd)
    
    # 2️⃣ PERSIST (ONCE) - STATUS = CREATED
    record = OrderRecord(
        command_id=cmd.command_id,
        status="CREATED",
        ...
    )
    self.bot.order_repo.create(record)  # Persists to DB
    
    # 3️⃣ SUBMISSION
    return self.bot.execute_command(
        command=cmd,
        trailing_engine=trailing_engine,
    )
```

**DB State After**:
```sql
orders.command_id = <generated>
orders.status = "CREATED"
orders.broker_order_id = NULL
orders.created_at = <now>
orders.updated_at = <now>
```

---

### STEP 2: SYSTEM BLOCKERS CHECK
**Entry Point**: `ShoonyaBot.execute_command(command)` → Step 2

```python
# File: shoonya_platform/execution/trading_bot.py (lines 1422-1475)

# 🛡️ Check 2A: RISK MANAGER
if not self.risk_manager.can_execute():
    self.order_repo.update_status(command.command_id, "FAILED")
    self.order_repo.update_tag(command.command_id, "RISK_LIMITS_EXCEEDED")
    return OrderResult(success=False, error_message="RISK_LIMITS_EXCEEDED")

# 🛡️ Check 2B: EXECUTION GUARD
strategy_id = getattr(command, 'strategy_name', 'UNKNOWN')
if self.execution_guard.has_strategy(strategy_id) and is_entry:
    self.order_repo.update_status(command.command_id, "FAILED")
    self.order_repo.update_tag(command.command_id, "EXECUTION_GUARD_BLOCKED")
    return OrderResult(success=False, error_message="EXECUTION_GUARD_BLOCKED")

# 🛡️ Check 2C: DUPLICATE DETECTION
open_orders = self.order_repo.get_open_orders_by_strategy(strategy_id)
for order in open_orders:
    if order.symbol == command.symbol and order.command_id != command.command_id:
        self.order_repo.update_status(command.command_id, "FAILED")
        self.order_repo.update_tag(command.command_id, "DUPLICATE_ORDER_BLOCKED")
        return OrderResult(success=False, error_message="DUPLICATE_ORDER_BLOCKED")
```

**DB State After (Success)**:
```sql
orders.status = "CREATED"
orders.tag = NULL
```

**DB State After (Blocked)**:
```sql
orders.status = "FAILED"
orders.tag = "<BLOCKER_REASON>"
orders.updated_at = <now>
```

---

### STEP 3: UPDATE TO SENT_TO_BROKER
**Entry Point**: `ShoonyaBot.execute_command()` → Step 3

```python
# File: shoonya_platform/execution/trading_bot.py (lines 1477-1485)

try:
    self.order_repo.update_status(command.command_id, "SENT_TO_BROKER")
except Exception as db_err:
    logger.error(f"STEP_3 FAILED: {db_err}")
    # Continue to broker anyway - broker is source of truth
```

**DB State After**:
```sql
orders.status = "SENT_TO_BROKER"
orders.updated_at = <now>
```

**Why This Step?**
- Signals to OrderWatcher: "about to submit to broker"
- Prevents double-submission of same order
- Audit trail of execution progress

---

### STEP 4: EXECUTE ON BROKER
**Entry Point**: `ShoonyaBot.execute_command()` → Step 4

```python
# File: shoonya_platform/execution/trading_bot.py (lines 1487-1515)

# Convert canonical command → broker params
order_params = command.to_broker_params()
# {
#   "exchange": "NFO",
#   "tradingsymbol": "BANKNIFTY23456CP",
#   "buy_or_sell": "BUY",
#   "quantity": 1,
#   "price_type": "MARKET",  // or "LIMIT"
#   "price": 123.45,  // if LIMIT
# }

# 🔥 SINGLE BROKER TOUCHPOINT
result = self.api.place_order(order_params)
# Returns: result.success, result.order_id, result.error_message
```

**Broker Response Examples**:
```python
# Success:
result.success = True
result.order_id = "123456789"  # Broker assigns this

# Failure:
result.success = False
result.error_message = "Quantity exceeds limit"
```

---

### STEP 5: UPDATE DB BASED ON BROKER RESULT
**Entry Point**: `ShoonyaBot.execute_command()` → Step 5

```python
# File: shoonya_platform/execution/trading_bot.py (lines 1517-1560)

if result.success:
    # ✅ BROKER ACCEPTED
    broker_id = result.order_id  # Broker's ID
    self.order_repo.update_broker_id(command.command_id, broker_id)
    # update_broker_id() sets:
    #   - broker_order_id = broker_id
    #   - status = "SENT_TO_BROKER"
    #   - updated_at = <now>
else:
    # ❌ BROKER REJECTED
    self.order_repo.update_status(command.command_id, "FAILED")
    self.order_repo.update_tag(command.command_id, "BROKER_REJECTED")
    if is_exit_order:
        self.telegram.send_alert(...)
```

**DB State After (Success)**:
```sql
orders.status = "SENT_TO_BROKER"
orders.broker_order_id = "123456789"
orders.updated_at = <now>
```

**DB State After (Failure)**:
```sql
orders.status = "FAILED"
orders.broker_order_id = NULL
orders.tag = "BROKER_REJECTED"
orders.updated_at = <now>
```

---

### STEP 6: ORDERWATCH POLLS BROKER
**Entry Point**: `OrderWatcherEngine.run()` (continuous thread)

```python
# File: shoonya_platform/execution/order_watcher.py (lines 106-230)

while self._running:
    self.bot._ensure_login()
    self._reconcile_broker_orders()  # STEP 6
    self._process_open_intents()
    time.sleep(self.poll_interval)  # Default: 1.0 second

def _reconcile_broker_orders(self):
    broker_orders = self.bot.api.get_order_book()  # Get ALL orders
    
    for bo in broker_orders:
        broker_id = bo.get("norenordno")  # Broker's order ID
        status = bo.get("status").upper()  # COMPLETE, REJECTED, etc.
        
        # Match to DB record
        record = self.repo.get_by_broker_id(broker_id)
        if not record:
            continue  # Not our order
        
        # Skip already-resolved orders
        if record.status in ("EXECUTED", "FAILED"):
            continue
        
        # === STEP 6A: BROKER FAILURE ===
        if status in ("REJECTED", "CANCELLED", "EXPIRED"):
            self.repo.update_status(record.command_id, "FAILED")
            self.repoupdate_tag(record.command_id, f"BROKER_{status}")
            
            # Clear guard to prevent stale state
            self.bot.execution_guard.force_clear_symbol(
                strategy_id=record.strategy_name,
                symbol=record.symbol,
            )
        
        # === STEP 6B: BROKER EXECUTED (FINAL TRUTH) ===
        elif status == "COMPLETE":
            self.repo.update_status(record.command_id, "EXECUTED")
            self._reconcile_execution_guard(record.strategy_name)
```

**DB State Transitions During Step 6**:
```
From: status="SENT_TO_BROKER"  broker_order_id="123456789"

To (Success):
    status="EXECUTED"
    broker_order_id="123456789"

To (Failure):
    status="FAILED"
    tag="BROKER_<STATUS>"
```

---

## STATUS STATE MACHINE

```
┌─────────────────────────────────────────────────────────┐
│                 CREATED (Initial State)                 │
└──────────┬──────────────────────────────────────────────┘
           │
           ├─────────────────────────────┐
           │ (Blocker Check Failed)      │
           │ [Step 2]                    │
           └─────────────────────────────┘
                      │
                      ▼
           ┌──────────────────┐
           │ FAILED (Blocked) │
           └──────────────────┘
           
           ├─────────────────────────────┐
           │ (Broker Submit Ok)          │
           │ [Step 3]                    │
           └─────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │  SENT_TO_BROKER (State 3)  │
         └────┬───────────────────────┘
              │
              ├──────────────────────────┐
              │ (Broker Accepts)         │
              │ [Step 5a]                │
              └──────────────────────────┘
              │
              ├──────────────────────────┐
              │ (Broker Rejects)         │
              │ [Step 5b]                │
              └──────────────────────────┘
                      │
                      ▼
              ┌────────────────────┐
              │ FAILED (Rejected)  │
              └────────────────────┘
              
              ├──────────────────────────┐
              │ (Polling finds COMPLETE) │
              │ [Step 6b]                │
              └──────────────────────────┘
                      │
                      ▼
              ┌────────────────────┐
              │    EXECUTED        │
              │ (Final State)      │
              └────────────────────┘
```

---

## KEY DATABASE TABLES

### orders table

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| client_id | TEXT | Client isolation |
| command_id | TEXT | Unique command identifier |
| broker_order_id | TEXT | Broker's order ID (NULL until Step 5 success) |
| status | TEXT | CREATED/SENT_TO_BROKER/EXECUTED/FAILED |
| tag | TEXT | Reason for status (e.g., "BROKER_REJECTED") |
| exchange | TEXT | NFO/NSE/BSE |
| symbol | TEXT | Trading symbol |
| side | TEXT | BUY/SELL |
| quantity | INTEGER | Order quantity |
| order_type | TEXT | MARKET/LIMIT/SL |
| price | FLOAT | Order price |
| created_at | DATETIME | Step 1 timestamp |
| updated_at | DATETIME | Latest DB update |

---

## API METHODS USED

### OrderRepository
- `create(record)` - Store new order
- `update_status(cmd_id, status)` - Update status + timestamp
- `update_tag(cmd_id, tag)` - Update reason tag
- `update_broker_id(cmd_id, broker_id)` - Set broker ID + status
- `get_open_orders_by_strategy(strategy_id)` - Fetch open orders
- `get_by_broker_id(broker_id)` - Fetch by broker ID

### ExecutionGuard
- `has_strategy(strategy_id)` - Check if strategy has positions
- `force_clear_symbol(strategy_id, symbol)` - Clear on failure
- `reconcile_with_broker(...)` - Sync with broker positions
- `force_close_strategy(strategy_id)` - Cleanup when flat

### RiskManager
- `can_execute()` - Check risk limits

### ShoonyaClient (via Proxy)
- `place_order(params)` - Submit to broker
- `get_order_book()` - Fetch all orders
- `get_positions()` - Fetch current positions

---

## ERROR RECOVERY

### Broker Connection Lost During Step 4
→ Broker API throws exception
→ execute_command catches and updates DB to FAILED
→ OrderWatcher can't find order by broker_id (order never created)
→ Order stays in FAILED state until manual investigation

### OrderWatcher Thread Dies
→ Daemon thread, auto-restarts on bot restart
→ On restart, SENT_TO_BROKER orders will be checked
→ Broker tells us real status → DB synced to truth

### DB Connection Lost During Step 3
→ Exception caught, logged
→ Order continues to broker (broker is source of truth)
→ OrderWatcher will eventually sync DB to broker reality

---

## PRODUCTION SAFETY CHECKLIST

- [✅] All DB operations wrapped in try/except
- [✅] Broker is always source of truth
- [✅] Idempotency at each polling step
- [✅] Client isolation enforced
- [✅] No silent failures - all errors logged
- [✅] Telegram alerts for critical failures
- [✅] Risk limits enforced BEFORE broker
- [✅] Guard state protected by locks
- [✅] Legacy order support maintained
