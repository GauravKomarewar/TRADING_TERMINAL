# 📑 ORDER DIAGNOSTICS - MASTER INDEX

## 🎯 START HERE

You asked: **"Why aren't my orders appearing in the orderbook?"**

Answer: **RMS (Risk Management System) blocked them due to excessive losses.**

But now you have **complete visibility** into why and where orders fail.

---

## 🚀 Get Started in 5 Minutes

### 1. See Your Orders (Terminal)
```bash
cd c:\Users\gaura\OneDrive\Desktop\shoonya\shoonya_platform
python verify_orders.py
```

**This shows**:
- How many orders total
- How many in each status
- Which ones failed and why

### 2. See Visual Dashboard (Web)
```
http://localhost:8000/dashboard/web/orderbook.html
```

**Look at the TOP** - you'll see:
- Total Orders: X
- Created/Pending: Y
- Executed: Z
- Failed: W

### 3. See Full Details (Web)
```
http://localhost:8000/dashboard/web/order_diagnostics.html
```

**Scroll down** to see:
- 6-stage pipeline diagram
- Failed orders list
- Pending orders tracker
- Data quality checks

---

## 📚 Documentation Map

### Quick Lookup (1 min)
→ `QUICK_REFERENCE.txt` - Cheat sheet

### Quick Start (10 min)
→ `QUICK_START_DIAGNOSTICS.md` - Step-by-step guide

### Complete Guide (30 min)
→ `ORDER_PLACEMENT_GUIDE.md` - Everything explained

### Implementation Details (20 min)
→ `IMPLEMENTATION_ORDER_DIAGNOSTICS.md` - What was added

### Executive Summary (15 min)
→ `ORDER_DIAGNOSTICS_FINAL_SUMMARY.md` - Complete summary

### File Changes (5 min)
→ `FILES_CHANGED.md` - What was modified/created

---

## 🛠️ Tools You Have Now

| Tool | How to Use | Purpose |
|------|-----------|---------|
| **Verify Script** | `python verify_orders.py` | Check database for all orders |
| **Orderbook Page** | `/dashboard/web/orderbook.html` | Visual dashboard with status cards |
| **Diagnostics Page** | `/dashboard/web/order_diagnostics.html` | Full pipeline visualization |
| **API Endpoint 1** | `GET /dashboard/diagnostics/orders` | Programmatic order status |
| **API Endpoint 2** | `GET /dashboard/diagnostics/intent-verification` | Intent pipeline check |
| **Intent Logs** | `tail -f logs/intent_tracking.log` | Audit trail for each order |

---

## 🎓 Your Situation Explained

### What You're Seeing
```
Order placed → Intent created → Database saved → 🚫 BLOCKED by RMS → No orderbook
```

### Why It's Happening
```json
{
  "daily_pnl": -499.00,           // Your current loss
  "max_daily_loss": -15.00,       // System limit
  "status": "EXIT_TRIGGERED"      // Risk management active
}
```

**Your loss is 33 times larger than the limit!**
System is protecting you by blocking new orders.

### How to Fix It
1. Close current losing positions
2. Reduce loss to at least -15 (or positive)
3. Try placing order again
4. Diagnostics will show it progressing through 6 stages

---

## 🔍 Complete Order Flow

```
1. DASHBOARD
   You submit order form
   ✅ Confirm: Check logs for "📥 orders queued"

2. DATABASE
   Order saved with status: CREATED
   ✅ Confirm: python verify_orders.py

3. RISK CHECK
   RMS validates loss limits
   ❌ YOUR CASE: Loss too high, blocked here
   ✅ Confirm: Look for "RMS: Max loss breach"

4. BROKER SEND (skipped if RMS blocks)
   Consumer sends to broker
   Status: SENT_TO_BROKER
   ✅ Confirm: Check broker_order_id in database

5. WATCHER POLL
   OrderWatcher gets fill status
   Status: EXECUTED or FAILED
   ✅ Confirm: See in orderbook dashboard

6. ORDERBOOK
   Order visible in web UI
   ✅ Confirm: Check orderbook page
```

