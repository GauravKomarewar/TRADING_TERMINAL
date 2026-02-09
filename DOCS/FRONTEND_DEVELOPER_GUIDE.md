# Frontend Pages Quick Reference & Developer Guide

## Page Overview

### 1. **login.html** - Authentication Entry Point
- **Purpose:** User login to dashboard
- **Endpoint:** `POST /auth/login`
- **Redirect:** Successful login → `/dashboard/web/dashboard.html`
- **Features:**
  - Simple password entry
  - Visual feedback
  - Keyboard shortcut (Enter key)
  - Session-based authentication

---

### 2. **dashboard.html** - Orders & System Status
- **Purpose:** View system orders and broker orders in real-time
- **Endpoints Used:**
  - `GET /dashboard/home/status` (periodic refresh)
  - `POST /dashboard/orders/cancel/system` (cancel orders)
  - `POST /dashboard/orders/modify/system` (modify orders)
  - `POST /dashboard/orders/cancel/system/all` (batch cancel)
  
- **Key Features:**
  - Real-time order monitoring
  - Order status badges
  - Modify/Cancel actions
  - Auto-refresh every 5 seconds
  - CSV export for orders

- **Order Types Displayed:**
  - System Orders (Intent Layer) - CREATED, TRIGGERED, EXECUTED, CANCELLED, REJECTED
  - Broker Orders (Execution Layer) - OPEN, PENDING, COMPLETE

---

### 3. **home.html** - Dashboard Snapshot
- **Purpose:** Overview of positions, risk, and market data
- **Endpoints Used:**
  - `GET /dashboard/home/status` (initial load)
  
- **Information Displayed:**
  - Portfolio positions (with P&L)
  - Risk status (daily loss, cooldown, etc.)
  - Market data heartbeat
  - Open orders count
  - Active signals

---

### 4. **place_order.html** - Order Placement (3 Methods)
- **Purpose:** Place manual orders using intents

#### Method 1: Generic Single Order
- **Endpoint:** `POST /dashboard/intent/generic`
- **Form Fields:**
  - Exchange (NFO, NSE, BSE, etc.)
  - Symbol (with autocomplete)
  - Side (BUY/SELL)
  - Qty
  - Product (MIS/NRML/CNC)
  - Order Type (MARKET/LIMIT)
  - Price (for LIMIT)
  - Optional: Triggered Orders, Target, Stop Loss, Trailing SL

- **Validation:**
  - ✅ Symbol required
  - ✅ Qty > 0
  - ✅ Price required for LIMIT orders
  - ✅ All errors show to user

- **Response:** `{ accepted: true, intent_id: "DASH-GEN-..." }`

#### Method 2: Basket Multiple Orders
- **Endpoint:** `POST /dashboard/intent/basket`
- **Process:**
  1. Add multiple orders to basket
  2. Review orders in basket
  3. Submit all at once
  4. Orders separated: EXITs first, then ENTRIEs (risk-safe ordering)

- **Response:** `{ accepted: true, intent_id: "DASH-BAS-..." }`

#### Method 3: Advanced Multi-Leg
- **Endpoint:** `POST /dashboard/intent/advanced`
- **Features:**
  - Multiple legs for options strategies
  - Each leg has target_type (DELTA/THETA/GAMMA/VEGA/PRICE/PREMIUM)
  - Parallel execution of legs

- **Response:** `{ accepted: true, intent_id: "DASH-ADV-..." }`

---

### 5. **option_chain_dashboard.html** - Options Chain & Basket Orders
- **Purpose:** View option chain and place basket orders from chain

#### Features:
- Real-time option chain display
- Strike-by-strike view with Greeks
- Column visibility toggle
- ATM highlighting (orange)
- Basket functionality integrated

#### Order Placement:
- **Endpoint:** `POST /dashboard/intent/basket`
- **Process:**
  1. Click on strike prices to add to basket
  2. Select side (BUY/SELL) and quantity
  3. Choose product and order type
  4. Click "Basket" icon to open modal
  5. Review and confirm
  6. Submit as batch intent

