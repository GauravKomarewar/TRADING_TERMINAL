# Shoonya Platform - Complete File Map

## 📂 ALL FILES INVOLVED IN ORDER EXECUTION

### **TIER 1: ENTRY POINT FILES (Receive external inputs)**

#### HTTP/REST Endpoints
```
api/http/execution_app.py
├─ /webhook (TradingView)
│  └─ Line 74: webhook()
│     └─ Calls: bot.process_alert(alert_data)
│
└─ /telegram/webhook (Telegram)
   └─ telegram_controller.py
      └─ handle_message() parses commands
```

#### Dashboard API Endpoints
```
api/dashboard/api/intent_router.py
├─ /dashboard/intent/generic (Line 48)
│  └─ submit_generic_intent()
│     └─ Returns: IntentResponse with intent_id
│
├─ /dashboard/intent/strategy (Line 67)
│  └─ submit_strategy_intent()
│     └─ Returns: IntentResponse with intent_id
│
├─ /dashboard/intent/advanced (Line 90)
│  └─ submit_advanced_intent()
│     └─ Returns: IntentResponse with intent_id
│
└─ /dashboard/intent/basket (Line 134)
   └─ submit_basket_intent()
      └─ Returns: IntentResponse with intent_id
```

---

### **TIER 2: INTENT PERSISTENCE FILES**

#### Dashboard Intent Service (Persistence)
```
api/dashboard/services/intent_utility.py
├─ submit_generic_intent() (Line 56)
│  └─ _insert_intent() (Line 165)
│     └─ INSERT INTO control_intents (type=GENERIC)
│
├─ submit_strategy_intent() (Line 129)
│  └─ _insert_intent() (Line 165)
│     └─ INSERT INTO control_intents (type=STRATEGY)
│
└─ submit_basket_intent()
   └─ _insert_intent() (Line 165)
      └─ INSERT INTO control_intents (type=BASKET)
```

#### Dashboard Schemas
```
api/dashboard/api/intent_schemas.py
├─ GenericIntentRequest (Line 125)
├─ StrategyIntentRequest (Line 149)
├─ AdvancedIntentRequest
├─ AdvancedLegRequest
├─ BasketIntentRequest
├─ GenericSide (Enum: BUY, SELL)
├─ StrategyAction (Enum: ENTRY, EXIT, ADJUST, FORCE_EXIT)
└─ IntentResponse (Line 157)
```

---

### **TIER 3: ASYNC CONSUMERS (Background polling)**

#### Generic Intent Consumer
```
execution/generic_control_consumer.py
├─ __init__() (Line 59)
│  └─ GenericControlIntentConsumer(bot, stop_event)
│
├─ run_forever() (Line 67)
│  └─ Polls every 1 second
│
├─ _claim_next_intent() 
│  └─ UPDATE control_intents SET status=CLAIMED
│
├─ _process_next_intent() (Line 193)
│  └─ Detects: GENERIC / BASKET / ADVANCED
│
├─ _execute_generic_payload() (Line 82)
│  └─ Converts to alert → bot.process_alert()
│
└─ _handle_broker_control_intent()
   └─ Handles: CANCEL_BROKER_ORDER, MODIFY_BROKER_ORDER
```

#### Strategy Intent Consumer
```
execution/strategy_control_consumer.py
├─ __init__() (Line 49)
│  └─ StrategyControlConsumer(strategy_manager, stop_event)
│
├─ run_forever() (Line 65)
│  └─ Polls every 1 second
│
├─ _claim_next_strategy_intent()
│  └─ UPDATE control_intents SET status=CLAIMED (type=STRATEGY)
│
└─ _process_next_strategy_intent() (Line 74)
   ├─ Extract: strategy_name, action
   └─ Route: ENTRY / EXIT / ADJUST / FORCE_EXIT
      ├─ bot.request_entry(strategy_name)
      ├─ bot.request_exit(strategy_name)
      ├─ bot.request_adjust(strategy_name)
      └─ bot.request_force_exit(strategy_name)
```

