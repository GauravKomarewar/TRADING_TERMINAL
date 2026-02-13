# Configuration Flow - Exact Code Locations & Snippets

**Analysis Date:** 2026-02-12

---

## 1️⃣ DASHBOARD SAVES CONFIG

### Location: [router.py](shoonya_platform/api/dashboard/api/router.py#L1027)

```python
# Line 1027-1052
@router.post("/strategy/config/save")
def save_strategy_config(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Save a strategy config section (entry/adjustment/exit/rms)."""
    
    name = payload.get("name", "").strip()
    section = payload.get("section", "").strip().lower()
    config = payload.get("config")

    if not name:
        raise HTTPException(400, "Strategy name is required")
    
    if section not in _VALID_SECTIONS:  # {"identity", "entry", "adjustment", "exit", "rms"}
        raise HTTPException(400, f"Invalid section '{section}'...")
    
    if not isinstance(config, dict):
        raise HTTPException(400, "config must be a JSON object")

    slug = _slugify(name)  # Convert to safe filename
    filepath = _STRATEGY_CONFIGS_DIR / f"{slug}.json"

    # Load existing or create new
    existing = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["name"] = name
    existing[section] = config
    existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    filepath.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    logger.info("Strategy config saved: %s / %s", name, section)

    return {"saved": True, "name": name, "section": section, "file": slug + ".json"}
```

**What Happens:**
✅ Validates section is known  
✅ Validates config is dict  
✅ Saves to JSON file  
❌ **NO VALIDATION** of exchange, symbol, order_type, etc.  
❌ **NO RESOLUTION** of expiry, db_path, live_option_data  

**Missing:** Call to ConfigResolutionService

---

## 2️⃣ DASHBOARD STARTS STRATEGY EXECUTION

### Location: [router.py](shoonya_platform/api/dashboard/api/router.py#L1810)

```python
# Line 1810-1860
@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(
    strategy_name: str,
    ctx=Depends(require_dashboard_auth)
):
    """Start a specific strategy by name from saved_configs/"""
    
    try:
        runner = get_runner_singleton(ctx)
        
        # Check if strategy is already running
        if strategy_name in runner._strategies:
            logger.info(f"ℹ️ Strategy {strategy_name} already running")
            return {
                "success": False,
                "strategy_name": strategy_name,
                "message": "Strategy already running",
                "timestamp": datetime.now().isoformat()
            }
        
        # Load the strategy config from saved_configs/
        from shoonya_platform.strategies.strategy_factory import create_strategy
        
        strategy_file = STRATEGY_CONFIG_DIR / f"{strategy_name}.json"
        if not strategy_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Strategy config not found: {strategy_name}.json"
            )
        
        with open(strategy_file, 'r') as f:
            config = json.load(f)
        
        # Validate config is enabled
        if not config.get("enabled", False):
            return {
                "success": False,
                "strategy_name": strategy_name,
                "message": "Strategy is disabled in config",
                "timestamp": datetime.now().isoformat()
            }
        
        # Register and start only this strategy
        try:
            # Use factory to create strategy (respects strategy_type in config)
            strategy = create_strategy(config)
            
            # Extract market_type from config (default: live_feed_market)
            market_config = config.get("market_config", {})
            market_type = market_config.get("market_type", "live_feed_market")
            
            registered = runner.register_with_config(
                name=strategy_name,
                strategy=strategy,
                market=None,  # Market managed via market_adapter
                config=market_config,
                market_type=market_type
            )
            
            # ... rest of code
```

**What Happens:**
✅ Loads config from JSON file  
✅ Calls create_strategy(config)  
✅ Gets market_type from config  
❌ **NO VALIDATION** of config fields  
❌ **NO RESOLUTION** of missing fields  
❌ **NO PRE-FLIGHT CHECK** that everything is valid  

**Missing:** ConfigResolutionService call BEFORE create_strategy()

---

## 3️⃣ CONFIG LOADING

### Location: [strategy_control_consumer.py](shoonya_platform/execution/strategy_control_consumer.py#L430)

