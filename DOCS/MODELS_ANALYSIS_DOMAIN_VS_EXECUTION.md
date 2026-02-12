# Models Analysis: domain/models.py vs execution/models.py

**Finding**: ✅ These should NOT be merged - they serve different purposes

---

## 1. **execution/models.py** (19 lines)

### Purpose
Interface between **strategy** and **OMS execution**

### Contains
```python
@dataclass(frozen=True)
class Intent:
    action: Literal["BUY", "SELL"]        # What to do
    symbol: str                           # What symbol
    qty: int                              # How many
    tag: str                              # Leg identifier
    order_type: Literal["MKT", "LMT"]     # Market or Limit
    price: float                          # Limit price if LMT
```

### Used By
```
✅ strategies/engine/engine.py           (executes intents)
✅ strategies/engine/engine_no_recovery.py (executes intents)
✅ execution/broker.py                   (places orders from intents)
```

### Responsibility
- Simple, immutable, frozen dataclass
- **Strategy → OMS communication interface**
- No business logic
- No persistence

---

## 2. **domain/models.py** (275 lines)

### Purpose
**Application domain models** - data records, trading results, account info

### Contains
```python
@dataclass
class TradeRecord:
    timestamp, strategy_name, execution_type, symbol, direction, 
    quantity, price, order_id, status, pnl
    → to_dict(), from_dict() methods

@dataclass
class OrderParams:
    API order parameters (trantype, prd, exch, tsym, qty, prctyp, prc, dscqty, trgprc, ret, remarks)
    → to_dict() conversion

@dataclass
class LegData:
    Individual strategy leg (tradingsymbol, direction, qty, order_type, price, product_type)
    → from_dict(), to_order_params()

@dataclass
class AlertData:
    Parsed alert (execution_type, strategy_name, exchange, legs, test_mode, underlying, expiry, product_type)
    → from_dict() parsing

@dataclass
class OrderResult:
    API response (success, order_id, status, error_message, response_data)
    → from_api_response() conversion

@dataclass
class LegResult:
    Leg execution result (leg_data, order_result, order_params, execution_time)

@dataclass
class AccountInfo:
    Account state (available_cash, used_margin, positions, orders)
    → from_api_data() conversion

@dataclass
class BotStats:
    Bot statistics (total_trades, today_trades, successful_trades, failed_trades, success_rate, last_activity)
    → from_trade_records() calculation
```

### Used By
```
✅ execution/trading_bot.py              (main execution loop - uses all 6)
✅ brokers/shoonya/client.py            (broker client - uses OrderResult, AccountInfo)
```

### Responsibility
- **Application-level** domain models
- **OMS ↔ Dashboard** communication
- **Persistence** and reporting
- **API response** transformations
- **Statistics** calculation

---

## 3. **Key Differences**

| Aspect | execution/models.py | domain/models.py |
|--------|-------------------|-----------------|
| **Purpose** | Strategy-to-OMS interface | Application domain models |
| **Audience** | Internal (strategies, broker) | Internal (OMS, dashboard) |
| **Scope** | Single intent object | Complete trading domain |
| **Size** | 19 lines (1 class) | 275 lines (7 classes) |
| **Immutability** | ✅ Frozen (immutable) | ❌ Mutable records |
| **Conversion** | ❌ No conversions | ✅ Many conversions |
| **Usage** | Strategy execution flow | Trade recording, reporting |
| **Persistence** | ❌ Not persisted | ✅ Persisted (recorded) |
| **Dashboard** | ❌ Not used | ✅ Sent to dashboard |

---

## 4. **Why Separate? ✅**

### Good Separation Because:

1. **Different Concerns**
   - execution/models: **Strategy logic** (what to execute)
   - domain/models: **Business domain** (trading records, stats)

2. **Different Audiences**
   - execution/models: Strategies + Broker
   - domain/models: OMS + Dashboard + Reporting

