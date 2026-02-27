# Shoonya Platform - Order Execution Flow Analysis

## 📋 Executive Summary

This document details **all entry and exit order execution paths** in the Shoonya Platform and identifies **which files generate intents** for each type of order.

---

## 🎯 System Architecture Overview

The system is built on a **3-layer architecture**:

1. **Intent Generation Layer** - Files that create execution intents (ENTRY/EXIT/ADJUST)
2. **Intent Processing Layer** - Files that consume and route intents  
3. **Execution Layer** - Files that execute orders on the broker

---

## 📌 FILES GENERATING INTENTS

### **ENTRY ORDER INTENTS - 4 Sources**

| Intent Source | File | Function | Intent Type |
|---|---|---|---|
| **TradingView Webhook** | `api/http/execution_app.py` | `/webhook` endpoint | Generic/Strategy |
| **Dashboard UI** | `api/dashboard/api/intent_router.py` | `/intent/generic`, `/intent/strategy`, `/intent/advanced`, `/intent/basket` | Generic/Strategy/Advanced/Basket |
| **Strategy Execution** | `execution/trading_bot.py` | `process_alert()` | Strategy-based |
| **Telegram Commands** | `api/http/telegram_controller.py` | User command handler | Manual/Dashboard |

### **EXIT ORDER INTENTS - 3 Sources**

| Intent Source | File | Function | Intent Type |
|---|---|---|---|
| **Dashboard UI** | `api/dashboard/api/intent_router.py` | `/intent/generic` with exit action | Generic EXIT |
| **Strategy Execution** | `execution/trading_bot.py` | `process_alert()` with exit execution | Strategy EXIT |
| **Risk Manager** | `risk/supreme_risk.py` | `request_force_exit()` | Risk-driven EXIT |
| **OrderWatcherEngine** | `execution/order_watcher.py` | `handle_exit_intent()` | SL/Trailing EXIT |

---

## 🔄 ENTRY ORDER EXECUTION PATH

### **Path 1: TradingView Webhook → Direct Execution**

```
TradingView Signal
    ↓
/webhook endpoint (execution_app.py)
    ↓ (validate signature)
process_alert() [trading_bot.py]
    ↓
parse_alert_data()
    ↓
ExecutionGuard.validate_and_prepare()
    ├─ Check: No duplicate entry
    ├─ Check: Position not locked
    └─ Return: Validated intents
    ↓
process_leg() [for each leg]
    ├─ Create UniversalOrderCommand
    ├─ Fetch LTP (if needed)
    ├─ Validate order_type/price
    └─ Append to pending_commands
    ↓
CommandService.submit()
    ├─ Validate order
    ├─ Create OrderRecord (status=CREATED)
    ├─ Execute via ShoonyaClient
    └─ Return OrderResult with broker_order_id
    ↓
Track OrderRecord
    ├─ Status: SENT_TO_BROKER
    └─ Store in persistence/data/orders.db
    ↓
OrderWatcherEngine monitors for:
    ├─ COMPLETE → mark EXECUTED
    ├─ CANCELLED → mark FAILED
    └─ SL/Trailing triggers
```

**Key Files:**
- Entry Point: `api/http/execution_app.py:webhook()`
- Intent Creation: `execution/trading_bot.py:process_alert()`
- Command Routing: `execution/command_service.py:submit()`
- Execution: `brokers/shoonya/client.py:place_order()`
- Monitoring: `execution/order_watcher.py:_reconcile_broker_orders()`

---

### **Path 2: Dashboard → Generic Intent → Execution**

```
Dashboard UI (Web/API)
    ↓
POST /dashboard/intent/generic (intent_router.py)
    ↓ (validate GenericIntentRequest)
DashboardIntentService.submit_generic_intent()
    ├─ Create unique intent_id (DASH-GEN-*)
    ├─ Persist to control_intents table
    └─ Return IntentResponse (ACCEPTED)
    ↓
GenericControlIntentConsumer (background thread)
    ├─ Poll control_intents table every 1 second
    ├─ Claim next intent (UPDATE status = CLAIMED)
    └─ Process: _execute_generic_payload()
    ↓
Convert to alert format:
    ├─ Build leg from payload
    ├─ Create alert_payload (PineScript format)
    └─ Call bot.process_alert()
    ↓
[SAME AS PATH 1 FROM HERE]
process_alert() → ExecutionGuard → process_leg() → submit()
    ↓
Update intent status: ACCEPTED / REJECTED / FAILED
```

