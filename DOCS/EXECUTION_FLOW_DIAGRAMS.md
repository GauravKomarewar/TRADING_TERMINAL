# Shoonya Platform - Flow Diagrams

## 1. HIGH-LEVEL SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL SOURCES                                   │
├──────────────────┬──────────────────┬────────────────┬──────────────────────┤
│  TradingView     │  Dashboard UI    │  Telegram      │  Risk/Strategy Logic │
│  Webhooks        │  (Web Interface) │  Bot Commands  │  (Internal Alerts)   │
└────┬─────────────┴────┬─────────────┴────┬───────────┴──────┬──────────────┘
     │                  │                    │                   │
     │                  │                    │                   │
┌────▼──────────────────▼────────────────────▼───────────────────▼──────────────┐
│                     INTENT GENERATION LAYER                                    │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐        │
│  │ /webhook         │  │ /intent/generic  │  │ request_exit()     │        │
│  │ (execution_app)  │  │ (intent_router)  │  │ request_force_exit│        │
│  │                  │  │                  │  │ (trading_bot)      │        │
│  │ Returns OrderId  │  │ Returns IntentId │  │ Returns nothing    │        │
│  │ Immediately      │  │ (queued)         │  │ (registers only)   │        │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬───────────┘        │
│           │                     │                     │                     │
│  ┌────────▼─────────┐  ┌────────▼─────────┐  ┌───────▼────────────┐       │
│  │ Async to Bot     │  │ Async to Queue   │  │ Async to Queue     │       │
│  │ process_alert()  │  │ control_intents  │  │ or pending_commands│       │
│  └──────────────────┘  └──────────────────┘  └────────────────────┘       │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
         ┌──────────▼────────┐   ┌───▼──────────┐  ┌─▼──────────────────┐
         │ process_alert()   │   │ Consumers    │  │ OrderWatcherEngine │
         │ (immediate)       │   │ (polling)    │  │ (background)       │
         │                   │   │              │  │                    │
         │ - ExecutionGuard  │   │ - Generic    │  │ - Monitors ENTRY   │
         │ - Duplicate block │   │ - Strategy   │  │ - Triggers SL/TRL  │
         │ - process_leg()   │   │              │  │ - Executes EXIT    │
         │ - submit()        │   │              │  │                    │
         └───────────────────┘   └──────────────┘  └────────────────────┘
                    │                   │                    │
                    └───────────────────┼────────────────────┘
                                        │
                    ┌───────────────────▼────────────────┐
                    │    COMMAND SERVICE LAYER           │
                    ├────────────────────────────────────┤
                    │                                    │
                    │  submit() → ENTRY/ADJUST           │
                    │  register() → EXIT only            │
                    │                                    │
                    │  Creates OrderRecord               │
                    │  Executes via broker               │
                    │                                    │
                    └────────────┬─────────────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │  ShoonyaClient.place_order│
                    │  .modify_order()          │
                    │  .cancel_order()          │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │   BROKER SHOONYA API      │
                    │   (Real Trading)          │
                    └───────────────────────────┘
```

---

## 2. ENTRY ORDER FULL FLOW (5 Paths)

### **PATH 1: TradingView Webhook (Direct)**

```
TradingView Strategy
        │
        │ (JSON POST with signature)
        ▼
/webhook endpoint
(execution_app.py)
        │
    Validate signature
        │
    Parse JSON payload
        │
        ▼
process_alert(alert_data)
(trading_bot.py)
        │
    Check risk manager
    can_execute?
        │
        ├─ YES →→→ Continue
        │
        └─ NO →→→ BLOCKED
                  (return blocked status)
        │
    Parse alert data
        │
    ExecutionGuard
    reconcile_with_broker()
        │
    ExecutionGuard
    validate_and_prepare()
        │
        ├─ Check for duplicate entry
        ├─ Check for conflicts
        └─ Return validated intents
        │
    For each leg:
    process_leg()
        │
        ├─ Create UniversalOrderCommand
        ├─ Validate order_type/price
        ├─ Check LIMIT requirement (ScriptMaster)
        └─ Add to pending_commands
        │
    CommandService.submit()
        │
        ├─ Validate order
        ├─ Create OrderRecord (status=CREATED)
        ├─ Send to broker
        └─ Update status=SENT_TO_BROKER
        │
        ▼
OrderRecord in orders.db
execution_type=ENTRY
status=SENT_TO_BROKER
broker_order_id=assigned
        │