**You're stuck at Step 3** - RMS risk check.

---

## 📋 What Was Added

### New Web Pages
- ✅ Enhanced orderbook.html (status cards)
- ✅ order_diagnostics.html (full pipeline view)

### New Tools
- ✅ verify_orders.py (command-line verification)
- ✅ intent_tracker.py (order lifecycle logging)

### New API Endpoints
- ✅ /dashboard/diagnostics/orders
- ✅ /dashboard/diagnostics/intent-verification

### Documentation
- ✅ 5 comprehensive guides
- ✅ 1 quick reference card
- ✅ 1 file change summary

---

## 🎯 Quick Actions

### Right Now (Do These First)

**1. Verify orders exist in database:**
```bash
python verify_orders.py
```

**2. Check web dashboard:**
```
Open: http://localhost:8000/dashboard/web/orderbook.html
Look at: Status cards at the top
```

**3. Find why orders failed:**
```
Open: http://localhost:8000/dashboard/web/order_diagnostics.html
Scroll to: "Failed Orders" section
```

### Next (Fix The Issue)

**1. Close losing positions**
- Your PnL: -₹499
- RMS limit: -₹15
- Action: Reduce loss first

**2. Try placing order again**
- After loss is < -₹15
- RMS will allow it
- Monitor via diagnostics page

**3. Watch progression**
- Open diagnostics page
- See order move through 6 stages
- Confirm it reaches orderbook

---

## 📊 What Each Page Shows

### Orderbook (`/dashboard/web/orderbook.html`)
```
TOP:
  Total Orders: 42
  Created/Pending: 2 ⚠️
  Executed: 35 ✅
  Failed: 5 ❌

MIDDLE:
  System Orders table (all OMS orders)
  Broker Orders table (live from broker)
```

**Updates every 3 seconds**

### Diagnostics (`/dashboard/web/order_diagnostics.html`)
```
SECTION 1: Status Cards
  Total | CREATED | SENT_TO_BROKER | EXECUTED | FAILED

SECTION 2: Pipeline Visualization
  6 stages with emoji indicators [1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣]

SECTION 3: Failed Orders
  List of rejected orders with reasons

SECTION 4: Pending Orders
  Orders waiting for broker confirmation

SECTION 5: Recent Activity
  Last 20 orders with timestamps
```

**Updates every 5 seconds**

---

## 🔧 Troubleshooting Quick Links

### "Orders not showing up"
→ Read: `QUICK_START_DIAGNOSTICS.md` → Section "Fix Your Issue"

### "Why are orders blocked"
→ Read: `ORDER_PLACEMENT_GUIDE.md` → Section "Fixing Your Issue"

### "How to verify orders in DB"
→ Read: `QUICK_REFERENCE.txt` → Section "3 Tools to Check Orders"

### "Complete order flow"
→ Read: `ORDER_PLACEMENT_GUIDE.md` → Section "How Order Pipeline Works"

### "Setup and usage"
→ Read: `IMPLEMENTATION_ORDER_DIAGNOSTICS.md` → Section "How to Use"

---

## 💻 Command Reference

```bash
# Check all orders
python verify_orders.py

# Check specific order
python verify_orders.py --order=COMMAND_ID_HERE

# Watch intent logs (real-time)
tail -f logs/intent_tracking.log

# Count orders by status (if you have sqlite3)
sqlite3 shoonya_platform/persistence/data/orders.db \
  "SELECT status, COUNT(*) FROM orders GROUP BY status"

# List failed orders (if you have sqlite3)
sqlite3 shoonya_platform/persistence/data/orders.db \
  "SELECT command_id, symbol FROM orders WHERE status='FAILED'"
```

---

## 🌐 URL Reference

```
Orderbook Dashboard:
  http://localhost:8000/dashboard/web/orderbook.html

Diagnostics Page:
  http://localhost:8000/dashboard/web/order_diagnostics.html

Place Order:
  http://localhost:8000/dashboard/web/place_order.html

API Queries (in browser or curl):
  http://localhost:8000/dashboard/diagnostics/orders
  http://localhost:8000/dashboard/diagnostics/intent-verification
```