---

### **TIER 4: CORE EXECUTION ENGINE**

#### Trading Bot (Main Processor)
```
execution/trading_bot.py
├─ __init__() (Line 100+)
│  └─ Initialize all components
│
├─ process_alert() (Line 784) [★ CRITICAL ★]
│  ├─ Parse alert data
│  ├─ ExecutionGuard.reconcile_with_broker()
│  ├─ ExecutionGuard.validate_and_prepare()
│  ├─ For each leg: process_leg()
│  └─ Returns: {status, message, ...}
│
├─ process_leg() (Line 628)
│  ├─ Create UniversalOrderCommand
│  ├─ Validate order_type/price
│  ├─ CommandService.submit() [ENTRY only]
│  └─ Track in trade_records
│
├─ request_exit() (Line 360) [★ EXIT ★]
│  ├─ Fetch broker positions
│  ├─ Determine exit side
│  └─ CommandService.register()
│
├─ request_force_exit() (Line 1394) [★ RISK EXIT ★]
│  ├─ For each position
│  └─ CommandService.register()
│
├─ has_live_entry_block()
│  ├─ Check: pending_commands
│  ├─ Check: OrderRepository
│  └─ Check: api.get_positions()
│
├─ start_order_watcher() (Line 1429)
│  └─ Launch OrderWatcherEngine
│
└─ start_control_intent_consumers() (Line 453)
   ├─ Launch GenericControlIntentConsumer
   └─ Launch StrategyControlConsumer
```

#### Command Service (Routing Gate)
```
execution/command_service.py [★ GATE KEEPER ★]
├─ __init__()
│  └─ Store bot reference
│
├─ submit() (Line 100) [★ ENTRY/ADJUST ONLY ★]
│  ├─ Validate order
│  ├─ Create OrderRecord (status=CREATED)
│  ├─ Send to broker immediately
│  ├─ Update status=SENT_TO_BROKER
│  └─ Return: OrderResult (order_id or error)
│
├─ register() (Line 45) [★ EXIT ONLY ★]
│  ├─ Validate order
│  ├─ Create OrderRecord (status=CREATED)
│  ├─ 🔒 NO broker submission
│  └─ OrderWatcherEngine picks up later
│
└─ register_modify_intent()
   └─ Registers order modification intent
```

#### Execution Guard (Validation)
```
execution/execution_guard.py
├─ __init__()
│  └─ Initialize position tracking
│
├─ validate_and_prepare() (Line 46) [★ VALIDATOR ★]
│  ├─ For ENTRY: Check duplicate, conflicts
│  ├─ For EXIT: Always allow
│  ├─ For ADJUST: Check compatibility
│  └─ Return: validated intents (filtered)
│
├─ reconcile_with_broker()
│  ├─ Update internal state from broker
│  └─ Prevent position mismatches
│
└─ force_clear_symbol()
   └─ Clear position on failure
```

#### Order Watcher Engine (Exit Executor)
```
execution/order_watcher.py [★ SOLE EXIT EXECUTOR ★]
├─ __init__() (Line 76)
│  └─ OrderWatcherEngine(bot, poll_interval=1.0)
│
├─ run() (Line 213)
│  └─ while _running:
│     ├─ _reconcile_broker_orders()
│     └─ _reconcile_broker_orders()
│
├─ _reconcile_broker_orders() (Line 100) [★ CRITICAL ★]
│  ├─ Fetch broker order book
│  ├─ Update local OrderRecord status
│  └─ Create shadow record for orphan orders
│
├─ _reconcile_broker_orders() (Line 236) [★ CRITICAL ★]
│  ├─ Get open ENTRY orders
│  ├─ For each: Fetch live LTP
│  ├─ Check: SL triggered?
│  ├─ Check: Trailing stop triggered?
│  └─ If YES: handle_exit_intent()
│
└─ handle_exit_intent() (Line 313) [★ EXIT TRIGGER ★]
   ├─ Determine exit_side
   ├─ Determine order_type (LIMIT/MARKET)
   ├─ Create UniversalOrderCommand
   └─ CommandService.register()
```