#### Data Filters:
- Symbol selection (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
- Expiry selection (active expiries only)
- Column visibility (OI, Volume, IV, Greeks)

---

### 6. **orderbook.html** - System & Broker Orders (Detailed View)
- **Purpose:** Detailed order viewing and management

#### Sections:
1. **System Orders (Intent Layer)**
   - Source, Strategy, User info
   - Risk parameters (SL, Target, Trailing SL)
   - Status and execution details

2. **Broker Orders (Execution Layer)**
   - Broker-specific details (Noren Order No, Account ID)
   - Fill information (Fill Shares, Avg Price)
   - Exchange-level status

#### Actions Available:
- ✏️ Modify Order (change type/price/qty)
- ❌ Cancel Order (individual or batch)
- 📥 Export CSV (all orders or filtered)
- 🔄 Refresh (manual refresh)

---

### 7. **diagnostics.html** - API Testing Tool
- **Purpose:** Test backend API endpoints directly

#### Available Tests:
1. **Dashboard Status API**
   - Tests: `GET /dashboard/home/status`
   - Shows: System orders, positions, risk state

2. **Expiries API**
   - Tests: `GET /dashboard/symbols/expiries`
   - Shows: Available expiry dates for symbols

3. **Option Chain API**
   - Tests: `GET /dashboard/option-chain`
   - Shows: Complete option chain for symbol + expiry

#### Usage:
- No login required (uses same session)
- Shows full JSON responses
- Useful for debugging API issues

---

### 8. **strategy_dnss.html** - Delta Neutral Short Strangle Strategy Control
- **Purpose:** Enter and manage DNSS strategy

#### Entry Configuration:
- Strategy name and version
- Entry/Exit times
- Lot quantity
- Cooldown seconds
- DNSS-specific parameters (Target Delta, Adjust Trigger, etc.)

#### Endpoint: `POST /intent/strategy/entry`
- Creates strategy-scoped control intent
- GenericControlIntentConsumer routes to strategy runner

#### Exit Controls:
- **Endpoint:** `POST /dashboard/intent/strategy`
- Actions:
  - `EXIT` - Normal exit at targets
  - `FORCE_EXIT` - Immediate exit

---

## Color Theme Reference

```css
/* Light Colors (Text) */
--text: #f1f5f9              /* Main text */
--muted: #94a3b8             /* Secondary text */

/* Dark Colors (Background) */
--bg: #0a0e13                /* Page background */
--panel: #151b26             /* Card background */
--panel-2: #1c2333           /* Lighter panels, inputs */
--panel-hover: #222938       /* Hover state */

/* Borders */
--border: #404856            /* Border color (improved contrast) */
--border-focus: #3b82f6      /* Focus state */

/* Status Colors */
--primary: #3b82f6           /* Primary action (blue) */
--success: #10b981           /* Success (green) */
--danger: #ef4444            /* Error/danger (red) */
--warning: #f59e0b           /* Warning (amber) */
```

---

## Common Code Patterns

### Form Validation Pattern
```javascript
if (!fieldValue) {
  resultElement.className = 'result bad';
  resultElement.innerHTML = '✖ Error message';
  return;
}
```

### Intent Submission Pattern
```javascript
const payload = {
  exchange: selectElement.value,
  symbol: inputElement.value,
  // ... other fields
};

const res = await fetch('/dashboard/intent/endpoint', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload)
});

if (!res.ok) {
  const err = await res.json();
  throw new Error(err.detail || 'Server error');
}

const data = await res.json();
// Show success with intent_id
```

### Authentication Check Pattern
```javascript
async function checkAuth() {
  try {
    const res = await fetch('/dashboard/home/status', {
      credentials: 'include'
    });
    if (res.status === 401) {
      window.location.href = '/';
    }
  } catch (e) {
    console.log('Auth check completed');
  }
}

window.addEventListener('DOMContentLoaded', checkAuth);
```

### Logout Pattern
```javascript
async function logout() {
  try {
    await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'include'
    });
  } catch (e) {
    console.log('Logout completed');
  }
  window.location.href = '/';
}
```

---

## Navigation Structure

All pages have consistent navigation with these links:
```
⚡ Shoonya OMS [Logo]
├─ Dashboard    → /dashboard/web/dashboard.html
├─ Home         → /dashboard/web/home.html
├─ Option Chain → /dashboard/web/option_chain_dashboard.html
├─ Place Order  → /dashboard/web/place_order.html
├─ Orderbook    → /dashboard/web/orderbook.html
├─ Diagnostics  → /dashboard/web/diagnostics.html
├─ DNSS Strategy → /dashboard/web/strategy_dnss.html
└─ [Logout Button]
```

---

## Environment Variables & Configuration

### Backend URLs
All endpoints assume backend is running on same origin:
- **Login:** `POST /auth/login`
- **Status:** `GET /dashboard/home/status`
- **Intents:** `POST /dashboard/intent/*`

### Database Path (Server-Side Only)
```
/home/ec2-user/shoonya_platform/shoonya_platform/persistence/data/orders.db
```

### Symbol Search Endpoint
```
GET /dashboard/symbols/search?q={query}
```

---

## Performance Tips for Users

1. **Don't refresh page** during order submission
2. **Use Orderbook** to track actual order status
3. **Check Diagnostics** if orders don't appear
4. **Review Dashboard Status** for system health
5. **Use Basket** to group related orders
6. **Monitor Risk Status** before large entries

---

## Troubleshooting Guide

### Orders Not Appearing
1. Check `dashboard.html` for order status
2. Run diagnostics test: `/dashboard/home/status`
3. Look for errors in broker orderbook

### Symbol Not Found
1. Use autocomplete in Place Order page
2. Verify symbol is tradeable on selected exchange
3. Check Option Chain for similar symbols

### Logout Not Working
1. Clear browser cookies
2. Check if session expired (401 error)
3. Try again from any page

### Intent Not Accepted
1. Check all required fields are filled
2. Verify schema matches in browser console
3. Run diagnostic API test
4. Check server logs

---

## Developer Notes

### Session Management
- Uses secure, HTTP-only cookies
- Expires after inactivity
- `checkAuth()` redirects on 401

### Intent Routing
1. Frontend sends JSON to `/dashboard/intent/*`
2. DashboardIntentService validates & persists
3. GenericControlIntentConsumer polls DB
4. Consumer routes to `bot.process_alert()`
5. ExecutionGuard enforces risk rules
6. Broker orders submitted

### Risk Management
- ExecutionGuard blocks orders exceeding risk limits
- Daily loss limits enforced
- Cooldown periods respected
- Broker position reconciliation required

---

## Quick Links
- Backend: [GitHub]
- Documentation: [README_DOCUMENTATION.md]
- Intent Schema: [INTENT_GENERATION_REFERENCE.md]
- Integration: [INTEGRATION_COMPLETE_REPORT.md]
- Frontend-Backend: [FRONTEND_BACKEND_ALIGNMENT.md]
