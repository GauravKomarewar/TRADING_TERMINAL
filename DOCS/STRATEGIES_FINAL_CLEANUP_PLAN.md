# STRATEGIES FOLDER - FINAL COMPREHENSIVE AUDIT & CLEANUP PLAN
**Date:** 2026-02-12  
**Status:** PRE-PRODUCTION CLEANUP  
**Focus:** Zero confusion, complete alignment, production-ready

---

## 📋 EXECUTIVE ASSESSMENT

### ✅ **Current Status: MOSTLY CLEAN**
- ✅ Core strategies folder is well-organized
- ✅ find_option.py is clean and centralized
- ✅ JSON config schema exists
- ✅ Strategy runner can load JSON

### ⚠️ **ISSUES FOUND (5 Major Gaps)**

| # | Issue | Severity | Location | Impact |
|---|-------|----------|----------|--------|
| 1 | No strategy validation service | HIGH | N/A | User can save invalid JSON → fails at runtime |
| 2 | No unified strategy API | HIGH | api/dashboard/api/ | No centralized strategy management |
| 3 | Web UI incomplete | HIGH | strategy.html, strategy_new.html | Users can't create/validate strategies |
| 4 | No strategy logging system | MEDIUM | strategies/ | No visibility into what's happening |
| 5 | Legacy HTML files confusing | MEDIUM | test_strategy_form.html | Users don't know which UI to use |

---

## 🗂️ FOLDER STRUCTURE AUDIT

### Current Strategies Folder
```
shoonya_platform/strategies/
├── ✅ find_option.py                    CLEAN - Core utility
├── ✅ market_adapter_factory.py         CLEAN - Adapter selection
├── ✅ strategy_runner.py                CLEAN - Runner with JSON loading
├── ⚠️ README.md                         OUTDATED - Needs update
├── saved_configs/
│   ├── ✅ STRATEGY_CONFIG_SCHEMA.json   CLEAN - JSON schema
│   ├── ✅ NIFTY_DNSS_TEMPLATE.json      CLEAN - Template
│   └── (user .json files go here)
├── database_market/
│   ├── ✅ adapter.py                    CLEAN - Uses find_option.py
│   └── __init__.py
├── live_feed_market/
│   ├── ✅ adapter.py                    CLEAN - Uses find_option.py
│   └── __init__.py
├── delta_neutral/
│   ├── ✅ dnss.py                       CLEAN - Strategy implementation
│   ├── adapter.py
│   └── __init__.py
├── engine/
│   ├── ✅ engine.py                     CLEAN - Execution (frozen)
│   ├── engine_no_recovery.py
│   └── __init__.py
├── universal_settings/
│   └── (utilities)
└── __init__.py
```

**Assessment:** ✅ **VERY CLEAN - No legacy files to remove**

---

## 🌐 WEB UI AUDIT

### Files Found
```
shoonya_platform/api/dashboard/web/
├── strategy.html              2466 lines - MAIN STRATEGY PAGE
├── strategy_new.html          3086 lines - DUPLICATE? Or NEW version?
└── (other pages)

Root directory:
└── test_strategy_form.html    Test file - SHOULD BE DELETED
```

### Issues

**1. Dual Strategy Files Confusion**
- Two files: `strategy.html` and `strategy_new.html`
- Users don't know which one to use
- Possible duplication vs. evolution

**2. No Validation System**
- HTML forms don't validate JSON schema
- Missing config validation before saving
- No smart parameter checking

**3. No Integration with Runner**
- Web form doesn't call strategy_runner.load_strategies_from_json()
- No way to see loaded strategies from UI
- No start/stop button functionality

**4. No Logging Display**
- Strategy logs not shown in UI
- No real-time execution status
- No error messages from failed strategies

### Legacy File
```
test_strategy_form.html - TEST FILE IN ROOT
- Location: Root directory (confusing)
- Should: DELETE or move to tests/
- Risk: User might reference this in docs
```

---

## API AUDIT

### Current Endpoints
```
POST /dashboard/system/force-exit        STRATEGY EXIT (exists)
POST /dashboard/orders/cancel/system    ORDER CANCEL (exists)
```

