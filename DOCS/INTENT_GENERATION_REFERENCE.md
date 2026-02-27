# Shoonya Platform - Intent Generation Quick Reference

## 🎯 FILES THAT GENERATE INTENTS

### **ENTRY INTENTS**

#### 1. **TradingView Webhook Path**
- **File**: `api/http/execution_app.py`
- **Function**: `webhook()` 
- **Line**: ~74
- **Trigger**: POST request from TradingView with JSON payload
- **Intent Generation**: 
  - Directly calls `bot.process_alert(alert_data)`
  - `process_alert()` creates `UniversalOrderCommand` objects
  - Commands submitted immediately to broker
- **Database**: `OrderRecord` table (direct insertion)
- **Status**: Synchronous (returns order_id immediately)

```python
# execution_app.py line ~74
@self.app.route("/webhook", methods=["POST"])
def webhook():
    # Validates signature
    # Parses JSON
    result = self.bot.process_alert(alert_data)  # ← INTENT GENERATED HERE
```

---

#### 2. **Dashboard Generic Intent Path**
- **File**: `api/dashboard/api/intent_router.py`
- **Function**: `submit_generic_intent()`
- **Line**: ~48
- **Trigger**: POST `/dashboard/intent/generic` with GenericIntentRequest
- **Intent Generation**:
  - Creates intent_id (DASH-GEN-{random})
  - Persists to `control_intents` table
  - `GenericControlIntentConsumer` polls and executes
  - Consumer calls `bot.process_alert()` asynchronously
- **Database**: `control_intents` table (async processing)
- **Status**: Asynchronous (client gets intent_id, execution follows)

```python
# intent_router.py line ~48
@router.post("/intent/generic", response_model=IntentResponse)
def submit_generic_intent(req: GenericIntentRequest, service: DashboardIntentService = Depends(get_intent_service)):
    return service.submit_generic_intent(req)  # ← INTENT CREATED HERE
```

**Full Path:**
```
submit_generic_intent() 
  → intent_utility.py:submit_generic_intent() (line ~56)
  → _insert_intent() (line ~165)
  → INSERT INTO control_intents
  → GenericControlIntentConsumer._process_next_intent()
  → _execute_generic_payload()
  → bot.process_alert()
  → OrderRecord created
```

---

#### 3. **Dashboard Strategy Intent Path**
- **File**: `api/dashboard/api/intent_router.py`
- **Function**: `submit_strategy_intent()`
- **Line**: ~67
- **Trigger**: POST `/dashboard/intent/strategy` with StrategyIntentRequest
- **Intent Generation**:
  - Creates intent_id (DASH-STR-{random})
  - Persists to `control_intents` with action
  - `StrategyControlConsumer` polls and routes
  - Routes to `bot.request_entry/exit/adjust/force_exit()`
  - Strategy generates internal intents
- **Database**: `control_intents` table
- **Status**: Asynchronous (strategy-driven execution)

```python
# intent_router.py line ~67
@router.post("/intent/strategy", response_model=IntentResponse)
def submit_strategy_intent(req: StrategyIntentRequest, service: DashboardIntentService = Depends(get_intent_service)):
    return service.submit_strategy_intent(req)  # ← INTENT CREATED HERE
```

**Action Mapping:**
```
action="ENTRY"       → bot.request_entry(strategy_name)
action="EXIT"        → bot.request_exit(strategy_name)
action="ADJUST"      → bot.request_adjust(strategy_name)
action="FORCE_EXIT"  → bot.request_force_exit(strategy_name)
```

---

#### 4. **Dashboard Advanced Multi-Leg Intent Path**
- **File**: `api/dashboard/api/intent_router.py`
- **Function**: `submit_advanced_intent()`
- **Line**: ~90
- **Trigger**: POST `/dashboard/intent/advanced` with AdvancedIntentRequest
- **Intent Generation**:
  - Creates intent_id (DASH-ADV-{random})
  - Persists all legs atomically
  - `GenericControlIntentConsumer` processes each leg
  - Each leg → `_execute_generic_payload()` → `bot.process_alert()`
- **Database**: `control_intents` table with legs array
- **Status**: Asynchronous (parallel leg execution)

```python
# intent_router.py line ~90
@router.post("/intent/advanced", response_model=IntentResponse)
def submit_advanced_intent(req: AdvancedIntentRequest, service: DashboardIntentService = Depends(get_intent_service)):
    # Creates intent with multiple legs
    service._insert_intent(intent_id=..., intent_type="ADVANCED", payload=...)  # ← HERE
```

---

