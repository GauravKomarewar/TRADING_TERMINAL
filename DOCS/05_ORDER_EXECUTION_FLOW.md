# Order Execution Flow

> Last verified: 2026-03-01 | Source: `execution/` package

## Intent-Based Order Management

The platform uses an **intent-based** architecture. No component places orders directly — instead, they create `UniversalOrderCommand` intents that flow through a processing pipeline.

---

## Three Entry Paths

### Path 1: External Webhook (TradingView / API)

```
TradingView Alert
     │
     ▼
ExecutionApp.webhook()           ← Flask (port 5000)
     │
     ▼
ShoonyaBot.process_alert()      ← Parses alert, validates signature
     │
     ▼
ShoonyaBot.process_leg()        ← Builds UniversalOrderCommand
     │
     ▼
CommandService.execute()         ← Places order via Broker
     │
     ▼
OrderWatcherEngine              ← Monitors fill status in background thread
     │
     ▼
OrderRepository                 ← Persists to SQLite
```

### Path 2: Dashboard Intent

```
Dashboard UI (strategy.html / place_order.html)
     │
     ▼
POST /dashboard/intent/generic   ← FastAPI (port 8000)
     │
     ▼
Intent Queue (thread-safe)      ← Queued, not executed immediately
     │
     ▼
GenericControlIntentConsumer     ← Background consumer thread
     │
     ▼
CommandService.execute()         ← Same shared service
     │
     ▼
OrderWatcherEngine → Broker → OrderRepository
```

### Path 3: Strategy Engine

```
StrategyExecutorService
     │
     ▼
PerStrategyExecutor (loop)
     │
     ├── EntryEngine.check()     → Entry conditions met?
     ├── AdjustmentEngine.check_and_apply() → Adjustment rules triggered?
     └── ExitEngine.check()      → Exit conditions met?
           │
           ▼
     StrategyControlConsumer     ← Processes strategy intents
           │
           ▼
     CommandService.execute()    ← Same shared service
           │
           ▼
     OrderWatcherEngine → Broker → OrderRepository
```

---

## Key Components in Detail

### UniversalOrderCommand (`execution/intent.py`)

The canonical order intent data model. Every order starts as this:

```python
@dataclass
class UniversalOrderCommand:
    symbol: str            # Trading symbol
    exchange: str          # NSE, NFO, MCX, etc.
    side: str              # BUY or SELL
    qty: int               # Quantity
    product_type: str      # NRML, MIS, CNC
    order_type: str        # MARKET, LIMIT, SL, SL-M
    price: float = 0.0     # Limit price (0 for MARKET)
    trigger_price: float = 0.0  # SL trigger
    strategy_name: str = ""
    tag: str = ""          # Client-side order tag
    test_mode: bool = False
```

### CommandService (`execution/command_service.py`)

Central order executor:
1. Receives `UniversalOrderCommand`
2. Calls `ExecutionGuard.validate_and_prepare()` for pre-trade checks
3. Calls `Broker.place_order()` to send to Shoonya API
4. Registers with `OrderRepository` for tracking
5. Passes to `OrderWatcherEngine` for fill monitoring

### OrderWatcherEngine (`execution/order_watcher.py`)

Background thread that:
1. Polls broker for order status updates
2. Detects fills, rejections, cancellations
3. Updates `OrderRepository` with final status
4. Notifies strategies of fills (via callbacks)
5. Handles partial fills and order modifications

### ExecutionGuard (`execution/execution_guard.py`)

Pre-trade validation:
- `validate_and_prepare()` — checks position limits, risk parameters, duplicate detection
- `reconcile_with_broker()` — syncs local state with broker positions
- `force_clear_symbol()` — emergency position clearing
- `has_strategy()` — checks if a strategy is registered

### Broker (`execution/broker.py`)

Abstraction layer over `ShoonyaClient`:
- `place_order(command)` → Shoonya API
- `modify_order(order_id, ...)` → Shoonya API
- `cancel_order(order_id)` → Shoonya API
- Handles retry logic and error mapping

### OrderRepository (`persistence/repository.py`)

SQLite-backed persistence:
- `create(order_record)` — Insert new order
- `update(order_record)` — Update status/fills
- `get_all()` — All orders
- `get_open_positions_by_strategy(strategy_name)` — Active positions
- Uses `get_connection()` from `database.py` for WAL mode + busy_timeout

---

## Intent Types

### Generic Intents (from Dashboard)

| Intent | Description |
|--------|-------------|
| `PLACE_ORDER` | New order placement |
| `MODIFY_ORDER` | Modify pending order |
| `CANCEL_ORDER` | Cancel pending order |
| `FORCE_EXIT` | Close specific position |
| `SQUARE_OFF_ALL` | Exit all positions |

### Strategy Intents (from Strategy Engine)

| Intent | Description |
|--------|-------------|
| `ENTRY` | Strategy entry (new legs) |
| `EXIT` | Strategy exit (close all legs) |
| `ADJUST` | Adjustment (close/open legs per rules) |
| `FORCE_EXIT` | Emergency exit all strategy positions |
| `RECOVERY` | Resume strategy from saved state |

---

## Order Lifecycle States

```
PENDING → PLACED → OPEN → FILLED
                       ↘ PARTIALLY_FILLED → FILLED
                       ↘ CANCELLED
                       ↘ REJECTED
```

All state transitions are recorded in `OrderRepository` with timestamps.

---

## Database

- **Engine:** SQLite 3 with WAL mode
- **Location:** `shoonya_platform/persistence/data/orders.db` (configurable: `ORDERS_DB_PATH`)
- **Access:** Always via `get_connection()` from `persistence/database.py`
- **Settings:** WAL journal, 5s busy_timeout, foreign keys enabled

---

## Dashboard Intent Consumer Architecture

```
Dashboard Request
     │
     ├── Generic intents → intent_queue (Queue)
     │                         │
     │                         ▼
     │                  GenericControlIntentConsumer (thread)
     │                         │
     │                         ▼
     │                  CommandService.execute()
     │
     └── Strategy intents → strategy_intent_queue (Queue)
                                │
                                ▼
                         StrategyControlConsumer (thread)
                                │
                                ▼
                         StrategyExecutorService
```

Both consumers run as daemon threads started by `ShoonyaBot.start_control_intent_consumers()`.
