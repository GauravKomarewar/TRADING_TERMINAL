# Market Detection & Live Tick Monitoring Explained

## 🎯 How Market Detection Works

### Detection Strategy: Multi-Layer Validation

The system uses **5 progressive checks** to determine if the market is active, with **live tick monitoring** as the primary indicator:

---

## 1️⃣ **Broker Login Validation** (Foundation)
```python
if not api.ensure_session():
    return False, "Login failed"
```
- **Purpose:** Verify broker API is accepting connections
- **Indicates:** Broker systems are online (not necessarily market open)
- **Fast fail:** If login fails, no point checking further

---

## 2️⃣ **Live Tick Feed Monitoring** (PRIMARY - Most Reliable)
```python
feed_health = check_feed_health()
feed_stats = get_feed_stats()

if feed_health.get('healthy'):
    last_tick_age = feed_stats.get('seconds_since_last_tick')
    if last_tick_age < 30:  # Ticks within last 30 seconds
        return True, "✅ Live ticks detected"
```

### How Tick Monitoring Works:

**Architecture:**
```
Market Exchange → Broker WebSocket → ShoonyaClient → LiveFeed → tick_data_store
                                                                        ↓
                                                                  Last Tick Time
                                                                  (_last_tick_time)
```

**Key Components:**

1. **WebSocket Connection** (`ShoonyaClient`)
   - Maintains persistent connection to broker
   - Receives real-time market data
   - Auto-reconnects on disconnection

2. **Tick Normalizer** (`LiveFeed.normalize_tick()`)
   - Receives raw tick data from WebSocket
   - Normalizes to standard format:
     ```python
     {
         'ltp': float,      # Last traded price
         'pc': float,       # Percentage change
         'v': int,          # Volume
         'o': float,        # Open
         'h': float,        # High
         'l': float,        # Low
         'c': float,        # Close
         'oi': int,         # Open interest
         'tt': str          # Tick timestamp
     }
     ```

3. **Tick Data Store** (`tick_data_store`)
   - Thread-safe dictionary storing latest tick for each symbol
   - Key: Token (e.g., "NSE|26000" for NIFTY)
   - Value: Normalized tick data
   - Updated on every tick reception

4. **Last Tick Tracker** (`_last_tick_time`)
   - Global variable tracking timestamp of most recent tick
   - Updated atomically on every tick
   - Used to calculate feed staleness

**Detection Logic:**

```python
# Check 1: Is WebSocket connected?
if is_feed_connected():  # Returns api.is_logged_in()
    
    # Check 2: Are ticks being received?
    feed_stats = get_feed_stats()
    seconds_since_last_tick = time.time() - _last_tick_time
    
    # Check 3: Are ticks fresh? (< 30 seconds)
    if seconds_since_last_tick < 30:
        # MARKET IS ACTIVE ✅
        # Ticks are flowing, prices are updating
        return True
```

**Why This is Most Reliable:**
- ✅ **Real-time:** Only active markets generate ticks
- ✅ **Immediate:** Detects market opening within seconds
- ✅ **Accurate:** No false positives from stale data
- ✅ **Continuous:** Ongoing validation throughout session
- ✅ **Weekend detection:** Catches mock trading, special sessions

---

## 3️⃣ **Quote Age Validation** (Fallback - Static Data)
```python
nifty_quote = api.get_quotes(exchange="NSE", token="26000")
quote_time = datetime.fromtimestamp(int(nifty_quote['ft']))
age = (datetime.now() - quote_time).total_seconds()

if age < 300:  # Less than 5 minutes
    return True, "Live quote detected"
```

- **Purpose:** Check if NIFTY quote timestamp is recent
- **Limitation:** Quotes can be cached/stale
- **Use case:** Fallback when WebSocket isn't subscribed yet

---

## 4️⃣ **Order Book Activity** (Historical Indicator)
```python
orders = api.get_order_book()
for order in orders:
    if order_placed_today(order):
        return True, "Recent orders detected"
```

- **Purpose:** Detect trading activity from today
- **Limitation:** Only shows if YOUR account traded
- **Use case:** Confirms you're active, not market-wide activity

---

## 5️⃣ **Broker Limits API** (Service Health)
```python
limits = api.get_limits()
if limits:
    logger.info("Broker operational but no market activity")
```

- **Purpose:** Verify broker backend is responding
- **Limitation:** Doesn't indicate market state
- **Use case:** System health check

---

## 🔍 Complete Detection Flow

```
START
  ↓
Login to Broker
  ↓
  ├─ Failed → RETURN: Market Closed
  ↓
Check Live Ticks (PRIMARY)
  ↓
  ├─ Ticks < 30s old → RETURN: ✅ Market Active (LIVE TICKS)
  ├─ WebSocket connected but no ticks → Continue checking
  ↓
Check Quote Age (FALLBACK)
  ↓
  ├─ Quote < 5min old → RETURN: ✅ Market Active (Quote)
  ↓
Check Order Book (FALLBACK)
  ↓
  ├─ Orders from today → RETURN: ✅ Market Active (Orders)
  ↓
Check Broker Limits
  ↓
  ├─ API responds → Log: Broker operational
  ↓
RETURN: ❌ No Market Activity
```

---

## 📊 Feed Health Monitoring

### Functions Available:

**1. `is_feed_connected()` → bool**
```python
# Quick check: Is WebSocket alive?
if is_feed_connected():
    print("WebSocket is connected")
```

**2. `get_feed_stats()` → dict**
```python
{
    "connected": True,                    # WebSocket status
    "subscribed_tokens": 50,              # Number of subscriptions
    "tokens_with_data": 48,               # Tokens receiving ticks
    "total_ticks_received": 125847,       # Lifetime tick count
    "seconds_since_last_tick": 1.2,       # Freshness indicator
    "feed_stale": False                   # Staleness flag (>30s)
}
```

**3. `check_feed_health()` → dict**
```python
{
    "healthy": True,
    "issues": [],                         # Critical problems
    "warnings": [],                       # Non-critical warnings
    "stats": { ... },                     # Full stats from above
    "timestamp": "2026-02-09T10:30:15"
}
```

### Staleness Detection

**Configuration:**
```python
HEARTBEAT_TIMEOUT = 30  # Seconds
```

**Logic:**
```python
if (current_time - _last_tick_time) > HEARTBEAT_TIMEOUT:
    feed_stale = True  # No ticks for 30+ seconds
    # Possible causes:
    # - Market closed
    # - Network issue  
    # - WebSocket disconnected
    # - No subscriptions
```

---

## 🚀 Auto-Refresh Implementation

### Dashboard Pages: 1-Second Auto-Refresh (No Manual Buttons)

**Implementation:**
```javascript
// Auto-start on page load
window.addEventListener('load', () => {
    updateDashboard(false);  // Initial load
    setInterval(() => updateDashboard(true), 1000);  // Refresh every 1s
});
```

**What Gets Refreshed:**
- ✅ Positions (PnL, LTP, quantities)
- ✅ Holdings (values, unrealized PnL)
- ✅ System status (connection, risk, heartbeat)
- ✅ Account limits (margin, exposure)

**Benefits:**
- 📊 **Real-time:** Positions update as market moves
- 🔄 **Automatic:** No manual intervention needed
- 🎯 **Lightweight:** Only fetches changed data
- 💚 **Visual indicator:** "Live Updates" badge with pulsing dot

**Visual Feedback:**
```html
<div class="auto-refresh-status">
    <span class="refresh-dot"></span>  <!-- Animated pulse -->
    <span>Live Updates</span>
</div>
```

```css
.refresh-dot {
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
```

---

## 🎯 Strategy Page: 2-Second Auto-Refresh

```javascript
document.addEventListener('DOMContentLoaded', () => {
    updateStrategyType();
    refreshMonitor();
    setInterval(refreshMonitor, 2000);  // Every 2 seconds
});
```

**What Gets Refreshed:**
- ✅ Active positions with current PnL
- ✅ Strategy status (ACTIVE/PAUSED/IDLE)
- ✅ Combined Greek values (Delta, Theta, Vega)
- ✅ Event log (latest strategy actions)
- ✅ Margin usage and limits

---

## 🔐 Weekend Market Check Integration

**Schedule:** Saturday/Sunday at 9:00 AM (systemd timer)

**Process:**
```bash
1. Timer triggers at 9:00 AM on weekends
2. Script runs market detection:
   ├─ Login to broker
   ├─ Check live tick feed (PRIMARY)
   ├─ Validate quote freshness
   ├─ Check order activity
   └─ Determine: Market active? YES/NO
3. If market active:
   ├─ Send Telegram alert: "Weekend market detected"
   ├─ Start trading service automatically
   └─ Log event
4. If market closed:
   ├─ Log: "No weekend activity"
   └─ Exit (check again at next scheduled time)
```

**Systemd Timer Configuration:**
```ini
[Timer]
OnCalendar=Sat,Sun *-*-* 09:00:00
Persistent=true
```

---

## 📈 Monitoring & Alerts

### Telegram Notifications

**Market Detection:**
```
🔔 WEEKEND MARKET DETECTED
✅ Live ticks: age 2.3s
📊 NIFTY: 21,850.50
⚡ Starting trading service...
```

**Feed Staleness:**
```
⚠️ FEED STALE WARNING
Last tick: 45 seconds ago
WebSocket: Connected
Action: Checking reconnection...
```

**Service Status:**
```
✅ SERVICE STARTED
Time: 09:00:15
Reason: Weekend market active
Status: Monitoring positions
```

---

## 🎯 Summary: Why This Approach Works

### Multi-Layer Defense
1. **Live ticks** = Real-time ground truth
2. **Quote age** = Static fallback
3. **Order activity** = Historical confirmation
4. **Broker status** = Service health

### Advantages
- ✅ **Accurate:** False positives eliminated by tick monitoring
- ✅ **Fast:** Detects market opening within seconds
- ✅ **Reliable:** Multiple fallbacks ensure robustness
- ✅ **Automated:** No manual intervention required
- ✅ **Real-time UI:** Users see live updates without clicking

### Trade-offs
- 🔌 Requires active WebSocket connection
- 📊 Depends on broker feed reliability
- ⏱️ 1-2s refresh = higher API calls (acceptable trade-off for real-time data)

---

**Result:** A comprehensive, real-time market detection system that automatically starts trading on weekends if sessions are active, with live dashboard updates requiring zero manual refreshes.