#### Intent/Command Models
```
execution/intent.py
├─ OrderSide (Literal: BUY, SELL)
├─ OrderType (Literal: MARKET, LIMIT, SL, SLM, etc)
├─ Product (Literal: MIS, NRML, CNC)
├─ TriggerType (Literal: NONE, ABOVE_PRICE, BELOW_PRICE)
├─ TrailingType (Literal: NONE, POINTS, PERCENT, ABSOLUTE)
├─ CommandSource (Literal: WEB, STRATEGY, SYSTEM)
│
└─ UniversalOrderCommand (Dataclass) [★ IMMUTABLE ★]
   ├─ command_id: str (uuid)
   ├─ created_at: datetime
   ├─ source: CommandSource
   ├─ user: str
   ├─ exchange: str
   ├─ symbol: str
   ├─ quantity: int
   ├─ side: OrderSide
   ├─ product: Product
   ├─ order_type: OrderType
   ├─ price: Optional[float]
   ├─ trigger_type: TriggerType
   ├─ trigger_price: Optional[float]
   ├─ stop_loss: Optional[float]
   ├─ target: Optional[float]
   ├─ trailing_type: TrailingType
   └─ trailing_value: Optional[float]
```

#### Trailing Stop Engine
```
execution/trailing.py
├─ PointsTrailing
│  └─ Tracks: high price, current distance
│     Fires when: LTP <= high - points
│
├─ PercentTrailing
│  └─ Tracks: high price, percent
│     Fires when: LTP <= high * (1 - percent)
│
└─ AbsoluteTrailing
   └─ Fires when: LTP <= absolute_price
```

---

### **TIER 5: BROKER INTERFACE**

#### Shoonya Client
```
brokers/shoonya/client.py
├─ place_order()
│  ├─ exchange, symbol, quantity, side
│  ├─ product, order_type, price
│  └─ Returns: {success, order_id, error}
│
├─ modify_order()
│  ├─ Modify price, quantity, type
│  └─ Returns: {success, error}
│
├─ cancel_order()
│  └─ Returns: {success, error}
│
├─ get_order_book()
│  └─ Returns: List[{norenordno, status, ...}]
│
├─ get_positions()
│  └─ Returns: List[{tsym, netqty, prd, ...}]
│
└─ get_ltp()
   └─ Returns: float (current price)
```

#### Broker Interface (Adapter)
```
execution/broker.py
├─ send()
│  ├─ Converts Engine intents → webhook JSON
│  ├─ Calls bot.process_alert()
│  └─ Returns execution result
```

---

### **TIER 6: PERSISTENCE LAYER**

#### Order Repository
```
persistence/repository.py
├─ create() 
│  └─ INSERT OrderRecord
│
├─ get_by_broker_id()
│  └─ SELECT OrderRecord WHERE broker_order_id=?
│
├─ get_open_orders()
│  └─ SELECT WHERE status != "EXECUTED"
│
├─ get_open_orders_by_strategy()
│  └─ SELECT WHERE strategy_name=? AND status != "EXECUTED"
│
├─ update_status()
│  └─ UPDATE status WHERE command_id=?
│
├─ update_status_by_broker_id()
│  └─ UPDATE status WHERE broker_order_id=?
│
└─ cleanup_old_closed_orders()
   └─ DELETE WHERE created_at < 3 days ago
```

#### OrderRecord Model
```
persistence/models.py
├─ OrderRecord (class)
│  ├─ command_id: str
│  ├─ broker_order_id: Optional[str]
│  ├─ execution_type: str (ENTRY, EXIT, ADJUST, BROKER_ONLY)
│  ├─ status: str (CREATED, SENT_TO_BROKER, EXECUTED, FAILED)
│  ├─ source: str
│  ├─ user: str
│  ├─ strategy_name: str
│  ├─ exchange: str
│  ├─ symbol: str
│  ├─ side: str (BUY, SELL)
│  ├─ quantity: int
│  ├─ product: str (MIS, NRML, CNC)
│  ├─ order_type: Optional[str]
│  ├─ price: Optional[float]
│  ├─ stop_loss: Optional[float]
│  ├─ target: Optional[float]
│  ├─ trailing_type: Optional[str]
│  ├─ trailing_value: Optional[float]
│  ├─ created_at: str
│  ├─ updated_at: str
│  └─ tag: Optional[str]
```

