# 🎯 QUICK VISUAL SUMMARY - All Intent Paths at a Glance

## 📊 ENTRY INTENT SOURCES (7 Total)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 1: TRADINGVIEW WEBHOOK                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/http/execution_app.py                                             │
│ Function: webhook() [Line 74]                                               │
│ Trigger: POST /webhook with TradingView signal                              │
│ Speed: SYNCHRONOUS (immediate)                                              │
│ Process: Direct → process_alert() → submit() → broker                       │
│ Returns: Order ID immediately or error                                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 2: DASHBOARD GENERIC INTENT                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/dashboard/api/intent_router.py                                    │
│ Function: submit_generic_intent() [Line 48]                                 │
│ Trigger: POST /dashboard/intent/generic                                     │
│ Speed: ASYNCHRONOUS (queued, then executed)                                 │
│ Process: Persist → GenericConsumer polls → process_alert() → submit()      │
│ Returns: Intent ID immediately, execution follows in background             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 3: DASHBOARD STRATEGY INTENT                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/dashboard/api/intent_router.py                                    │
│ Function: submit_strategy_intent() [Line 67]                                │
│ Trigger: POST /dashboard/intent/strategy with action=ENTRY                  │
│ Speed: ASYNCHRONOUS (strategy-driven)                                       │
│ Process: Persist → StrategyConsumer → bot.request_entry() → strategy        │
│ Returns: Intent ID, strategy generates intents internally                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 4: DASHBOARD ADVANCED (MULTI-LEG)                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/dashboard/api/intent_router.py                                    │
│ Function: submit_advanced_intent() [Line 90]                                │
│ Trigger: POST /dashboard/intent/advanced with multiple legs                 │
│ Speed: ASYNCHRONOUS (parallel leg execution)                                │
│ Process: Persist all → GenericConsumer → For each leg: process_alert()      │
│ Returns: Intent ID, all legs executed in background                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 5: DASHBOARD BASKET (ATOMIC)                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/dashboard/api/intent_router.py                                    │
│ Function: submit_basket_intent() [Line 134]                                 │
│ Trigger: POST /dashboard/intent/basket with order array                     │
│ Speed: ASYNCHRONOUS (risk-ordered atomic)                                   │
│ Process: Persist atomic → GenericConsumer → EXITs first, ENTRIEs next       │
│ Returns: Intent ID, atomic execution in background (exits first!)           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 6: TELEGRAM COMMANDS                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/http/telegram_controller.py                                       │
│ Function: handle_message()                                                  │
│ Trigger: User sends "/buy NIFTY50 50"                                       │
│ Speed: SYNCHRONOUS (immediate)                                              │
│ Process: Parse command → process_alert() → submit()                         │
│ Returns: Order ID or error via Telegram                                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SOURCE 7: STRATEGY INTERNAL ENTRY                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: Strategy implementation (various)                                      │
│ Function: entry() method                                                    │
│ Trigger: Internal logic (e.g., technical indicator)                         │
│ Speed: ASYNCHRONOUS (strategy-driven)                                       │
│ Process: Strategy generates alert → process_alert() → submit()              │
│ Returns: Order ID, tracked internally                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 EXIT INTENT SOURCES (4 Total)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ EXIT SOURCE 1: DASHBOARD DIRECT EXIT                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/dashboard/api/intent_router.py                                    │
│ Function: submit_generic_intent() with execution_type="EXIT" [Line 48]      │
│ Trigger: POST /dashboard/intent/generic (exit variant)                      │
│ Speed: ASYNCHRONOUS (queued)                                                │
│ Process: Persist → GenericConsumer → process_alert(EXIT) → submit()         │
│ Execution: Fetches position, determines exit side, submits immediately      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ EXIT SOURCE 2: DASHBOARD STRATEGY EXIT                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: api/dashboard/api/intent_router.py                                    │
│ Function: submit_strategy_intent() with action="EXIT" [Line 67]             │
│ Trigger: POST /dashboard/intent/strategy (EXIT action)                      │
│ Speed: ASYNCHRONOUS (via OrderWatcherEngine)                                │
│ Process: Persist → StrategyConsumer → request_exit() → register() [queued]  │
│ Execution: OrderWatcherEngine picks up on next cycle and executes           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ EXIT SOURCE 3: RISK MANAGER FORCE EXIT                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: risk/supreme_risk.py                                                  │
│ Function: heartbeat() [triggers request_force_exit()]                       │
│ Trigger: Daily PnL < loss threshold (checked every 5 seconds)               │
│ Speed: IMMEDIATE (sync registration, async broker execution)                │
│ Process: Detect violation → request_force_exit() → register() → OrderWatcher│
│ Execution: All active positions marked for exit, watcher executes ASAP      │
│ Special: Starts cooldown timer, prevents new trades                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ EXIT SOURCE 4: ORDERWATCHER SL/TRAILING                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ File: execution/order_watcher.py                                            │
│ Function: _reconcile_broker_orders() [Line 236] → handle_exit_intent() [Line 313]            │
│ Trigger: LTP reaches stop_loss or trailing_stop threshold (continuous)      │
│ Speed: CONTINUOUS MONITORING, TRIGGERED EXECUTION                           │
│ Process: Poll open ENTRYs → Check LTP → If threshold hit → handle_exit_intent()     │
│           → register() → Next cycle: execute                                │
│ Execution: Broker order placed (MARKET or LIMIT per rules)                  │
│ Special: Sole executor of SL/Trailing, no other path can trigger these      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 EXECUTION FLOW QUICK REFERENCE