### Missing Endpoints
```
❌ GET  /dashboard/strategy/list         List all strategies from saved_configs/
❌ GET  /dashboard/strategy/{name}       Get specific strategy config
❌ POST /dashboard/strategy/validate     Validate JSON before saving
❌ POST /dashboard/strategy/create       Create new strategy
❌ PUT  /dashboard/strategy/{name}       Update existing strategy
❌ DELETE /dashboard/strategy/{name}     Delete strategy
❌ POST /dashboard/strategy/{name}/start Start strategy
❌ POST /dashboard/strategy/{name}/stop  Stop strategy
❌ GET  /dashboard/strategy/{name}/logs  Get strategy execution logs
❌ GET  /dashboard/runner/status         Get runner status and metrics
❌ GET  /dashboard/runner/all-logs       Stream all strategy logs
```

**Impact:** Without these endpoints, web UI can't function properly

---

## VALIDATION SYSTEM AUDIT

### Current Validation
- ✅ JSON Schema exists (STRATEGY_CONFIG_SCHEMA.json)
- ✅ Runner validates config before registration
- ❌ No validation service exposed as API
- ❌ No validation in web form (client-side)
- ❌ No smart parameter checking

### What's Needed

**Validation Service Should:**
1. ✅ Validate against JSON schema
2. ✅ Check database exists (db_path)
3. ✅ Check time format (HH:MM)
4. ✅ Check numbers are in valid ranges
5. ✅ Check all required fields present
6. ✅ Check for all parameter combinations
7. ✅ Return clear error messages to user
8. ✅ Reject strategy with reason

---

## LOGGING SYSTEM AUDIT

### Current Status
```
❌ No centralized strategy logging
❌ No log streaming to UI
❌ No per-strategy log files
❌ No log levels configuration
```

### What's Needed
```
✅ Per-strategy logger created at startup
✅ Logs written to: logs/strategies/{strategy_name}.log
✅ Logs also captured in memory for UI streaming
✅ Real-time log feed to browser (WebSocket or polling)
✅ Log levels: DEBUG, INFO, WARNING, ERROR
✅ All runner metrics also logged
```

---

## START/STOP BUTTON FUNCTIONALITY AUDIT

### Current Status
```
⚠️ strategy_runner.start() exists
⚠️ strategy_runner.stop() exists
❌ No API endpoint to call start/stop
❌ No UI button that calls start/stop
❌ No runner lifecycle management
```

### What's Needed
```
✅ API: POST /dashboard/runner/start
✅ API: POST /dashboard/runner/stop
✅ API: GET  /dashboard/runner/status
✅ UI: Buttons that call these APIs
✅ UI: Real-time status display
✅ Backend: Maintain single runner instance
```

---

## COMPREHENSIVE SOLUTION PLAN

### 🎯 Phase 1: Clean & Standardize (Immediate)

**1.1 Delete Legacy Files**
```
DELETE: test_strategy_form.html (in root)
REASON: Confusing, should be in tests/ if needed
```

**1.2 Consolidate Strategy HTML**
```
ACTION: Decide between strategy.html and strategy_new.html
OPTION A: Keep strategy_new.html (newer?), delete strategy.html
OPTION B: Keep strategy.html, delete strategy_new.html
DECISION: ❓ Need your input - which is current/working?
```

**1.3 Update README**
```
FILE: shoonya_platform/strategies/README.md
UPDATE: 
  - Point to strategy.html/strategy_new.html
  - Explain JSON schema location
  - Explain template usage
  - Link to PRODUCTION_EXECUTION_GUIDE.md
```

**1.4 Create Strategy Configuration Service**
```
FILE: shoonya_platform/api/dashboard/services/strategy_config_service.py
PURPOSE:
  - Validate JSON against schema
  - Check database path exists
  - Validate all parameters
  - Return detailed error messages
```

**1.5 Create Strategy Logger System**
```
FILE: shoonya_platform/strategies/strategy_logger.py
PURPOSE:
  - Create per-strategy loggers
  - Maintain shared logger for UI access
  - Support real-time log streaming
```

---

### 🎯 Phase 2: Build API Layer (API Endpoints)