#### Database Manager
```
persistence/database.py
├─ SQLite connection manager
├─ Table initialization
└─ Query execution
```

---

### **TIER 7: RISK MANAGEMENT**

#### Supreme Risk Manager
```
risk/supreme_risk.py
├─ __init__()
│  └─ Load daily PnL, loss limits, cooldown
│
├─ heartbeat() [★ CALLED EVERY 5 SECONDS ★]
│  ├─ Calculate daily_pnl
│  ├─ Check: daily_pnl < -loss_limit?
│  ├─ Check: cooldown_timer active?
│  └─ If violation: request_force_exit()
│     └─ bot.request_force_exit()
│
├─ can_execute()
│  └─ Returns: bool (OK to execute or not)
│
├─ get_status()
│  └─ Returns: {daily_pnl, loss_hit, cooldown_until}
│
└─ track_pnl_ohlc()
   └─ Analytics: daily OHLC of PnL
```

---

### **TIER 8: VALIDATION & RULES**

#### Validation
```
execution/validation.py
├─ validate_order()
│  ├─ Check: symbol, quantity > 0
│  ├─ Check: side in {BUY, SELL}
│  ├─ Check: order_type valid
│  ├─ Check: price >= 0 if LIMIT
│  └─ Raise: ValueError if invalid
```

#### ScriptMaster (Instrument Rules)
```
scripts/scriptmaster.py
├─ requires_limit_order()
│  ├─ Takes: exchange, tradingsymbol
│  ├─ Returns: bool
│  └─ Logic: Checks if instrument requires LIMIT order
│
└─ Used by:
   ├─ process_leg() (validate)
   └─ order_watcher.handle_exit_intent() (enforce)
```

---

### **TIER 9: UTILITIES & HELPERS**

#### JSON Builder
```
utils/json_builder.py
├─ build_leg()
│  └─ Creates single leg object
│
├─ build_strategy_json()
│  └─ Creates TradingView-format JSON
│
├─ build_straddle() / build_strangle() / etc
│  └─ Creates multi-leg strategy JSON
```

#### Utils
```
utils/utils.py
├─ validate_webhook_signature()
├─ parse_json_safely()
├─ format_currency()
├─ log_exception()
└─ ... other helpers
```

---

### **TIER 10: EXTERNAL SERVICES**

#### Telegram Notifier
```
notifications/telegram.py
├─ send_message()
├─ send_alert_received()
├─ send_order_placing()
├─ send_error_message()
└─ ... notifications
```

#### Telegram Controller
```
api/http/telegram_controller.py
├─ handle_message()
│  ├─ Parses: /buy, /sell, /exit commands
│  ├─ Builds alert payload
│  └─ Calls: bot.process_alert()
│
└─ Allowed users: whitelist based
```

---

### **TIER 11: CONFIGURATION**

#### Config
```
core/config.py
├─ user_id, api_key, api_secret
├─ webhook_secret
├─ telegram_token, telegram_chat_id
├─ loss_limit, daily_loss_limit
├─ cooldown_duration
└─ ... other settings
```

---

## 🗺️ INTENT FLOW BY FILE

### **ENTRY INTENT GENERATION (Start → End)**