```python
# Line 430-470
def _load_strategy_config(self, strategy_name: str) -> dict:
    """
    Load strategy config from saved JSON file.
    
    Path: shoonya_platform/strategies/saved_configs/{slug}.json
    (saved by api/dashboard/api/router.py POST /strategy/config/save-all)
    
    Returns: Config dict with symbol, exchange, timing, risk params, etc.
    Returns: None if config not found.
    """
    try:
        # Slugify strategy name (same as frontend)
        slug = strategy_name.strip().lower()
        slug = re.sub(r'[^a-z0-9]+', '_', slug)
        slug = slug.strip('_') or 'unnamed'
        
        config_path = (
            Path(__file__).resolve().parents[2]
            / "shoonya_platform"
            / "strategies"
            / "saved_configs"
            / f"{slug}.json"
        )
        
        if not config_path.exists():
            logger.error(
                "❌ STRATEGY CONFIG NOT FOUND | %s | %s",
                strategy_name, config_path
            )
            return None
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        logger.info(
            "📋 Loaded strategy config | %s | identity=%s",
            strategy_name,
            config.get("identity", {}),
        )
        
        return config
```

**What Happens:**
✅ Loads from JSON file  
✅ Returns config dict  
❌ **NO VALIDATION** of contents  
❌ **NO RESOLUTION** of fields  

**Missing:** ConfigResolutionService call after loading

---

## 4️⃣ BUILD UNIVERSAL CONFIG (Strategy Execution Consumer)

### Location: [strategy_control_consumer.py](shoonya_platform/execution/strategy_control_consumer.py#L51)

```python
# Line 51-80
def build_universal_config(payload: dict) -> UniversalStrategyConfig:
    """Transform dashboard intent payload → UniversalStrategyConfig."""
    
    def _parse_time(val: str) -> dt_time:
        """Parse HH:MM or HH:MM:SS string to datetime.time."""
        try:
            return dt_time.fromisoformat(val)
        except (ValueError, AttributeError):
            parts = val.split(":")
            return dt_time(
                int(parts[0]), 
                int(parts[1]), 
                int(parts[2]) if len(parts) > 2 else 0
            )

    return UniversalStrategyConfig(
        strategy_name=payload["strategy_name"],
        strategy_version=payload["strategy_version"],

        exchange=payload["exchange"],
        symbol=payload["symbol"],
        instrument_type=payload["instrument_type"],  # OPTIDX/MCX/etc

        entry_time=_parse_time(payload["entry_time"]),
        exit_time=_parse_time(payload["exit_time"]),

        order_type=payload["order_type"],
        product=payload["product"],

        lot_qty=int(payload["lot_qty"]),
        params=payload.get("params", {}),

        poll_interval=float(payload.get("poll_interval", 2.0)),
        cooldown_seconds=int(payload.get("cooldown_seconds", 0)),
    )
```

**What Happens:**
✅ Parses times  
✅ Creates UniversalStrategyConfig  
❌ **NO VALIDATION** that exchange/symbol exist  
❌ **NO VALIDATION** that order_type valid  
❌ **NO RESOLUTION** of expiry or db_path  

**Missing:** ConfigResolutionService validation before this

---

## 5️⃣ STRATEGY FACTORY - CREATE STRATEGY

### Location: [strategy_factory.py](shoonya_platform/strategies/strategy_factory.py#L49)

```python
# Line 49-97
def create_strategy(config: Dict[str, Any]) -> Any:
    """
    Create a strategy instance from config.
    
    Args:
        config: Strategy configuration dict with 'strategy_type' field
        
    Returns:
        Strategy instance
    """
    _lazy_load_dnss()
    
    # Extract strategy_type (case-insensitive)
    strategy_type = config.get("strategy_type", "").strip()
    if not strategy_type:
        raise ValueError("Config missing 'strategy_type' field")
    
    # Look up in registry (case-insensitive)
    strategy_class = None
    for key, cls in STRATEGY_REGISTRY.items():
        if key.lower() == strategy_type.lower():
            strategy_class = cls
            break
    
    if strategy_class is None:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"Unknown strategy_type '{strategy_type}'. "
            f"Available: {available}"
        )
    
    # Instantiate
    try:
        strategy = strategy_class(config)
        strategy_name = config.get("strategy_name", strategy_type)
        logger.info(f"✅ Created strategy: {strategy_name} ({strategy_type})")
        return strategy
    except Exception as e:
        logger.error(f"❌ Failed to instantiate {strategy_type}: {e}")
        raise
```

