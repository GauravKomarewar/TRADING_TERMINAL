# Quick Reference: Configuration Flow Components

**Last Updated:** 2026-02-12

---

## 📍 KEY FILES & FUNCTIONS

### Dashboard & API Layer
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [router.py](shoonya_platform/api/dashboard/api/router.py) | `save_strategy_config()` | Save config to JSON | 1027 | ✅ |
| [router.py](shoonya_platform/api/dashboard/api/router.py) | `start_strategy_execution()` | Start strategy from config | 1810 | ✅ |
| [schemas.py](shoonya_platform/api/dashboard/api/schemas.py) | `StrategyEntryRequest` | Pydantic model | 188 | ⚠️ Missing validation |
| [schemas.py](shoonya_platform/api/dashboard/api/schemas.py) | `validate_instrument_type()` | Validates instrument | 243 | ⚠️ Not connected |

### Configuration Loading
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [strategy_control_consumer.py](shoonya_platform/execution/strategy_control_consumer.py) | `_load_strategy_config()` | Load from JSON file | 430 | ✅ |
| [strategy_control_consumer.py](shoonya_platform/execution/strategy_control_consumer.py) | `build_universal_config()` | Create UniversalStrategyConfig | 51 | ✅ |

### Strategy Creation & Validation
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [strategy_factory.py](shoonya_platform/strategies/strategy_factory.py) | `create_strategy()` | Create strategy from config | 49 | ✅ |
| [strategy_config_validator.py](shoonya_platform/strategies/strategy_config_validator.py) | `validate()` | Basic schema validation | 100 | ✅ Schema only |
| [strategy_config_validator.py](shoonya_platform/strategies/strategy_config_validator.py) | `_validate_market_config()` | Validate market section | 139 | ⚠️ Partial |
| [strategy_config_validator.py](shoonya_platform/strategies/strategy_config_validator.py) | `validate_strategy()` | Main entry point | 495 | ✅ |

### DNSS Adapter
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py) | `create_dnss_from_universal_config()` | DNSS-specific config | 31 | ✅ |
| [adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py) | `_calculate_expiry()` | Resolve expiry from ScriptMaster | 130 | ✅ (but late) |
| [adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py) | `dnss_config_to_universal()` | Convert DNSS → Universal | 250 | ✅ |

### Market Adapter Factory
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [market_adapter_factory.py](shoonya_platform/strategies/market_adapter_factory.py) | `create()` | Create market adapter | 19 | ⚠️ Partial validation |
| [market_adapter_factory.py](shoonya_platform/strategies/market_adapter_factory.py) | Validates `exchange`, `symbol` | Basic checks | 34 | ✅ |
| [market_adapter_factory.py](shoonya_platform/strategies/market_adapter_factory.py) | Checks `db_path` exists | File existence | 41 | ✅ |

### Option Chain & Supervisor
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py) | `bootstrap_defaults()` | Start chains for default symbols | 156 | ✅ |
| [supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py) | `ensure_chain()` | Ensure chain exists | 252 | ✅ |
| [supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py) | `_start_chain()` | Start single chain + determine db_path | 187 | ✅ (db_path hardcoded) |
| [supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py) | DB_PATH determination | `DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"` | 296 | ✅ (hardcoded) |
| [option_chain.py](shoonya_platform/market_data/option_chain/option_chain.py) | `live_option_chain()` | Factory for option chain | 1565 | ✅ |
| [option_chain.py](shoonya_platform/market_data/option_chain/option_chain.py) | `option_chain()` | High-level factory | 1445 | ✅ |

### Instruments & ScriptMaster
| File | Function | Purpose | Line | Status |
|------|----------|---------|------|--------|
| [instruments.py](shoonya_platform/market_data/instruments/instruments.py) | `get_expiry()` | Unified expiry resolver | 211 | ✅ Uses ScriptMaster |
| [instruments.py](shoonya_platform/market_data/instruments/instruments.py) | `get_spot_instrument()` | Resolve spot token | 135 | ✅ |
| [instruments.py](shoonya_platform/market_data/instruments/instruments.py) | `SPOT_TOKEN_REGISTRY` | Hard-coded spot tokens | 35 | ✅ |
| [utils.py](shoonya_platform/utils/utils.py) | `validate_order_type()` | Normalize/validate order type | 291 | ✅ Basic only |

---

## 🔗 DATA FLOW SEQUENCE