OrderWatcherEngine monitors
        │
        ├─ Broker returns COMPLETE
        │  └─ Update status=EXECUTED
        │
        ├─ Broker returns CANCELLED
        │  └─ Update status=FAILED
        │
        └─ Monitor SL/Trailing for exit
```

**Key Files:**
- Entry: `api/http/execution_app.py:webhook()` (line ~74)
- Processor: `execution/trading_bot.py:process_alert()` (line ~784)
- Executor: `execution/command_service.py:submit()` (line ~100)
- Monitor: `execution/order_watcher.py:_process_orders()` (line ~236)

---

### **PATH 2: Dashboard Generic Intent**

```
Dashboard UI
"Buy NIFTY50 @100"
        │
        ▼
POST /dashboard/intent/generic
(intent_router.py, line ~48)
        │
    Validate GenericIntentRequest
        │
        ▼
DashboardIntentService
.submit_generic_intent()
(intent_utility.py, line ~56)
        │
    Generate intent_id
    (DASH-GEN-{random})
        │
    Create payload dict
    {symbol, side, qty, ...}
        │
        ▼
_insert_intent() to control_intents
(intent_utility.py, line ~165)
        │
    INSERT INTO control_intents
    type=GENERIC
    status=PENDING
        │
        ▼
HTTP 200
IntentResponse
{"accepted": true,
 "intent_id": "DASH-GEN-abc123"}
        │
        ├─ Client satisfied immediately
        │  (async execution follows)
        │
        └─ Background polling starts
        │
GenericControlIntentConsumer
run_forever() (background thread)
(generic_control_consumer.py, line ~67)
        │
Every 1 second:
        │
_claim_next_intent()
        │
UPDATE control_intents
SET status=CLAIMED
WHERE id=... AND status=PENDING
        │
_execute_generic_payload()
(generic_control_consumer.py, line ~82)
        │
    Build alert leg:
    {tradingsymbol, direction, qty,
     order_type, price, ...}
        │
    Create alert_payload
    (PineScript format)
        │
        ▼
bot.process_alert(alert_payload)
(trading_bot.py:process_alert, line ~784)
        │
    [SAME AS PATH 1 FROM HERE]
        │
        └─→ ExecutionGuard
        └─→ process_leg()
        └─→ CommandService.submit()
        └─→ OrderRecord created
        └─→ Broker execution
        │
        ▼
_update_status(intent_id, "ACCEPTED")
        │
UPDATE control_intents
SET status=ACCEPTED
WHERE id=intent_id
        │
    Telegram notification
    sent (if enabled)
```

**Key Files:**
- Intent Creation: `api/dashboard/api/intent_router.py:submit_generic_intent()` (line ~48)
- Intent Persistence: `api/dashboard/services/intent_utility.py:submit_generic_intent()` (line ~56)
- Intent Consumer: `execution/generic_control_consumer.py:GenericControlIntentConsumer` (class)
- Processor: `execution/trading_bot.py:process_alert()` (line ~784)

---

### **PATH 3: Dashboard Strategy Intent**

```
Dashboard UI
"Strategy: NIFTY_short → ENTRY"
        │
        ▼
POST /dashboard/intent/strategy
(intent_router.py, line ~67)
        │
    Validate StrategyIntentRequest
        │
        ▼
DashboardIntentService
.submit_strategy_intent()
(intent_utility.py, line ~129)
        │
    Generate intent_id
    (DASH-STR-{random})
        │
    Create payload:
    {strategy_name, action}
    action ∈ {ENTRY, EXIT, ADJUST, FORCE_EXIT}
        │
        ▼
_insert_intent() to control_intents
(intent_utility.py, line ~165)
        │
    INSERT INTO control_intents
    type=STRATEGY
    status=PENDING
        │
        ▼
HTTP 200 IntentResponse
        │
        ├─ Client satisfied immediately
        │
        └─ Background polling starts
        │
StrategyControlConsumer
run_forever() (background thread)
(strategy_control_consumer.py, line ~49)
        │
Every 1 second:
        │
_claim_next_strategy_intent()
        │
_process_next_strategy_intent()
(strategy_control_consumer.py, line ~74)
        │
    Extract strategy_name & action
        │
    [ACTION DISPATCH]
        │
    ├─ action == "ENTRY"
    │  └─ bot.request_entry(strategy_name)
    │     └─ Calls strategy.entry()
    │        └─ Strategy generates intents
    │           via internal logic
    │
    ├─ action == "EXIT"
    │  └─ bot.request_exit(strategy_name)
    │
    ├─ action == "ADJUST"
    │  └─ bot.request_adjust(strategy_name)
    │
    └─ action == "FORCE_EXIT"
       └─ bot.request_force_exit(strategy_name)
        │