#### 5. **Dashboard Basket Intent Path**
- **File**: `api/dashboard/api/intent_router.py`
- **Function**: `submit_basket_intent()`
- **Line**: ~134
- **Trigger**: POST `/dashboard/intent/basket` with BasketIntentRequest
- **Intent Generation**:
  - Creates intent_id (DASH-BAS-{random})
  - Persists all orders atomically
  - Orders separated into EXIT and ENTRY
  - EXITs processed first (risk-safe), then ENTRIEs
  - Each order → `bot.process_alert()`
- **Database**: `control_intents` table with orders array
- **Status**: Asynchronous (atomic processing, exits-first)

```python
# intent_router.py line ~134
@router.post("/intent/basket", response_model=IntentResponse)
def submit_basket_intent(req: BasketIntentRequest, service: DashboardIntentService = Depends(get_intent_service)):
    return service.submit_basket_intent(req)  # ← INTENT CREATED HERE
```

**Risk-Safe Order:**
```
Extract all orders
  ↓
Separate: exits = [order if order.execution_type=="EXIT"]
Separate: entries = [order if order.execution_type!="EXIT"]
  ↓
Process exits first (reduces position)
  ↓
Process entries next (safer lower risk)
```

---

#### 6. **Telegram Command Path** (Manual Entry)
- **File**: `api/http/telegram_controller.py`
- **Function**: `handle_message()` (parse commands)
- **Trigger**: Telegram user sends `/buy SYMBOL QTY PRICE` command
- **Intent Generation**:
  - Parses command into order parameters
  - Creates `UniversalOrderCommand`
  - Calls `bot.process_alert()` with command
- **Database**: `OrderRecord` table (direct)
- **Status**: Synchronous (immediate execution)

```python
# telegram_controller.py
def handle_message(self, payload):
    # Parses /buy, /sell, /exit commands
    # Creates order from user input
    alert = build_alert_from_command(payload)
    result = self.bot.process_alert(alert)  # ← INTENT GENERATED HERE
```

---

#### 7. **Strategy Internal ENTRY**
- **File**: `execution/trading_bot.py` (or custom strategy files)
- **Function**: Strategy's `entry()` method
- **Trigger**: Internal strategy logic (e.g., technical indicator fired)
- **Intent Generation**:
  - Strategy creates alert payload
  - Posts to internal webhook (or direct call)
  - Calls `bot.process_alert()` with ENTRY execution_type
- **Database**: `OrderRecord` table (direct)
- **Status**: Asynchronous (strategy-driven)

```python
# Strategy implementation
class MyStrategy:
    def entry(self, signal):
        alert = {
            "secret_key": config.webhook_secret,
            "execution_type": "entry",
            "legs": [...]
        }
        bot.process_alert(alert)  # ← INTENT GENERATED HERE
```

---

### **EXIT INTENTS**

#### 1. **Dashboard Direct EXIT Path**
- **File**: `api/dashboard/api/intent_router.py`
- **Function**: `submit_generic_intent()` (with execution_type="EXIT")
- **Line**: ~48 (same endpoint, different payload)
- **Trigger**: POST `/dashboard/intent/generic` with execution_type="EXIT"
- **Intent Generation**:
  - Creates intent_id (DASH-GEN-{random})
  - Persists with execution_type="EXIT"
  - Consumer converts to alert with EXIT action
  - Calls `bot.process_alert(execution_type="EXIT")`
- **Database**: `control_intents` table
- **Status**: Asynchronous (intent-based exit)

```python
# Same endpoint as ENTRY, but with:
GenericIntentRequest(
    execution_type="EXIT",  # ← Key difference
    symbol="NIFTY50",
    qty=50,
    ...
)
```

---

#### 2. **Dashboard Strategy EXIT Path**
- **File**: `api/dashboard/api/intent_router.py`
- **Function**: `submit_strategy_intent()` (with action="EXIT")
- **Line**: ~67 (same endpoint, different action)
- **Trigger**: POST `/dashboard/intent/strategy` with action="EXIT"
- **Intent Generation**:
  - Creates intent_id (DASH-STR-{random})
  - Persists with action="EXIT"
  - `StrategyControlConsumer` routes to `bot.request_exit(strategy_name)`
  - `request_exit()` creates `UniversalOrderCommand` (execution_type=EXIT)
  - Calls `CommandService.register()` (not submit)
- **Database**: `OrderRecord` table (via register, not direct execution)
- **Status**: Asynchronous (order watcher executes)