```
╔═══════════════════════════════════════════════════════════════════╗
║ ENTRY ORDER FLOW (Typical Path)                                  ║
╚═══════════════════════════════════════════════════════════════════╝

Intent Source (7 choices)
        ↓
Process Alert (trading_bot.py:784)
        ├─ Parse alert
        ├─ Risk check (can_execute?)
        ├─ ExecutionGuard validation
        └─ Duplicate check
        ↓
For each leg: process_leg()
        ├─ Create UniversalOrderCommand
        ├─ Validate order
        ├─ Check ScriptMaster rules
        └─ Add to pending_commands
        ↓
CommandService.submit()
        ├─ Create OrderRecord (status=CREATED)
        ├─ Execute to broker
        └─ Update status=SENT_TO_BROKER
        ↓
OrderRecord created in database
        ↓
OrderWatcherEngine monitors
        ├─ Reconcile with broker
        ├─ Update status (COMPLETE → EXECUTED)
        ├─ Monitor for SL/Trailing
        └─ Position open for trading


╔═══════════════════════════════════════════════════════════════════╗
║ EXIT ORDER FLOW (Typical Path)                                   ║
╚═══════════════════════════════════════════════════════════════════╝

Exit Source (4 choices)
        ↓
Request Exit / Fire Exit
        ├─ Fetch broker position
        ├─ Determine exit side
        ├─ Validate quantity
        └─ Create UniversalOrderCommand (execution_type=EXIT)
        ↓
CommandService.register() 
        ├─ Validate order
        ├─ Create OrderRecord (status=CREATED)
        └─ 🔒 NO broker submission yet
        ↓
OrderRecord queued in database
        ↓
OrderWatcherEngine picks up
        ├─ Find new EXIT orders
        ├─ Validate order_type rules
        ├─ Execute to broker
        └─ Monitor for completion
        ↓
Broker executes, watcher updates
        ├─ status=SENT_TO_BROKER
        ├─ status=EXECUTED
        ├─ Remove entry from pending
        └─ Position closed
```

---

## 📈 SUMMARY TABLE

| # | Type | Source File | Function | Sync? | Speed |
|---|---|---|---|---|---|
| **ENTRY** | | | | | |
| 1 | TradingView | execution_app.py | webhook() | YES | Fast |
| 2 | Dashboard Generic | intent_router.py | submit_generic_intent() | NO | Medium |
| 3 | Dashboard Strategy | intent_router.py | submit_strategy_intent() | NO | Medium |
| 4 | Dashboard Advanced | intent_router.py | submit_advanced_intent() | NO | Medium |
| 5 | Dashboard Basket | intent_router.py | submit_basket_intent() | NO | Medium |
| 6 | Telegram | telegram_controller.py | handle_message() | YES | Fast |
| 7 | Strategy | Strategy | entry() | NO | Slow |
| **EXIT** | | | | | |
| 1 | Dashboard Direct | intent_router.py | submit_generic_intent() | NO | Medium |
| 2 | Dashboard Strategy | intent_router.py | submit_strategy_intent() | NO | Slow |
| 3 | Risk Manager | supreme_risk.py | request_force_exit() | YES | Fast |
| 4 | SL/Trailing | order_watcher.py | handle_exit_intent() | YES | Fast |

---

## 🎯 KEY FILES TO KNOW

### Must-Know Files:
- **api/http/execution_app.py** - TradingView entry
- **api/dashboard/api/intent_router.py** - Dashboard entry (all 4 types)
- **execution/trading_bot.py** - Core processor (process_alert, request_exit)
- **execution/command_service.py** - Command router (submit/register)
- **execution/order_watcher.py** - Exit executor (SL/Trailing)
- **execution/execution_guard.py** - Validator (duplicate check)
- **persistence/repository.py** - Database access

### Support Files:
- **api/dashboard/services/intent_utility.py** - Intent persistence
- **execution/generic_control_consumer.py** - Dashboard intent consumer
- **execution/strategy_control_consumer.py** - Strategy intent consumer
- **risk/supreme_risk.py** - Risk manager
- **brokers/shoonya/client.py** - Broker API

---

## 🔐 CRITICAL RULES

### Entry Guards:
✅ Duplicate blocked (3 layers: memory, DB, broker)  
✅ Conflicts prevented (ExecutionGuard)  
✅ Product type validated  
✅ Risk checks passed  

### Exit Guarantees:
✅ Position must exist  
✅ Quantity valid  
✅ OrderWatcherEngine is sole executor  
✅ Risk exits have priority  

---

## 📊 DATA FLOW

```
Intent Creation
    ↓
Persist to control_intents (if dashboard)
    ↓
Consumer processes (if async)
    ↓
Create UniversalOrderCommand
    ↓
CommandService routes
    ├─ submit() → direct execution
    └─ register() → queued execution
    ↓
OrderRecord created
    ↓
Broker order placed (or queued)
    ↓
OrderWatcherEngine reconciles
    ↓
Status updated (EXECUTED/FAILED)
    ↓
Position tracked / Closed
```

---

**Printed: January 31, 2026**  
**Documentation Version: 1.0**