**2.1 Strategy API Endpoints**
```
File: shoonya_platform/api/dashboard/api/router.py

ADD ENDPOINTS:
  # List all strategies from saved_configs/
  GET /dashboard/strategy/list
  
  # Get specific strategy
  GET /dashboard/strategy/{name}
  
  # Validate strategy JSON (before save)
  POST /dashboard/strategy/validate
  Body: { "config": {...}, "name": "..." }
  
  # Create new strategy
  POST /dashboard/strategy/create
  
  # Update existing strategy
  PUT /dashboard/strategy/{name}
  
  # Delete strategy
  DELETE /dashboard/strategy/{name}
```

**2.2 Strategy Control Endpoints**
```
File: shoonya_platform/api/dashboard/api/router.py

ADD ENDPOINTS:
  # Start runner
  POST /dashboard/runner/start
  
  # Stop runner
  POST /dashboard/runner/stop
  
  # Get runner status
  GET /dashboard/runner/status
  
  # Get all runner metrics
  GET /dashboard/runner/metrics
```

**2.3 Strategy Logging Endpoints**
```
File: shoonya_platform/api/dashboard/api/router.py

ADD ENDPOINTS:
  # Get logs for specific strategy
  GET /dashboard/strategy/{name}/logs
  Query: ?lines=100&level=INFO
  
  # Stream all logs (WebSocket)
  WS /dashboard/runner/logs/stream
  
  # Get runner execution logs
  GET /dashboard/runner/logs
```

---

### 🎯 Phase 3: Update Web UI

**3.1 Strategy List Page**
```
Update: strategy.html (or strategy_new.html - pick one)

FEATURES:
  ✅ Table of all strategies from saved_configs/
  ✅ Columns: Name, Enable, Market Type, Symbol, Status
  ✅ Action buttons: Edit, Delete, View Logs
  ✅ Create button: New Strategy
  ✅ Validation status indicator (✓, ✗, ⚠️)
```

**3.2 Create/Edit Strategy Page**
```
New Page: strategy_form.html (or update existing)

FEATURES:
  ✅ All fields from JSON schema as form inputs
  ✅ Smart parameter grouping (market config, entry, exit, etc)
  ✅ Real-time validation as user types
  ✅ Error messages for each field
  ✅ Save button (validates, then saves)
  ✅ Cancel button
  ✅ Load from template button
  ✅ Download current as JSON button
  ✅ Comparison with template button
```

**3.3 Control Console**
```
Update: strategy.html dashboard

FEATURES:
  ✅ Runner status (starting, running, stopped)
  ✅ Start button (enabled if stopped)
  ✅ Stop button (enabled if running)
  ✅ Refresh interval selector
  ✅ Auto-refresh toggle
  ✅ Last update timestamp
```

**3.4 Strategy Console**
```
Update: strategy.html dashboard

FEATURES:
  ✅ Real-time list of loaded strategies
  ✅ Symbol, Market Type, Entry Time, Exit Time per row
  ✅ Running/Stopped status indicator
  ✅ View Logs button
  ✅ Error indicator if start/stop failed
```

**3.5 Logging Display**
```
New Panel: strategy logs

FEATURES:
  ✅ Real-time log stream from selected strategy
  ✅ Log level filter (DEBUG, INFO, WARNING, ERROR)
  ✅ Auto-scroll toggle
  ✅ Clear logs button
  ✅ Download logs button
  ✅ Search logs input
  ✅ Timestamp on each log line
```

---

### 🎯 Phase 4: Update Runner Integration

**4.1 Backend Changes**
```
File: shoonya_platform/strategies/strategy_runner.py

ADD:
  - Singleton instance at module level
  - Lifecycle management (only 1 instance)
  - Log streaming support
  - Metrics collection (already exists)
  - Error capture and reporting
```

**4.2 Initialize Runner on Startup**
```
File: shoonya_platform/main.py or app startup

ADD:
  - Global runner instance creation
  - Initial strategy loading from saved_configs/
  - Error handling for load failures
  - Report status to dashboard
```

---

## IMPLEMENTATION CHECKLIST

### Cleanup (Day 1)
- [ ] Delete test_strategy_form.html from root
- [ ] Decide: Keep strategy.html OR strategy_new.html (delete one)
- [ ] Update strategies/README.md

