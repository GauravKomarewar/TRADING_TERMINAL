# Quick Start: Test Order Diagnostics

## 🚀 In 5 Minutes

### Step 1: Open Enhanced Orderbook
1. Open browser: `http://localhost:8000/dashboard/web/orderbook.html`
2. See **new status cards at the top**:
   ```
   Total Orders | Created/Pending | Executed | Failed
   ```
3. These auto-refresh every 3 seconds

### Step 2: Verify Your Orders Are in Database
Open terminal and run:
```bash
cd c:\Users\gaura\OneDrive\Desktop\shoonya\shoonya_platform
python verify_orders.py
```

You'll see:
```
📊 Total orders in database: X
📈 Orders by status:
  ⚙️ CREATED: 2        ← Waiting to be sent
  🚀 SENT_TO_BROKER: 0 ← Sent but awaiting fill
  ✅ EXECUTED: 35      ← Successfully filled
  ❌ FAILED: 5         ← Rejected by system
```

**✅ This confirms orders ARE being written to order.db**

### Step 3: Check Full Diagnostics Page
1. Open: `http://localhost:8000/dashboard/web/order_diagnostics.html`
2. Click "🔄 Refresh" or it auto-refreshes every 5 seconds
3. You'll see:
   - 📊 Order pipeline status
   - 🎯 Intent verification summary
   - ⚠️ Full 6-stage pipeline visualization
   - Failed orders with details
   - Pending orders tracking

---

## 🔍 Understanding Your Current Issue

### What You Reported
> "Orders placed but not showing in orderbook"

### What's Actually Happening

**From your logs**:
```
2026-02-07 17:46:17,599 - DASHBOARD.INTENT - INFO - 📥 DASHBOARD BASKET INTENT | 2 orders queued
2026-02-07 17:46:18,334 - shoonya_platform.risk.supreme_risk - CRITICAL - RMS: Max loss breach detected | pnl=-499.00 | max_loss=-15.00
2026-02-07 17:46:18,653 - EXECUTION.CONTROL - ERROR - ❌ BASKET FAILED | DASH-BASKET-ef48d1626e | step 1
```

**Translation**:
1. ✅ Orders queued successfully
2. ✅ Intents created successfully
3. ❌ **RMS blocked them** because:
   - Your current loss: -₹499
   - Your loss limit: -₹15
   - Breach: **32x over the limit!**

**This is NOT a bug. This is a FEATURE protecting you.**

### Why Orders Don't Show in Orderbook

```
Order Created (CREATED) 
  ↓ (Risk Check)
❌ RMS BLOCKS (pnl breach)
  ↓
Order never sent to broker
  ↓
Never gets broker_order_id
  ↓
Never reaches "SENT_TO_BROKER" state
  ↓
OrderWatcher never reconciles it
  ↓
Never executes, never shows in orderbook
```

---

## ✅ Fix Your Issue

### Option 1: Close Losing Positions (RECOMMENDED)
Your account has a **₹499 loss**. You need to:
1. Open your broker platform
2. Close the losing positions
3. Get PnL back to at least **-₹15** (or better: positive)
4. Then try placing orders again → RMS will allow them

### Option 2: Check Your Position PnL
```bash
python verify_orders.py
```

Look at the last 10 orders - see which ones executed with losses.

### Option 3: Verify Orders Are Actually in Database

Run this to see EXACTLY what's in your database:

```bash
python verify_orders.py
```

Then check specific order:
```bash
python verify_orders.py --order=DASH-BASKET-ef48d1626e
```

Output will show:
```
📋 Order Details:
  Command ID: DASH-BASKET-ef48d1626e
  Symbol: NIFTY
  Status: CREATED         ← Stuck here (never sent)
  Broker Order ID: NOT SET ← Never made it to broker
  Created: 2026-02-07 17:46:18
  Updated: 2026-02-07 17:46:18
```

**This proves**:
- ✅ Order WAS created in database
- ✅ Order WAS saved to disk
- ❌ But RMS blocked it from being sent to broker

---

## 📊 Complete Verification Checklist

- [ ] Run `python verify_orders.py` → See all orders
- [ ] Open `/dashboard/web/orderbook.html` → See status cards
- [ ] Open `/dashboard/web/order_diagnostics.html` → See full pipeline
- [ ] Check "Failed Orders" section for reasons
- [ ] Look at "Pending Orders" to find stuck orders
- [ ] Review diagnostics for data quality issues

---

## 🎯 What Each Status Means

| Status | Meaning | What Happened |
|--------|---------|---------------|
| **CREATED** | Order in OMS only | Dashboard created it, but RMS/consumer hasn't sent to broker yet |
| **SENT_TO_BROKER** | Waiting for broker | Order sent to broker, waiting for fill/rejection |
| **EXECUTED** | Fully filled | Broker filled the order, displayed in orderbook |
| **FAILED** | Rejected | Order was rejected by system (RMS, broker, validation) |

---

## 📝 Check Order History

### Via Database
```bash
python verify_orders.py
```

Output shows:
- All orders by status
- Recent orders (last 10)
- Failed orders with timestamps
- Data quality issues

### Via Web Dashboard
1. Open `/dashboard/web/orderbook.html`
2. See "System Orders" table with all details
3. See "Broker Orders" table (live from broker)