**Key Files:**
- Entry Point: `api/dashboard/api/intent_router.py:submit_generic_intent()`
- Intent Persistence: `api/dashboard/services/intent_utility.py:DashboardIntentService`
- Intent Consumer: `execution/generic_control_consumer.py:GenericControlIntentConsumer`
- Alert Converter: `execution/generic_control_consumer.py:_execute_generic_payload()`

---

### **Path 3: Dashboard → Strategy Intent → Execution**

```
Dashboard UI
    ↓
POST /dashboard/intent/strategy (intent_router.py)
    ↓ (validate StrategyIntentRequest)
DashboardIntentService.submit_strategy_intent()
    ├─ Create unique intent_id (DASH-STR-*)
    ├─ Persist to control_intents table
    ├─ action: ENTRY / EXIT / ADJUST / FORCE_EXIT
    └─ Return IntentResponse (ACCEPTED)
    ↓
StrategyControlConsumer (background thread)
    ├─ Poll control_intents table
    ├─ Claim next STRATEGY intent
    └─ Route based on action:
    ├─ ENTRY  → bot.request_entry(strategy_name)
    ├─ EXIT   → bot.request_exit(strategy_name)
    ├─ ADJUST → bot.request_adjust(strategy_name)
    └─ FORCE_EXIT → bot.request_force_exit(strategy_name)
    ↓
Strategy-specific logic:
    ├─ Fetch strategy instance from _live_strategies
    ├─ Call strategy.entry() / exit() / adjust()
    └─ Strategy generates intents via internal logic
    ↓
[INTEGRATES WITH PATH 1]
Generated intents → process_alert() → execution
```

**Key Files:**
- Entry Point: `api/dashboard/api/intent_router.py:submit_strategy_intent()`
- Intent Consumer: `execution/strategy_control_consumer.py:StrategyControlConsumer`
- Strategy Manager: `execution/trading_bot.py` (acts as strategy manager)

---

### **Path 4: Dashboard → Advanced Multi-Leg Intent**

```
Dashboard UI
    ↓
POST /dashboard/intent/advanced (intent_router.py)
    ↓ (validate AdvancedIntentRequest)
DashboardIntentService._insert_intent()
    ├─ Create unique intent_id (DASH-ADV-*)
    ├─ Persist with type="ADVANCED"
    ├─ Payload contains array of legs
    └─ Return IntentResponse (ACCEPTED)
    ↓
GenericControlIntentConsumer
    ├─ Detect intent_type == "ADVANCED"
    └─ Process each leg individually
    ↓
For each leg:
    ├─ Build alert payload
    ├─ Call bot.process_alert()
    └─ Track success/failure
    ↓
Update intent status: ACCEPTED / PARTIALLY ACCEPTED / REJECTED
```

**Key Files:**
- Entry Point: `api/dashboard/api/intent_router.py:submit_advanced_intent()`
- Intent Consumer: `execution/generic_control_consumer.py:GenericControlIntentConsumer._process_next_intent()`

---

### **Path 5: Dashboard → Basket Intent (Atomic Multi-Order)**

```
Dashboard UI
    ↓
POST /dashboard/intent/basket (intent_router.py)
    ↓ (validate BasketIntentRequest)
DashboardIntentService.submit_basket_intent()
    ├─ Create unique intent_id (DASH-BAS-*)
    ├─ Persist all orders atomically
    ├─ Order preserved in persistence
    └─ Return IntentResponse (ACCEPTED)
    ↓
GenericControlIntentConsumer
    ├─ Detect intent_type == "BASKET"
    ├─ Extract orders array from payload
    └─ Separate into EXIT orders and ENTRY orders
    ↓
Risk-Safe Order:
    1. Process all EXITs first (reduces risk)
    2. Process all ENTRIEs next (safer after exits)
    ↓
For each order:
    ├─ Build alert payload
    ├─ Call bot.process_alert()
    └─ Track atomic success
```