### API Creation (Day 2-3)
- [ ] Create strategy_config_service.py with validation
- [ ] Create strategy_logger.py with logging system
- [ ] Add all 12 API endpoints to router.py
- [ ] Add WebSocket for log streaming

### UI Updates (Day 4-5)
- [ ] Update strategy list page with all features
- [ ] Create/update strategy form page
- [ ] Update control console
- [ ] Create strategy console
- [ ] Add logging display

### Integration (Day 6)
- [ ] Update strategy_runner for singleton pattern
- [ ] Initialize runner on app startup
- [ ] Test load/save flow end-to-end
- [ ] Test start/stop flow end-to-end
- [ ] Test logging display

### Testing & Documentation (Day 7)
- [ ] E2E test: Create strategy via UI
- [ ] E2E test: Validate strategy with bad JSON
- [ ] E2E test: Start/stop runner via UI
- [ ] E2E test: View logs in real-time
- [ ] Update documentation
- [ ] README update with UI screenshots

---

## JSON VALIDATION - COMPREHENSIVE SPEC

### What Should Be Validated

```python
VALIDATION_RULES = {
    # Required fields
    "name": {
        "type": "string",
        "required": True,
        "min_length": 1,
        "max_length": 100,
        "pattern": "^[A-Za-z0-9_]+$",
        "error": "Name must be alphanumeric + underscore"
    },
    
    "market_config": {
        "required": True,
        "fields": {
            "market_type": {
                "enum": ["database_market", "live_feed_market"],
                "error": "Must be 'database_market' or 'live_feed_market'"
            },
            "exchange": {
                "enum": ["NFO", "MCX", "NCDEX", "CDSL"],
                "error": "Invalid exchange"
            },
            "symbol": {
                "type": "string",
                "required": True,
                "error": "Symbol required"
            },
            "db_path": {
                "type": "string",
                "required_if": {"market_type": "database_market"},
                "file_exists": True,
                "error": "Database file not found: {value}"
            }
        }
    },
    
    "entry": {
        "required": True,
        "fields": {
            "entry_time": {
                "type": "string",
                "pattern": "^[0-2][0-9]:[0-5][0-9]$",
                "error": "Invalid time format: use HH:MM (24-hour)"
            },
            "target_ce_delta": {
                "type": "number",
                "min": 0,
                "max": 1,
                "error": "Delta must be between 0 and 1"
            },
            "target_pe_delta": {
                "type": "number",
                "min": 0,
                "max": 1,
                "error": "Delta must be between 0 and 1"
            },
            "quantity": {
                "type": "integer",
                "min": 1,
                "error": "Quantity must be positive"
            }
        }
    },
    
    "exit": {
        "required": True,
        "fields": {
            "exit_time": {
                "type": "string",
                "pattern": "^[0-2][0-9]:[0-5][0-9]$",
                "error": "Invalid time format: use HH:MM (24-hour)"
            },
            "profit_target": {
                "type": "number",
                "min": 0,
                "error": "Profit target must be positive"
            },
            "max_loss": {
                "type": "number",
                "min": 0,
                "error": "Max loss must be positive"
            }
        },
        "conditional": {
            "if": {"profit_target": "missing", "max_loss": "missing"},
            "then": "error: must have profit_target OR max_loss"
        }
    }
}
```

### Smart Parameter Validation

```python
SMART_CHECKS = [
    # Entry time must be before exit time
    {
        "name": "entry_before_exit",
        "check": lambda cfg: cfg["entry"]["entry_time"] < cfg["exit"]["exit_time"],
        "error": "Entry time must be before exit time"
    },
    
    # If CE delta = PE delta, that's okay (symmetric)
    # If CE delta != PE delta, must be intentional (warn but don't error)
    {
        "name": "asymmetric_deltas_warning",
        "check": lambda cfg: cfg["entry"]["target_ce_delta"] != cfg["entry"]["target_pe_delta"],
        "level": "warning",
        "message": "Asymmetric deltas: CE={ce}, PE={pe} (intentional?)"
    },
    
    # Profit target should be > max loss
    {
        "name": "profit_target_vs_loss",
        "check": lambda cfg: cfg["exit"]["profit_target"] > cfg["exit"]["max_loss"],
        "level": "warning",
        "message": "Profit target ({profit}) should be > max loss ({loss})"
    },
    
    # Check if delta drift trigger is reasonable
    {
        "name": "delta_drift_trigger_reasonable",
        "check": lambda cfg: cfg["adjustment"]["delta_drift_trigger"] > cfg["entry"]["target_ce_delta"],
        "level": "warning",
        "message": "Delta drift trigger ({trigger}) should be > entry target ({target})"
    },
]
```

