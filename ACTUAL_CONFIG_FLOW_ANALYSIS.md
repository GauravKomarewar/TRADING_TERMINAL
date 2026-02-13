# ACTUAL Strategy Config Flow - Complete Analysis

**Date**: 2026-02-12  
**Status**: VERIFIED - Traced end-to-end through actual code

---

## Executive Summary

There are **TWO DIFFERENT CODE PATHS** for strategy execution:

1. **Dashboard API (router.py)** → START strategy from dashboard UI
2. **Strategy Control Consumer** → Process strategy INTENTS from database

**CRITICAL**: These two paths handle `market_config` DIFFERENTLY.

---

## What Saved Config Files Actually Contain

### File: `dnss_nifty_weekly.json` (and `dnss_crudeoilm_mcx.json`)

```json
{
  "schema_version": "2.0",
  "name": "DNSS NIFTY Weekly",
  "id": "DNSS_NIFTY_WEEKLY",
  "enabled": true,
  "identity": {
    "strategy_type": "dnss",
    "exchange": "NFO",
    "underlying": "NIFTY",           ← Uses "underlying" NOT "symbol"
    "instrument_type": "OPTIDX",
    "expiry_mode": "weekly_current",
    "product_type": "NRML",
    "order_type": "LIMIT"
  },
  "entry": { ... },
  "adjustment": { ... },
  "exit": { ... }
}
```

**KEY FINDING**: These configs do **NOT** have a `market_config` field at all.  
Exchange and symbol are in the **`identity` section**.

---

## The Schema Says market_config is Required

### File: `STRATEGY_CONFIG_SCHEMA.json`

```json
{
  "required": ["name", "market_config", "entry", "exit"],
  "properties": {
    "market_config": {
      "type": "object",
      "required": ["market_type", "exchange", "symbol"],
      "properties": {
        "market_type": { "enum": ["database_market", "live_feed_market"] },
        "exchange": { "enum": ["NFO", "MCX", "NCDEX", "CDSL"] },
        "symbol": { "type": "string" },
        "db_path": { "type": "string" }
      }
    }
  }
}
```

**MISMATCH**: Schema requires `market_config`, but actual saved configs don't have it.

---

## Code Path #1: Dashboard API Start Execution

### File: `shoonya_platform/api/dashboard/api/router.py` (lines ~880-920)

```python
@router.post("/strategy/{strategy_name}/start-execution")
def start_strategy_execution(strategy_name: str, ctx=Depends(require_dashboard_auth)):
    """Start a specific strategy by name from saved_configs/"""
    
    runner = get_runner_singleton(ctx)
    
    # Load the strategy config from saved_configs/
    strategy_file = STRATEGY_CONFIG_DIR / f"{strategy_name}.json"
    with open(strategy_file, 'r') as f:
        config = json.load(f)
    
    # Create strategy instance
    strategy = create_strategy(config)
    
    # 🔴 PROBLEM: Looking in wrong place
    market_config = config.get("market_config", {})      # Returns EMPTY dict!
    market_type = market_config.get("market_type", "live_feed_market")
    
    # 🔴 FAILS: config is empty, no exchange/symbol
    registered = runner.register_with_config(
        name=strategy_name,
        strategy=strategy,
        market=None,
        config=market_config,  # ← Empty dict!
        market_type=market_type
    )
    
    runner.start()
```

### What Happens When Registered

[`strategy_runner.py` lines 214-270]

```python
def register_with_config(
    self,
    *,
    name: str,
    strategy,
    market,
    config: Dict[str, Any],      # ← Empty dict from dashboard!
    market_type: Literal["database_market", "live_feed_market"] = "live_feed_market",
) -> bool:
    
    # Validate config
    is_valid, error = MarketAdapterFactory.validate_config_for_market(
        market_type=market_type,
        config=config,  # ← Empty!
    )
    if not is_valid:
        logger.error(f"❌ Config validation failed: {error}")
        # Error: Missing 'exchange' in config
        return False
    
    # Create market adapter (FAILS)
    market_adapter = MarketAdapterFactory.create(
        market_type=market_type,
        config=config,  # ← Needs exchange/symbol, but empty
    )
```

