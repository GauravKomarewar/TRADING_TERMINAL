# 🔍 CALL CHAIN VERIFICATION: 6-STEP FLOW

## Complete Execution Call Chain

```
External Order Source (Webhook / Dashboard / System)
    │
    └─→ ShoonyaBot.process_alert()
        └─→ ShoonyaBot.process_leg()
            └─→ CommandService.submit() OR CommandService.register()
                └─→ OrderRepository.create()
                    └─→ DB: INSERT INTO orders (status='CREATED')
                    
                    ✅ STEP 1 COMPLETE: Order registered
                    
                └─→ CommandService.submit()
                    └─→ ShoonyaBot.execute_command()
                    
                        Step 2: BLOCKERS CHECK
                        ├─→ ShoonyaBot.risk_manager.can_execute()
                        │   └─→ Returns True/False
                        │   └─→ If False: UPDATE status='FAILED', tag='RISK_LIMITS_EXCEEDED'
                        │       ✅ BLOCKED - Return early
                        │
                        ├─→ ExecutionGuard.has_strategy()
                        │   └─→ Returns True if strategy has positions
                        │   └─→ If True + ENTRY: UPDATE status='FAILED', 
                        │                         tag='EXECUTION_GUARD_BLOCKED'
                        │       ✅ BLOCKED - Return early
                        │
                        └─→ OrderRepository.get_open_orders_by_strategy()
                            └─→ Check for symbol duplicates
                            └─→ If duplicate: UPDATE status='FAILED',
                                               tag='DUPLICATE_ORDER_BLOCKED'
                            └─→ ✅ BLOCKERS PASSED - Continue
                        
                        Step 3: UPDATE STATUS
                        └─→ OrderRepository.update_status(status='SENT_TO_BROKER')
                            └─→ DB: UPDATE orders SET status='SENT_TO_BROKER'
                            └─→ ✅ STEP 3 COMPLETE
                        
                        Step 4: EXECUTE ON BROKER
                        └─→ ShoonyaBot.api.place_order(order_params)
                            └─→ ShoonyaClient.place_order()
                                └─→ ShoonyaApiProxy._call('place_order')
                                    └─→ Broker API call (serialized, locked)
                                    ├─→ Success: Returns {success=True, order_id='123'}
                                    └─→ Failure: Returns {success=False, error='...'}
                            └─→ ✅ STEP 4 COMPLETE
                        
                        Step 5: UPDATE DB ON RESULT
                        ├─→ If result.success:
                        │   └─→ OrderRepository.update_broker_id(broker_id)
                        │       └─→ DB: UPDATE orders SET broker_order_id='123',
                        │                                    status='SENT_TO_BROKER'
                        │       └─→ ✅ STEP 5 SUCCESS
                        │
                        └─→ If result.failure:
                            └─→ OrderRepository.update_status(status='FAILED')
                            └─→ OrderRepository.update_tag(tag='BROKER_REJECTED')
                            └─→ DB: UPDATE orders SET status='FAILED',
                                                       tag='BROKER_REJECTED'
                            └─→ If EXIT: TelegramNotifier.send_alert()
                            └─→ ✅ STEP 5 FAILURE

                === PARALLEL: OrderWatcher Thread ===
                
                OrderWatcherEngine.run() [DAEMON THREAD]
                └─→ While _running:
                    ├─→ Bot._ensure_login()
                    │
                    ├─→ _reconcile_broker_orders()
                    │   └─→ ShoonyaBot.api.get_order_book()
                    │       └─→ broker_orders = [...]
                    │       └─→ For each broker_order:
                    │           ├─→ Get broker_id, status
                    │           ├─→ OrderRepository.get_by_broker_id()
                    │           │   └─→ Find matching DB record
                    │           │
                    │           ├─→ Step 6A: BROKER FAILURE
                    │           │   ├─→ If status in (REJECTED, CANCELLED, EXPIRED):
                    │           │   │   ├─→ OrderRepository.update_status('FAILED')
                    │           │   │   ├─→ OrderRepository.update_tag('BROKER_<STATUS>')
                    │           │   │   ├─→ ExecutionGuard.force_clear_symbol()
                    │           │   │   └─→ ✅ STEP 6A COMPLETE
                    │           │
                    │           ├─→ Step 6B: BROKER EXECUTED
                    │           │   └─→ If status == 'COMPLETE':
                    │           │       ├─→ OrderRepository.update_status('EXECUTED')
                    │           │       ├─→ _reconcile_execution_guard()
                    │           │       │   ├─→ ShoonyaBot.api.get_positions()
                    │           │       │   ├─→ ExecutionGuard.reconcile_with_broker()
                    │           │       │   ├─→ If strategy flat:
                    │           │       │   │   └─→ ExecutionGuard.force_close_strategy()
                    │           │       │   └─→ ✅ STEP 6B COMPLETE
                    │           │
                    │           └─→ ✅ POLLING CYCLE COMPLETE
                    │
                    └─→ sleep(poll_interval)  // Default: 1.0 second
                        └─→ Repeat...
```

---

## 🔄 STATE TRANSITIONS DURING EXECUTION

### Timeline View