```
TradingView Path:
  execution_app.py:webhook() 
  → trading_bot.py:process_alert() 
  → execution/execution_guard.py:validate_and_prepare()
  → trading_bot.py:process_leg()
  → command_service.py:submit()
  → brokers/shoonya/client.py:place_order()
  → persistence/repository.py:create() [OrderRecord]

Dashboard Generic Path:
  intent_router.py:submit_generic_intent()
  → intent_utility.py:submit_generic_intent()
  → intent_utility.py:_insert_intent() [control_intents]
  ↓ (async)
  generic_control_consumer.py:_process_next_intent()
  → generic_control_consumer.py:_execute_generic_payload()
  → trading_bot.py:process_alert() [same as TradingView from here]

Dashboard Strategy Path:
  intent_router.py:submit_strategy_intent()
  → intent_utility.py:submit_strategy_intent()
  → intent_utility.py:_insert_intent() [control_intents]
  ↓ (async)
  strategy_control_consumer.py:_process_next_strategy_intent()
  → trading_bot.py:request_entry()
  → strategy.entry() [internal logic generates intents]

Dashboard Advanced Path:
  intent_router.py:submit_advanced_intent()
  → intent_utility.py:_insert_intent() [control_intents]
  ↓ (async)
  generic_control_consumer.py:_process_next_intent() [detect ADVANCED]
  ↓ (for each leg)
  generic_control_consumer.py:_execute_generic_payload()
  → trading_bot.py:process_alert()

Dashboard Basket Path:
  intent_router.py:submit_basket_intent()
  → intent_utility.py:submit_basket_intent()
  → intent_utility.py:_insert_intent() [control_intents]
  ↓ (async)
  generic_control_consumer.py:_process_next_intent() [detect BASKET]
  ├─ Separate EXITs
  ├─ Separate ENTRIEs
  ├─ Process EXITs first (risk-safe)
  └─ Process ENTRIEs next
  ↓ (for each order)
  generic_control_consumer.py:_execute_generic_payload()
  → trading_bot.py:process_alert()

Telegram Path:
  telegram_controller.py:handle_message()
  → telegram_controller.py (parse command)
  → trading_bot.py:process_alert()

Strategy Path:
  strategy.entry() [internal]
  → trading_bot.py:process_alert()
```

---

### **EXIT INTENT GENERATION (Start → End)**

```
Dashboard Direct EXIT:
  intent_router.py:submit_generic_intent() [execution_type=EXIT]
  → intent_utility.py:submit_generic_intent()
  → intent_utility.py:_insert_intent() [control_intents]
  ↓ (async)
  generic_control_consumer.py:_process_next_intent()
  → generic_control_consumer.py:_execute_generic_payload()
  → trading_bot.py:process_alert() [execution_type=EXIT]
  → command_service.py:submit() [direct execution]
  → brokers/shoonya/client.py:place_order()

Dashboard Strategy EXIT:
  intent_router.py:submit_strategy_intent() [action=EXIT]
  → intent_utility.py:submit_strategy_intent()
  → intent_utility.py:_insert_intent() [control_intents]
  ↓ (async)
  strategy_control_consumer.py:_process_next_strategy_intent()
  → trading_bot.py:request_exit()
  → command_service.py:register() [queued]
  ↓ (async, next watcher cycle)
  order_watcher.py:_reconcile_broker_orders()
  → order_watcher.py executes it

Risk Manager EXIT:
  risk/supreme_risk.py:heartbeat()
  → trading_bot.py:request_force_exit()
  → command_service.py:register() [queued]
  ↓ (async, next watcher cycle)
  order_watcher.py:_reconcile_broker_orders()

SL/Trailing EXIT:
  order_watcher.py:_reconcile_broker_orders()
  → (check SL/Trailing)
  → order_watcher.py:handle_exit_intent()
  → command_service.py:register() [queued]
  ↓ (async, next watcher cycle)
  order_watcher.py:_reconcile_broker_orders()
  → (executes registered exit)
```

---

## 🔑 KEY CONCEPTS

1. **Intent** = user's wish (may be blocked)
2. **Order** = actual broker order (has order_id)
3. **Command** = UniversalOrderCommand (immutable)
4. **OrderRecord** = database representation
5. **register()** = queue for later execution
6. **submit()** = execute immediately

---