**What Happens:**
✅ Looks up strategy_type in registry  
✅ Creates strategy instance  
✅ Passes config to strategy class  
❌ **NO VALIDATION** of config contents  
❌ **Config must have all required fields already**  

**Missing:** ConfigResolutionService call BEFORE instantiation

---

## 6️⃣ DNSS ADAPTER - CREATE FROM UNIVERSAL CONFIG

### Location: [delta_neutral/adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py#L31)

```python
# Line 31-115
def create_dnss_from_universal_config(
    universal_config: UniversalStrategyConfig,
    market,  # DBBackedMarket instance
    get_option_func: Optional[Callable] = None,
    expiry: Optional[str] = None,
) -> DeltaNeutralShortStrangleStrategy:
    """Convert UniversalStrategyConfig to DNSS Strategy Instance"""
    
    # Validate input
    if not universal_config:
        raise ValueError("UniversalStrategyConfig required")
    
    if not market:
        raise ValueError("DBBackedMarket instance required")
    
    # Extract DNSS-specific parameters
    params = universal_config.params or {}
    
    # Validate required DNSS parameters exist
    required_params = [
        "target_entry_delta",
        "delta_adjust_trigger",
        "max_leg_delta",
        "profit_step",
        "cooldown_seconds",
    ]
    
    missing = [p for p in required_params if p not in params]
    if missing:
        raise ValueError(f"Missing required DNSS params: {missing}")
    
    # Create DNSS-specific strategy config
    dnss_config = StrategyConfig(
        entry_time=universal_config.entry_time,
        exit_time=universal_config.exit_time,
        
        target_entry_delta=float(params["target_entry_delta"]),
        delta_adjust_trigger=float(params["delta_adjust_trigger"]),
        max_leg_delta=float(params["max_leg_delta"]),
        
        profit_step=float(params["profit_step"]),
        cooldown_seconds=int(params["cooldown_seconds"]),
    )
    
    # Get option selection function
    if get_option_func is None:
        get_option_func = market.get_nearest_option
    
    # Calculate current expiry if not provided
    if expiry is None:
        expiry_mode = params.get("expiry_mode", "weekly_current")
        expiry = _calculate_expiry(
            exchange=universal_config.exchange,
            symbol=universal_config.symbol,
            expiry_mode=expiry_mode
        )
    
    # Create and return fully initialized DNSS strategy
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=universal_config.exchange,
        symbol=universal_config.symbol,
        expiry=expiry,
        lot_qty=universal_config.lot_qty,
        get_option_func=get_option_func,
        config=dnss_config,
    )
    
    return strategy
```

**What Happens:**
✅ Validates required DNSS params  
✅ Calls _calculate_expiry() → queries ScriptMaster ✅  
✅ Creates DeltaNeutralShortStrangleStrategy  
❌ **No db_path available**  
❌ **No live_option_data reference**  
❌ **No validation that symbol exists in ScriptMaster**  

**Missing:** pre-flight validation before this point

---

## 7️⃣ EXPIRY RESOLUTION IN ADAPTER (ONLY PLACE IT HAPPENS)

### Location: [delta_neutral/adapter.py](shoonya_platform/strategies/standalone_implementations/delta_neutral/adapter.py#L130)

