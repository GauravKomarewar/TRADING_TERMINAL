# Strategy System Guide

> Last verified: 2026-03-01 | Source: `shoonya_platform/strategy_runner/`

## Overview

The strategy system lives entirely in `shoonya_platform/strategy_runner/`. There is **no other strategy engine** — all old `strategy_engine`, `strategy_manager`, and `strategies/` references are obsolete.

---

## Architecture

```
                    Dashboard API
                         │
                         ▼
              StrategyExecutorService          ◄── Lifecycle manager
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   PerStrategyExecutor  ...     PerStrategyExecutor    ◄── One per strategy
          │
          ├── StrategyExecutor         ◄── Loads JSON config
          │       │
          │       ├── EntryEngine      ◄── Evaluates entry conditions, opens legs
          │       ├── AdjustmentEngine ◄── Per-rule cooldown, condition-based adjustments
          │       ├── ExitEngine       ◄── EOD/SL/TP/trailing exit logic
          │       ├── ConditionEngine  ◄── evaluates condition arrays
          │       ├── MarketReader     ◄── Market data interface
          │       └── BrokerReconciliation  ◄── Position reconciliation
          │
          ├── StrategyState            ◄── In-memory state (legs, PnL, Greeks)
          └── StatePersistence         ◄── JSON-file state snapshots
```

---

## Key Components

### StrategyExecutor (`executor.py`)

Main entry point for strategy logic. Initialized with a JSON config path:

```python
# Path is relative to the project root (shoonya_platform/)
executor = StrategyExecutor(config_path="shoonya_platform/strategy_runner/saved_configs/nifty_dnss_actual.json")
```

Internally creates: `ConditionEngine`, `EntryEngine`, `AdjustmentEngine`, `ExitEngine`, `MarketReader`, `BrokerReconciliation`.

### StrategyExecutorService (`strategy_executor_service.py` — 1785 lines)

Service-level wrapper that manages multiple strategies concurrently. Key methods:
- `register_strategy(name, config)` — Load and register a strategy
- `unregister_strategy(name)` — Stop and remove a strategy
- `start_strategy(name)` — Begin execution loop
- `stop_strategy(name)` — Graceful shutdown
- `get_strategy_status(name)` — Current status/PnL/legs

### Config Schema Validator (`config_schema.py` — 1345 lines)

Validates JSON configs against schema version 4.0:

```python
from shoonya_platform.strategy_runner.config_schema import validate_config

is_valid, issues = validate_config(config_dict)
# issues: List[ValidationError] with .severity ("error"/"warning") and .message
```

**Required top-level sections:** `schema_version`, `name`, `identity`, `timing`, `schedule`, `entry`, `exit`
**Optional sections:** `adjustment`, `rms`, `market_data`, `id`, `description`, `type`

### EntryEngine (`entry_engine.py`)

Evaluates global conditions + per-leg conditions. If all pass during the entry window, generates entry orders for each configured leg.

### AdjustmentEngine (`adjustment_engine.py`)

Processes adjustment rules with:
- **Per-rule cooldowns** — tracked in `_rule_last_fired` dict (not global state)
- **Max per day** — tracked via `state.adjustments_today`
- **Max total** — tracked via `state.lifetime_adjustments`
- **Leg guards** — skip if target leg is inactive
- **IF/ELSE branches** — each rule can have conditions + else_conditions

### ExitEngine (`exit_engine.py`)

Handles: EOD exit (at `eod_exit_time`), stop-loss, take-profit, trailing stops, manual force-exit.

### ConditionEngine (`condition_engine.py`)

Evaluates condition arrays with comparators:
- Standard: `>=`, `<=`, `==`, `!=`, `>`, `<`
- Range: `between`
- Logical: `AND`/`OR` join operators

Supports parameters: `combined_pnl`, `leg_pnl`, `delta`, `gamma`, `theta`, `vega`, `iv`, `underlying_ltp`, `india_vix`, `index_<NAME>_ltp`, `index_<NAME>_change_pct`, etc.

### StrategyState (`state.py`)

In-memory state tracking:
- `legs: Dict[str, LegState]` — active/inactive leg positions
- `adjustments_today`, `lifetime_adjustments` — counters
- `last_adjustment_time` — timestamp
- `set_index_ticks(data)` — inject index data (VIX, etc.)
- Dynamic leg references: `higher_delta_leg`, `most_profitable_leg`, `deepest_itm_leg`, etc.

### Universal Settings (`universal_settings/`)

- `universal_registry.py` — `list_strategy_templates()` — discovers all strategy configs
- `universal_strategy_reporter.py` — `build_strategy_report(strategy)` — generates status reports
- `writer.py` — `StrategyRunWriter` — persists run history to SQLite

---

## Strategy Lifecycle (Dashboard-Driven)

### 1. Create/Save Config

```
POST /dashboard/strategy/save
Body: { "name": "NIFTY_DNSS", "config": { ... } }
```

Saves to `strategy_runner/saved_configs/<name>.json`.

### 2. Start Execution

```
POST /dashboard/strategy/{name}/start-execution
```

Dashboard → StrategyControlConsumer → `bot.start_strategy_executor(name, config)` → StrategyExecutorService registers and starts the strategy loop.

### 3. Monitor

```
GET /dashboard/strategy/{name}/execution-status
GET /dashboard/strategy/all-status
```

Returns: state, PnL, active legs, Greeks, adjustments count.

### 4. Stop Execution

```
POST /dashboard/strategy/{name}/stop-execution
```

Graceful shutdown: stops the strategy loop, optionally exits positions.

### 5. Force Exit All Positions

```
POST /dashboard/strategy/{name}/force-exit
```

Immediately exits all active legs for the strategy.

---

## Adjustment Rule Example

```json
{
  "name": "delta_rebalance",
  "priority": 1,
  "cooldown_sec": 300,
  "max_per_day": 5,
  "conditions": [
    { "parameter": "combined_delta", "comparator": ">=", "value": 0.3 }
  ],
  "action": {
    "type": "close_leg",
    "close_tag": "HIGHER_DELTA_LEG"
  },
  "else_enabled": true,
  "else_conditions": [
    { "parameter": "combined_delta", "comparator": "<=", "value": -0.3 }
  ],
  "else_action": {
    "type": "close_leg",
    "close_tag": "LOWER_DELTA_LEG"
  }
}
```

**Action types:** `close_leg`, `partial_close_lots`, `reduce_by_pct`, `open_hedge`, `roll_to_next_expiry`, `convert_to_spread`, `simple_close_open_new`

---

## Strike Modes

| Mode | Required Fields | Description |
|------|----------------|-------------|
| `standard` | `strike_selection` | ATM, ITM1, OTM2, etc. |
| `exact` | `exact_strike` | Specific strike price |
| `atm_points` | `atm_offset_points` | ATM ± N points |
| `atm_pct` | `atm_offset_pct` | ATM ± N% of underlying |
| `match_leg` | `match_leg`, `match_param` | Match another leg's strike/delta |