**Key Files:**
- Entry Point: `api/dashboard/api/intent_router.py:submit_basket_intent()`
- Intent Consumer: `execution/generic_control_consumer.py:GenericControlIntentConsumer._process_next_intent()`

---

## 🚪 EXIT ORDER EXECUTION PATH

### **Path 1: Dashboard Direct EXIT (Generic Intent)**

```
Dashboard UI
    ↓
POST /dashboard/intent/generic with execution_type="EXIT"
    ↓
DashboardIntentService.submit_generic_intent()
    ├─ Persist to control_intents table
    └─ execution_type = "EXIT"
    ↓
GenericControlIntentConsumer
    ├─ Fetch control intent
    ├─ _execute_generic_payload()
    └─ Payload → alert_payload (execution_type="EXIT")
    ↓
bot.process_alert() [execution/trading_bot.py]
    ├─ execution_type = "EXIT"
    ├─ Skip ExecutionGuard (EXIT always allowed)
    └─ For each leg:
        ├─ Fetch broker position
        ├─ Validate position exists
        ├─ Determine exit_direction (SELL if BUY, BUY if SELL)
        ├─ Adjust qty if needed
        └─ process_leg() → CommandService.submit()
    ↓
CommandService.submit()
    ├─ Create OrderRecord (execution_type="EXIT")
    ├─ Execute via broker
    └─ Return broker_order_id
    ↓
OrderRecord status: SENT_TO_BROKER
    ↓
OrderWatcherEngine monitors for completion
```

**Key Files:**
- Entry: `api/dashboard/api/intent_router.py`
- Intent Consumer: `execution/generic_control_consumer.py:_execute_generic_payload()`
- Processor: `execution/trading_bot.py:process_alert()`
- Executor: `execution/command_service.py:submit()`

---

### **Path 2: Dashboard Strategy EXIT**

```
Dashboard UI
    ↓
POST /dashboard/intent/strategy with action="EXIT"
    ↓
DashboardIntentService.submit_strategy_intent()
    ├─ Persist intent with action="EXIT"
    └─ strategy_name specified
    ↓
StrategyControlConsumer
    ├─ Claim STRATEGY intent
    ├─ action = "EXIT"
    └─ bot.request_exit(strategy_name)
    ↓
bot.request_exit() [trading_bot.py]
    ├─ 🔒 Fetch broker positions
    ├─ Find position for strategy symbol
    ├─ Determine exit side
    ├─ Create UniversalOrderCommand
    └─ CommandService.register() → EXIT intent
    ↓
CommandService.register() [execution/command_service.py]
    ├─ 🔒 Create OrderRecord (execution_type="EXIT")
    ├─ 🔒 NO broker submission (register only)
    └─ Wait for OrderWatcherEngine to execute
    ↓
OrderWatcherEngine
    ├─ Poll OrderRepository for EXIT orders
    ├─ Convert EXIT intent → broker order
    └─ Execute when ready
```

**Key Files:**
- Entry: `api/dashboard/api/intent_router.py:submit_strategy_intent()`
- Intent Consumer: `execution/strategy_control_consumer.py`
- Request Handler: `execution/trading_bot.py:request_exit()`
- Registration: `execution/command_service.py:register()`
- Execution: `execution/order_watcher.py`

---

### **Path 3: Risk Manager Force EXIT**

```
Risk Manager Heartbeat [risk/supreme_risk.py]
    ├─ Monitor daily PnL
    ├─ Check loss limits
    ├─ Check cooldown periods
    └─ If violated:
        └─ request_force_exit()
    ↓
bot.request_force_exit() [trading_bot.py]
    ├─ Signal ALL active positions to exit
    ├─ Set reason="RISK_FORCE_EXIT"
    └─ For each position:
        ├─ Create exit_cmd
        ├─ CommandService.register()
        └─ Wait for OrderWatcherEngine
    ↓
OrderWatcherEngine executes forced exits
    ├─ Convert to broker order
    ├─ Execute immediately
    └─ Log as forced exit
    ↓
Track: OrderRecord with tag="RISK_FORCE_EXIT"
```