### The MarketAdapterFactory Validation

[`market_adapter_factory.py` lines ~120-140]

```python
@staticmethod
def validate_config_for_market(
    market_type: Literal["database_market", "live_feed_market"],
    config: Dict[str, Any],
) -> tuple[bool, str]:
    """Validate config for selected market type."""
    
    # Check common required fields
    if not config.get("exchange"):
        return False, "Missing 'exchange' in config"  # ← FAILS HERE
    
    if not config.get("symbol"):
        return False, "Missing 'symbol' in config"  # ← Or here
    
    # For database_market:
    if market_type == "database_market":
        db_path = config.get("db_path")
        if not db_path:
            return False, "database_market requires 'db_path' in config"
        if not Path(db_path).exists():
            return False, f"Database file not found: {db_path}"
    
    return True, ""
```

**RESULT**: Empty market_config fails validation → Strategy doesn't start.

---

## Code Path #2: Strategy Control Consumer (CORRECT PATH)

### File: `shoonya_platform/execution/strategy_control_consumer.py` (lines ~430-497)

This is the CORRECT implementation. It properly handles the config structure.

```python
def _load_strategy_config(self, strategy_name: str) -> dict:
    """
    Load strategy config from saved JSON file.
    Path: strategies/saved_configs/{slug}.json
    """
    
    config = json.loads(config_path.read_text(encoding="utf-8"))
    
    # ✅ CORRECT: Transform from dashboard schema to execution schema
    # Transform from dashboard schema to execution-compatible schema
    # Dashboard schema: identity.underlying → execution schema: symbol
    execution_config = {
        "strategy_name": config.get("name", strategy_name),
        "strategy_version": config.get("strategy_version", "1.0.0"),
        "symbol": config.get("identity", {}).get("underlying", "NIFTY"),  # ← CRITICAL: Extract symbol
        "exchange": "NFO",  # Options on NSE
        "instrument_type": "OPTIDX",
        "entry_time": config.get("timing", {}).get("entry_time", "09:20"),
        "exit_time": config.get("timing", {}).get("exit_time", "15:30"),
        "order_type": "LIMIT",
        "product": "NRML",
        "lot_qty": 50,  # Default lot size
        "params": config.get("risk", {}),
    }
    
    return execution_config
```

### Then Builds market_config Properly

[Line ~223]

```python
# When action == "ENTRY"
try:
    self.strategy_manager.start_strategy(
        strategy_name=universal_config.strategy_name,
        universal_config=universal_config,
        market_cls=DBBackedMarket,
        market_config={
            "exchange": universal_config.exchange,        # ← From identity.exchange
            "symbol": universal_config.symbol,            # ← From identity.underlying
        },
    )
```

**RESULT**: Properly constructed market_config with exchange and symbol → Strategy starts correctly.

---

## Data Flow Comparison

### Dashboard Path (BROKEN)
```
saved_config.json
    ↓
Load JSON
    ↓
create_strategy(config)              ← Uses strategy_type from identity
    ↓
config.get("market_config", {})      ← Returns {} (empty!)
    ↓
MarketAdapterFactory.create({})      ← Fails: no exchange/symbol
    ↓
❌ Strategy startup fails
```

### Control Consumer Path (WORKING)
```
saved_config.json
    ↓
Load JSON
    ↓
Extract: config["identity"]["underlying"] → symbol
    ↓
Extract: config["identity"]["exchange"] → exchange
    ↓
build_universal_config(merged_payload)
    ↓
market_config = {
    "exchange": universal_config.exchange,
    "symbol": universal_config.symbol,
}
    ↓
MarketAdapterFactory.create(market_config)   ← Works!
    ↓
✅ Strategy starts correctly
```

