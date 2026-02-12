# Comprehensive Strategy System Improvement Plan

## Executive Summary
The strategy system needs end-to-end improvements from form creation through execution. Current issues:

1. **Form Complexity**: Strategy form is overly complex with leg builders (not used in execution)
2. **Field Mismatch**: Form fields don't map to `UniversalStrategyConfig` requirements
3. **No SQLite Selection**: No mechanism to auto-select .sqlite files by symbol/expiry
4. **Parameter Validation**: Minimal validation of required fields before save
5. **Incomplete JSON Editor**: No direct JSON editing capability
6. **Missing Logger**: No dedicated strategy execution logger window
7. **Button Integration**: Control buttons may not have all handlers implemented

---

## Part 1: UniversalStrategyConfig Field Mapping

### Current Required Fields (from build_universal_config):
```python
UniversalStrategyConfig(
    strategy_name,          # String - name of strategy
    strategy_version,       # String - version number
    exchange,              # String - NFO, BFO, MCX
    symbol,                # String - NIFTY, BANKNIFTY, etc
    instrument_type,       # String - OPTIDX, MCX, etc
    entry_time,            # datetime.time - HH:MM:SS
    exit_time,             # datetime.time - HH:MM:SS
    order_type,            # String - Market, Limit, SL-Market
    product,               # String - MIS, NRML
    lot_qty,               # Integer - quantity per order
    params,                # Dict - strategy parameters
    poll_interval,         # Float - polling interval (default 2.0)
    cooldown_seconds,      # Integer - cooldown between orders
)
```

### Form Fields to Replace/Fix:
Current form has these but in wrong structure:
- `sName` → `strategy_name` ✓
- `sSegment` (NFO/BFO/MCX) → `exchange` ✓
- `sUnderlying` + Symbol → need combined symbol field
- Missing: `instrument_type` (should auto-detect from exchange)
- `schEntry` → `entry_time` ✓
- `schExit` → `exit_time` ✓
- `sOrderType` → `order_type` ✓
- `sProduct`  (MIS/NRML) → `product` ✓
- `sLots` → `lot_qty` ✓
- Missing: `strategy_version` (default v1)
- Missing: `params` JSON field

---

## Part 2: Form Simplification

### New Tab Structure:
```html
Tab 1: Quick Config
  - Identity section (name, version, type)
  - Market section (exchange, symbol, instrument_type)
  - Timing section (entry_time, exit_time)  
  - Execution section (order_type, product, lot_qty)
  - Parameters section (JSON editor for params)
  - Save button with validation feedback

Tab 2: JSON Editor
  - Full JSON text area for direct editing
  - Syntax validation
  - Load/Save buttons
  - Live validation against schema

Tab 3: Validation
  - Field validation status (required vs optional)
  - SQLite file availability
  - UniversalStrategyConfig build test
  - Validation report with errors and warnings
```

### Remove:
- Complex leg builders (entry/adjustment/exit legs)
- Combined condition builders (not used in UniversalStrategyConfig)
- Advanced parameter triggers (not currently supported)
- Schedule section (only entry_time/exit_time needed)
- Risk management section (complex, needs own dialog)

---

## Part 3: SQLite File Auto-Selection

### Implementation:
1. Get symbol from form (e.g., "NIFTY")
2. List available .sqlite files in trading database folder
3. Auto-detect correct file by symbol and optionally expiry
4. Show selected file path in form with change option

### API Endpoint Needed:
```json
GET /dashboard/api/sqlite-files
Query: ?symbol=NIFTY&expiry=weekly

Response:
{
  "symbol": "NIFTY",
  "available_files": [
    {"path": "NIFTY_weekly.sqlite", "size": 5242880, "records": 2500},
    {"path": "NIFTY_monthly.sqlite", "size": 1048576, "records": 800}
  ],
  "selected": "NIFTY_weekly.sqlite"
}
```

---

## Part 4: Parameter Validation