```python
StrategyIntentRequest(
    strategy_name="NIFTY_short",
    action="EXIT",  # ← Key difference
    reason="Dashboard EXIT"
)

# Routes to:
bot.request_exit(strategy_name)  # ← INTENT GENERATED HERE
  → Creates UniversalOrderCommand (execution_type=EXIT)
  → CommandService.register()
  → Waits for OrderWatcherEngine
```

---

#### 3. **Risk Manager Force EXIT Path**
- **File**: `risk/supreme_risk.py`
- **Function**: `request_force_exit()` (called by heartbeat)
- **Trigger**: Daily PnL < loss threshold OR cooldown active AND new trade attempted
- **Intent Generation**:
  - `heartbeat()` monitors risk continuously
  - If violation detected, calls `bot.request_force_exit()`
  - Sends Telegram alert
  - For each active position:
    - Creates `UniversalOrderCommand` (execution_type=EXIT)
    - Calls `CommandService.register()`
- **Database**: `OrderRecord` table
- **Status**: Synchronous intent registration, asynchronous broker execution

```python
# risk/supreme_risk.py
def heartbeat(self):
    if self.daily_pnl < -self.loss_limit:
        self.bot.request_force_exit()  # ← INTENT GENERATED HERE
```

**Key Behavior:**
```
Risk violation detected
  ↓
Telegram notification sent
  ↓
All active positions marked for exit
  ↓
OrderWatcherEngine prioritizes these exits
  ↓
Positions closed immediately
  ↓
Cooldown timer started
  ↓
No new trades allowed for duration
```

---

#### 4. **OrderWatcherEngine Auto-EXIT (SL/Trailing)**
- **File**: `execution/order_watcher.py`
- **Function**: `handle_exit_intent()` (called by `_reconcile_broker_orders()`)
- **Line**: ~313
- **Trigger**: ENTRY order's SL/Trailing threshold breached
- **Intent Generation**:
  - `_reconcile_broker_orders()` polls open ENTRY orders
  - Fetches live LTP
  - Checks against `stop_loss` or `trailing_stop` values
  - If threshold breached, calls `handle_exit_intent()`
  - Creates `UniversalOrderCommand` (execution_type=EXIT)
  - Calls `CommandService.register()`
- **Database**: `OrderRecord` table
- **Status**: Asynchronous (continuous monitoring, triggered execution)

```python
# order_watcher.py line ~313
def handle_exit_intent(self, cmd, ...):
    # Determine exit direction
    exit_side = "SELL" if cmd.side == "BUY" else "BUY"
    
    # Create exit command
    exit_cmd = UniversalOrderCommand.from_order_params(
        order_params={...},
        source=ENGINE_SOURCE,
    )
    
    self.bot.command_service.register(exit_cmd)  # ← INTENT GENERATED HERE
```

**Monitoring Logic:**
```
For each ENTRY order:
  ├─ Get live LTP
  ├─ Check: LTP <= stop_loss_price?
  │  └─ YES → Fire SL exit
  │
  └─ Check: Trailing stop conditions?
     ├─ POINTS: LTP dropped X points from high
     ├─ PERCENT: LTP dropped X% from high
     ├─ ABSOLUTE: LTP at specific level
     └─ YES → Fire trailing exit
```

---

## 📊 INTENT GENERATION SUMMARY TABLE

| **Intent Type** | **Source File** | **Function** | **Entry Point** | **Database** | **Execution** | **Intent ID Format** |
|---|---|---|---|---|---|---|
| **ENTRY** | | | | | | |
| TradingView | `execution_app.py` | `webhook()` | POST `/webhook` | OrderRecord | Sync | Auto (broker_id) |
| Dashboard Generic | `intent_router.py` | `submit_generic_intent()` | POST `/intent/generic` | control_intents | Async | DASH-GEN-{10} |
| Dashboard Strategy | `intent_router.py` | `submit_strategy_intent()` | POST `/intent/strategy` | control_intents | Async | DASH-STR-{10} |
| Dashboard Advanced | `intent_router.py` | `submit_advanced_intent()` | POST `/intent/advanced` | control_intents | Async | DASH-ADV-{10} |
| Dashboard Basket | `intent_router.py` | `submit_basket_intent()` | POST `/intent/basket` | control_intents | Async | DASH-BAS-{10} |
| Telegram | `telegram_controller.py` | `handle_message()` | Telegram msg | OrderRecord | Sync | Auto |
| Strategy | Strategy impl | `entry()` | Internal call | OrderRecord | Async | Auto |
| **EXIT** | | | | | | |
| Dashboard Direct | `intent_router.py` | `submit_generic_intent()` | POST `/intent/generic` | control_intents | Async | DASH-GEN-{10} |
| Dashboard Strategy | `intent_router.py` | `submit_strategy_intent()` | POST `/intent/strategy` | control_intents | Async | DASH-STR-{10} |
| Risk Manager | `supreme_risk.py` | `request_force_exit()` | heartbeat() trigger | OrderRecord | Sync Reg | Auto |
| SL/Trailing | `order_watcher.py` | `handle_exit_intent()` | LTP threshold | OrderRecord | Sync Reg | Auto |