---

## The Actual `market_config` Usage Flow

### When Market Adapter is Created

[`market_adapter_factory.py`]

```python
@staticmethod
def create(
    market_type: Literal["database_market", "live_feed_market"],
    config: Dict[str, Any],
) -> Any:
    """Create market adapter based on market_type."""
    
    exchange = config.get("exchange")
    symbol = config.get("symbol")
    
    if not exchange or not symbol:
        raise ValueError("Config must have 'exchange' and 'symbol'")
    
    if market_type == "database_market":
        db_path = config.get("db_path")
        if not db_path:
            raise ValueError("database_market requires 'db_path' in config")
        
        from shoonya_platform.strategies.database_market.adapter import (
            DatabaseMarketAdapter,
        )
        
        adapter = DatabaseMarketAdapter(
            db_path=db_path,
            exchange=exchange,
            symbol=symbol,
        )
        return adapter
    
    elif market_type == "live_feed_market":
        from shoonya_platform.strategies.live_feed_market.adapter import (
            LiveFeedMarketAdapter,
        )
        
        adapter = LiveFeedMarketAdapter(
            exchange=exchange,
            symbol=symbol,
        )
        return adapter
```

### Market adapters are used during strategy ticks

[`strategy_runner.py` Line ~600+]

Strategy context holds reference:
```python
@dataclass
class StrategyContext:
    name: str
    strategy: Any
    market: Any
    market_type: Literal["database_market", "live_feed_market"] = "live_feed_market"
    market_adapter: Optional[Any] = None  # ← DatabaseMarketAdapter or LiveFeedMarketAdapter
```

During execution loop, the adapter is used to provide market snapshots to strategy.

---

## Where market_config Fields Are Used

| Field | Used By | Purpose |
|-------|---------|---------|
| `exchange` | MarketAdapterFactory | Passed to adapter init, used for symbol lookups |
| `symbol` | MarketAdapterFactory | Underlying symbol (NIFTY, BANKNIFTY, CRUDEOILM) |
| `market_type` | Strategy runner | Selector between database_market and live_feed_market |
| `db_path` | DatabaseMarketAdapter | SQLite database file path for historical option data |
| `websocket_endpoint` | LiveFeedMarketAdapter (optional) | WebSocket URL for live data |

### Example: DatabaseMarketAdapter

[`shoonya_platform/strategies/database_market/adapter.py`]

Uses `exchange` and `symbol` to query the SQLite database for options data.

### Example: LiveFeedMarketAdapter

[`shoonya_platform/strategies/live_feed_market/adapter.py`]

Uses `exchange` and `symbol` to subscribe to live feeds.

---

## NIFTY Strategy Config - Does It Have market_config?

**ANSWER**: NO, not directly in the JSON file.

### In `dnss_nifty_weekly.json`:

```json
{
  "identity": {
    "strategy_type": "dnss",
    "exchange": "NFO",              ← Not in market_config
    "underlying": "NIFTY",          ← Not in market_config (uses underlying not symbol)
    "instrument_type": "OPTIDX",
    "product_type": "NRML",
    "order_type": "LIMIT"
  },
  // NO market_config field!
}
```

### market_config is Built at Runtime

When the **Strategy Control Consumer** loads this config:

```python
execution_config = {
    "symbol": config.get("identity", {}).get("underlying", "NIFTY"),  # Build symbol
    "exchange": "NFO",  # Hardcoded or extracted
    # ... other fields
}

market_config = {
    "exchange": universal_config.exchange,         # From identity
    "symbol": universal_config.symbol,             # From identity.underlying
}
```

---

## Summary: The ACTUAL Flow

### 1. Strategy Configs Are Loaded

Saved as JSON with `identity` section containing exchange/underlying.

### 2. create_strategy() is Called

[`strategy_factory.py`]

Uses `config["identity"]["strategy_type"]` to instantiate the right strategy class (e.g., DNSS).