```python
# Line 130-180
def _calculate_expiry(exchange: str, symbol: str, expiry_mode: str) -> str:
    """
    Get current option expiry from ScriptMaster (NOT date calculation)
    
    DNSS trades option strangles, so we query OPTION expiries, not futures.
    ScriptMaster has the ACTUAL expiry dates per exchange:
    - NFO NIFTY: Weekly Thursdays
    - MCX CRUDEOILM: Different dates (17-FEB, 17-MAR, 16-APR, etc.)
    - MCX has no fixed day pattern - use scriptmaster truth
    
    Args:
        exchange: "NFO", "BFO", or "MCX"
        symbol: "NIFTY", "BANKNIFTY", "CRUDEOILM", etc.
        expiry_mode: "weekly_current" or "monthly_current" (hint for selection)
    
    Returns:
        Expiry date string in format "12FEB2026" (from ScriptMaster)
    
    Raises:
        ValueError: If no option expiry found for the symbol
    """
    try:
        exchange = exchange.upper()
        symbol = symbol.upper()
        
        # Query ScriptMaster for ACTUAL option expiry dates
        expiries = options_expiry(symbol, exchange)
        
        if not expiries:
            raise ValueError(
                f"No option expiries found for {symbol} on {exchange}. "
                f"Check if instrument is tradable."
            )
        
        # Find appropriate expiry based on mode
        today = date.today()
        today_str = today.strftime("%d-%b-%Y").upper()
        
        # Filter expiries >= today (upcoming expiries only)
        upcoming = []
        for exp_str in expiries:
            try:
                exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                if exp_date >= today:
                    upcoming.append(exp_str)
            except ValueError:
                continue
        
        if not upcoming:
            # No upcoming expiry today, use first available
            upcoming = expiries
        
        # Select based on mode
        if expiry_mode == "weekly_current":
            # For weekly: use 1st upcoming expiry (nearest)
            selected = upcoming[0]
        elif expiry_mode == "monthly_current":
            # For monthly: find the LAST expiry of current month
            current_month = today.month
            current_year = today.year
            
            month_expiries = []
            for exp_str in upcoming:
                try:
                    exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                    if exp_date.month == current_month and exp_date.year == current_year:
                        month_expiries.append(exp_str)
                except ValueError:
                    continue
            
            if month_expiries:
                # Use last expiry of current month
                selected = month_expiries[-1]
            else:
                # No monthly expiry in current month, use first upcoming
                selected = upcoming[0]
        else:
            # Default: first upcoming
            selected = upcoming[0]
        
        # Return in format "12FEB2026" (uppercase, no dashes)
        return selected.replace("-", "").upper()
    
    except Exception as e:
        raise ValueError(
            f"Failed to get option expiry for {symbol} on {exchange}: {e}"
        )
```

**What Happens:**
✅ Queries ScriptMaster via options_expiry(symbol, exchange)  
✅ Filters tradable expiries (after market close)  
✅ Selects based on mode  
✅ Returns expiry string  
❌ **Called too late** (during strategy creation, not validation)  
❌ **Not in central ConfigResolutionService**  
❌ **No validation that symbol exists BEFORE calling options_expiry()**  

---

## 8️⃣ MARKET ADAPTER FACTORY

### Location: [market_adapter_factory.py](shoonya_platform/strategies/market_adapter_factory.py#L19)

```python
# Line 19-97
class MarketAdapterFactory:
    """Factory for creating appropriate market adapter."""

    @staticmethod
    def create(
        market_type: Literal["database_market", "live_feed_market"],
        config: Dict[str, Any],
    ) -> Any:
        """
        Create market adapter based on market_type.
        
        Args:
            market_type: "database_market" or "live_feed_market"
            config: Strategy config with exchange, symbol, db_path, etc.
            
        Returns:
            Initialized adapter instance (DatabaseMarketAdapter or LiveFeedMarketAdapter)
        """
        
        exchange = config.get("exchange")
        symbol = config.get("symbol")
        
        if not exchange or not symbol:
            raise ValueError("Config must have 'exchange' and 'symbol'")
        
        # ========================================================
        # LATCH: Select market backend
        # ========================================================
        
        if market_type == "database_market":
            logger.info(f"🔄 Selecting: DATABASE_MARKET for {exchange}:{symbol}")
            
            db_path = config.get("db_path")
            if not db_path:
                raise ValueError("database_market requires 'db_path' in config")
            
            # Verify database exists
            if not Path(db_path).exists():
                raise FileNotFoundError(f"Database not found: {db_path}")
            
            # Import here to avoid circular imports
            from shoonya_platform.strategies.database_market.adapter import (
                DatabaseMarketAdapter,
            )
            
            adapter = DatabaseMarketAdapter(
                db_path=db_path,
                exchange=exchange,
                symbol=symbol,
            )
            logger.info(f"✓ Database adapter initialized for {exchange}:{symbol}")
            return adapter
        
        elif market_type == "live_feed_market":
            logger.info(f"🔄 Selecting: LIVE_FEED_MARKET for {exchange}:{symbol}")
            
            # Import here to avoid circular imports
            from shoonya_platform.strategies.live_feed_market.adapter import (
                LiveFeedMarketAdapter,
            )
            
            adapter = LiveFeedMarketAdapter(
                exchange=exchange,
                symbol=symbol,
            )
            logger.info(f"✓ Live feed adapter initialized for {exchange}:{symbol}")
            return adapter
        
        else:
            raise ValueError(
                f"Unknown market_type: {market_type}. "
                f"Must be 'database_market' or 'live_feed_market'"
            )
```