---

## 🔍 FINDING INTENT GENERATION IN CODE

### **To find where ENTRY intents are created:**
```bash
# Search for UniversalOrderCommand creation
grep -r "UniversalOrderCommand" --include="*.py" | grep -i entry

# Search for process_alert calls (ENTRY execution)
grep -r "process_alert" --include="*.py" | head -20

# Search for CommandService.submit (ENTRY submission)
grep -r "command_service.submit" --include="*.py"

# Search for intent persistence
grep -r "control_intents" --include="*.py"
```

### **To find where EXIT intents are created:**
```bash
# Search for CommandService.register (EXIT registration)
grep -r "command_service.register" --include="*.py"

# Search for request_exit calls
grep -r "request_exit" --include="*.py"

# Search for handle_exit_intent (SL/Trailing exits)
grep -r "handle_exit_intent" --include="*.py"

# Search for FORCE_EXIT
grep -r "FORCE_EXIT\|force_exit" --include="*.py"
```

---

## 📝 KEY CONCEPTS

### **Synchronous vs Asynchronous Execution**

**Synchronous (Immediate):**
- TradingView Webhook → direct `process_alert()` → OrderRecord → broker
- Return: order_id or error immediately
- Client knows execution result right away

**Asynchronous (Queued):**
- Dashboard Intent → persist to `control_intents` → consumer polls → execution
- Return: intent_id (not order_id) immediately
- Consumer processes in background thread
- Eventual consistency (execution may take seconds)

### **Register vs Submit**

**`CommandService.submit()`:**
- Used for: ENTRY, ADJUST orders
- Behavior: Creates OrderRecord + Executes immediately to broker
- Returns: OrderResult with order_id (success/failure)

**`CommandService.register()`:**
- Used for: EXIT orders only
- Behavior: Creates OrderRecord + Does NOT execute immediately
- Returns: Nothing (async via OrderWatcherEngine)
- Reason: Allows centralized EXIT execution logic in OrderWatcher

### **Intent vs Order**

**Intent:**
- Represents user's wish (buy/sell)
- May be blocked (duplicate, risk, etc)
- Persisted to DB for audit trail

**Order:**
- Represents broker order (actual market participation)
- Created after intent succeeds validation
- OrderRecord with broker_order_id

---

## ✅ VERIFICATION CHECKLIST

If you want to verify all intent paths are covered:

- [ ] **ENTRY - TradingView**: Can receive webhook and place order
- [ ] **ENTRY - Dashboard Generic**: UI button → order placed
- [ ] **ENTRY - Dashboard Strategy**: Select strategy → ENTRY button → order placed
- [ ] **ENTRY - Advanced**: Multi-leg entry works
- [ ] **ENTRY - Basket**: Multiple orders atomic execution
- [ ] **ENTRY - Telegram**: `/buy SYMBOL QTY` command works
- [ ] **ENTRY - Strategy**: Internal logic generates entries
- [ ] **EXIT - Dashboard**: UI exit button → position closed
- [ ] **EXIT - Strategy**: Strategy EXIT command → position closed
- [ ] **EXIT - Risk**: Daily loss hit → auto force exit
- [ ] **EXIT - SL/Trailing**: Position held → SL triggered → auto exit
- [ ] **Order Watcher**: Monitors and executes queued exits

---

## 🔗 CROSS-REFERENCES

### **If you need to add a NEW entry path:**
1. Create intent generation in new file: `def new_intent()` 
2. Register with CommandService: `command_service.submit()`
3. Update intent_router.py if API endpoint
4. Add to process_alert() workflow
5. Test via order_watcher monitoring

### **If you need to add a NEW exit path:**
1. Create exit intent: calls `command_service.register()` or creates UniversalOrderCommand
2. OrderWatcherEngine automatically picks it up
3. No changes needed to order_watcher if following same pattern
4. Update control intent consumers if via dashboard

### **If you need to modify validation:**
1. ExecutionGuard: `validate_and_prepare()` (duplicate, conflicts)
2. CommandService: `validate_order()` (order validity)
3. ScriptMaster: `requires_limit_order()` (instrument rules)
4. RiskManager: `can_execute()` (daily limits, cooldown)