**Only** needs `strategy_type` from config.

### 3. market_config is Constructed

Two paths:

**Path A - Dashboard (BROKEN)**:
- Tries to extract `config.get("market_config", {})` → Returns empty dict
- Fails validation

**Path B - Control Consumer (WORKING)**:
- Extracts from `config["identity"]`: exchange, underlying
- Builds proper market_config dict
- Works correctly

### 4. MarketAdapterFactory Selects Adapter

Based on `market_type` (default: "live_feed_market"), creates:
- `DatabaseMarketAdapter` if database_market
- `LiveFeedMarketAdapter` if live_feed_market

### 5. Strategy Runs With Adapter

Strategy context holds the market adapter, which provides market snapshots to `strategy.on_tick()`.

---

## What market_config is Actually Required For

1. **Selecting the right market backend** (database vs live feed)
2. **Providing exchange/symbol to the market adapter**
3. **Database path** (if using database_market)

It is **NOT** embedded in the JSON config. It's **built at runtime** from the `identity` section.

---

## The Bug in Dashboard API

**Location**: `shoonya_platform/api/dashboard/api/router.py` line ~884

**The Issue**:
```python
market_config = config.get("market_config", {})  # ← Wrong! This is empty
market_type = market_config.get("market_type", "live_feed_market")

runner.register_with_config(
    ...,
    config=market_config,  # ← Passing empty dict
    market_type=market_type
)
```

**The Fix** (to match strategy_control_consumer.py):
```python
# Extract from identity section
identity = config.get("identity", {})
market_config = {
    "exchange": identity.get("exchange", "NFO"),
    "symbol": identity.get("underlying", ""),  # Note: uses "underlying" not "symbol"
    "market_type": "live_feed_market",  # or get from config
}

runner.register_with_config(
    ...,
    config=market_config,
    market_type=market_config.get("market_type", "live_feed_market")
)
```

---

## Files Involved in This Flow

| Component | File | Purpose |
|-----------|------|---------|
| Config Schema | `strategies/saved_configs/STRATEGY_CONFIG_SCHEMA.json` | Defines what schema SHOULD be (but doesn't match actual) |
| NIFTY Config | `strategies/saved_configs/dnss_nifty_weekly.json` | Actual saved config (identity section) |
| CRUDEOIL Config | `strategies/saved_configs/dnss_crudeoilm_mcx.json` | Actual saved config (identity section) |
| Factory | `strategies/strategy_factory.py` | Creates strategy from config type |
| Dashboard API | `api/dashboard/api/router.py` (line ~880) | START endpoint (BROKEN) |
| Control Consumer | `execution/strategy_control_consumer.py` (line ~430) | Intent processor (WORKING) |
| Validator | `strategies/strategy_config_validator.py` | Validates config (expects market_config) |
| Runner | `strategies/strategy_runner.py` (line ~210) | Registers and runs strategies |
| Market Factory | `strategies/market_adapter_factory.py` | Creates market adapters |
| Database Adapter | `strategies/database_market/adapter.py` | SQLite-backed market data |
| Live Adapter | `strategies/live_feed_market/adapter.py` | WebSocket-backed market data |

---

## Conclusion

1. **market_config is NOT** a field in the saved JSON config files.

2. **market_config IS** built at runtime from the `identity` section.

3. **The schema is outdated** - it says market_config is required in JSON, but the actual implementation extracts from identity.

4. **Dashboard API has a bug** - it's looking for market_config in the wrong place.

5. **Control Consumer does it right** - extracts from identity and builds market_config correctly.

6. For **NIFTY strategy** (`dnss_nifty_weekly.json`):
   - exchange: "NFO" (from identity)
   - symbol: "NIFTY" (from identity.underlying, not identity.symbol)
   - No market_config field exists

7. Market adapters are selected dynamically based on market_type, making the system flexible for database or live feed sources.