3. **Different Lifecycle**
   - execution/models: Ephemeral (created, executed, discarded)
   - domain/models: Persistent (recorded in DB, sent to dashboard)

4. **Different Transformation Needs**
   - execution/models: None (immutable, as-is)
   - domain/models: Many (API conversion, dict conversion, calculations)

5. **Different States**
   - execution/models: Frozen (immutable, cannot change)
   - domain/models: Mutable (updated with results, time info, etc)

---

## 5. **Data Flow (Why They're Separate)**

```
Strategy                    execution/models.Intent        OMS
┌────────────┐              ┌─────────────────┐      ┌──────────┐
│  DNSS      │─────────────→│  Intent         │     │ Broker   │
│ Strategy   │ (intent to   │ ─────────────── │     │ (places  │
│            │  execute)    │ - action: BUY   │────→│  order)  │
│            │              │ - symbol: NIFTY │     │          │
│            │              │ - qty: 50       │     │          │
│            │              └─────────────────┘     │          │
└────────────┘                                       └──────────┘

OMS                         domain/models.*          Dashboard
┌────────────────────────────────────────────────┐    ┌───────┐
│ trading_bot.py                                  │   │ Dash  │
│                                                │   │ board │
│ ✅ TradeRecord (what happened)                 │   │       │
│ ✅ OrderResult (API response)                  │───→│ Shows │
│ ✅ BotStats (performance metrics)              │   │ PnL,  │
│ ✅ AccountInfo (cash, margin, positions)       │   │ Stats │
│ ✅ LegData (order parameters)                  │   │       │
│ ✅ AlertData (parsed trade signal)             │   │       │
└────────────────────────────────────────────────┘    └───────┘
```

---

## 6. **Current Usage Verification**

### execution/models.py Usage ✅
```
strategies/engine/engine.py:40          from shoonya_platform.execution.models import Intent
strategies/engine/engine_no_recovery.py:33   from shoonya_platform.execution.models import Intent
execution/broker.py:15                  from shoonya_platform.execution.models import Intent
```
**Purpose**: Executing and placing orders

### domain/models.py Usage ✅
```
execution/trading_bot.py:99             from shoonya_platform.domain.models import 
                                        TradeRecord, AlertData, LegResult, BotStats, 
                                        OrderResult, AccountInfo

brokers/shoonya/client.py:104           from shoonya_platform.domain.models import 
                                        OrderResult, AccountInfo
```
**Purpose**: Recording trades, dashboard communication, API interactions

---

## **Recommendation: DO NOT MERGE** ✅

### Reasons:

1. **Single Responsibility Principle** ✅
   - execution/models = Intent specification (immutable)
   - domain/models = Business domain (mutable, persistent)

2. **Clean Separation of Concerns** ✅
   - Strategy layer uses Intent (what to execute)
   - OMS/Domain layer uses business models (recording, analytics)

3. **Different Lifecycle** ✅
   - Intent: Created → Executed → Discarded
   - Domain Models: Created → Recorded → Persisted → Reported

4. **Zero Redundancy** ✅
   - No overlap in classes
   - No duplicate definitions
   - Each serves distinct purpose

5. **Clear Architecture** ✅
   - Easier for new developers to understand
   - Intent = Strategy interface
   - Domain = Business logic

---

## **Current State Assessment**

```
✅ GOOD SEPARATION
   - No conflicts
   - No duplication
   - Clear responsibilities
   - Each has distinct audience
   - Each has distinct lifecycle

❌ NO NEED TO MERGE
   - Would create confusion
   - Would violate SRP
   - Would couple unrelated concerns
   - Would make code harder to maintain
```

---

## **Conclusion**

**Keep both files separate.** They're not duplicates - they're complements serving different architectural layers:

- **execution/models.py** = Interface layer (Strategy ↔ OMS)
- **domain/models.py** = Domain layer (Business models)

This is **good microarchitecture**. ✅