_update_status(intent_id, "ACCEPTED")
        │
UPDATE control_intents
SET status=ACCEPTED
```

**Key Files:**
- Intent Creation: `api/dashboard/api/intent_router.py:submit_strategy_intent()` (line ~67)
- Intent Consumer: `execution/strategy_control_consumer.py:StrategyControlConsumer` (class)
- Strategy Manager: `execution/trading_bot.py:request_entry/exit/adjust/force_exit()` (line ~360+)

---

### **PATH 4: Dashboard Advanced Multi-Leg Intent**

```
Dashboard UI
"Multi-leg spread entry"
        │
        ▼
POST /dashboard/intent/advanced
(intent_router.py, line ~90)
        │
    Validate AdvancedIntentRequest
    {legs: [{symbol, side, qty, order_type, price}, ...]}
        │
        ▼
DashboardIntentService._insert_intent()
(intent_utility.py, line ~165)
        │
    Generate intent_id (DASH-ADV-{random})
        │
    INSERT INTO control_intents
    type=ADVANCED
    payload={legs: [...]}
        │
        ▼
HTTP 200
        │
GenericControlIntentConsumer
        │
_process_next_intent()
        │
    Detect: intent_type == "ADVANCED"
        │
    Extract legs from payload
        │
    For each leg:
        │
    _execute_generic_payload()
        │
        ├─ Build alert leg
        ├─ Create alert_payload
        └─ bot.process_alert()
        │
        ▼
    Track success/failure per leg
        │
    [Continue to EXECUTION]
```

**Key Files:**
- Intent Creation: `api/dashboard/api/intent_router.py:submit_advanced_intent()` (line ~90)
- Intent Consumer: `execution/generic_control_consumer.py:_process_next_intent()` (line ~193)

---

### **PATH 5: Dashboard Basket Intent (Atomic)**

```
Dashboard UI
"Basket: [SELL stale pos, BUY new pos]"
        │
        ▼
POST /dashboard/intent/basket
(intent_router.py, line ~134)
        │
    Validate BasketIntentRequest
    {orders: [{execution_type, symbol, side, qty}, ...]}
        │
        ▼
DashboardIntentService.submit_basket_intent()
        │
    Generate intent_id (DASH-BAS-{random})
        │
    Persist all orders atomically:
    INSERT INTO control_intents
    type=BASKET
    payload={orders: [all orders]}
        │
        ▼
HTTP 200 (all orders queued)
        │
GenericControlIntentConsumer
        │
_process_next_intent()
        │
    Detect: intent_type == "BASKET"
        │
    Extract orders array
        │
    RISK-SAFE ORDERING:
    ├─ Separate EXIT orders
    ├─ Separate ENTRY orders
    └─ Process EXITs first (reduces risk)
        │
    For each EXIT order:
    ├─ _execute_generic_payload()
    ├─ bot.process_alert(execution_type=EXIT)
    └─ Track result
        │
    For each ENTRY order:
    ├─ _execute_generic_payload()
    ├─ bot.process_alert(execution_type=ENTRY)
    └─ Track result
        │
    Update intent status:
    ACCEPTED / PARTIALLY_ACCEPTED / REJECTED
```

**Key Files:**
- Intent Creation: `api/dashboard/api/intent_router.py:submit_basket_intent()` (line ~134)
- Intent Consumer: `execution/generic_control_consumer.py:_process_next_intent()` (line ~240)

---

## 3. EXIT ORDER FULL FLOW (4 Paths)

### **PATH 1: Dashboard Direct EXIT**

```
Dashboard UI
"Exit NIFTY50 position"
        │
        ▼
POST /dashboard/intent/generic
(with execution_type="EXIT")
(intent_router.py, line ~48)
        │
    Validate & persist intent
        │
        ▼
GenericControlIntentConsumer
        │
_execute_generic_payload()
        │
    Build leg (direction set to current position inverse)
    Create alert_payload with execution_type="EXIT"
        │
        ▼
