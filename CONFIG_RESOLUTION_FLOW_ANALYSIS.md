# Configuration Resolution & Validation Flow Analysis
**Date:** 2026-02-12  
**Status:** PRODUCTION ANALYSIS - Missing ConfigResolutionService  

---

## Executive Summary

There is **NO centralized ConfigResolutionService** in the system. Configuration flows through multiple paths without proper validation/resolution against ScriptMaster:

1. **Dashboard → API → Execution**: No instrument validation
2. **Config Loading → Strategy Creation**: Missing expiry resolution
3. **Market Adapter Selection**: Partial db_path validation only
4. **Supervisor.py ↔ Live Option Chain**: Missing orchestration

**CRITICAL GAPS:**
- ❌ No validation that `exchange + symbol` exists in ScriptMaster
- ❌ No resolution of `order_type` allowed for instrument
- ❌ No automatic `expiry` resolution from ScriptMaster
- ❌ No centralized `db_path` determination (supervisor.py hardcodes pattern)
- ❌ No pre-flight check before strategy execution

---

## PART 1: Configuration Flow Paths

### PATH 1: Dashboard → API Router → Execution
**Entry Point:** [api/dashboard/api/router.py](api/dashboard/api/router.py#L1027)

```
1. Dashboard Form Input
   ↓
2. POST /strategy/config/save (router.py:1027)
   └─ Saves to: strategies/saved_configs/{slug}.json
   └─ NO VALIDATION - just JSON structure check
   
3. StrategyEntryRequest Pydantic model (schemas.py:188)
   ├─ validate_dnss_contract()     ← Only validates strategy-specific params
   ├─ validate_time_fields()        ← Only validates time format
   └─ validate_instrument_type()    ← Returns ✅ always (NOT connected to ScriptMaster)
   
4. POST /strategy/{strategy_name}/start-execution (router.py:1810)
   └─ Loads config from: strategies/saved_configs/{strategy_name}.json
   └─ Creates strategy via: create_strategy(config)
   └─ NO CONFIG RESOLUTION HAPPENS HERE
```

**MISSING:** Pre-flight validation that:
- Exchange + symbol exists in ScriptMaster
- Instrument type (OPTIDX/OPTSTK/FUT/MCX) matches symbol
- Order type is allowed for this instrument

---

### PATH 2: Config Loading → Strategy Creation
**Files:**
- [strategy_factory.py](shoonya_platform/strategies/strategy_factory.py#L49) - Creates strategy from config
- [strategy_control_consumer.py](shoonya_platform/execution/strategy_control_consumer.py#L177) - Loads saved config
- [delta_neutral/adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py#L31) - Converts to DNSS

```
1. _load_strategy_config() (strategy_control_consumer.py:430)
   ├─ Loads: strategies/saved_configs/{slug}.json
   ├─ Returns: Dict with identity, entry, exit, adjustment, rms
   └─ NO VALIDATION
   
2. Merge dashboard intent with loaded config (strategy_control_consumer.py:193)
   ├─ merged_payload = {**saved_config, **payload}
   └─ NO CONFLICT RESOLUTION
   
3. build_universal_config(payload) (strategy_control_consumer.py:51)
   ├─ Creates: UniversalStrategyConfig
   ├─ Fields: exchange, symbol, instrument_type, entry_time, exit_time, order_type, product, lot_qty
   └─ ❌ NO SCRIPTMASTER VALIDATION
   
4. create_strategy(config) (strategy_factory.py:49)
   ├─ Looks up strategy_type in STRATEGY_REGISTRY
   ├─ Calls: strategy_class(config)
   └─ For DNSS: calls create_dnss_from_universal_config()
   
5. create_dnss_from_universal_config() (delta_neutral/adapter.py:31)
   ├─ Validates: Required DNSS params exist (target_entry_delta, delta_adjust_trigger, etc.)
   ├─ Creates: StrategyConfig(entry_time, exit_time, deltas, profit_step, cooldown)
   ├─ Calls: _calculate_expiry() 
   │  └─ Queries: options_expiry(symbol, exchange) from SCRIPTMASTER ✅
   │  └─ Returns: Expiry (e.g., "12FEB2026")
   └─ Creates: DeltaNeutralShortStrangleStrategy(exchange, symbol, expiry, lot_qty, config)
```

**MISSING:** 
- ❌ No validation that symbol+exchange exists in SCRIPTMASTER BEFORE _calculate_expiry()
- ❌ No check that order_type is allowed for this instrument
- ❌ No determination of db_path at this point

---

### PATH 3: Market Adapter Selection & Initialization
**File:** [market_adapter_factory.py](shoonya_platform/strategies/market_adapter_factory.py#L19)

```
1. MarketAdapterFactory.create(market_type, config)
   ├─ Validates: exchange & symbol exist in config ✅
   ├─ If market_type == "database_market":
   │  ├─ Requires: db_path in config
   │  ├─ Validates: Path exists (Path.exists()) ✅
   │  ├─ Creates: DatabaseMarketAdapter(db_path, exchange, symbol)
   │  └─ ❌ NO CHECK that db_path is correct for this exchange/symbol/expiry
   │
   └─ If market_type == "live_feed_market":
      └─ Creates: LiveFeedMarketAdapter(exchange, symbol)
      └─ ❌ NO LIVE OPTION DATA SOURCE SPECIFIED
```

**CRITICAL ISSUE:** 
- db_path must come from config BUT:
  - ❌ Where is db_path SET in config?
  - ❌ How does DNSS strategy get db_path?
  - ❌ Who owns determining correct db_path for exchange/symbol/expiry?

---

### PATH 4: Supervisor.py - Option Chain DB Management
**File:** [supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py#L1)

```
1. bootstrap_defaults() (supervisor.py:156)
   ├─ Creates default chains for:
   │  └─ NFO:NIFTY, NFO:BANKNIFTY, MCX:CRUDEOILM
   └─ For each: get_expiry() → _start_chain(exchange, symbol, expiry)

2. _start_chain(exchange, symbol, expiry) (supervisor.py:187)
   ├─ Creates: live_option_chain(api_client, exchange, symbol, expiry, auto_start_feed=False)
   ├─ Determines DB path:
   │  └─ db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"  ← HARDCODED PATTERN
   ├─ Creates: OptionChainStore(db_path)
   ├─ Stores in: self._chains[key] = {oc, store, db_path, start_time, last_health_check}
   └─ Returns: True/False
```

**KEY ISSUE:**
```python
# supervisor.py:296 - DB PATH IS DETERMINED HERE
db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
```

- ✅ Supervisor determines db_path (good)
- ❌ But strategy doesn't know where supervisor puts the db
- ❌ db_path NOT returned to caller
- ❌ db_path NOT stored in config for reference

---

## PART 2: Where Configuration Validation / Resolution Should Happen

### 1. ⚠️ ORDER_TYPE VALIDATION (MISSING)

**Current Reality:**
```python
# utils.py:291
def validate_order_type(order_type: str) -> str:
    """Normalize order type (MKT → MARKET, LMT → LIMIT)"""
    if order_type in ['MKT', 'MARKET']:
        return 'MKT'
    elif order_type in ['LMT', 'LIMIT']:
        return 'LMT'
    else:
        raise ValueError(f"Invalid order type: {order_type}")
```

**WHAT'S MISSING:**
```python
# SHOULD EXIST BUT DOESN'T
def validate_order_type_for_instrument(order_type: str, exchange: str, symbol: str, instrument: str) -> bool:
    """
    Validate that order_type is allowed for this instrument in ScriptMaster.
    
    Example:
    - NFO:NIFTY:OPTIDX → MARKET ✅ (most brokers allow)
    - Some exchanges → LIMIT required
    - MCX options → checking against SCRI PTMASTER needed
    
    Should check:
    1. ScriptMaster record for exchange/symbol/instrument
    2. Broker capability matrix (hardcoded per broker)
    """
    pass
```

**Who Should Implement:**
- `ConfigResolutionService.validate_order_type_for_instrument()`
- Called BEFORE creating strategy

---

### 2. ⚠️ SYMBOL EXISTENCE & VALIDATION (MISSING)

**Current Reality:** NO centralized check

**WHAT'S MISSING:**
```python
# SHOULD EXIST BUT DOESN'T
def validate_exchange_symbol_exists(exchange: str, symbol: str) -> bool:
    """
    Validate instrument exists in ScriptMaster.
    
    Checks:
    1. exchange in SCRIPTMASTER
    2. symbol in SCRIPTMASTER[exchange]
    3. At least one contract exists
    
    Returns: True if valid, False otherwise
    Raises: InstrumentNotFound if exchange or symbol invalid
    """
    from scripts.scriptmaster import SCRIPTMASTER
    
    if exchange.upper() not in SCRIPTMASTER:
        raise InstrumentNotFound(f"Unknown exchange: {exchange}")
    
    records = SCRIPTMASTER[exchange.upper()]
    matching = [r for r in records.values() if r.get("Symbol") == symbol.upper()]
    
    if not matching:
        raise InstrumentNotFound(f"{symbol} not found on {exchange}")
    
    return True
```

**Who Should Implement:**
- `ConfigResolutionService.validate_instrument_exists()`
- Called when dashboard saves config, AND before strategy execution

---

### 3. ⚠️ EXPIRY RESOLUTION (PARTIAL - in adapter, MISSING in validator)

**Current Reality:**
```python
# delta_neutral/adapter.py:130 - PARTIAL EXISTS
def _calculate_expiry(exchange: str, symbol: str, expiry_mode: str) -> str:
    """Get current option expiry from ScriptMaster"""
    expiries = options_expiry(symbol, exchange)
    if not expiries:
        raise ValueError(f"No option expiries found for {symbol} on {exchange}")
    
    # Select based on mode (weekly_current vs monthly_current)
    selected = upcoming[0]  # Returns first upcoming expiry
    return selected
```

**ISSUES:**
- ✅ Exists in adapter.py
- ❌ ONLY called when creating DNSS strategy
- ❌ NOT available to validator (happens too late)
- ❌ NOT in ConfigResolutionService (centralized)
- ❌ Called AFTER strategy construction happens

**WHAT'S MISSING:**
```python
# ConfigResolutionService - should resolve expiry EARLY
def resolve_expiry(
    exchange: str, 
    symbol: str, 
    instrument_type: str,  # OPTIDX, OPTSTK, FUT
    expiry_mode: str = "weekly_current"
) -> str:
    """
    Resolve option/future expiry from ScriptMaster at CONFIG TIME.
    
    Returns: Expiry string (DD-MMM-YYYY or format from ScriptMaster)
    Raises: ValueError if no tradable expiry found
    """
    from scripts.scriptmaster import options_expiry, fut_expiry, get_expiry
    
    if instrument_type in ("OPTIDX", "OPTSTK"):
        expiries = options_expiry(symbol, exchange)
    else:
        return fut_expiry(symbol, exchange, result=0)
    
    if not expiries:
        raise ValueError(f"No expiries for {symbol}/{exchange}")
    
    # Filter tradable expiries...
    return selected_expiry
```

---

### 4. ⚠️ DB_PATH DETERMINATION (MISSING - Critical)

**Current Reality:**
```
Supervisor determines:
    db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
    
But:
- Strategy has NO WAY to know this path
- Config doesn't have db_path pre-populated
- DatabaseMarketAdapter requires db_path in config
```

**THE PROBLEM:**

```python
# strategy_factory.py:49 (Strategy Creation)
strategy = create_strategy(config)  # Config missing db_path!

# Then later...
market_adapter = MarketAdapterFactory.create("database_market", config)
# ↑ WILL FAIL: db_path not in config!
```

**WHAT'S MISSING:**
```python
# ConfigResolutionService - should determine db_path
def resolve_db_path(
    exchange: str,
    symbol: str,
    expiry: str,
    instrument_type: str,
    market_type: str = "database_market"
) -> str:
    """
    Determine correct SQLite database path for this configuration.
    
    Rules:
    1. If market_type == "live_feed_market" → None (no DB)
    2. If market_type == "database_market":
       - Check supervisor.py DB_BASE_DIR for pattern
       - db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
       - Validate path exists
       - Return absolute path
    
    Returns: Path string or None
    Raises: FileNotFoundError if database doesn't exist
    """
    from pathlib import Path
    
    if market_type == "live_feed_market":
        return None
    
    # Option chain DB pattern from supervisor.py:296
    DB_BASE_DIR = Path(__file__).parent / "data"
    db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
    
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}\n"
            f"Supervisor must create chain for {symbol} first"
        )
    
    return str(db_path)
```

---

### 5. ⚠️ LIVE OPTION DATA SOURCE (COMPLETELY MISSING)

**Current Reality:**
```python
# schemas.py:167 (StrategyEntryRequest)
# NO FIELD for live_option_data or how to get it

# delta_neutral/adapter.py:31 (create_dnss_from_universal_config)
get_option_func: Optional[Callable] = None  # Where does this come from?
```

**THE PROBLEM:**

Strategy needs live option data (`live_option_chain`), but:
- ❌ Never passed in config
- ❌ Never resolved dynamically
- ❌ No reference to supervisor
- ❌ Not passed through MarketAdapter

**WHAT'S MISSING:**
```python
# ConfigResolutionService - should get live option data reference
def resolve_live_option_data(
    exchange: str,
    symbol: str,
    expiry: str,
    supervisor  # OptionChainSupervisor instance
):
    """
    Get live option chain for this instrument from supervisor.
    
    Returns: OptionChainData instance or callable
    Raises: RuntimeError if chain not available
    """
    from shoonya_platform.market_data.option_chain.supervisor import OptionChainSupervisor
    
    # Ensure supervisor has chain for this instrument
    chain_key = f"{exchange}:{symbol}:{expiry}"
    
    if not supervisor.has_chain(chain_key):
        # Try to start it
        success = supervisor.ensure_chain(
            exchange=exchange,
            symbol=symbol,
            expiry=expiry
        )
        if not success:
            raise RuntimeError(f"Failed to start option chain: {chain_key}")
    
    # Get reference to chain
    return supervisor.get_chain(chain_key)
```

---

## PART 3: The Missing ConfigResolutionService

### Design

```python
# SHOULD EXIST: shoonya_platform/strategies/config_resolution_service.py

class ConfigResolutionService:
    """
    CENTRAL validation & resolution for strategy configurations.
    
    Orchestrates all config validation and resolution at ONE place:
    1. Validates instrument exists in ScriptMaster
    2. Resolves expiry from ScriptMaster
    3. Validates order_type for instrument
    4. Determines db_path for market data
    5. Resolves live_option_data reference
    6. Validates all cross-field dependencies
    """
    
    def __init__(self, supervisor=None, broker=None):
        """
        Args:
            supervisor: OptionChainSupervisor (for live data)
            broker: Broker client (for capability matrix)
        """
        self.supervisor = supervisor
        self.broker = broker
    
    def resolve_and_validate_config(self, config: dict) -> ResolvedConfig:
        """
        MAIN ENTRY POINT: Validate and resolve ALL config fields.
        
        Steps:
        1. Validate basic structure
        2. Validate instrument exists
        3. Resolve expiry
        4. Validate order_type for this instrument
        5. Determine db_path
        6. Get live_option_data reference
        7. Validate cross-field relationships
        8. Return fully resolved config with all fields populated
        
        Args:
            config: Raw config dict from dashboard/file
        
        Returns:
            ResolvedConfig with all fields validated & populated
        
        Raises:
            ConfigValidationError: If any validation fails (with clear message)
        """
        pass
    
    def validate_instrument_exists(self, exchange: str, symbol: str) -> bool:
        """Check exchange + symbol exists in ScriptMaster"""
        pass
    
    def validate_order_type_for_instrument(
        self, 
        order_type: str, 
        exchange: str, 
        symbol: str,
        instrument_type: str
    ) -> bool:
        """Check order_type allowed for this instrument"""
        pass
    
    def resolve_expiry(
        self,
        exchange: str,
        symbol: str,
        instrument_type: str,
        expiry_mode: str = "weekly_current"
    ) -> str:
        """Get tradable expiry from ScriptMaster"""
        pass
    
    def resolve_db_path(
        self,
        exchange: str,
        symbol: str,
        expiry: str,
        market_type: str = "database_market"
    ) -> Optional[str]:
        """Determine SQLite path for this config"""
        pass
    
    def resolve_live_option_data(
        self,
        exchange: str,
        symbol: str,
        expiry: str
    ):
        """Get live option chain reference from supervisor"""
        pass
```

### Where It Should Be Called

```
1. ✅ Dashboard Form Submission (router.py:1027)
   POST /strategy/config/save
   └─ Call: config_service.resolve_and_validate_config(payload)
   └─ Store resolved config

2. ✅ Before Strategy Execution (router.py:1810)
   POST /strategy/{strategy_name}/start-execution
   └─ Call: config_service.resolve_and_validate_config(loaded_config)
   └─ Populate: db_path, live_option_data, verified expiry

3. ✅ Before Strategy Creation (strategy_factory.py:49)
   create_strategy(config)
   └─ Ensure: config already resolved & validated
   └─ Or: config_service.resolve_and_validate_config(config)

4. ✅ Before Market Adapter Creation (market_adapter_factory.py:34)
   MarketAdapterFactory.create(market_type, config)
   └─ Assume: db_path already in config (from resolver)
```

---

## PART 4: Current Config Validator Status

**File:** [strategy_config_validator.py](shoonya_platform/strategies/strategy_config_validator.py)

### What It DOES (Basic Structure)
✅ Validates JSON structure  
✅ Validates required fields present  
✅ Validates time format (HH:MM)  
✅ Validates value ranges (0-1 for delta)  
✅ Validates product type enum  

### What It DOESN'T DO (Critical Gaps)
❌ Doesn't check ScriptMaster for symbol existence  
❌ Doesn't validate order_type for instrument  
❌ Doesn't resolve expiry  
❌ Doesn't check db_path  
❌ Doesn't resolve live_option_data  
❌ Not called during config save (dashboard)  
❌ Not called during strategy execution  

### Usage
```python
from shoonya_platform.strategies.strategy_config_validator import validate_strategy

result = validate_strategy(config, "MY_STRATEGY")
print(result.to_dict())  # Returns errors, warnings, info
```

**Problem:** This is ONLY for basic schema validation, NOT for config resolution.

---

## PART 5: Exact Data Flow - Shows What's Missing

```
DASHBOARD (Form Input)
         ↓
POST /strategy/config/save (router.py:1027)
         ↓
         ┌─────────────────────────────────────────────────┐
         │ ❌ MISSING: ConfigurationResolutionService     │
         │ ❌ Should:                                      │
         │    - Validate symbol exists in ScriptMaster    │
         │    - Validate order_type for instrument        │
         │    - Resolve expiry from ScriptMaster          │
         │    - Determine db_path                         │
         │    - Get live_option_data reference            │
         └─────────────────────────────────────────────────┘
                         ↓
    SAVE to strategies/saved_configs/{slug}.json
    (Config may be INCOMPLETE/UNRESOLVED)
                         ↓
POST /strategy/{strategy_name}/start-execution (router.py:1810)
                         ↓
    LOAD strategies/saved_configs/{slug}.json
                         ↓
         ┌─────────────────────────────────────────────────┐
         │ ❌ MISSING: ConfigurationResolutionService     │
         │ ❌ Should happen HERE (before strategy start)  │
         └─────────────────────────────────────────────────┘
                         ↓
    build_universal_config(payload)
    → UniversalStrategyConfig(exchange, symbol, ...)
                         ↓
    create_strategy(config)
    → strategy_factory.py:create_strategy()
    → Creates DNSS or other
                         ↓
    For DNSS: create_dnss_from_universal_config()
    → _calculate_expiry() ✅ (resolves expiry HERE)
    → ❌ NO db_path available yet
    → ❌ NO live_option_data reference
                         ↓
    MarketAdapterFactory.create("database_market", config)
    → ❌ FAILS: db_path not in config
                         ↓
    STRATEGY CREATION FAILS ❌
```

---

## PART 6: Solution Architecture

### Changes Needed

**1. Create ConfigResolutionService** (NEW FILE)
```
Path: shoonya_platform/strategies/config_resolution_service.py

Methods:
- resolve_and_validate_config(config) → ResolvedConfig
- validate_instrument_exists(exchange, symbol) → bool
- validate_order_type_for_instrument(...) → bool
- resolve_expiry(exchange, symbol, instrument_type) → str
- resolve_db_path(exchange, symbol, expiry, market_type) → str | None
- resolve_live_option_data(exchange, symbol, expiry) → OptionChainData | None
```

**2. Call at Strategic Points**

Route | Current | Change
------|---------|-------
POST /strategy/config/save | NO validation | Call resolver.resolve_and_validate_config()
POST /strategy/start-execution | NO validation | Call resolver before create_strategy()
create_strategy() | Assumes config valid | Add resolver call
MarketAdapterFactory.create() | Checks db_path exists | Assume populated by resolver

**3. Update Market Adapter Config**

From:
```python
config = {
    "exchange": "NFO",
    "symbol": "NIFTY",
    "db_path": "/path/to/db.sqlite"  # ← WHERE DOES THIS COME FROM?
}
```

To:
```python
resolved = ConfigResolutionService.resolve_and_validate_config(config)
# resolved = {
#     "exchange": "NFO",
#     "symbol": "NIFTY",
#     "expiry": "12FEB2026",  # ← RESOLVED FROM SCRIPTMASTER
#     "instrument_type": "OPTIDX",  # ← VALIDATED
#     "order_type": "MARKET",  # ← VALIDATED FOR INSTRUMENT
#     "db_path": "/path/to/supervisor_data/NFO_NIFTY_12FEB2026.sqlite",  # ← DETERMINED
#     "live_option_data": <OptionChainData>,  # ← RESOLVED FROM SUPERVISOR
# }
```

---

## PART 7: ScriptMaster Integration Points

### Where ScriptMaster is Currently Used

Location | Purpose | Status
---------|---------|-------
[instruments.py](shoonya_platform/market_data/instruments/instruments.py#L23) | Get FNO details | ✅ Imported
[delta_neutral/adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py#L20) | Get option expiry | ✅ Used (_calculate_expiry)
[option_chain.py](shoonya_platform/market_data/option_chain/option_chain.py#L138) | Build from ScriptMaster | ✅ load_from_scriptmaster()
[supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py#L42) | Periodic refresh | ✅ refresh_scriptmaster()

### What's NOT Using It

- ❌ Order type validation (no broker capability matrix)
- ❌ Symbol existence check at config time
- ❌ Centralized instrument validation

---

## PART 8: Summary Table - What's Missing

| Responsibility | Current | Where | Should Be | Status |
|---|---|---|---|---|
| Validate instrument exists | None | validate_instrument_exists() | ConfigResolutionService | ❌ MISSING |
| Validate order_type for instrument | validate_order_type() | utils.py | ConfigResolutionService.validate_order_type_for_instrument() | ⚠️ PARTIAL |
| Resolve expiry from ScriptMaster | _calculate_expiry() | delta_neutral/adapter.py | ConfigResolutionService.resolve_expiry() | ⚠️ WRONG PLACE |
| Determine db_path | Hardcoded | supervisor.py:296 | ConfigResolutionService.resolve_db_path() | ❌ NOT EXPOSED |
| Get live_option_data ref | None | Not resolved | ConfigResolutionService.resolve_live_option_data() | ❌ MISSING |
| Call resolver | None | None | dashboard router + strategy_factory | ❌ MISSING |
| Config validation at save-time | None | None | POST /strategy/config/save | ❌ MISSING |
| Config validation at exec-time | None | None | POST /strategy/start-execution | ❌ MISSING |

---

## PART 9: Exact Call Chain That Should Exist

```python
# IDEAL FLOW (DOESN'T EXIST YET)

# ===== DASHBOARD SAVE =====
@router.post("/strategy/config/save")
def save_strategy_config(payload: dict):
    # NEW: Resolve & validate FIRST
    resolver = ConfigResolutionService(supervisor, broker)
    try:
        resolved = resolver.resolve_and_validate_config(payload)
    except ConfigValidationError as e:
        raise HTTPException(400, str(e))
    
    # Save RESOLVED config
    config_path.write_text(json.dumps(resolved))
    return {"saved": True, "resolved_config": resolved}

# ===== STRATEGY EXECUTION =====
@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(strategy_name: str):
    # Load saved config
    config = json.loads(config_path.read_text())
    
    # Verify still valid (may have changed since save)
    resolver = ConfigResolutionService(supervisor, broker)
    try:
        resolved = resolver.resolve_and_validate_config(config)
    except ConfigValidationError as e:
        raise HTTPException(400, str(e))
    
    # Now create strategy with FULLY RESOLVED config
    strategy = create_strategy(resolved)
    
    # Market adapter will find db_path in resolved config
    market = MarketAdapterFactory.create(
        market_type=resolved["market_type"],
        config=resolved
    )
    
    # Start running
    runner.register(strategy_name, strategy, market)
    
    return {"started": True}

# ===== STRATEGY FACTORY =====
def create_strategy(config: dict):
    # Assume config is ALREADY resolved
    # If not: resolver.resolve_and_validate_config(config)
    strategy_type = config.get("strategy_type", "")
    strategy_class = STRATEGY_REGISTRY.get(strategy_type.lower())
    return strategy_class(config)

# ===== MARKET ADAPTER =====
def MarketAdapterFactory.create(market_type: str, config: dict):
    if market_type == "database_market":
        db_path = config.get("db_path")
        # ✅ NOW GUARANTEED TO EXIST (from resolver)
        return DatabaseMarketAdapter(db_path, exchange, symbol)
    elif market_type == "live_feed_market":
        # ✅ Get from resolver (or supervisor)
        live_data = config.get("live_option_data")
        return LiveFeedMarketAdapter(exchange, symbol, live_data=live_data)
```

---

## CONCLUSION

**What's Working:**
- ✅ Dashboard saves configs (partial)
- ✅ Strategy creation via factory
- ✅ Expiry calculation in adapter (but too late)
- ✅ Strategy execution routing

**What's Missing:**
- ❌ **ConfigResolutionService** (centralized validation + resolution)
- ❌ ScriptMaster validation at config time
- ❌ Order type validation for instrument
- ❌ db_path determination exported to config
- ❌ live_option_data reference resolution
- ❌ Pre-flight validation before strategy execution

**Impact:** Strategies can fail at execution time due to unvalidated/unresolved configs. Needs ConfigResolutionService to validate early and resolve all dependencies.

