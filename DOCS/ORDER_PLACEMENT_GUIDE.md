# Order Placement Troubleshooting Guide

## Problem: Orders Placed But Not Appearing in Orderbook

Your logs show:
- ✅ Intent queued: "2 orders queued"
- ✅ Intent created: Dashboard received intent
- ❌ **FAILED**: RMS (Risk Management System) max loss breach

### Root Cause: RMS Emergency Exit

```
RMS: Max loss breach detected | pnl=-499.00 | max_loss=-15.00 | triggering exit
🔴 DAILY MAX LOSS HIT | triggering risk exit
❌ BASKET FAILED | step 1
EXIT: no eligible positions after filtering
```

Your **current PnL is -499.00**, but your **max loss threshold is -15.00**. This is a massive breach that triggered emergency system exit.

---

## How Order Pipeline Works

```
1. WEB: Dashboard order form
   ↓
2. INTENT: UniversalOrderCommand created
   ↓
3. DB: Order written to orders.db (status: CREATED)
   ↓
4. CONSUMER: Execution system receives intent
   ↓
5. RISK CHECK: RMS validates risk limits ⚠️ ← YOUR ISSUE
   ↓
6. BROKER: If risk passes, broker API called
   ↓
7. DB UPDATE: Order status → SENT_TO_BROKER
   ↓
8. WATCHER: Polls broker for confirmation
   ↓
9. DB UPDATE: Order status → EXECUTED or FAILED
   ↓
10. ORDERBOOK: Displays final order state
```

---

## Tracking Order Status

**Use the new Diagnostics page** (`/dashboard/web/order_diagnostics.html`):
- Shows all orders (created, pending, executed, failed)
- Tracks status transitions
- Identifies bottlenecks

**Or verify orders via database**:

```bash
cd c:\Users\gaura\OneDrive\Desktop\shoonya\shoonya_platform
python verify_orders.py
```

**Check specific order**:
```bash
python verify_orders.py --order=COMMAND_ID_HERE
```

---

## What's Happening NOW

### Step 1: Intent Creation
When you submit an order from the dashboard, a `UniversalOrderCommand` intent is created:

**File**: `shoonya_platform/api/dashboard/api/router.py` → `/dashboard/intent/basket`

Log sample:
```
📥 DASHBOARD BASKET INTENT | 2 orders queued
```

### Step 2: Database Write
Orders are immediately written to `shoonya_platform/persistence/data/orders.db`:

**Status**: `CREATED` (not yet sent to broker)

Check database:
```bash
python verify_orders.py
```

Output shows:
```
📈 Orders by status:
  ⚙️ CREATED: X          ← Waiting to be sent
  🚀 SENT_TO_BROKER: Y   ← Sent but awaiting fill
  ✅ EXECUTED: Z        ← Filled
  ❌ FAILED: W          ← Rejected
```

### Step 3: Risk Check (WHERE YOUR ORDERS FAIL)
Before sending to broker, RMS checks:

**File**: `shoonya_platform/risk/supreme_risk.py`

Your config probably has:
```
max_daily_loss = -15.00  (₹15 loss limit)
current_pnl = -499.00    (actual loss)
```

❌ **Breach detected** → Emergency exit triggered