bot.process_alert()
(execution_type="EXIT")
(trading_bot.py, line ~784)
        │
    Skip ExecutionGuard 
    (EXIT always allowed)
        │
    For each leg:
    ├─ Fetch broker positions
    ├─ Validate position exists
    ├─ Determine exit side (inverse of position)
    ├─ Adjust qty if needed
    └─ process_leg(execution_type="EXIT")
        │
        ▼
CommandService.submit()
(execution_type="EXIT")
        │
    Create OrderRecord
    execution_type=EXIT
    status=CREATED
        │
    Send to broker
    via ShoonyaClient
        │
    Update status=SENT_TO_BROKER
        │
        ▼
OrderWatcherEngine monitors
        │
    Broker COMPLETE
    └─ Update status=EXECUTED
    └─ Remove from pending
    └─ Position closed
```

**Key Files:**
- Intent Creation: `api/dashboard/api/intent_router.py:submit_generic_intent()` (line ~48)
- Intent Consumer: `execution/generic_control_consumer.py:_execute_generic_payload()` (line ~82)
- Processor: `execution/trading_bot.py:process_alert()` (line ~784, EXIT handling ~900-950)
- Executor: `execution/command_service.py:submit()` (line ~100)

---

### **PATH 2: Dashboard Strategy EXIT**

```
Dashboard UI
"Strategy: NIFTY_short → EXIT"
        │
        ▼
POST /dashboard/intent/strategy
(with action="EXIT")
(intent_router.py, line ~67)
        │
    Persist intent
        │
        ▼
StrategyControlConsumer
        │
_process_next_strategy_intent()
        │
    action == "EXIT"
        │
        ▼
bot.request_exit(strategy_name)
(trading_bot.py, line ~360)
        │
    Fetch broker positions
        │
    Find position for strategy symbol
        │
    If position exists & qty != 0:
        │
    ├─ Determine exit_side
    │  (SELL if BUY, BUY if SELL)
    │
    ├─ Create UniversalOrderCommand
    │  execution_type=EXIT
    │
    └─ CommandService.register()
        │
        ▼
CommandService.register()
(execution/command_service.py, line ~45)
        │
    Create OrderRecord
    execution_type=EXIT
    status=CREATED
        │
    🔒 NO broker submission yet
    (just register intent)
        │
    Store in OrderRepository
        │
        ▼
OrderWatcherEngine monitoring
        │
_process_orders() polls repository
        │
Finds new EXIT order
        │
    Validates order_type rules
    (via ScriptMaster.requires_limit_order)
        │
    Executes to broker
        │
    Monitors for COMPLETE
        │
    Updates status=EXECUTED
        │
    Closes position
        │
    Marks ENTRY order as executed
```

**Key Files:**
- Intent Creation: `api/dashboard/api/intent_router.py:submit_strategy_intent()` (line ~67)
- Intent Consumer: `execution/strategy_control_consumer.py:StrategyControlConsumer` (class)
- Exit Requester: `execution/trading_bot.py:request_exit()` (line ~360)
- Registration: `execution/command_service.py:register()` (line ~45)
- Executor: `execution/order_watcher.py:_process_orders()` (line ~236)

---

### **PATH 3: Risk Manager FORCE EXIT**

```
Risk Manager
(risk/supreme_risk.py)
heartbeat() called every 5 seconds
        │
    Check daily PnL
        │
    Check against loss threshold
        │
    Check cooldown period active
        │
    If ANY violation:
        │
        ▼
request_force_exit()
(trading_bot.py, line ~1394)
        │
    Telegram alert sent:
    "RISK VIOLATION - FORCE EXIT"
        │
    Fetch all broker positions
        │
    For each active position:
        │
    ├─ Create UniversalOrderCommand
    │  side = inverse of position
    │  reason = "RISK_FORCE_EXIT"
    │
    └─ CommandService.register()
        │
        ▼
CommandService.register()
        │
    Create OrderRecord
    execution_type=EXIT
    tag="RISK_FORCE_EXIT"
    status=CREATED
        │
        ▼
OrderWatcherEngine
        │
    Detects forced exit orders
        │
    Executes immediately (high priority)
        │
    Closes all positions
        │
    Restarts risk cooldown timer
        │
        ▼
Telegram: "Force exit complete"
Trading halted for cooldown period
```

**Key Files:**
- Risk Check: `risk/supreme_risk.py:heartbeat()` (line ~???)
- Exit Trigger: `execution/trading_bot.py:request_emergency_exit()` (line ~1394)
- Registration: `execution/command_service.py:register()` (line ~45)
- Executor: `execution/order_watcher.py:_process_orders()` (line ~236)

---

### **PATH 4: OrderWatcherEngine SL/Trailing EXIT**

```
OrderWatcherEngine
(continuous background thread)
(execution/order_watcher.py)
        │
        ▼