### Error Response Format

```python
{
    "valid": False,
    "errors": [
        {
            "field": "market_config.db_path",
            "message": "Database file not found: /invalid/path.db",
            "level": "error",
            "type": "file_not_found"
        }
    ],
    "warnings": [
        {
            "field": "entry",
            "message": "Asymmetric deltas: CE=0.30, PE=0.40",
            "level": "warning",
            "type": "asymmetric_config"
        }
    ]
}
```

---

## LOGGING SYSTEM - COMPREHENSIVE SPEC

### Logger Setup

```python
# File: shoonya_platform/strategies/strategy_logger.py

class StrategyLogger:
    """Per-strategy logger with UI streaming support"""
    
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.log_file = f"logs/strategies/{strategy_name}.log"
        self.memory_buffer = collections.deque(maxlen=1000)  # Last 1000 lines
        
        # Create file handler
        self.file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=10_000_000,  # 10MB
            backupCount=5
        )
        
        # Create logger
        self.logger = logging.getLogger(f"STRATEGY.{strategy_name}")
        self.logger.addHandler(self.file_handler)
        self.logger.addHandler(MemoryHandler())  # Custom to buffer
        
    def get_recent_logs(self, lines: int = 100) -> List[str]:
        """Get recent logs from memory buffer"""
        return list(self.memory_buffer)[-lines:]
```

### Integration with Strategy

```python
# In strategy_runner.py, on_tick():

logger = StrategyLogger(name)
logger.logger.info(f"Tick {tick_count}: delta_drift={drift}")
logger.logger.warning(f"Delta exceeded trigger: {delta}")
logger.logger.error(f"Entry failed: {error}")
```

### UI Display

```javascript
// strategy.html JavaScript

async function streamLogs(strategyName) {
    const ws = new WebSocket(`ws://localhost/dashboard/runner/logs/stream?strategy=${strategyName}`);
    
    ws.onmessage = (event) => {
        const log = JSON.parse(event.data);
        displayLog(log);  // Add to log panel
        scrollToBottom();  // Auto-scroll
    };
}
```

---

## START/STOP BUTTON - COMPREHENSIVE SPEC

### API Implementation

```python
# In router.py

@router.post("/dashboard/runner/start")
async def runner_start(ctx=Depends(require_dashboard_auth)):
    """Start the global strategy runner"""
    from shoonya_platform.strategies.strategy_runner import global_runner
    
    if global_runner.get_status()['running']:
        return {
            "success": False,
            "message": "Runner already running",
            "status": global_runner.get_status()
        }
    
    try:
        # Load all strategies from saved_configs/
        results = global_runner.load_strategies_from_json(
            config_dir="saved_configs/",
            strategy_factory=lambda cfg: DNSS(cfg)
        )
        
        # Start runner
        global_runner.start()
        
        return {
            "success": True,
            "message": f"Runner started with {len([r for r in results.values() if r])} strategies",
            "strategies_loaded": results,
            "status": global_runner.get_status()
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to start: {str(e)}",
            "error": str(e)
        }

@router.post("/dashboard/runner/stop")
async def runner_stop(ctx=Depends(require_dashboard_auth)):
    """Stop the global strategy runner"""
    from shoonya_platform.strategies.strategy_runner import global_runner
    
    if not global_runner.get_status()['running']:
        return {
            "success": False,
            "message": "Runner not running",
            "status": global_runner.get_status()
        }
    
    try:
        global_runner.stop()
        
        return {
            "success": True,
            "message": "Runner stopped",
            "status": global_runner.get_status()
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to stop: {str(e)}",
            "error": str(e)
        }