**Key Files:**
- Risk Trigger: `risk/supreme_risk.py:heartbeat()`
- Exit Request: `execution/trading_bot.py:request_emergency_exit()`
- Registration: `execution/command_service.py:register()`
- Execution: `execution/order_watcher.py`

---

### **Path 4: OrderWatcherEngine Auto EXIT (SL/Trailing)**

```
OrderWatcherEngine polling loop [execution/order_watcher.py]
    ├─ Every 1 second: _reconcile_broker_orders()
    ├─ Fetch open ENTRY orders
    ├─ Get live LTP for each symbol
    └─ For each ENTRY order:
        ├─ Check: stop_loss triggered?
        ├─ Check: trailing_stop triggered?
        └─ If YES: handle_exit_intent()
    ↓
handle_exit_intent() [order_watcher.py]
    ├─ Determine exit direction (SELL if BUY, vice versa)
    ├─ Determine order_type (LIMIT if required, MARKET else)
    ├─ Create UniversalOrderCommand (execution_type="EXIT")
    └─ CommandService.register()
    ↓
CommandService.register()
    ├─ Create OrderRecord (execution_type="EXIT")
    ├─ 🔒 NO direct execution
    └─ Mark original entry as exit-triggered
    ↓
OrderWatcherEngine (next cycle)
    ├─ Fetch new EXIT orders
    ├─ Validate order_type rules (via ScriptMaster)
    ├─ Execute to broker
    └─ Monitor completion
    ↓
Status tracking:
    ├─ ENTRY order: status="EXIT_TRIGGERED"
    ├─ EXIT order: status="SENT_TO_BROKER" → "EXECUTED"
    └─ Mark entry as executed (remove from pending)
```

**Key Files:**
- Monitoring: `execution/order_watcher.py:_reconcile_broker_orders()`
- Exit Trigger: `execution/order_watcher.py:handle_exit_intent()`
- Registration: `execution/command_service.py:register()`
- Rules Validation: `scripts/scriptmaster.py:requires_limit_order()`

---

### **Path 5: OrderWatcherEngine Orphan Order Cleanup**

```
OrderWatcherEngine._reconcile_broker_orders()
    ├─ Fetch broker order book
    └─ For each broker order:
        ├─ Lookup in OrderRepository
        ├─ If found: Update status (COMPLETE/CANCELLED/REJECTED)
        └─ If NOT found (orphan):
            ├─ Log warning ONCE per runtime
            ├─ If COMPLETE: Create shadow OrderRecord
            │   └─ execution_type="BROKER_ONLY" (non-actionable)
            └─ Never inject as actionable ENTRY
    ↓
Shadow Record Purpose:
    ├─ Observability (tests, reporting)
    ├─ No authority violation
    └─ Marked with tag="ORPHAN_BROKER_ORDER"
```

**Key Files:**
- Reconciliation: `execution/order_watcher.py:_reconcile_broker_orders()`
- Shadow Record: `persistence/models.py:OrderRecord`

---

## 📊 INTENT GENERATION SUMMARY TABLE

### **Entry Intents Generated By:**

| File | Function | Trigger | Intent ID Format | Database |
|---|---|---|---|---|
| `execution_app.py` | `webhook()` | TradingView signal | Auto (via trading_bot) | orders.db → OrderRecord |
| `intent_router.py` | `submit_generic_intent()` | Dashboard UI | DASH-GEN-{random} | orders.db → control_intents |
| `intent_router.py` | `submit_strategy_intent()` | Dashboard UI | DASH-STR-{random} | orders.db → control_intents |
| `intent_router.py` | `submit_advanced_intent()` | Dashboard UI | DASH-ADV-{random} | orders.db → control_intents |
| `intent_router.py` | `submit_basket_intent()` | Dashboard UI | DASH-BAS-{random} | orders.db → control_intents |
| `telegram_controller.py` | Command handler | Telegram | Auto (via bot) | orders.db → OrderRecord |
| Strategy Script | `entry()` method | Internal logic | Via process_alert | orders.db → OrderRecord |

### **Exit Intents Generated By:**