while _running:
    _reconcile_broker_orders()
    _process_orders()
    sleep(1 second)
        │
        ├─ Every reconcile cycle:
        │  ├─ Fetch broker order book
        │  ├─ Update DB status for known orders
        │  └─ Handle orphan orders (shadow record)
        │
        └─ Every process cycle:
           │
           ▼
        _process_orders()
        (line ~236)
           │
        Get open ENTRY orders
        (from pending_commands or OrderRepository)
           │
        For each ENTRY order:
           │
           ├─ Skip if already exit-fired
           │
           ├─ Fetch live LTP
           │  via bot.api.get_ltp(exchange, symbol)
           │
           ├─ Calculate P&L against price
           │
           ├─ Check STOP LOSS:
           │  if LTP <= stop_loss_level:
           │      └─ TRIGGER SL EXIT
           │
           ├─ Check TRAILING STOP:
           │  (if trailing_type != NONE)
           │  ├─ Points: LTP drops X points from high
           │  ├─ Percent: LTP drops X% from high
           │  ├─ Absolute: LTP at specific level
           │  └─ If triggered:
           │      └─ TRIGGER TRAILING EXIT
           │
           └─ If exit triggered:
              │
              ▼
           _fire_exit()
           (line ~313)
              │
              ├─ Determine exit_side
              │  (SELL if ENTRY was BUY, vice versa)
              │
              ├─ Determine order_type
              │  if requires_limit_order():
              │      use LIMIT with SL price
              │  else:
              │      use MARKET
              │
              ├─ Create UniversalOrderCommand
              │  execution_type=EXIT
              │  source=ENGINE_SOURCE
              │
              └─ CommandService.register()
                 │
                 ▼
              OrderRecord created
              execution_type=EXIT
              status=CREATED
                 │
              Mark original ENTRY
              _exit_fired=True
              (prevent double-trigger)
                 │
              Next polling cycle:
              _process_orders()
              │
              Finds new EXIT order
              Executes to broker
              │
              Monitors for COMPLETE
              │
              Updates status=EXECUTED
              │
              Position closed
              │
              Removed from pending_commands
              │
              Trade logged