@router.get("/dashboard/runner/status")
async def runner_status(ctx=Depends(require_dashboard_auth)):
    """Get runner status and metrics"""
    from shoonya_platform.strategies.strategy_runner import global_runner
    
    return {
        "status": global_runner.get_status(),
        "metrics": global_runner.get_metrics()
    }
```

### UI Implementation

```javascript
// strategy.html

const startButton = document.getElementById('btn-runner-start');
const stopButton = document.getElementById('btn-runner-stop');
const statusDisplay = document.getElementById('runner-status');

startButton.addEventListener('click', async () => {
    startButton.disabled = true;
    startButton.textContent = 'Starting...';
    
    try {
        const response = await fetch('/dashboard/runner/start', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();
        
        if (data.success) {
            statusDisplay.innerHTML = `
                <div class="status-running">
                    <span class="indicator"></span>
                    RUNNING
                    <span class="timestamp">${new Date().toLocaleTimeString()}</span>
                </div>
            `;
            startButton.style.display = 'none';
            stopButton.style.display = 'block';
            stopButton.disabled = false;
            
            // Update strategy list
            loadStrategyList();
        } else {
            alert(`Failed: ${data.message}`);
        }
    } catch (error) {
        alert(`Error: ${error}`);
    } finally {
        startButton.disabled = false;
        startButton.textContent = 'Start';
    }
});

stopButton.addEventListener('click', async () => {
    stopButton.disabled = true;
    stopButton.textContent = 'Stopping...';
    
    try {
        const response = await fetch('/dashboard/runner/stop', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();
        
        if (data.success) {
            statusDisplay.innerHTML = `
                <div class="status-stopped">
                    <span class="indicator"></span>
                    STOPPED
                </div>
            `;
            stopButton.style.display = 'none';
            startButton.style.display = 'block';
            startButton.disabled = false;
        } else {
            alert(`Failed: ${data.message}`);
        }
    } catch (error) {
        alert(`Error: ${error}`);
    } finally {
        stopButton.disabled = false;
        stopButton.textContent = 'Stop';
    }
});
```

---

## FINAL SUMMARY

### ✅ What's Clean Now
- All code files in strategies/ folder are well-organized
- find_option.py is single source of truth
- JSON schema exists and is correct
- Runner can load JSON files

### ⚠️ What Needs Fixing (Priority Order)

**1. Delete Legacy Files (5 min)**
- test_strategy_form.html

**2. Decide on HTML Files (2 min)**
- Keep one of: strategy.html or strategy_new.html
- Delete the other

**3. Build Validation Service (4 hours)**
- Create strategy_config_service.py
- Validate JSON schema
- Check parameters smartly
- Return clear errors

**4. Build Logging System (3 hours)**
- Create strategy_logger.py
- Per-strategy logs
- Memory buffer for UI
- Log streaming support

**5. Add API Endpoints (4 hours)**
- 12 new endpoints in router.py
- WebSocket for log streaming
- Start/stop runner functionality

**6. Update Web UI (8 hours)**
- Strategy list view
- Create/edit form
- Control console
- Strategy console
- Logging display

**7. Backend Integration (2 hours)**
- Runner singleton instance
- Initialization on startup
- Error reporting

**Total Effort:** 2-3 days (Full stack)

---

## ALIGNMENT GUARANTEE

After implementation, you'll have:

✅ **One single folder:** `saved_configs/` for all strategies  
✅ **One UI flow:** Create → Validate → Save → Start/Stop  
✅ **One validation:** Smart parameter checking with clear errors  
✅ **One logging:** All strategies visible in real-time  
✅ **No confusion:** All controls in one place  
✅ **No legacy:** Clean, modern, production-ready  

**Result:** Anyone can pick up the system and understand it instantly.

---

## YOUR DECISION NEEDED

1. **Strategy HTML:** Which one to keep? 
   - strategy.html (2466 lines)
   - strategy_new.html (3086 lines)

2. **Implementation timing:**
   - Build everything now? (2-3 days)
   - Phase it? (cleanup now, rest later)
   - Focus on critical path only? (validation + API)

3. **Priority:**
   - Validation first (prevents bad configs)
   - UI first (users see functionality)
   - Logging first (visibility into execution)

Let me know and I'll implement immediately!
