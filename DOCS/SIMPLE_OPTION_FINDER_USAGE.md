# Simple Option Finder - Usage Guide

**One function to rule them all!**

File: `shoonya_platform/strategies/find_option.py`

## Quick Examples

### 1. Find Any Option by ANY Field

```python
from shoonya_platform.strategies.find_option import find_option

# Find CE option with delta ≈ 0.3
option = find_option(
    field="delta", 
    value=0.3, 
    option_type="CE",
    symbol="NIFTY"
)
print(option['symbol'])  # NIFTY_25FEB_23700_CE

# Find option at strike 23700
option = find_option(field="strike", value=23700, symbol="NIFTY")

# Find option with LTP ≈ 200
option = find_option(field="ltp", value=200, option_type="CE", symbol="NIFTY")

# Find option with OI ≈ 5,000,000
option = find_option(field="oi", value=5000000, symbol="NIFTY")

# Find option with volume ≈ 100,000
option = find_option(field="volume", value=100000, symbol="NIFTY")

# Find option with implied volatility ≈ 15
option = find_option(field="iv", value=15, symbol="NIFTY")
```

### 2. Find Multiple Options (Sorted by Distance)

```python
from shoonya_platform.strategies.find_option import find_options

# Get top 5 options closest to delta 0.3
options = find_options(
    field="delta", 
    value=0.3, 
    limit=5,
    symbol="NIFTY"
)

for opt in options:
    print(f"{opt['symbol']}: delta={opt['delta']}")
```

### 3. In Strategy Code

```python
from shoonya_platform.strategies.find_option import find_option

class DeltaNeutralShortStrangleStrategy:
    def on_entry(self):
        # Find CE with delta ≈ 0.3
        ce = find_option(
            field="delta",
            value=0.3,
            option_type="CE",
            symbol=self.symbol
        )
        
        # Find PE with delta ≈ -0.3
        pe = find_option(
            field="delta",
            value=0.3,  # Use absolute value
            option_type="PE",
            symbol=self.symbol,
            use_absolute=True
        )
        
        if ce and pe:
            self.enter_strangle(ce, pe)
```

### 4. In Tests

```python
from shoonya_platform.strategies.find_option import find_option

def test_delta_selection():
    # Find CE option with delta 0.3
    option = find_option(field="delta", value=0.3, option_type="CE")
    
    assert option is not None
    assert float(option['delta']) <= 0.35
    assert float(option['delta']) >= 0.25
```

### 5. In Web Pages (JSON API)

**Frontend sends JSON:**
```javascript
// place_order.html - Advanced Leg Selector
const criteria = {
    field: "delta",
    value: 0.3,
    symbol: "NIFTY",
    option_type: "CE"
};

fetch("/api/find-option", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(criteria)
})
.then(res => res.json())
.then(data => {
    if (data.success) {
        console.log(`Selected: ${data.option.symbol}`);
        console.log(`Delta: ${data.option.delta}`);
    }
});
```

**Backend router.py:**
```python
from shoonya_platform.strategies.find_option import find_option_json

@app.post("/api/find-option")
def find_option_endpoint(request: dict):
    return find_option_json(request)
```

### 6. Multiple Criteria

```python
from shoonya_platform.strategies.find_option import find_option_by_multiple_criteria

# Find option close to: delta=0.3 AND strike=23700 AND ltp=200
option = find_option_by_multiple_criteria(
    criteria={
        "delta": 0.3,
        "strike": 23700,
        "ltp": 200
    },
    weighting={
        "delta": 2.0,      # Weight delta more heavily
        "strike": 1.0,
        "ltp": 0.5
    },
    symbol="NIFTY"
)
```

### 7. Get Exact Option Details

```python
from shoonya_platform.strategies.find_option import get_option_details

# By symbol
option = get_option_details(symbol="NIFTY_25FEB_23700_CE")

# By token
option = get_option_details(token=12345)
```

---

## Available Fields to Search By

```
Greeks:
- delta
- gamma
- theta
- vega
- iv (implied volatility)

Price/Strike:
- strike
- ltp (last traded price)
- bid
- ask
- open
- high
- low
- close

Volume/Open Interest:
- oi (open interest)
- volume
- bid_qty
- ask_qty

Greeks Specific:
- delta_pe
- delta_ce
- gamma_pe
- gamma_ce
- theta_pe
- theta_ce
- vega_pe
- vega_ce

And ANY other field in the database!
```

---

## Return Value

Complete option details:

```python
{
    'symbol': 'NIFTY_25FEB_23700_CE',
    'token': 12345,
    'strike': 23700,
    'option_type': 'CE',
    'exchange': 'NFO',
    'expiry': '2025-02-25',
    'delta': 0.30,
    'gamma': 0.005,
    'theta': -0.25,
    'vega': 0.15,
    'iv': 18.5,
    'ltp': 250.50,
    'bid': 250.00,
    'ask': 251.00,
    'oi': 5000000,
    'volume': 150000,
    ... all other fields from database
}
```

---

## Usage in Different Parts of Codebase

### Strategy Runner
```python
# strategies/strategy_runner.py
from shoonya_platform.strategies.find_option import find_option

def execute_strategy(strategy, config):
    # Strategy can call find_option internally
    option = find_option(field="delta", value=config['target_delta'])
    strategy.execute(option)
```

### Web Pages (Advanced Leg)
```html
<!-- dashboard/web/place_order.html -->
<script>
function selectAdvancedLeg() {
    const criteria = {
        field: document.getElementById('field').value,
        value: parseFloat(document.getElementById('value').value),
        symbol: document.getElementById('symbol').value
    };
    
    fetch('/api/find-option', {
        method: 'POST',
        body: JSON.stringify(criteria)
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            populateLegDetails(data.option);
        }
    });
}
</script>
```

### Option Chain Dashboard
```python
# dashboard/routes/option_chain.py
from shoonya_platform.strategies.find_option import find_options

@app.get("/api/option-chain/delta-range")
def get_delta_range(symbol: str, delta: float, tolerance: float = 0.05):
    # Get all options within delta range
    options = find_options(
        field="delta",
        value=delta,
        symbol=symbol,
        limit=100
    )
    return options
```

### Strategy Pages
```python
# dashboard/routes/strategy.py
from shoonya_platform.strategies.find_option import find_option

@app.post("/api/strategy/preview-entry")
def preview_entry(strategy_config: dict):
    # Show user what options would be selected
    ce = find_option(
        field="delta",
        value=strategy_config['target_delta'],
        option_type="CE",
        symbol=strategy_config['symbol']
    )
    
    pe = find_option(
        field="delta",
        value=strategy_config['target_delta'],
        option_type="PE",
        symbol=strategy_config['symbol'],
        use_absolute=True
    )
    
    return {
        'ce_option': ce,
        'pe_option': pe
    }
```

---

## That's It!

**One simple function.** No framework. No complexity.

Just:
- Pass field name (any field!)
- Pass target value
- Get back full option details
- Use anywhere (strategy, test, web page, route, etc.)

Works with:
- ✅ Strategy runner
- ✅ Tests
- ✅ Web pages (JSON API)
- ✅ Advanced leg selector
- ✅ Option chain dashboard
- ✅ Strategy preview pages
- ✅ Any other code needing option lookup

**DB Support:**
- SQLite (option_chain table)
- Auto-detects database location
- Pass db_path if custom location

**That's all you need. Simple as that.**
