# Shoonya Platform - Executive Summary of Order Execution

## 📌 WHAT THIS DOCUMENT COVERS

This is the **complete mapping** of:
1. **All entry order paths** (where orders start)
2. **All exit order paths** (where orders end)
3. **Which files generate intents** for each path
4. **How intents flow through the system**

---

## 🎯 QUICK ANSWER: WHICH FILES GENERATE INTENTS?

### **FILES THAT GENERATE ENTRY INTENTS:**

| # | File | Function | Trigger |
|---|---|---|---|
| 1 | `api/http/execution_app.py` | `webhook()` | TradingView signal arrives |
| 2 | `api/dashboard/api/intent_router.py` | `submit_generic_intent()` | User clicks "Buy" on dashboard |
| 3 | `api/dashboard/api/intent_router.py` | `submit_strategy_intent()` | User clicks strategy "ENTRY" button |
| 4 | `api/dashboard/api/intent_router.py` | `submit_advanced_intent()` | User submits multi-leg spread |
| 5 | `api/dashboard/api/intent_router.py` | `submit_basket_intent()` | User submits atomic order basket |
| 6 | `api/http/telegram_controller.py` | `handle_message()` | User sends `/buy NIFTY50 50 100` |
| 7 | Strategy Script | `entry()` | Technical indicator fires internally |

### **FILES THAT GENERATE EXIT INTENTS:**

| # | File | Function | Trigger |
|---|---|---|---|
| 1 | `api/dashboard/api/intent_router.py` | `submit_generic_intent()` | User clicks "Sell" on dashboard |
| 2 | `api/dashboard/api/intent_router.py` | `submit_strategy_intent()` | User clicks strategy "EXIT" button |
| 3 | `risk/supreme_risk.py` | `request_force_exit()` | Daily loss exceeds limit |
| 4 | `execution/order_watcher.py` | `handle_exit_intent()` | Stop loss or trailing stop triggered |

---

## 🔄 THE 7 ENTRY PATHS

### **Path 1: TradingView Webhook**
```
TradingView Strategy Signal
    ↓ (HTTPS POST with JSON)
/webhook endpoint (execution_app.py:74)
    ↓
process_alert() (trading_bot.py:784)
    ↓
ExecutionGuard validation
    ↓
process_leg() → CommandService.submit()
    ↓
Broker order placed immediately
```
**Key Feature**: Synchronous, immediate execution  
**Database**: OrderRecord (direct)  
**Intent Source**: TradingView

---

### **Path 2: Dashboard Generic Intent**
```
Dashboard UI → "Buy 50 NIFTY50 @ MARKET"
    ↓ (HTTP POST)
/dashboard/intent/generic (intent_router.py:48)
    ↓
DashboardIntentService.submit_generic_intent()
    ↓
Persist to control_intents table
    ↓ (HTTP 200 returns immediately)
GenericControlIntentConsumer polls (background)
    ↓
Convert to alert → bot.process_alert()
    ↓
Broker order placed
```
**Key Feature**: Asynchronous, queued execution  
**Database**: control_intents table (then OrderRecord)  
**Intent Source**: Dashboard UI

---

### **Path 3: Dashboard Strategy Intent**
```
Dashboard UI → "Strategy: NIFTY_short → ENTRY"
    ↓ (HTTP POST)
/dashboard/intent/strategy (intent_router.py:67)
    ↓
DashboardIntentService.submit_strategy_intent()
    ↓
Persist to control_intents (action="ENTRY")
    ↓ (HTTP 200 returns immediately)
StrategyControlConsumer polls (background)
    ↓
bot.request_entry(strategy_name)
    ↓
Strategy's entry() method generates intents
    ↓
Broker orders placed via strategy logic
```
**Key Feature**: Strategy-driven, delegated execution  
**Database**: control_intents + OrderRecord  
**Intent Source**: Strategy internal logic

---

