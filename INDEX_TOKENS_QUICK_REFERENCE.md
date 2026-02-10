# Index Tokens Quick Reference

## What's New?

Your trading dashboard now displays **live index prices** (NIFTY, BANKNIFTY, SENSEX, INDIAVIX) in a ticker below the main controls. Prices update automatically every 2 seconds during market hours.

## For Traders

### Dashboard Features

**Index Ticker** (Below Controls)
- Shows major indices with live LTP and % change
- Color-coded: Green ▲ (up), Red ▼ (down)
- Auto-hides when no data available
- Fully responsive on mobile

**Supported Indices:**
| Symbol | Exchange | Use Case |
|--------|----------|----------|
| **NIFTY** | NSE | Equity index (primary) |
| **BANKNIFTY** | NSE | Banking sector |
| **FINNIFTY** | NSE | Financial services |
| **SENSEX** | BSE | Alternate equity index |
| **INDIAVIX** | NSE | Market volatility |
| **BANKEX** | BSE | Alternate banking index |

### How It Works

1. **Automatic Subscription** - Index tokens subscribe automatically when you start the service
2. **Live Updates** - Dashboard fetches prices every 2 seconds
3. **Integration** - Works alongside option chain without any interference

## For Developers

### Core Module

```python
from shoonya_platform.market_data.feeds import index_tokens_subscriber

# Get live prices for major indices
data = index_tokens_subscriber.get_index_prices()
# Returns: {'NIFTY': {'ltp': 25912.5, 'pc': 0.25, ...}, ...}

# Get single index
nifty = index_tokens_subscriber.get_index_price('NIFTY')
print(f"NIFTY @ {nifty['ltp']} ({nifty['pc']}% change)")

# Manual subscription (if needed)
count, symbols = index_tokens_subscriber.subscribe_index_tokens(api_client)
print(f"Subscribed to {count} indices: {symbols}")

# Get metadata
meta = index_tokens_subscriber.get_index_metadata('NIFTY')
# {symbol: 'NIFTY', exchange: 'NSE', token: '26000', name: 'Nifty 50'}
```

### API Endpoints

**Get Current Prices**
```bash
curl http://localhost:5000/dashboard/index-tokens/prices
```

Response:
```json
{
  "subscribed": ["NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX"],
  "indices": {
    "NIFTY": {
      "ltp": 25912.50,
      "pc": 0.25,
      "v": 1234567,
      "o": 25900,
      "h": 25950,
      "l": 25850,
      "c": 25912
    }
  },
  "timestamp": 1707583845.123
}
```

**List Available Indices**
```bash
curl http://localhost:5000/dashboard/index-tokens/list
```

Response:
```json
{
  "all": {
    "NIFTY": {
      "symbol": "NIFTY",
      "exchange": "NSE",
      "token": "26000",
      "name": "Nifty 50"
    }
  },
  "subscribed": ["NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX"],
  "major": ["NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX"]
}
```

### Architecture

```
Live Feed (WebSocket)
    ↓ [Tick Data]
Tick Data Store (shared, thread-safe)
    ↓ [Pull on demand]
index_tokens_subscriber
    ↓ [HTTP REST]
Dashboard API
    ↓ [Browser fetch]
Index Ticker HTML/JS
    ↓ [Display]
User Dashboard
```

**Key Design:**
- **Pull-based** (not push) - no callbacks, no queues
- **Shared storage** - uses same `tick_data_store` as option chain
- **Thread-safe** - protected by existing live_feed locks
- **Graceful degradation** - works even if subscription partially fails
- **Zero overhead** - adds ~1 API call per 2 seconds. Negligible impact.

## Configuration

### Add/Remove Indices from Ticker Display

Edit dashboard HTML (line ~810):
```javascript
const order = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX', 'INDIAVIX', 'BANKEX'];
// Reorder, add, or remove as needed
```

### Change Refresh Interval

Edit dashboard HTML (line ~740):
```javascript
indexTokensTimer = setInterval(() => {
    loadIndexTokens();
}, 2000);  // Change 2000 (ms) to desired value
```

### Change Startup Behavior

Edit trading_bot.py (line ~283):
```python
# Make index subscription mandatory (fail if unavailable)
count, symbols = index_tokens_subscriber.subscribe_index_tokens(self.api_proxy)
if count == 0:
    raise RuntimeError("Failed to subscribe to index tokens")
```

## Troubleshooting

### Ticker Not Showing

**Problem:** Index ticker appears empty or hidden

**Solutions:**
1. Check browser console (F12) for errors
2. Verify API endpoint working: `curl http://localhost:5000/dashboard/index-tokens/prices`
3. Ensure live feed is connected: Check logs for "Live feed started"
4. Try hard refresh: Ctrl+F5 (Windows) or Cmd+Shift+R (Mac)

### Stale Prices

**Problem:** Index prices not updating

**Solutions:**
1. Check if market is open (9:15 AM - 3:30 PM IST on weekdays)
2. Verify live feed health: Check option chain updating (should work if indices subscribed)
3. Check network tab (F12) - API should return 200 with data
4. Restart service if stuck

### Missing Indices

**Problem:** Expected index not showing

**Possible Causes:**
- Index not yet subscribed (subscription happens once on startup)
- API returning incomplete data (wait a few ticks, data populates gradually)
- Custom filter in `order` array (edit if intentionally removed)

## Advanced Usage

### Strategy Integration

```python
def market_regime_detector():
    """Detect market regime from index volatility."""
    try:
        vix = index_tokens_subscriber.get_index_price('INDIAVIX')
        if vix['ltp'] > 25:  # High volatility
            return "VOLATILE"
        else:
            return "CALM"
    except:
        return "UNKNOWN"

def adaptive_position_sizing():
    """Size positions based on index breadth."""
    data = index_tokens_subscriber.get_index_prices()
    
    # Count up/down indices
    gainers = sum(1 for d in data.values() if d and d.get('pc', 0) > 0)
    losers = sum(1 for d in data.values() if d and d.get('pc', 0) < 0)
    
    breadth = gainers / (gainers + losers) if (gainers + losers) > 0 else 0.5
    
    if breadth > 0.7:  # Strong uptrend
        position_size = 1.5  # Increase size
    elif breadth < 0.3:  # Strong downtrend
        position_size = 0.75  # Reduce size
    else:
        position_size = 1.0  # Normal
    
    return position_size
```

### Custom Dashboard Widget

```javascript
async function createIndexWidget() {
    const res = await fetch('/dashboard/index-tokens/prices');
    const data = await res.json();
    
    const nifty = data.indices.NIFTY;
    const status = nifty.pc > 0 ? '📈' : '📉';
    
    return `
        <div class="custom-widget">
            ${status} NIFTY @ ₹${nifty.ltp} (${nifty.pc}%)
        </div>
    `;
}
```

## Support

For issues or questions:
1. Check [INDEX_TOKENS_IMPLEMENTATION_GUIDE.md](./INDEX_TOKENS_IMPLEMENTATION_GUIDE.md) for detailed technical docs
2. Review console logs: Check browser console (F12) and server logs
3. Test API directly: Use curl commands above to isolate issues
4. Check GitHub commit history: Reference commit 1a3e9f9 for changes

---

**Last Updated:** February 10, 2026  
**Status:** Production Ready ✅