### HTML Form Validation:
```javascript
// Check all required fields before save
const validationRules = {
  strategy_name: { required: true, type: 'string', minLength: 3 },
  exchange: { required: true, enum: ['NFO','BFO','MCX'] },
  symbol: { required: true, pattern: /^[A-Z0-9]+$/ },
  instrument_type: { required: true, enum: ['OPTIDX','MCX'] },
  entry_time: { required: true, type: 'time' },
  exit_time: { required: true, type: 'time' },
  order_type: { required: true, enum: ['MKT','LMT','SL','SLM'] },
  product: { required: true, enum: ['MIS','NRML'] },
  lot_qty: { required: true, type: 'number', min: 1 },
}

// Build UniversalStrategyConfig to test it works
try {
  const config = buildUniversalConfig(payload);
  // If successful, validation passes
} catch(e) {
  // Show specific error
  validationStatus.error = e.message;
}
```

---

## Part 5: Strategy Logger Window

### New Component:
```html
<div id="strategyLogger" class="strategy-logger">
  <div class="logger-header">
    <div class="logger-title">📋 Strategy Execution Log</div>
    <div class="logger-controls">
      <select id="logFilter" onchange="filterLogs(this.value)">
        <option value="">-- All --</option>
        <option value="INFO">INFO</option>
        <option value="WARNING">WARNING</option>
        <option value="ERROR">ERROR</option>
        <option value="DEBUG">DEBUG</option>
      </select>
      <button onclick="clearLogs()">Clear</button>
      <button onclick="downloadLogs()">Download</button>
    </div>
  </div>
  <div class="logger-body" id="loggerBody">
    <div class="log-empty">No logs yet</div>
  </div>
</div>
```

### Features:
- Real-time log streaming (WebSocket or polling)
- Timestamped entries with log levels
- Syntax highlighting for different levels
- Filter by strategy name and log level
- Auto-scroll to latest
- Clear and download buttons
- Persistent across strategy changes

---

## Part 6: API Endpoints Needed

### 1. Get SQLite Files (New)
```
GET /dashboard/api/sqlite-files?symbol=NIFTY&expiry=weekly

Response:
{
  "symbol": "NIFTY",
  "available_files": [
    {"path": "data/NIFTY.sqlite", "size": 5242880, "modified": "2026-02-11"}
  ],
  "selected": "data/NIFTY.sqlite"
}
```

### 2. Validate Strategy Config (New)
```
POST /dashboard/api/validate-strategy-config

Request:
{
  "strategy_name": "NIFTY Weekly",
  "exchange": "NFO",
  "symbol": "NIFTY",
  ...all UniversalStrategyConfig fields...
}

Response:
{
  "valid": true,
  "errors": [],
  "warnings": ["lot_qty: using default"],
  "config_test": {
    "created": true,
    "strategy_name": "NIFTY_WEEKLY",
    "fields_count": 10
  }
}
```

### 3. Build Strategy Config (New)
```
POST /dashboard/api/build-strategy-config

Request:
{
  "strategy_name": "NIFTY Weekly",
  ...all UniversalStrategyConfig fields...
}

Response:
{
  "success": true,
  "config": {
    "strategy_name": "NIFTY_WEEKLY",
    "strategy_version": "1.0",
    ...
  },
  "base64_json": "eyJzdHJhdGVneV9uYW1lIjogIk5JRlRZX1dlZWtseSJ9"
}
```

### 4. Get Strategy Logs (New)
```
GET /dashboard/api/strategy-logs?strategy_name=NIFTY_WEEKLY&limit=100&level=INFO

Response:
{
  "strategy_name": "NIFTY_WEEKLY",
  "logs": [
    {
      "timestamp": "2026-02-11T09:20:00Z",
      "level": "INFO",
      "message": "Strategy started",
      "source": "StrategyRunner"
    }
  ]
}
```

---

## Part 7: Implementation Order