| File | Function | Trigger | Intent ID Format | Database |
|---|---|---|---|---|
| `intent_router.py` | `submit_generic_intent()` | Dashboard UI (exit) | DASH-GEN-{random} | orders.db → control_intents |
| `intent_router.py` | `submit_strategy_intent()` | Dashboard UI (EXIT action) | DASH-STR-{random} | orders.db → control_intents |
| `trading_bot.py` | `request_exit()` | Dashboard/Strategy | Auto (via command_service) | orders.db → OrderRecord |
| `supreme_risk.py` | `request_force_exit()` | Risk violation | Auto (via trading_bot) | orders.db → OrderRecord |
| `order_watcher.py` | `handle_exit_intent()` | SL/Trailing trigger | Auto (via command_service) | orders.db → OrderRecord |

---

## 🔐 CRITICAL RULES & GUARDS

### **Entry Order Guards:**

1. **Duplicate Entry Block** (3-layer defense):
   - Memory check: `has_live_entry_block()` 
   - DB check: `OrderRepository.get_open_orders_by_strategy()`
   - Broker check: `api.get_positions()`

2. **Execution Guard Validation**:
   - `ExecutionGuard.validate_and_prepare()`
   - Returns only validated intents
   - Raises RuntimeError if blocked

3. **Product Type Matching**:
   - Enforced in `process_leg()`
   - SL orders must be triggered (from ScriptMaster rules)

### **Exit Order Guards:**

1. **Position Existence Check**:
   - Fetch positions via `api.get_positions()`
   - Reject if position not found or qty=0

2. **Quantity Validation**:
   - Adjust if requested > available
   - Log warning for partial exit

3. **Product Type Consistency**:
   - Must match broker position
   - Raises error if mismatch

4. **Risk Manager Authority**:
   - Can force exit any position
   - Overrides normal constraints
   - Marked with tag="RISK_FORCE_EXIT"

---

## 🗄️ DATABASE FLOW

### **control_intents Table** (Dashboard-only intents):
```
id                 | type    | payload           | source    | status    | created_at
DASH-GEN-abc123    | GENERIC | {legs:[...]}      | DASHBOARD | ACCEPTED  | timestamp
DASH-STR-def456    | STRATEGY| {strategy:..}     | DASHBOARD | ACCEPTED  | timestamp
DASH-ADV-ghi789    | ADVANCED| {legs:[...]}      | DASHBOARD | ACCEPTED  | timestamp
DASH-BAS-jkl012    | BASKET  | {orders:[...]}    | DASHBOARD | ACCEPTED  | timestamp
```

### **OrderRecord Table** (All broker orders):
```
command_id        | execution_type | status         | symbol    | side | qty | broker_order_id
cmd-uuid-1        | ENTRY          | SENT_TO_BROKER | NIFTY50   | BUY  | 50  | BRK-001
cmd-uuid-2        | ENTRY          | EXECUTED       | NIFTY50   | BUY  | 50  | BRK-001
cmd-uuid-3        | EXIT           | CREATED        | NIFTY50   | SELL | 50  | (pending)
cmd-uuid-4        | EXIT           | SENT_TO_BROKER | NIFTY50   | SELL | 50  | BRK-002
cmd-uuid-5        | EXIT           | EXECUTED       | NIFTY50   | SELL | 50  | BRK-002
```

---

## 🎯 EXECUTION LIFECYCLE

### **ENTRY Order Lifecycle:**

```
1. INTENT CREATED (in-memory)
   - UniversalOrderCommand built
   - Added to pending_commands list

2. SUBMITTED (registration)
   - CommandService.submit()
   - OrderRecord created (status=CREATED)
   - Sent to broker via ShoonyaClient

3. BROKER ACCEPTED
   - OrderRecord status=SENT_TO_BROKER
   - broker_order_id assigned
   - OrderWatcherEngine monitors

4. BROKER EXECUTED
   - Broker reports COMPLETE
   - OrderWatcherEngine updates status=EXECUTED
   - Removed from pending_commands
   - Trade recorded

5. POSITION OPEN
   - Tracking for SL/Trailing via OrderWatcherEngine
   - Available for EXIT orders
```

### **EXIT Order Lifecycle:**