### Via API (Programmatic)
```bash
# Get all orders
curl http://localhost:8000/dashboard/orderbook

# Get diagnostics
curl http://localhost:8000/dashboard/diagnostics/orders

# Get intent verification
curl http://localhost:8000/dashboard/diagnostics/intent-verification
```

---

## 🧪 Test the Full Pipeline

### Simulate Complete Order Journey

Once you fix the RMS issue (reduce losses), place an order and trigger all stages:

1. **Stage 1 - Intent Created**
   - Place order via `/dashboard/web/place_order.html`
   - Check log: `2026-02-07 HH:MM:SS - DASHBOARD.INTENT - 📥 Order queued`

2. **Stage 2 - DB Write**
   - Run: `python verify_orders.py`
   - Verify order appears in database with status: `CREATED`

3. **Stage 3 - Risk Check**
   - If RMS passes, order proceeds
   - If blocked, you'll see: `RMS: [reason] breach detected`

4. **Stage 4 - Sent to Broker**
   - Check: `python verify_orders.py --order=COMMAND_ID`
   - Status should be: `SENT_TO_BROKER`
   - Broker Order ID should be set

5. **Stage 5 - Broker Confirm**
   - Wait 2-5 seconds
   - OrderWatcher polls broker
   - Status updates to: `EXECUTED`

6. **Stage 6 - Orderbook**
   - Order now shows in `/dashboard/web/orderbook.html`
   - Both "System Orders" and "Broker Orders" sections

---

## 📈 Monitor in Real-Time

### Terminal: Watch Intent Logs
```bash
tail -f logs/intent_tracking.log
```

You'll see JSON lines like:
```json
{"stage": "INTENT_CREATED", "command_id": "CMD-123", "symbol": "NIFTY", ...}
{"stage": "DB_WRITE", "command_id": "CMD-123", "status": "CREATED", ...}
{"stage": "SENT_TO_BROKER", "command_id": "CMD-123", "broker_order_id": "XT0001", ...}
{"stage": "EXECUTED", "command_id": "CMD-123", "filled_qty": 1, "avg_price": 20500.50}
```

### Browser: Watch Dashboard
1. Open `/dashboard/web/order_diagnostics.html`
2. See "Recent Activity" update in real-time
3. Status cards update every 5 seconds

### Monitor RMS State
Check if risk exit is still active:
```python
# File: config_env/primary.env points to RISK_STATE_FILE
# Usually: logs/risk/current_state.json

# Contains:
{
  "daily_pnl": -499.00,
  "max_daily_loss": -15.00,
  "status": "NORMAL" or "EXIT_TRIGGERED"
}
```

When "EXIT_TRIGGERED", no new orders allowed → **Fix by reducing losses**

---

## 🐛 If Still Issues...

### Problem: Orders showing FAILED
**Check**: 
```bash
python verify_orders.py
```
Look for "Recent failed orders" section.

Each FAILED order will show a reason (RMS, broker, validation error, etc.)

### Problem: No orders in database
**Possible causes**:
1. Dashboard not running
2. Order submission failed (check API response in F12 console)
3. Wrong client_id isolation

**Check**:
```bash
python verify_orders.py
```
If returns 0 orders, database is working but no orders were saved.

### Problem: Orders SENT_TO_BROKER but not EXECUTED
**Possible causes**:
1. OrderWatcher not running
2. Broker API timeout
3. Order still pending (normal for some types)

**Check**:
- OrderWatcher should be running constantly
- Check `logs/` for "OrderWatcherEngine" lines
- Wait 30 seconds for broker to confirm

### Problem: Diagnostics page shows errors
Check browser console (F12):
- Look for API errors
- Check network tab for 404/500 responses
- Verify API endpoints exist in router

---

## 🎓 Understanding the New Tools

### Tool 1: `python verify_orders.py`
**What**: Directly reads SQLite database
**When**: Whenever you want to verify orders exist
**Output**: Status distribution, recent orders, failed orders

### Tool 2: `/dashboard/orderbook.html` (Enhanced)
**What**: Web interface with status cards
**When**: Monitor orders in real-time
**New feature**: Status breakdown at top (Total, Pending, Executed, Failed)

### Tool 3: `/dashboard/order_diagnostics.html` (New)
**What**: Full pipeline visibility
**When**: Debug why order failed
**Shows**: 6-stage pipeline, data quality, recent activity

### Tool 4: `logs/intent_tracking.log` (New)
**What**: JSON logs of each order stage
**When**: Audit trail for specific order
**Command**: `tail -f logs/intent_tracking.log`

---

## 🚨 Your Immediate Action

1. **Check Current Status**:
   ```bash
   python verify_orders.py
   ```

2. **Identify Losing Positions**:
   - Look at "Recent failed orders"
   - Or open broker platform
   - Find positions with losses

3. **Close Losses**:
   - Manually close positions
   - Get PnL back to -₹15 or better

4. **Try Placing Order Again**:
   - Use `/dashboard/web/place_order.html`
   - Order should be accepted (no RMS block)
   - Check orderbook after 5 seconds

5. **Verify Full Pipeline**:
   - Open `/dashboard/web/order_diagnostics.html`
   - See order move through 6 stages
   - Confirm "EXECUTED" in orderbook

---

**You now have 3+ ways to verify your orders at each stage!** 🎉

Need help? Run `python verify_orders.py` - it has detailed output explaining what's happening.