### Phase 1: Core Form Simplification (Day 1)
- [ ] Replace builder modal tabs with Quick Config, JSON Editor, Validation
- [ ] Remove complex leg builders
- [ ] Create simple UniversalStrategyConfig field form
- [ ] Add symbol field with dropdown
- [ ] Add entry_time and exit_time inputs
- [ ] Add params JSON editor

### Phase 2: Validation & API Integration (Day 1-2)
- [ ] Add client-side field validation
- [ ] Create /dashboard/api/validate-strategy-config endpoint
- [ ] Add validation tab showing real-time feedback
- [ ] Integrate error messages in form

### Phase 3: SQLite Selection (Day 2)
- [ ] Create /dashboard/api/sqlite-files endpoint
- [ ] Add symbol change listener to fetch available files
- [ ] Show file selection dropdown in form
- [ ] Store selected file path in strategy config

### Phase 4: JSON Editor (Day 2)
- [ ] Create JSON editor section with full text area
- [ ] Add JSON validation (parse check)
- [ ] Show pretty-print toggle
- [ ] Add load/save buttons

### Phase 5: Strategy Logger (Day 3)
- [ ] Create logger window UI at bottom of page
- [ ] Implement /dashboard/api/strategy-logs endpoint
- [ ] Add real-time log polling (every 2 seconds)
- [ ] Add filter and clear buttons
- [ ] Style with consistent theme

### Phase 6: Button Integration (Day 3)
- [ ] Verify Start button calls /dashboard/intent/strategy with ENTRY
- [ ] Verify Pause button calls with ADJUST
- [ ] Verify Stop button calls with EXIT
- [ ] Add real-time status updates
- [ ] Show running indicator during execution

---

## Part 8: Code Examples

### Simplified Form Structure:
```html
<div class="bsec active" id="sec-quick">
  <div class="form-row cols-2">
    <div class="f-group">
      <label class="f-label">Strategy Name *</label>
      <input class="f-input" id="quickName" placeholder="e.g. NIFTY Weekly">
    </div>
    <div class="f-group">
      <label class="f-label">Version</label>
      <input class="f-input" id="quickVersion" placeholder="1.0" value="1.0">
    </div>
  </div>

  <div class="form-row cols-3">
    <div class="f-group">
      <label class="f-label">Exchange *</label>
      <select class="f-select" id="quickExchange" onchange="onExchangeChange()">
        <option value="">-- Select --</option>
        <option value="NFO">NFO (NSE F&O)</option>
        <option value="BFO">BFO (BSE F&O)</option>
        <option value="MCX">MCX</option>
      </select>
    </div>
    <div class="f-group">
      <label class="f-label">Symbol *</label>
      <select class="f-select" id="quickSymbol" onchange="onSymbolChange()">
        <option value="">-- Select --</option>
        <option value="NIFTY">NIFTY</option>
        <option value="BANKNIFTY">BANKNIFTY</option>
        <option value="FINNIFTY">FINNIFTY</option>
      </select>
    </div>
    <div class="f-group">
      <label class="f-label">Instrument Type *</label>
      <select class="f-select" id="quickInstrumentType">
        <option value="">-- Auto-detect --</option>
        <option value="OPTIDX">OPTIDX</option>
        <option value="MCX">MCX</option>
      </select>
    </div>
  </div>

  <div class="form-row cols-2">
    <div class="f-group">
      <label class="f-label">Entry Time *</label>
      <input class="f-input" id="quickEntryTime" type="time" value="09:20">
    </div>
    <div class="f-group">
      <label class="f-label">Exit Time *</label>
      <input class="f-input" id="quickExitTime" type="time" value="15:15">
    </div>
  </div>

  <div class="form-row cols-3">
    <div class="f-group">
      <label class="f-label">Order Type *</label>
      <select class="f-select" id="quickOrderType">
        <option value="MKT">Market</option>
        <option value="LMT">Limit</option>
        <option value="SLM">SL-Market</option>
      </select>
    </div>
    <div class="f-group">
      <label class="f-label">Product *</label>
      <select class="f-select" id="quickProduct">
        <option value="NRML">NRML (Overnight)</option>
        <option value="MIS">MIS (Intraday)</option>
      </select>
    </div>
    <div class="f-group">
      <label class="f-label">Lot Quantity *</label>
      <input class="f-input" id="quickLotQty" type="number" value="1" min="1">
    </div>
  </div>

  <div class="form-row cols-1">
    <div class="f-group">
      <label class="f-label">Strategy Parameters (JSON)</label>
      <textarea class="f-textarea" id="quickParams" placeholder='{"some_param": "value"}'>{}</textarea>
    </div>
  </div>

  <div class="f-group">
    <label class="f-label">SQLite Database File</label>
    <div style="display:flex;gap:8px;">
      <select class="f-select" id="quickSqliteFile" style="flex:1;">
        <option value="">-- Loading --</option>
      </select>
      <button onclick="refreshSqliteFiles()" style="padding:8px 16px;background:var(--border);border:none;border-radius:6px;cursor:pointer;">↻ Refresh</button>
    </div>
  </div>
</div>
```