```

**Key Files:**
- Monitoring: `execution/order_watcher.py:_process_orders()` (line ~236)
- Exit Trigger: `execution/order_watcher.py:_fire_exit()` (line ~313)
- Registration: `execution/command_service.py:register()` (line ~45)

---

## 4. INTENT FLOW QUICK MATRIX

```
INTENT TYPE         │ SOURCE FILE             │ GENERATOR FUNCTION        │ CONSUMER         │ DATABASE
────────────────────┼─────────────────────────┼──────────────────────────┼──────────────────┼──────────────
ENTRY-TradingView   │ execution_app.py        │ webhook()                 │ process_alert()  │ OrderRecord
ENTRY-Dashboard     │ intent_router.py        │ submit_generic_intent()   │ GenericConsumer  │ control_intents
ENTRY-Strategy      │ intent_router.py        │ submit_strategy_intent()  │ StrategyConsumer │ control_intents
ENTRY-Advanced      │ intent_router.py        │ submit_advanced_intent()  │ GenericConsumer  │ control_intents
ENTRY-Basket        │ intent_router.py        │ submit_basket_intent()    │ GenericConsumer  │ control_intents
EXIT-Dashboard      │ intent_router.py        │ submit_generic_intent()   │ GenericConsumer  │ control_intents
EXIT-Strategy       │ intent_router.py        │ submit_strategy_intent()  │ StrategyConsumer │ control_intents
EXIT-Risk           │ supreme_risk.py         │ request_force_exit()      │ OrderWatcher     │ OrderRecord
EXIT-SL/Trailing    │ order_watcher.py        │ _fire_exit()              │ (self)           │ OrderRecord
```

---

## 5. DATABASE FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────┐
│                   PERSISTENCE LAYER (SQLite)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │  control_intents TABLE (Dashboard-only)                    │ │
│ ├────────────┬──────────┬──────────────┬──────────┬──────────┤ │
│ │ id         │ type     │ payload      │ status   │ created_ │ │
│ │            │          │              │          │ at       │ │
│ ├────────────┼──────────┼──────────────┼──────────┼──────────┤ │
│ │ DASH-GEN-* │ GENERIC  │ {legs:[...]} │ PENDING  │ timestamp│ │
│ │ DASH-STR-* │ STRATEGY │ {strategy:..}│ CLAIMED  │ timestamp│ │
│ │ DASH-ADV-* │ ADVANCED │ {legs:[...]} │ ACCEPTED │ timestamp│ │
│ │ DASH-BAS-* │ BASKET   │ {orders:[..]}│ REJECTED │ timestamp│ │
│ └────────────┴──────────┴──────────────┴──────────┴──────────┘ │
│                          │                                      │
│                          │ Consumed by:                         │
│                          ├─ GenericControlConsumer              │
│                          └─ StrategyControlConsumer             │
│                                                                 │
│ ┌────────────────────────────────────────────────────────────┐ │
│ │  OrderRecord TABLE (All orders: ENTRY/EXIT/ADJUST)         │ │
│ ├──────────────┬──────────────┬──────────┬──────────────────┤ │
│ │ command_id   │ execution_   │ broker_  │ status           │ │
│ │              │ type         │ order_id │                  │ │
│ ├──────────────┼──────────────┼──────────┼──────────────────┤ │
│ │ uuid-1       │ ENTRY        │ (null)   │ CREATED          │ │
│ │ uuid-2       │ ENTRY        │ BRK-001  │ SENT_TO_BROKER   │ │
│ │ uuid-3       │ ENTRY        │ BRK-001  │ EXECUTED         │ │
│ │ uuid-4       │ EXIT         │ (null)   │ CREATED          │ │
│ │ uuid-5       │ EXIT         │ BRK-002  │ SENT_TO_BROKER   │ │
│ │ uuid-6       │ EXIT         │ BRK-002  │ EXECUTED         │ │
│ │ uuid-7       │ BROKER_ONLY  │ BRK-003  │ EXECUTED         │ │
│ └──────────────┴──────────────┴──────────┴──────────────────┘ │
│                          │                                      │
│                          │ Monitored by:                        │
│                          ├─ OrderRepository queries             │
│                          └─ OrderWatcherEngine polls            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. COMMAND SERVICE ROUTING DIAGRAM

```
┌──────────────────────────────────────────────────────────────┐
│             CommandService (Gate Keeper)                      │
│         execution/command_service.py                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  def submit(cmd, execution_type):                           │
│      ├─ execution_type = ENTRY or ADJUST                   │
│      ├─ HARD BLOCK: EXIT forbidden                         │
│      ├─ Validate order                                      │
│      ├─ Setup trailing engine if needed                    │
│      ├─ Create OrderRecord (status=CREATED)                │
│      ├─ Execute via ShoonyaClient.place_order()            │
│      └─ Return OrderResult                                 │
│                                                              │
│                          │                                   │
│          ┌───────────────┴───────────────┐                  │
│          │                               │                  │
│          ▼                               ▼                  │
│    ┌──────────────┐             ┌──────────────┐           │
│    │ SUCCESS      │             │ FAILURE      │           │
│    │              │             │              │           │
│    │ Return       │             │ Return       │           │
│    │ order_id     │             │ error        │           │
│    │              │             │              │           │
│    │ Add to       │             │ OrderRecord  │           │
│    │ pending_     │             │ status=      │           │
│    │ commands     │             │ FAILED       │           │
│    │              │             │              │           │
│    └──────────────┘             └──────────────┘           │
│                                                              │
│  def register(cmd):                                         │
│      ├─ cmd must be EXIT (or ERROR if not)                 │
│      ├─ Validate order                                      │
│      ├─ Create OrderRecord (status=CREATED)                │
│      ├─ 🔒 NO broker submission                            │
│      └─ Return nothing (async via OrderWatcher)            │
│                                                              │
│                          │                                   │
│          ┌───────────────┴───────────────┐                  │
│          │                               │                  │
│          ▼                               ▼                  │
│    ┌──────────────┐             ┌──────────────┐           │
│    │ REGISTERED   │             │ VALIDATION   │           │
│    │              │             │ ERROR        │           │
│    │ OrderRecord  │             │              │           │
│    │ queued for   │             │ OrderRecord  │           │
│    │ OrderWatcher │             │ status=      │           │
│    │              │             │ FAILED       │           │
│    │ Watcher will │             │              │           │
│    │ execute when │             └──────────────┘           │
│    │ ready        │                                         │
│    │              │                                         │
│    └──────────────┘                                         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