**What Happens:**
✅ Validates exchange & symbol present  
✅ For database_market: Checks db_path required  
✅ Validates db_path file exists  
❌ **db_path must already be in config**  
❌ **No check that db_path is CORRECT for this exchange/symbol/expiry**  
❌ **No live_option_data source for live_feed_market**  

**Critical Issue:** WHERE DOES db_path COME FROM IN CONFIG?

---

## 9️⃣ SUPERVISOR - DB_PATH DETERMINATION

### Location: [supervisor.py](shoonya_platform/market_data/option_chain/supervisor.py#L287)

```python
# Line 187-340
def _start_chain(
    self, 
    exchange: str, 
    symbol: str, 
    expiry: str,
    retry: bool = True,
) -> bool:
    """
    Start option chain with retry logic and failure tracking.
    
    Args:
        exchange: NFO / BFO / MCX
        symbol: Underlying symbol
        expiry: Option expiry
        retry: Enable retry with exponential backoff
        
    Returns:
        True if successful, False otherwise
    """
    key = f"{exchange}:{symbol}:{expiry}"

    with self._lock:
        if key in self._chains:
            return True
        
        # Check if recently failed
        if key in self._failed_chains:
            last_attempt, attempt_count = self._failed_chains[key]
            
            # Exponential backoff: 2s, 4s, 8s, 16s, 32s
            backoff = min(
                CHAIN_RETRY_BASE_DELAY * (2 ** min(attempt_count, 5)), 60
            )
            
            if time.time() - last_attempt < backoff:
                logger.debug(
                    "Chain %s in backoff period (%.0fs remaining)",
                    key, backoff - (time.time() - last_attempt)
                )
                return False

    logger.info(
        "🚀 Starting option chain | %s %s | Expiry=%s",
        exchange, symbol, expiry
    )

    # Retry logic with exponential backoff
    max_attempts = MAX_CHAIN_RETRY_ATTEMPTS if retry else 1
    
    for attempt in range(1, max_attempts + 1):
        try:
            oc = live_option_chain(
                api_client=self.api_client,
                exchange=exchange,
                symbol=symbol,
                expiry=expiry,
                auto_start_feed=False,  # Feed is owned by ShoonyaBot
            )
            
            # Success!
            # ⚠️ DB_PATH DETERMINED HERE:
            db_path = (
                DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
            )

            store = OptionChainStore(db_path)

            with self._lock:
                self._chains[key] = {
                    "oc": oc,
                    "store": store,
                    "db_path": db_path,
                    "start_time": time.time(),
                    "last_health_check": time.time(),
                }
                
                # Clear from failed chains
                self._failed_chains.pop(key, None)
            
            logger.info("✅ Option chain started | %s", key)
            return True

        except Exception as e:
            logger.warning(
                "⚠️ Chain start attempt %d/%d failed | %s | %s",
                attempt, max_attempts, key, str(e)
            )
            # ... retry logic ...
```

**What Happens:**
✅ Determines db_path:  `DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"`  
✅ Creates OptionChainStore with db_path  
✅ Stores in _chains dict  
❌ **db_path NEVER RETURNED OR EXPOSED**  
❌ **Not available to strategy config**  
❌ **Caller doesn't know where db_path is**  

**CRITICAL PROBLEM:**
```python
db_path = DB_BASE_DIR / f"{exchange}_{symbol}_{expiry}.sqlite"
# ↑ ONLY KNOWN INSIDE SUPERVISOR
# ↓ NEVER PASSED TO STRATEGY CONFIG
```

---

## 🔟 VALIDATION STRUCTURES

### Schema Validation (Minimal)