### Sequence 1: Dashboard Save Config
```
1. POST /strategy/config/save
   └─ router.py:1027 save_strategy_config()
   ├─ payload = {...}
   ├─ NO VALIDATION ❌
   └─ SAVE to strategies/saved_configs/{slug}.json
```

**Missing:** ConfigResolutionService call to validate + resolve

---

### Sequence 2: Start Strategy Execution
```
1. POST /strategy/{strategy_name}/start-execution
   └─ router.py:1810 start_strategy_execution()
   ├─ Load config from strategies/saved_configs/{slug}.json
   │  └─ strategy_control_consumer.py:430 _load_strategy_config()
   ├─ NO VALIDATION ❌
   ├─ create_strategy(config)
   │  └─ strategy_factory.py:49 create_strategy()
   │  └─ Calls: strategy_class(config) [e.g., DNSS]
   │  └─ For DNSS: delta_neutral/adapter.py:31 create_dnss_from_universal_config()
   │  │  ├─ _calculate_expiry() → calls options_expiry(symbol, exchange) ✅
   │  │  ├─ NO db_path available yet ❌
   │  │  └─ NO live_option_data reference ❌
   │  └─ Returns: DeltaNeutralShortStrangleStrategy
   ├─ MarketAdapterFactory.create(market_type, config)
   │  └─ market_adapter_factory.py:34 create()
   │  ├─ Checks: config has exchange, symbol ✅
   │  ├─ For database_market:
   │  │  ├─ Requires: db_path in config ✅
   │  │  └─ Checks: Path exists ✅
   │  └─ Returns: DatabaseMarketAdapter or LiveFeedMarketAdapter
   └─ Register & start strategy
```

**Missing:** 
- ConfigResolutionService call before create_strategy()
- db_path population in config
- live_option_data resolution

---

### Sequence 3: Where db_path is Determined (Supervisor)
```
1. supervisor.py:187 _start_chain()
   ├─ Input: exchange, symbol, expiry
   ├─ Determines: db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
   ├─ Creates: OptionChainStore(db_path)
   ├─ Stores in: self._chains[key] = {oc, store, db_path, ...}
   └─ ❌ NEVER RETURNS db_path TO CALLER
```

**Problem:** Strategy doesn't know where supervisor puts the database!

---

### Sequence 4: Expiry Resolution (Currently in Adapter)
```
1. delta_neutral/adapter.py:130 _calculate_expiry()
   ├─ Input: exchange, symbol, expiry_mode
   ├─ Calls: options_expiry(symbol, exchange) from SCRIPTMASTER ✅
   ├─ Filters: tradable expiries (after market close)
   ├─ Selects: based on mode (weekly_current vs monthly_current)
   └─ Returns: expiry string (e.g., "12FEB2026")
```

**Problem:**
- Called AFTER strategy init decision
- Not available to validator
- Not in central config resolution service

---

## ⚠️ VALIDATION GAPS

### What is Validated
```
✅ JSON structure (required fields, types)
✅ Time format (HH:MM)
✅ Value ranges (0-1 for delta)
✅ Enum values (LIMIT, MARKET, etc. - GENERIC)
✅ Product type (NRML, MIS, CNC - GENERIC)
```

### What is NOT Validated
```
❌ Symbol exists in ScriptMaster?
❌ Exchange known to ScriptMaster?
❌ OrderType allowed for THIS instrument?
❌ Expiry tradable TODAY?
❌ Database file exists?
❌ Can supervisor provide live data?
❌ All fields consistent with universe?
```

---

## 🎯 WHERE MISSING: ConfigResolutionService

### Should Be Called At These Points

**1. Config Save (Dashboard)**
```python
@router.post("/strategy/config/save")
def save_strategy_config(payload: dict):
    resolver = ConfigResolutionService(supervisor, broker)
    resolved = resolver.resolve_and_validate_config(payload)  # ❌ MISSING
    save(resolved)
```

**2. Strategy Execution Start**
```python
@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(strategy_name: str):
    config = load_config()
    resolver = ConfigResolutionService(supervisor, broker)
    resolved = resolver.resolve_and_validate_config(config)  # ❌ MISSING
    strategy = create_strategy(resolved)
```

**3. Strategy Factory**
```python
def create_strategy(config: dict):
    # resolver.resolve_and_validate_config(config)  # ❌ NOT CALLED
    strategy = STRATEGY_REGISTRY[config["strategy_type"]](config)
```

---

## 📊 Methods That SHOULD Exist

### ConfigResolutionService