### JSON Editor Tab:
```html
<div class="bsec" id="sec-json">
  <div class="form-row cols-1">
    <div class="f-group">
      <label class="f-label">Strategy JSON Configuration</label>
      <textarea class="f-textarea" id="jsonEditor" style="min-height:300px;font-family:var(--font-mono);font-size:11px;">
{
  "strategy_name": "NIFTY Weekly",
  "strategy_version": "1.0",
  "exchange": "NFO",
  "symbol": "NIFTY",
  "instrument_type": "OPTIDX"
}
      </textarea>
    </div>
  </div>
  <div style="display:flex;gap:8px;">
    <button onclick="formatJSON()" style="padding:8px 16px;">Format JSON</button>
    <button onclick="validateJSON()" style="padding:8px 16px;">Validate</button>
    <button onclick="loadJSONFromFile()" style="padding:8px 16px;">Load File</button>
    <div id="jsonStatus" style="margin-left:auto;padding:8px 16px;color:var(--muted);font-size:11px;"></div>
  </div>
</div>
```

### Validation Tab:
```html
<div class="bsec" id="sec-validation">
  <div class="sec-divider">Field Validation</div>
  <div id="validationReport" style="display:flex;flex-direction:column;gap:8px;"></div>
  
  <div class="sec-divider">UniversalStrategyConfig Build Test</div>
  <button onclick="runBuildTest()" style="padding:8px 16px;margin-bottom:16px;">Test Build Configuration</button>
  <div id="buildTestResult" style="background:var(--panel-2);border:1px solid var(--border);border-radius:6px;padding:12px;font-family:var(--font-mono);font-size:11px;max-height:200px;overflow-y:auto;display:none;"></div>
</div>
```

---

## Part 9: Testing Checklist

- [ ] Strategy created with minimal required fields
- [ ] All required fields validated
- [ ] UniversalStrategyConfig builds successfully
- [ ] SQLite file auto-selection works
- [ ] Strategy saved to /saved_configs/
- [ ] Strategy loads correctly from saved config
- [ ] Start button executes ENTRY intent
- [ ] Logger shows real-time logs
- [ ] Stop button removes strategy
- [ ] Pause button works (ADJUST intent)
- [ ] Validation tab shows correct status
- [ ] JSON editor allows direct editing
- [ ] Error messages are helpful and specific

---

## Part 10: Priority

**Critical (Blocking execution):**
1. Simplify form to map to UniversalStrategyConfig
2. Add all required fields properly mapped
3. Fix save/load to work with new structure
4. Ensure existing buttons work

**Important (Production quality):**
1. Add validation tab with real feedback
2. Implement SQLite file auto-selection
3. Add JSON editor for power users
4. Create strategy logger window

**Nice-to-have:**
1. Advanced schedule section
2. Risk management templates
3. Import/export capabilities