**Location:** [schemas.py](shoonya_platform/api/dashboard/api/schemas.py#L188)

```python
# Line 188-250
class StrategyEntryRequest(BaseModel):
    """Strategy-scoped control intent."""

    strategy_name: str = Field(
        ..., min_length=1, description="Registered strategy name"
    )

    action: StrategyAction = Field(
        ..., description="ENTRY / EXIT / ADJUST / FORCE_EXIT"
    )

    reason: Optional[str] = "DASHBOARD_STRATEGY"


class StrategyEntryRequest(BaseModel):
    strategy_name: str
    strategy_version: str

    exchange: Exchange  # Enum validation only
    symbol: str
    instrument_type: str   # OPTIDX / OPTSTK / FUT / MCX

    entry_time: str        # ISO time
    exit_time: str

    order_type: OrderType  # Enum: MARKET, LIMIT, STOP, STOP_LIMIT
    product: Product       # Enum: NRML, MIS, CNC

    lot_qty: int
    params: dict

    poll_interval: Optional[float] = 2.0
    cooldown_seconds: Optional[int] = 0
    
    @model_validator(mode="after")
    def validate_time_fields(self):
        try:
            time.fromisoformat(self.entry_time)
            time.fromisoformat(self.exit_time)
        except Exception:
            raise ValueError(
                "entry_time and exit_time must be ISO time only (HH:MM:SS)"
            )
        return self
        
    @model_validator(mode="after")
    def validate_dnss_contract(self):
        """Validate DNSS-specific params only for DNSS strategies."""
        name_lower = (self.strategy_name or "").lower()
        version_lower = (self.strategy_version or "").lower()
        is_dnss = "dnss" in name_lower or "dnss" in version_lower
        if is_dnss:
            # ... DNSS param validation ...
        return self
```

**What It Does:**
✅ Type checking (exchange is Exchange enum, lot_qty is int)  
✅ Time format validation (ISO format)  
✅ DNSS-specific param validation  
❌ **Doesn't check exchange exists in ScriptMaster**  
❌ **Doesn't check symbol exists**  
❌ **Doesn't check order_type for THIS instrument**  
❌ **Not called during config save**  

---

### Strategy Config Validator (Schema Only)

**Location:** [strategy_config_validator.py](shoonya_platform/strategies/strategy_config_validator.py#L85)

```python
# Line 85-180
class StrategyConfigValidator:
    """Validate strategy configuration"""
    
    # Valid enum values
    VALID_MARKET_TYPES = ["database_market", "live_feed_market"]
    VALID_EXCHANGES = ["NFO", "MCX", "NCDEX", "CDSL"]
    VALID_ENTRY_TYPES = ["delta_neutral", "directional", "calendar_spread", "butterfly", "iron_condor"]
    VALID_ADJUSTMENT_TYPES = ["delta_drift", "stop_loss_triggered", "time_decay", "vega_spike"]
    VALID_EXIT_TYPES = ["profit_target", "stop_loss", "time_based", "manual"]
    VALID_ORDER_TYPES = ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
    VALID_PRODUCTS = ["NRML", "MIS", "CNC"]
    
    def validate(self, config: Dict[str, Any], config_name: Optional[str] = None) -> ValidationResult:
        """
        Validate strategy configuration comprehensively.
        
        Args:
            config: Strategy configuration dictionary
            config_name: Name of strategy (optional)
            
        Returns:
            ValidationResult with errors and warnings
        """
        name = config_name or config.get("name", "UNKNOWN")
        self.result = ValidationResult(name)
        
        logger.info(f"🔍 Validating strategy: {name}")
        
        try:
            # Phase 1: Basic structure
            self._validate_basic_structure(config)
            if self.result.errors:
                return self.result
            
            # Phase 2: Required fields
            self._validate_required_fields(config)
            
            # Phase 3: Market config
            self._validate_market_config(config.get("market_config", {}))
            
            # Phase 4: Entry config
            self._validate_entry_config(config.get("entry", {}))
            
            # Phase 5: Exit config
            self._validate_exit_config(config.get("exit", {}))
            
            # Phase 6: Optional configs
            self._validate_adjustment_config(config.get("adjustment", {}))
            self._validate_execution_config(config.get("execution", {}))
            self._validate_risk_management_config(config.get("risk_management", {}))
            
            # Phase 7: Smart cross-field validation
            self._validate_cross_fields(config)
            
            # Summary
            if self.result.valid:
                self.result.add_info(f"✅ Configuration is valid")
                logger.info(f"✅ {name} validation PASSED")
            else:
                logger.error(f"❌ {name} validation FAILED ({len(self.result.errors)} errors)")
        
        except Exception as e:
            self.result.add_error("_general", f"Validation error: {str(e)}", "system_error")
```

**What It Does:**
✅ Schema validation (types, enums, structure)  
✅ Value range checking  
❌ **Doesn't connect to ScriptMaster**  
❌ **Not called during config save**  
❌ **Not called during strategy execution**  

**Usage:**
```python
result = validate_strategy(config, "MY_STRATEGY")
print(result.to_dict())
```

**BUT:** This is NEVER CALLED in the dashboard or execution flow!

---

## ⚠️ CRITICAL MISSING CALL POINTS

### Missing Call #1: Config Save (dashboard)

```python
# CURRENT: router.py:1027
@router.post("/strategy/config/save")
def save_strategy_config(payload: dict):
    # ✅ Validates section enum
    # ✅ Validates config is dict
    # ❌ MISSING: resolver.resolve_and_validate_config(payload)
    
    existing["name"] = name
    existing[section] = config
    filepath.write_text(...)  # Save UNRESOLVED config
```

**Should Be:**
```python
@router.post("/strategy/config/save")
def save_strategy_config(payload: dict):
    # NEW: Resolve & validate
    resolver = ConfigResolutionService(supervisor, broker)
    resolved = resolver.resolve_and_validate_config(payload)  # ← MISSING
    
    existing["name"] = name
    existing.update(resolved)  # Save RESOLVED config
    filepath.write_text(...)
```

---

### Missing Call #2: Strategy Execution Start (dashboard)

```python
# CURRENT: router.py:1810
@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(strategy_name: str):
    config = json.load(config_path)  # Load config
    # ❌ MISSING: resolver.resolve_and_validate_config(config)
    
    strategy = create_strategy(config)  # Config may be incomplete!
    # ← Strategy creation may fail with db_path missing
```

**Should Be:**
```python
@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(strategy_name: str):
    config = json.load(config_path)
    
    # NEW: Resolve & validate
    resolver = ConfigResolutionService(supervisor, broker)
    resolved = resolver.resolve_and_validate_config(config)  # ← MISSING
    
    strategy = create_strategy(resolved)  # Now has all fields
```

---

### Missing Call #3: Strategy Factory

```python
# CURRENT: strategy_factory.py:49
def create_strategy(config: Dict[str, Any]):
    # ❌ MISSING: resolver.resolve_and_validate_config(config)
    
    strategy_class = STRATEGY_REGISTRY.get(strategy_type.lower())
    # Creates strategy - may fail if config incomplete
    return strategy_class(config)
```

**Should Be:**
```python
def create_strategy(config: Dict[str, Any]):
    # Ensure config is resolved
    if "db_path" not in config and config.get("market_type") == "database_market":
        resolve_config(config)  # ← MISSING
    
    strategy_class = STRATEGY_REGISTRY.get(strategy_type.lower())
    return strategy_class(config)
```

---

## SUMMARY: What's Missing vs. What Exists

| Component | Exists | Where | Status |
|-----------|--------|-------|--------|
| **OrderTypeValidation** | ❌ | validate_order_type() | Basic only (no instrument check) |
| **SymbolExistence** | ❌ | None | Missing |
| **ExpiryResolution** | ✅ | _calculate_expiry() in adapter | Wrong place (too late) |
| **ExpiryValidation** | ❌ | None | Missing |
| **db_pathDetermination** | ✅ | supervisor.py:296 | Not exposed to config |
| **db_pathValidation** | ⚠️ | MarketAdapterFactory | Only file existence |
| **live_option_dataResolution** | ❌ | None | Missing |
| **ConfigResolutionService** | ❌ | None | **DOES NOT EXIST** |
| **PreflightValidation** | ❌ | None | Missing |
| **CallPoints** | ❌ | None | Not integrated |