```
1. EXIT INTENT CREATED
   - Via Dashboard, Strategy, or Risk Manager
   - Via SL/Trailing trigger from OrderWatcherEngine
   - UniversalOrderCommand built (execution_type=EXIT)

2. INTENT REGISTERED (not submitted)
   - CommandService.register() called
   - OrderRecord created (status=CREATED)
   - 🔒 NOT sent to broker yet

3. WAITING FOR WATCHER
   - OrderWatcherEngine polls OrderRepository
   - Detects new EXIT orders
   - Validates order_type rules (via ScriptMaster)

4. EXECUTED BY WATCHER
   - OrderWatcherEngine.execute_exit()
   - Creates broker order
   - Monitors for completion

5. BROKER COMPLETED
   - OrderRecord status=EXECUTED
   - Position closed
   - ENTRY order marked as executed
```

---

## 📈 ARCHITECTURE DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INTENT SOURCES                              │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────┤
│ TradingView  │ Dashboard UI │  Telegram    │ Risk Manager │ Strategy│
│  Webhook     │              │  Commands    │   Alerts     │  Logic  │
└──────────────┴──────────────┴──────────────┴──────────────┴─────────┘
       │              │               │              │           │
       │              │               │              │           │
┌──────────────┬──────────────┬──────────────────────────────────────┐
│ /webhook     │ /intent/*    │      bot.process_alert()            │
│ endpoint     │ endpoints    │      bot.request_exit()             │
│ (execution   │ (intent_     │      bot.request_force_exit()       │
│  _app.py)    │ router.py)   │                                     │
│              │              │                                     │
│              │ Intent       │                                     │
│              │ persisted    │                                     │
│              │ to control_  │                                     │
│              │ intents      │                                     │
│              │ table        │                                     │
└──────┬───────┴──┬───────────┴──────────┬───────────────────────────┘
       │          │                      │
       │    ┌─────▼────────┐             │
       │    │ CONSUMERS    │             │
       │    │ (background  │             │
       │    │  threads)    │             │
       │    │              │             │
       │    │ GenericControl    │        │
       │    │ Consumer      │             │
       │    │              │             │
       │    │ StrategyControl   │        │
       │    │ Consumer      │             │
       │    └──────┬────────┘             │
       │           │                     │
       └───────────┼─────────────────────┘
                   │
                   ▼
            ┌──────────────────┐
            │ trading_bot.py   │
            │ process_alert()  │
            └────────┬─────────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
         ▼           ▼           ▼
    ┌────────────┐ ┌──────────┐ ┌──────────┐
    │Execution  │ │OrderWatcher  │OrderWatcher│
    │Guard      │ │(SL/Trailing) │(Reconcile) │
    │Validation │ │              │           │
    └────────────┘ └──────────┘ └──────────┘
         │                      │
         ▼                      │
    ┌─────────────────────────┐ │
    │ CommandService          │ │
    │ .submit() / .register() │ │
    └────────────┬────────────┘ │
                 │              │
         ┌───────┴──────────────┘
         │
         ▼
    ┌─────────────────────────────┐
    │  ShoonyaClient              │
    │  .place_order()             │
    │  .modify_order()            │
    │  .cancel_order()            │
    └────────────┬────────────────┘
                 │
                 ▼
         ┌──────────────────┐
         │   BROKER API     │
         │   (Shoonya)      │
         └──────────────────┘
```

---

## 🔍 DETAILED INTENT GENERATION MAPPING

### **ENTRY Intents**

**1. TradingView Path:**
```
File: api/http/execution_app.py:webhook()
Line: ~74
↓
Calls: bot.process_alert(alert_data)
File: execution/trading_bot.py:process_alert()
Line: ~784
↓
Creates: UniversalOrderCommand via process_leg()
File: execution/trading_bot.py:process_leg()
Line: ~628
↓
Submits: CommandService.submit()
File: execution/command_service.py:submit()
Line: ~100
```

**2. Dashboard Generic Path:**
```
File: api/dashboard/api/intent_router.py:submit_generic_intent()
Line: ~48
↓
Calls: service.submit_generic_intent(req)
File: api/dashboard/services/intent_utility.py:submit_generic_intent()
Line: ~56
↓
Persists: control_intents table (type=GENERIC)
↓
Consumed by: GenericControlIntentConsumer
File: execution/generic_control_consumer.py:_process_next_intent()
Line: ~193
↓
Calls: _execute_generic_payload()
Line: ~82
↓
Calls: bot.process_alert()
File: execution/trading_bot.py:process_alert()
Line: ~784
```

**3. Dashboard Strategy Path:**
```
File: api/dashboard/api/intent_router.py:submit_strategy_intent()
Line: ~67
↓
Calls: service.submit_strategy_intent(req)
File: api/dashboard/services/intent_utility.py:submit_strategy_intent()
Line: ~129
↓
Persists: control_intents table (type=STRATEGY)
↓
Consumed by: StrategyControlConsumer
File: execution/strategy_control_consumer.py:_process_next_strategy_intent()
Line: ~74
↓
Routes based on action (ENTRY/EXIT/ADJUST/FORCE_EXIT)
ENTRY action: bot.request_entry(strategy_name)
File: execution/trading_bot.py:request_entry()
Line: ~??? (if exists)
```

**4. Dashboard Advanced Path:**
```
File: api/dashboard/api/intent_router.py:submit_advanced_intent()
Line: ~90
↓
Calls: service._insert_intent() with type=ADVANCED
File: api/dashboard/services/intent_utility.py:_insert_intent()
Line: ~165
↓
Persists: control_intents table (type=ADVANCED)
↓
Consumed by: GenericControlIntentConsumer
File: execution/generic_control_consumer.py:_process_next_intent()
Line: ~193
↓
Processes each leg individually via _execute_generic_payload()
```

**5. Dashboard Basket Path:**
```
File: api/dashboard/api/intent_router.py:submit_basket_intent()
Line: ~134
↓
Calls: service.submit_basket_intent(req)
File: api/dashboard/services/intent_utility.py:submit_basket_intent()
Line: ~??? 
↓
Persists: control_intents table (type=BASKET)
↓
Consumed by: GenericControlIntentConsumer
File: execution/generic_control_consumer.py:_process_next_intent()
Line: ~193
↓
Special handling: Separates EXIT vs ENTRY orders
File: execution/generic_control_consumer.py:_process_next_intent()
Line: ~240
```

---

### **EXIT Intents**

**1. Dashboard Direct EXIT Path:**
```
File: api/dashboard/api/intent_router.py:submit_generic_intent()
Line: ~48 (with execution_type="EXIT")
↓
Calls: service.submit_generic_intent(req)
File: api/dashboard/services/intent_utility.py:submit_generic_intent()
Line: ~56
↓
Persists: control_intents table
Payload contains: execution_type="EXIT"
↓
Consumed by: GenericControlIntentConsumer
File: execution/generic_control_consumer.py:_execute_generic_payload()
Line: ~82
↓
Calls: bot.process_alert() with execution_type="EXIT"
File: execution/trading_bot.py:process_alert()
Line: ~784 (special EXIT handling ~900-950)
↓
Calls: process_leg() for EXIT
Line: ~860-920
↓
Creates: UniversalOrderCommand (execution_type=EXIT)
↓
Submits: CommandService.submit()
Line: ~100
```

**2. Dashboard Strategy EXIT Path:**
```
File: api/dashboard/api/intent_router.py:submit_strategy_intent()
Line: ~67 (with action="EXIT")
↓
Calls: service.submit_strategy_intent(req)
↓
Persists: control_intents table (type=STRATEGY, action=EXIT)
↓
Consumed by: StrategyControlConsumer
File: execution/strategy_control_consumer.py:_process_next_strategy_intent()
Line: ~97
↓
Routes: action == "EXIT"
↓
Calls: bot.request_exit(strategy_name)
File: execution/trading_bot.py:request_exit()
Line: ~360
↓
Creates: UniversalOrderCommand (execution_type=EXIT)
↓
Calls: CommandService.register()
File: execution/command_service.py:register()
Line: ~45
```

**3. Risk Manager Force EXIT Path:**
```
File: risk/supreme_risk.py:heartbeat()
Line: ~??? 
↓
Detects: Loss threshold exceeded OR cooldown period active
↓
Calls: bot.request_force_exit()
File: execution/trading_bot.py:request_emergency_exit()
Line: ~1394
↓
For each position:
↓
Creates: UniversalOrderCommand (reason="RISK_FORCE_EXIT")
↓
Calls: CommandService.register()
File: execution/command_service.py:register()
Line: ~45
```

**4. OrderWatcherEngine SL/Trailing EXIT Path:**
```
File: execution/order_watcher.py:_reconcile_broker_orders()
Line: ~236
↓
Gets: open ENTRY orders from pending_commands or OrderRepository
↓
For each ENTRY:
↓
Fetches: LTP via bot.api.get_ltp()
↓
Checks: stop_loss or trailing_stop triggered
Lines: ~300-340
↓
If triggered: Calls handle_exit_intent()
Line: ~313
↓
Creates: UniversalOrderCommand (execution_type=EXIT)
↓
Calls: CommandService.register()
File: execution/command_service.py:register()
Line: ~45
```

---

## 📊 QUICK REFERENCE: WHICH FILE GENERATES WHAT

| Intent Type | Source File | Function | Line(s) | DB Table |
|---|---|---|---|---|
| **ENTRY - TradingView** | execution_app.py | webhook() | ~74 | orders.db → OrderRecord |
| **ENTRY - Dashboard Generic** | intent_router.py | submit_generic_intent() | ~48 | orders.db → control_intents |
| **ENTRY - Dashboard Strategy** | intent_router.py | submit_strategy_intent() | ~67 | orders.db → control_intents |
| **ENTRY - Dashboard Advanced** | intent_router.py | submit_advanced_intent() | ~90 | orders.db → control_intents |
| **ENTRY - Dashboard Basket** | intent_router.py | submit_basket_intent() | ~134 | orders.db → control_intents |
| **ENTRY - Telegram** | telegram_controller.py | handle_message() | ~? | orders.db → OrderRecord |
| **EXIT - Dashboard Direct** | intent_router.py | submit_generic_intent() | ~48 | orders.db → control_intents |
| **EXIT - Dashboard Strategy** | intent_router.py | submit_strategy_intent() | ~67 | orders.db → control_intents |
| **EXIT - Risk Manager** | supreme_risk.py | request_force_exit() | ~? | orders.db → OrderRecord |
| **EXIT - SL/Trailing** | order_watcher.py | handle_exit_intent() | ~313 | orders.db → OrderRecord |

---

## 🔗 CRITICAL FILE REFERENCES

### **Intent Generation Files:**
1. `api/http/execution_app.py` - TradingView webhook ingestion
2. `api/dashboard/api/intent_router.py` - Dashboard intent APIs
3. `api/dashboard/services/intent_utility.py` - Intent persistence service
4. `execution/trading_bot.py` - Core alert processor & exit requester
5. `risk/supreme_risk.py` - Risk-driven exit generation
6. `api/http/telegram_controller.py` - Telegram command parsing

### **Intent Processing Files:**
1. `execution/generic_control_consumer.py` - Dashboard intent consumer
2. `execution/strategy_control_consumer.py` - Strategy intent consumer

### **Execution Files:**
1. `execution/command_service.py` - Command router (submit/register)
2. `execution/order_watcher.py` - Exit executor & SL/Trailing manager
3. `execution/execution_guard.py` - Risk guard & duplicate protection
4. `execution/intent.py` - Intent/Command data structures
5. `brokers/shoonya/client.py` - Broker API client

### **Persistence Files:**
1. `persistence/repository.py` - Order repository (CRUD operations)
2. `persistence/models.py` - OrderRecord & database models
3. `persistence/database.py` - SQLite connection manager

---

## ✅ SUMMARY

### **Entry Order Sources:**
- ✅ TradingView WebhookWebhook
- ✅ Dashboard Generic Intent
- ✅ Dashboard Strategy Intent  
- ✅ Dashboard Advanced Multi-Leg Intent
- ✅ Dashboard Basket Intent
- ✅ Telegram Commands
- ✅ Strategy Internal Logic

### **Exit Order Sources:**
- ✅ Dashboard Direct EXIT Intent
- ✅ Dashboard Strategy EXIT Action
- ✅ Risk Manager Force EXIT
- ✅ OrderWatcherEngine (SL/Trailing Triggers)

All intents are **persisted to database** before execution, ensuring **restart safety** and **audit trail**.