### **Path 4: Dashboard Advanced (Multi-Leg)**
```
Dashboard UI → Multi-leg spread (e.g., strangle, condor)
    ↓ (HTTP POST)
/dashboard/intent/advanced (intent_router.py:90)
    ↓
DashboardIntentService._insert_intent()
    ↓
Persist to control_intents (type="ADVANCED")
    ↓ (HTTP 200 returns immediately)
GenericControlIntentConsumer polls
    ↓
For each leg: convert → bot.process_alert()
    ↓
All legs submitted to broker
```
**Key Feature**: Atomic multi-leg, parallel execution  
**Database**: control_intents + OrderRecord (per leg)  
**Intent Source**: Dashboard UI

---

### **Path 5: Dashboard Basket (Atomic Orders)**
```
Dashboard UI → Basket of orders [EXIT old, ENTRY new]
    ↓ (HTTP POST)
/dashboard/intent/basket (intent_router.py:134)
    ↓
DashboardIntentService.submit_basket_intent()
    ↓
Persist all orders atomically to control_intents
    ↓ (HTTP 200 returns immediately)
GenericControlIntentConsumer polls
    ↓
Risk-safe ordering:
  1. Process all EXITs first (reduce position)
  2. Process all ENTRIEs next (lower risk)
    ↓
Orders submitted to broker
```
**Key Feature**: Atomic execution, risk-ordered  
**Database**: control_intents + OrderRecord  
**Intent Source**: Dashboard UI

---

### **Path 6: Telegram Commands**
```
User sends: "/buy NIFTY50 50"
    ↓ (Telegram API)
Telegram webhook → telegram_controller.py
    ↓
handle_message() parses command
    ↓
Builds alert payload
    ↓
bot.process_alert()
    ↓
Broker order placed
```
**Key Feature**: Interactive command-line style  
**Database**: OrderRecord (direct)  
**Intent Source**: Telegram bot user

---

### **Path 7: Strategy Internal ENTRY**
```
Strategy script running
    ↓
Technical indicator fires (e.g., price crosses MA)
    ↓
Strategy's entry() method called
    ↓
Generates alert payload internally
    ↓
Posts to webhook or direct bot.process_alert()
    ↓
Broker order placed
```
**Key Feature**: Fully automated, no UI  
**Database**: OrderRecord  
**Intent Source**: Strategy algorithm

---

## 🚪 THE 4 EXIT PATHS

### **Exit Path 1: Dashboard Direct EXIT**
```
Dashboard UI → "Exit position"
    ↓ (HTTP POST)
/dashboard/intent/generic with execution_type="EXIT"
    ↓
GenericControlIntentConsumer polls
    ↓
bot.process_alert(execution_type="EXIT")
    ↓
Fetch broker position
Determine exit side (inverse of position)
    ↓
process_leg() → CommandService.submit()
    ↓
Broker order placed
```
**Key Feature**: User-triggered exit  
**Speed**: Asynchronous  
**Database**: control_intents + OrderRecord

---

### **Exit Path 2: Dashboard Strategy EXIT**
```
Dashboard UI → "Strategy: NIFTY_short → EXIT"
    ↓ (HTTP POST)
/dashboard/intent/strategy with action="EXIT"
    ↓
StrategyControlConsumer polls
    ↓
bot.request_exit(strategy_name)
    ↓
Fetch broker position
Create UniversalOrderCommand (execution_type=EXIT)
    ↓
CommandService.register()
    ↓ (registers, does NOT execute yet)
OrderWatcherEngine picks it up (next cycle)
    ↓
Broker order placed
```
**Key Feature**: Strategy-aware exit  
**Speed**: Asynchronous (via watcher)  
**Database**: control_intents + OrderRecord

---

### **Exit Path 3: Risk Manager FORCE EXIT**
```
Risk Manager heartbeat() runs every 5 seconds
    ↓
Checks: daily_pnl < loss_threshold?
    ↓ (YES)
bot.request_force_exit()
    ↓
Telegram alert: "RISK VIOLATION - FORCE EXIT"
    ↓
For each active position:
  Create UniversalOrderCommand (execution_type=EXIT)
  CommandService.register()
    ↓
OrderWatcherEngine prioritizes these exits
    ↓
Broker orders placed immediately
    ↓
Cooldown timer started
No new trades allowed for duration
```
**Key Feature**: Risk-driven, automatic, emergency  
**Speed**: Immediate registration, broker ASAP  
**Database**: OrderRecord (direct)