```python
class ConfigResolutionService:
    
    def resolve_and_validate_config(self, config: dict) -> dict:
        """❌ DOES NOT EXIST"""
        # Should return config with ALL these fields populated/validated:
        # - exchange, symbol, instrument_type (VALIDATED)
        # - order_type (VALIDATED for instrument)
        # - expiry (RESOLVED from ScriptMaster)
        # - db_path (DETERMINED + VALIDATED)
        # - live_option_data (RESOLVED from supervisor)
        pass
    
    def validate_instrument_exists(self, exchange: str, symbol: str) -> bool:
        """❌ DOES NOT EXIST"""
        # Check SCRIPTMASTER
        pass
    
    def validate_order_type_for_instrument(
        self, order_type: str, exchange: str, symbol: str, instrument: str
    ) -> bool:
        """❌ DOES NOT EXIST"""
        # Check broker capability + SCRIPTMASTER
        pass
    
    def resolve_expiry(
        self, exchange: str, symbol: str, instrument_type: str
    ) -> str:
        """❌ DOES NOT EXIST"""
        # Calls: _calculate_expiry() from adapter
        # BUT should be centralized here
        pass
    
    def resolve_db_path(
        self, exchange: str, symbol: str, expiry: str, market_type: str
    ) -> Optional[str]:
        """❌ DOES NOT EXIST"""
        # Replicates supervisor.py:296 db_path determination
        pass
    
    def resolve_live_option_data(
        self, exchange: str, symbol: str, expiry: str
    ):
        """❌ DOES NOT EXIST"""
        # Gets from supervisor or creates on demand
        pass
```

---

## 🔴 CRITICAL UNRESOLVED

### 1. Where Does db_path Come From?

**Current State:**
- Supervisor determines: `DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"`
- Stored in: `supervisor._chains[key]["db_path"]`
- Never returned or exposed

**Needed:**
- ConfigResolutionService.resolve_db_path() should determine it
- Should be populated in config BEFORE strategy creation
- MarketAdapterFactory should find it in config

**Flow:**
```
Dashboard/Config → resolve_db_path() → config["db_path"] → MarketAdapterFactory
```

---

### 2. Where Does live_option_data Come From?

**Current State:**
- None - not tracked in config at all
- Passed as `get_option_func` parameter to DNSS

**Needed:**
- ConfigResolutionService.resolve_live_option_data()
- Should get reference from supervisor.ensure_chain()
- Should be available to strategy

**Flow:**
```
Dashboard/Config → resolve_live_option_data() → config["live_option_data"] → Strategy
```

---

### 3. How to Know Expiry is Tradable?

**Current State:**
- _calculate_expiry() filters based on time
- But called too late (during strategy creation)

**Needed:**
- Check at CONFIG TIME
- Market might have closed today (for expiry day)
- Supervisor might not have started chain yet

**Flow:**
```
Dashboard Config → validate_expiry_tradable() → ERROR or RESOLVED_EXPIRY
```

---

## 📋 Summary Table

| Concern | Current | Solution | Priority |
|---------|---------|----------|----------|
| **Validate Symbol Exists** | None | ConfigResolutionService | 🔴 CRITICAL |
| **Validate Order Type** | validate_order_type() in utils.py | ConfigResolutionService.validate_order_type_for_instrument() | 🔴 CRITICAL |
| **Resolve Expiry** | _calculate_expiry() in adapter | ConfigResolutionService.resolve_expiry() | 🟡 HIGH |
| **Determine db_path** | Hardcoded in supervisor | ConfigResolutionService.resolve_db_path() | 🔴 CRITICAL |
| **Get live_option_data** | Not resolved | ConfigResolutionService.resolve_live_option_data() | 🟡 HIGH |
| **Pre-flight Validation** | None | Call resolver before strategy creation | 🔴 CRITICAL |
| **Config Validator Usage** | Not called | Call in dashboard save & execution start | 🟡 HIGH |

---

## 🏗️ Next Steps (In Order)

1. ✅ **Understand current flow** ← YOU ARE HERE
2. 🔲 Create ConfigResolutionService class
3. 🔲 Implement validation methods (instrument, order_type)
4. 🔲 Implement resolution methods (expiry, db_path, live_option_data)
5. 🔲 Call resolver from dashboard router (config save)
6. 🔲 Call resolver from dashboard router (strategy execution)
7. 🔲 Update config schema to include resolved fields
8. 🔲 Test complete flow end-to-end