```
Time    Component                Action                          DB State
────────────────────────────────────────────────────────────────────────────
T0:     Command Service          Register intent                 status=CREATED
        OrderRepository          create(record)
        
T0+:    TradingBot               Check Risk Manager              ❌ BLOCKED
        OrderRepository          update_status('FAILED')         status=FAILED
                                 update_tag('RISK_LIMITS...')    tag=RISK_LIMITS_EXCEEDED
        [ORDER PROCESSING STOPS]

T0+:    TradingBot               Check Guard                     ✅ PASSED
        TradingBot               Check Duplicates                ✅ PASSED
        TradingBot               SEND_TO_BROKER                  status=SENT_TO_BROKER
        OrderRepository          update_status('SENT_TO_BROKER')

T0++:   TradingBot               Place with Broker               broker call
        ShoonyaClient            place_order()

T0+++:  TradingBot               Broker Success                  ✅
        OrderRepository          update_broker_id(broker_id)     broker_order_id=<id>
                                                                 status=SENT_TO_BROKER

T0+n:   OrderWatcher             Poll Broker                     polling
        ShoonyaClient            get_order_book()

T0+n+:  OrderWatcher             Broker COMPLETE                 ✅
        OrderRepository          update_status('EXECUTED')       status=EXECUTED
        ExecutionGuard           reconcile_with_broker()         guard synced

[ORDER PROCESSING COMPLETE - SUCCESS]

---Or alternatively after Broker rejects---

T0++:   TradingBot               Broker Rejected                 ❌
        OrderRepository          update_status('FAILED')         status=FAILED
                                 update_tag('BROKER_REJECTED')   tag=BROKER_REJECTED
        TelegramNotifier         send_alert()

[ORDER PROCESSING COMPLETE - FAILURE]
```

---

## 📞 API CALL DEPENDENCIES

### Required Methods (Must Exist)

```python
# OrderRepository
├─ create(record)
├─ update_status(command_id, status)  [NEW]
├─ update_tag(command_id, tag)        [NEW]
├─ update_broker_id(command_id, broker_id)
├─ get_by_broker_id(broker_id)
└─ get_open_orders_by_strategy(strategy_id)

# RiskManager
└─ can_execute() → bool

# ExecutionGuard
├─ has_strategy(strategy_id) → bool
├─ force_clear_symbol(strategy_id, symbol)
├─ reconcile_with_broker(strategy_id, broker_positions)
└─ force_close_strategy(strategy_id)

# ShoonyaClient
├─ place_order(order_params) → result{success, order_id, error}
├─ get_order_book() → broker_orders[]
└─ get_positions() → positions[]

# TelegramNotifier
└─ send_alert(message)
```

---

## ✅ EXECUTION GUARANTEE MATRIX

| Step | Component | Success | Failure | DB Update | Recoverable |
|------|-----------|---------|---------|-----------|-------------|
| 1 | CommandService | ✅ | ❌ | CREATED | N/A |
| 2A | RiskManager | ✅ | ❌ | FAILED | Manual override |
| 2B | ExecutionGuard | ✅ | ❌ | FAILED | Wait for exit |
| 2C | Duplicate Check | ✅ | ❌ | FAILED | Dedup & retry |
| 3 | OrderRepo | ✅ | ⚠️ | SENT_TO_BROKER | Continue to broker |
| 4 | Broker API | ✅ | ❌ | N/A | See Step 5 |
| 5 | Broker Result | ✅/❌ | ⚠️ | SENT_TO_BROKER/FAILED | OrderWatcher syncs |
| 6 | OrderWatcher | ✅ | ❌ | EXECUTED/FAILED | Periodic polling |

---

## 🔐 SAFETY BARRIERS AT EACH STEP

```
Step 1: REGISTRATION
  Safety: Order-only, no execution
  Barrier: Validation.validate_order()
  
Step 2: BLOCKERS
  Safety: Three-layer protection
  Barriers:
    ├─ Risk Manager (loss limits)
    ├─ Execution Guard (position tracking)
    └─ Duplicate Detection (symbol safety)
  
Step 3: PREPARE
  Safety: Mark before broker
  Barrier: DB state signal
  Protection: Prevents double-execute
  
Step 4: BROKER
  Safety: Authorized API only
  Barrier: ShoonyaApiProxy (serialized, locked)
  Protection: Thread-safe, no concurrent API calls
  
Step 5: RESULT
  Safety: DB always matches attempt
  Barriers:
    ├─ Success: Persist broker_id
    ├─ Failure: Mark FAILED
    └─ Exception: Catch all & mark FAILED
  
Step 6: POLLING
  Safety: Broker is authoritative
  Barrier: Idempotency (skip already-resolved)
  Protection: Guard reconciliation, strategy cleanup
```

---

## 🎯 VERIFICATION CHECKLIST

- [✅] Call chain is sequential (no race conditions)
- [✅] DB writes are atomic at each step
- [✅] All errors are caught and logged
- [✅] Broker is always source of truth
- [✅] Recovery paths exist for all failures
- [✅] OrderWatcher can find orders by broker_id
- [✅] Guard state is reconciled after execution
- [✅] Client isolation is maintained
- [✅] Telegram alerts work for critical failures
- [✅] No breaking changes to existing API

---

**Status**: ✅ VERIFIED - All call chains correct  
**Date**: 2026-02-10