---

### **Exit Path 4: OrderWatcherEngine (SL/Trailing)**
```
OrderWatcherEngine runs continuously (every 1 sec)
    ↓
For each ENTRY order in pending:
  Get live LTP
  Check: LTP <= stop_loss_level?
  Check: Trailing stop triggered?
    ↓ (YES to either)
handle_exit_intent()
    ↓
Create UniversalOrderCommand (execution_type=EXIT)
Determine exit_side, order_type (LIMIT vs MARKET)
    ↓
CommandService.register()
    ↓
OrderWatcherEngine's next cycle executes it
    ↓
Broker order placed
    ↓
Position closed
```
**Key Feature**: Automated, market-data-driven  
**Speed**: Continuous monitoring, triggered execution  
**Database**: OrderRecord

---

## 🗂️ DATABASE FLOW

### **Two Main Tables:**

**1. control_intents** (Dashboard-only, async queue)
```
Only populated by:
- submit_generic_intent()
- submit_strategy_intent()
- submit_advanced_intent()
- submit_basket_intent()

Statuses:
- PENDING → CLAIMED → ACCEPTED / REJECTED / FAILED

Consumer threads:
- GenericControlIntentConsumer
- StrategyControlConsumer
```

**2. OrderRecord** (All orders, complete lifecycle)
```
Populated by:
- CommandService.submit() [ENTRY/ADJUST, direct execution]
- CommandService.register() [EXIT, deferred execution]
- TradingView webhook [direct]
- Telegram commands [direct]
- OrderWatcherEngine [SL/trailing exits]
- Risk manager [forced exits]

Statuses:
- CREATED → SENT_TO_BROKER → EXECUTED / FAILED

Monitored by:
- OrderWatcherEngine (reconciliation with broker)
- Reports and dashboards
```

---

## 🔐 CRITICAL GUARDS

### **Entry Guards:**
1. **Duplicate Block** - Memory + DB + Broker checks
2. **Execution Guard** - Conflict validation
3. **Product Type** - Must match instrument rules
4. **Risk Manager** - Can reject based on limits

### **Exit Guards:**
1. **Position Exists** - Must have position to exit
2. **Quantity Valid** - Can't exit more than held
3. **Risk Priority** - Force exits override all
4. **Order Type Rules** - SL must be LIMIT per rules

---

## 📊 ARCHITECTURE LAYERS

```
┌─ PRESENTATION LAYER ─────────────────────────────┐
│ - TradingView Webhook                             │
│ - Dashboard Web UI                                │
│ - Telegram Bot                                    │
│ - Strategy Scripts                                │
└─────────────────┬───────────────────────────────┘
                  │
┌─ INTENT GENERATION LAYER ────────────────────────┐
│ - execution_app.py (webhook endpoint)             │
│ - intent_router.py (dashboard endpoints)          │
│ - telegram_controller.py (telegram interface)     │
│ - trading_bot.py (core processor)                 │
└─────────────────┬───────────────────────────────┘
                  │
┌─ QUEUE/ASYNC LAYER ──────────────────────────────┐
│ - control_intents table (dashboard queues)        │
│ - GenericControlIntentConsumer (polls)            │
│ - StrategyControlConsumer (polls)                 │
└─────────────────┬───────────────────────────────┘
                  │
┌─ EXECUTION LAYER ────────────────────────────────┐
│ - ExecutionGuard (validates)                      │
│ - CommandService (routes: submit/register)        │
│ - OrderWatcherEngine (monitors, triggers SL)      │
└─────────────────┬───────────────────────────────┘
                  │
┌─ BROKER LAYER ───────────────────────────────────┐
│ - ShoonyaClient (API calls)                       │
│ - Shoonya Broker (live trading)                   │
└──────────────────────────────────────────────────┘
```

---

## ✅ IMPLEMENTATION CHECKLIST