### Step 4: Broker Send
If RMS passes (which it won't until you reduce losses):

**File**: `shoonya_platform/execution/broker.py`

Order sent to Shoonya broker API→ Returns `norenordno` (broker order ID) → DB updated to `SENT_TO_BROKER`

### Step 5: Watcher Reconciliation
OrderWatcher polls broker every 1-2 seconds:

**File**: `shoonya_platform/execution/order_watcher.py`

Checks broker order status → Updates local database → Displays in orderbook

---

## Fixing Your Issue

### Option 1: Reduce Losses (RECOMMENDED)

The system is working correctly - it's **protecting you** from further losses.

Your current position is losing ₹499. You need to:

1. **Close losing positions manually** OR
2. **Wait for price recovery** OR
3. **Verify the PnL calculation is correct**

Once losses are below ₹15, RMS will allow new orders.

### Option 2: Adjust Risk Settings

Edit risk config:
```python
# File: shoonya_platform/risk/supreme_risk.py

MAX_DAILY_LOSS = 15.00    # Current: ₹15
MAX_LOSS_PERCENT = 0.5    # Current: 0.5% of capital
```

⚠️ **WARNING**: Only increase if you understand the consequences!

### Option 3: Temporary Override (DEBUG ONLY)

For testing only - add to your order:
```json
{
  "symbol": "NIFTY",
  "quantity": 1,
  "side": "BUY",
  "override_rms": true
}
```

⚠️ Only works for manual override testing!

---

## Verify Order at Each Stage

### Check if Order Exists in Database

```bash
python verify_orders.py
```

Output:
```
📊 Total orders in database: 42
📈 Orders by status:
  ⚙️ CREATED: 2
  🚀 SENT_TO_BROKER: 0
  ✅ EXECUTED: 35
  ❌ FAILED: 5
```

### Check RMS State

Check the risk state file:
```
config_env/primary.env → RISK_STATE_FILE
```

Contains:
```json
{
  "daily_pnl": -499.00,
  "max_daily_loss": -15.00,
  "status": "EXIT_TRIGGERED"
}
```

### Check OrderWatcher Logs

Look for "OrderWatcherEngine" in logs:
```
OrderWatcherEngine: reconciling broker orders
OrderWatcherEngine: broker_id=XT0001, status=FILLED
OrderWatcherEngine: updating order status=EXECUTED
```

---

## Complete Order Tracking Endpoints

### 1. Orderbook (All Orders)
```
GET /dashboard/orderbook
```
Returns:
- `system_orders`: Orders in OMS layer
- `broker_orders`: Live broker order book

### 2. Order Diagnostics (Full Pipeline)
```
GET /dashboard/diagnostics/orders
```
Returns:
- Status breakdown
- Failed orders with reasons
- Pending orders
- Executed orders

### 3. Intent Verification
```
GET /dashboard/diagnostics/intent-verification
```
Returns:
- Intent generation pipeline status
- Broker mapping verification
- Data quality issues
- Recent activity

**Access all via web**:
- Orderbook: `/dashboard/web/orderbook.html`
- Diagnostics: `/dashboard/web/order_diagnostics.html`

---

## Next Steps

1. **Open Diagnostics page**: `/dashboard/web/order_diagnostics.html`
2. **Check failed orders**: Look for Failed section
3. **Verify database**: Run `python verify_orders.py`
4. **Close losing trades**: Reduce PnL to below ₹15 threshold
5. **Try placing orders again**: RMS should allow them now

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Orders placed but not in orderbook | RMS max loss breach | Close losing positions |
| SENT_TO_BROKER but not EXECUTED | Broker taking time | Wait 10-30s, check broker API |
| No broker_order_id in DB | Broker API error | Check broker connectivity |
| Status stuck at CREATED | Consumer not running | Restart execution consumer |
| Missing orders in DB | Intent not received | Check API logs |

---

## For Developers

### Adding Order Tracking

```python
from shoonya_platform.execution.intent_tracker import get_intent_tracker

tracker = get_intent_tracker(client_id)

# Log intent creation
tracker.log_intent_created("CMD-001", {"symbol": "NIFTY", "side": "BUY"})

# Log DB write
tracker.log_db_write("CMD-001", "CREATED")

# Log broker send
tracker.log_sent_to_broker("CMD-001", "XT0001")

# Log execution
tracker.log_order_executed("CMD-001", "XT0001", 1, 20500.50)

# Log failure
tracker.log_order_failed("CMD-001", "XT0001", reason="Insufficient liquidity")
```

### Accessing Intent Logs

```bash
tail -f logs/intent_tracking.log
```

Each line is JSON:
```json
{"stage": "INTENT_CREATED", "command_id": "CMD-001", "symbol": "NIFTY", ...}
{"stage": "DB_WRITE", "command_id": "CMD-001", "status": "CREATED", ...}
{"stage": "SENT_TO_BROKER", "command_id": "CMD-001", "broker_order_id": "XT0001", ...}
{"stage": "EXECUTED", "command_id": "CMD-001", "filled_qty": 1, "avg_price": 20500.50}
```

---

## Need Help?

1. Check orderbook diagnostics page
2. Run `python verify_orders.py`
3. Check `logs/intent_tracking.log`
4. Monitor RMS state file for risk triggers
5. Review API response codes in browser console (F12)