---

## 📖 Reading Path by Use Case

### "I want quick answers"
1. QUICK_REFERENCE.txt
2. Run: python verify_orders.py
3. Open: order_diagnostics.html
4. Done!

### "I want to understand everything"
1. QUICK_START_DIAGNOSTICS.md
2. ORDER_PLACEMENT_GUIDE.md
3. Run tools to verify
4. Read IMPLEMENTATION_ORDER_DIAGNOSTICS.md

### "I'm a developer"
1. FILES_CHANGED.md (what was modified)
2. IMPLEMENTATION_ORDER_DIAGNOSTICS.md (technical details)
3. intent_tracker.py (code)
4. router.py (API endpoints)

### "I want to fix my RMS issue"
1. QUICK_REFERENCE.txt → "Your Immediate Action"
2. ORDER_PLACEMENT_GUIDE.md → "Fixing Your Issue"
3. QUICK_START_DIAGNOSTICS.md → "Immediate Action"

---

## ✅ Verification Checklist

Before you start, make sure:

- [ ] Can access orderbook at localhost:8000
- [ ] Dashboard is running
- [ ] Database exists at shoonya_platform/persistence/data/orders.db
- [ ] Browser console (F12) works for checking logs
- [ ] Terminal access available for python verify_orders.py

---

## 🎯 Your Immediate Next Steps

### Step 1 (Now)
```bash
python verify_orders.py
```
Copy the output and review it

### Step 2 (Now)
Open these in browser:
- `http://localhost:8000/dashboard/web/orderbook.html`
- `http://localhost:8000/dashboard/web/order_diagnostics.html`

### Step 3 (Next 15 min)
Read: `QUICK_START_DIAGNOSTICS.md`

### Step 4 (Next hour)
Close losing positions to fix RMS issue

### Step 5 (After fix)
Place new order and watch it move through 6 stages

---

## 📞 If You Need Help

1. **Can't access tools?** → Check database path in verify_orders.py
2. **Diagnostics page 404?** → Restart dashboard, check router.py added
3. **No orders in database?** → Check API responses in browser F12 console
4. **Still confused?** → Read QUICK_START_DIAGNOSTICS.md completely

---

## 🎨 Status Indicators Legend

```
⚙️ CREATED       = Order in database, not yet sent to broker
🚀 SENT_TO_BROKER = Order sent to broker, awaiting fill
✅ EXECUTED      = Order filled and confirmed
❌ FAILED        = Order rejected/cancelled
📥 QUEUED        = Just received by system
🚫 BLOCKED       = RMS stopped it (your case)
⏳ PENDING       = Waiting for something
```

---

## 🏆 What You Can Now Do

✅ **See all orders** - Not just successful ones
✅ **Track each stage** - From creation to execution
✅ **Identify failures** - Know exactly why orders fail
✅ **Monitor RMS** - See when risk limits are breached
✅ **Verify database** - Confirm orders are persisted
✅ **Audit trail** - Complete JSON logs of each step
✅ **Real-time updates** - See changes as they happen
✅ **Root cause analysis** - Find bottlenecks instantly

---

## 🚀 Bottom Line

**Before**: "Order placed, disappeared, no idea why"
**Now**: "Order placed → See exactly where it failed → Know how to fix it"

**You have complete visibility into your entire order pipeline!**

---

## 📍 Quick Links

- **Quick Lookup**: `QUICK_REFERENCE.txt`
- **Quick Start**: `QUICK_START_DIAGNOSTICS.md`
- **Full Guide**: `ORDER_PLACEMENT_GUIDE.md`
- **Features**: `IMPLEMENTATION_ORDER_DIAGNOSTICS.md`
- **Summary**: `ORDER_DIAGNOSTICS_FINAL_SUMMARY.md`
- **File Changes**: `FILES_CHANGED.md`
- **This File**: `INDEX.md` ← You are here

---

**Last Updated**: 2026-02-07  
**Status**: ✅ Complete & Ready  
**Support**: All documentation included  

**START WITH**: `python verify_orders.py` → Then open `/dashboard/web/order_diagnostics.html`