### **If adding a new entry path:**
- [ ] Create intent generation function
- [ ] Register with CommandService.submit()
- [ ] Handle in process_alert() if needed
- [ ] Validate order via validation.py
- [ ] Test with OrderWatcherEngine
- [ ] Document in intent_router.py

### **If adding a new exit path:**
- [ ] Create exit request function
- [ ] Call CommandService.register() (not submit)
- [ ] OrderWatcherEngine automatically picks up
- [ ] Implement exit detection logic
- [ ] Test SL/Trailing if applicable
- [ ] Ensure risk guards respected

### **If modifying guard logic:**
- [ ] ExecutionGuard.validate_and_prepare() for duplicate/conflicts
- [ ] CommandService.validate_order() for order validity
- [ ] RiskManager.can_execute() for position limits
- [ ] ScriptMaster.requires_limit_order() for instrument rules

---

## 📚 DOCUMENTATION FILES CREATED

1. **EXECUTION_FLOW_ANALYSIS.md** - Detailed flow diagrams and explanations
2. **EXECUTION_FLOW_DIAGRAMS.md** - ASCII diagrams for visual understanding
3. **INTENT_GENERATION_REFERENCE.md** - File-by-file intent source mapping
4. **THIS FILE** - Executive summary and quick reference

---

## 🔗 KEY FILE LOCATIONS

### **Intent Generation:**
- `api/http/execution_app.py` - TradingView webhook
- `api/dashboard/api/intent_router.py` - Dashboard endpoints
- `api/http/telegram_controller.py` - Telegram handling
- `execution/trading_bot.py` - Core processor

### **Intent Processing:**
- `execution/generic_control_consumer.py` - Async intent consumer
- `execution/strategy_control_consumer.py` - Strategy intent consumer

### **Execution:**
- `execution/command_service.py` - Command router
- `execution/order_watcher.py` - SL/Trailing executor
- `execution/execution_guard.py` - Validation guard
- `brokers/shoonya/client.py` - Broker API

### **Persistence:**
- `persistence/repository.py` - Order CRUD
- `persistence/models.py` - OrderRecord schema
- `persistence/database.py` - DB connection

### **Risk:**
- `risk/supreme_risk.py` - Risk enforcement

---

## 🎓 LEARNING PATH

1. **Start here**: Read this file (SUMMARY)
2. **Understand flows**: Read EXECUTION_FLOW_ANALYSIS.md
3. **Visual reference**: Check EXECUTION_FLOW_DIAGRAMS.md
4. **Find specifics**: Use INTENT_GENERATION_REFERENCE.md
5. **Read code**: Follow the file locations and line numbers

---

## ❓ FAQ

**Q: Where do ENTRY orders originate?**  
A: 7 files create entry intents:
- `execution_app.py` (TradingView)
- `intent_router.py` (Dashboard - 4 types)
- `telegram_controller.py` (Telegram)
- Strategy scripts (internal)

**Q: Where do EXIT orders originate?**  
A: 4 files/mechanisms create exit intents:
- `intent_router.py` (Dashboard)
- `supreme_risk.py` (Risk manager)
- `order_watcher.py` (SL/Trailing)

**Q: Which is faster: dashboard or webhook?**  
A: TradingView webhook is faster (synchronous). Dashboard is asynchronous (queued).

**Q: How are duplicate entries blocked?**  
A: 3-layer check: memory (pending_commands), DB (OrderRepository), broker (get_positions).

**Q: What executes SL/Trailing stops?**  
A: OrderWatcherEngine exclusively. No other component can trigger these.

**Q: Can EXIT orders execute immediately?**  
A: Depends on path:
- Dashboard direct EXIT: yes (via process_alert)
- Dashboard strategy EXIT: no (queued in OrderRecord, watcher executes)
- Risk force EXIT: yes (registered, watcher prioritizes)
- SL/Trailing: yes (watcher executes)

---

## 📞 QUESTIONS?

Refer to:
- **How does X work?** → EXECUTION_FLOW_ANALYSIS.md
- **Show me the diagram** → EXECUTION_FLOW_DIAGRAMS.md
- **Which file does Y?** → INTENT_GENERATION_REFERENCE.md
- **What's the overview?** → THIS FILE

