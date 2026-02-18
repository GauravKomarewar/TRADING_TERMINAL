# Perfect Strategy Builder User Guide

File covered: `perfect_strategy_builder.html`

## 1. Purpose
The Strategy Builder lets you design full options strategies with:
- Strategy identity and market data source
- Entry logic per leg
- Combined (strategy-level) IF/ELSE gates
- Adjustment rules
- Exit and risk controls
- Schedule controls

This guide explains every field, how logic is evaluated, and how to avoid conflicting setups.

## 2. Core Logic Model

### 2.1 Building blocks
- Condition row: `Parameter + Comparator + Value`
- Condition block: one or more rows joined with `AND/OR`
- Grouped blocks: multiple condition blocks joined with `AND/OR`
- Branches: `IF` and optional `ELSE`

### 2.2 Combined vs leg conditions
- Combined conditions are strategy-level context.
- Leg conditions are per-leg rules.
- Builder imports combined blocks into each leg/rule using `condition_imports` and merged `*_block` values.
- UI restore separates imported combined logic from user leg logic, so no hidden double-overrides in editor.

### 2.3 Important consistency rules in this version
- Entry combined gate is not duplicated at top-level runtime condition payload.
- Combined IF/ELSE are persisted under `combined_conditions` and action details metadata.
- Nested logic trees are flattened recursively for compatibility outputs.

## 3. Top Bar Actions
- `Import`: Load local JSON strategy file into builder.
- `Load`: Load saved strategy from server list.
- `Reset`: Clear current form and reset defaults.
- `Save`: Validate and save strategy to backend (`PUT`, fallback `POST create`).
- `Close`: Return to strategy list page.

## 4. Tabs and Parameters

## 4.1 Identity Tab

### Strategy Name
- Required.
- Human-readable strategy name.

### Strategy ID (auto)
- Auto-generated uppercase slug from name.
- Used as internal ID if not manually changed.

### Lot Multiplier
- Numeric multiplier for strategy lot sizing.

### Symbol
- Underlying symbol (loaded from active symbols API).

### DB File (.sqlite)
- Option chain database file for symbol/expiry.

### Expiry (from DB file)
- Parsed from DB filename.

### Exchange
- Auto-filled from symbol / DB file.

### Product Type
- `MIS`, `NRML`, `CNC`.

### Order Type
- Global default order type: `MARKET`, `LIMIT`, `SL`, `SLM`.

### Expiry-Day Trade toggle
- `Blocked`: skip entry when trading day equals expiry day.
- `Allowed`: permit expiry-day entry.

### Description
- Optional strategy notes.

### DB Path
- Auto-generated full DB path.

## 4.2 Entry Tab

This tab has two levels:
1. Entry legs (per-leg IF/ELSE and execution)
2. Combined Entry Gate (strategy-level IF/ELSE imported into legs)

### 4.2.1 Add Entry Leg
Each leg includes:

#### Condition Mode
- Structure is fixed as `IF (...) THEN execute`.
- ELSE toggle enables `IF THEN ELSE` mode.

#### IF Conditions
- Add one or more condition blocks.
- In each block add one or more parameters.
- Join buttons `AND/OR` appear between conditions.

#### ELSE Conditions
- Visible only when ELSE toggle is enabled.
- Same structure as IF branch.

#### IF TRUE THEN Execution Parameters
- Buy / Sell: `BUY` or `SELL`
- CE / PE: `CE` or `PE`
- Strike Select:
  - `ATM`, `ATM+1`, `ATM-1`, `ATM+2`, `ATM-2`
  - `By Delta`, `By Strike`, `By Premium`, `OTM %`
- Strike / Value: input interpretation depends on strike mode.
- Lots: numeric quantity.
- Order Type Override: blank means use global order type.
- Execution Metric: metric used for selection/execution heuristics.

#### ELSE THEN Execution Parameters
- Same shape as IF execution branch.
- Includes `Copy IF THEN to ELSE THEN` helper.

### 4.2.2 Combined Entry Gate
- Purpose: strategy-level gate imported into all entry legs.
- IF Conditions: add grouped combined condition blocks.
- ELSE Branch toggle: enables ELSE combined conditions.
- ELSE Conditions: optional fallback branch.

Saved behavior:
- Combined blocks stored in:
  - `entry.combined_conditions.if_block`
  - `entry.combined_conditions.else_block`
- Imported into each leg via:
  - `leg.condition_imports.entry_combined`
  - merged into `leg.conditions_block` and `leg.else_conditions_block` where applicable.

## 4.3 Adjustment Tab

### Lock behavior
- Adjustment section is disabled until at least one Entry leg exists.

### Add Adjustment Rule
Each rule has:

#### Trigger Conditions
- Condition style: `Tagged Leg -> Metric -> Comparator -> Value`
- Tagged Leg list is built from Entry leg tags (`LEG@1`, `LEG@2`, ...).
- Metric choices:
  - `LTP`, `Delta`, `Gamma`, `Theta`, `Vega`, `IV`, `P&L`, `P&L %`, `OI`, `Strike`

#### Adjustment Action
- Current action type: `Simple Close + Open New`
- Configure one or more leg pairs:
  - Close Leg: choose tagged entry leg.
  - Open New Leg fields:
    - New Buy/Sell
    - New CE/PE
    - New Strike Select
    - New Strike/Value
    - New Lots
    - New Order Type
- Max Adjustments / Day
- Cooldown (seconds)

### Combined Adjustment Gate
- IF/ELSE combined conditions at strategy level.
- Imported into each adjustment rule conditions using `condition_imports.adjustment_combined`.
- Stored under `adjustment.combined_conditions`.

## 4.4 Exit & Risk Tab

This tab has 4 parts:
1. Strategy-level P&L exits
2. Greek/position risk limits
3. Per-leg exit rules
4. Combined Exit Gate

### 4.4.1 Strategy-Level P&L Exits

#### Target Profit
- Amount (₹)
- % of Premium
- On Hit action:
  - `Exit All Legs`, `Trail Profit`, `Partial 50%`, `Lock & Trail`

#### Stop Loss
- Amount (₹)
- % of Premium
- On Hit action:
  - `Exit All Legs`, `Trigger Adjustment`, `Partial 50%`

#### Trailing Stop Loss
- Trail (₹)
- Lock-in (₹)
- Trail Step (₹)

### 4.4.2 Greek & Position Risk Limits
- Max Net Delta
- On Delta Breach action
- Max IV / Min IV
- Max Capital
- Max Legs

### 4.4.3 Per-Leg Exit Rules
For each Exit rule:
- Exit Leg Reference:
  - tagged leg, `All Legs`, `Profitable Legs`, `Loss-making Legs`
- Exit Order Type
- Condition Mode (`instant`, `and`, `or`, `if_then`, `if_then_else`)
- Execution Metric
- Priority
- Exit Conditions blocks
- Leg-level P&L:
  - Profit Target
  - Stop Loss
  - Trailing

### 4.4.4 Combined Exit Gate
- IF/ELSE combined condition groups.
- Combined IF is merged into exit pipeline and EOD time exit is auto-added.
- Stored under `exit.combined_conditions`.

## 4.5 Schedule Tab

### Frequency
- `Daily`, `Weekly`, `Monthly (Expiry Week)`, `Manual Only`

### Entry Time
- Strategy entry time.

### Exit Time (EOD)
- Scheduled final exit time.

### Expiry Type
- `Current Weekly`, `Next Weekly`, `Monthly`, `Next Monthly`

### DTE Min / DTE Max
- Allowed days-to-expiry range.

### Square Off Before (mins)
- Minutes before exit for forced square-off.

### Entry on Expiry Day
- `Yes` / `No`

### Active Days
- Click-button day selector (Mon-Sun).
- If none selected, builder defaults to Mon-Fri on read/save safety paths.

## 5. Condition Parameters Reference

## 5.1 Common comparators
- `>`, `>=`, `<`, `<=`, `==`, `!=`, `~=`
- `between`, `not_between` (enter two comma-separated values)

## 5.2 DB/Market parameters (non-combined rows)
Categories available in leg conditions:

### Option Legs
- `CE LTP`, `PE LTP`
- `CE Strike`, `PE Strike`
- `CE OI`, `PE OI`

### Greeks
- `CE Delta`, `PE Delta`
- `CE Gamma`, `PE Gamma`
- `CE Theta`, `PE Theta`
- `CE Vega`, `PE Vega`

### Volatility
- `CE IV`, `PE IV`

### Premium
- `Total Premium`
- `CE Decay %`, `PE Decay %`, `Total Decay %`

### Strategy
- `Net Delta`, `Delta Diff (CE-PE)`
- `Combined P&L`, `Combined P&L %`
- `Any Leg Delta (abs)`
- `Both Legs Delta Below`, `Both Legs Delta Above`
- `Max Leg Delta`, `Min Leg Delta`
- `Higher Delta Leg`, `Lower Delta Leg`
- `Most Profitable Leg`, `Least Profitable Leg`

### Time
- `Current Time (HH:MM)`
- `Time In Position (sec)`
- `Time Since Last Adj (sec)`

### Index/Ticker
- `Underlying Spot`
- `Spot Change`, `Spot Change %`
- `India VIX`
- `ATM Strike`
- `Futures LTP`
- Dynamic index token params loaded from `/dashboard/index-tokens/list`:
  - `<INDEX> LTP`
  - `<INDEX> Chg%`

### Tagged Legs
- Auto-generated from Entry tags:
  - `tag.LEG@x.ltp`
  - `tag.LEG@x.delta`
  - ... all leg metrics

## 5.3 Combined gate parameter list
Combined rows are intentionally limited to global metrics:
- `Net Delta`
- `Combined P&L`
- `Combined P&L %`
- `Delta Diff`
- `Any Leg Delta`
- `Both Legs Delta Below`
- `Both Legs Delta Above`
- `Current Time`
- `Underlying Spot`
- `India VIX`
- `Combined Entry IF True (0/1)`
- `Combined Adj IF True (0/1)`
- `Combined Exit IF True (0/1)`
- plus dynamic index token metrics

## 6. UX Rules and Visual Cues
- Each condition block is tagged as `Block 1`, `Block 2`, etc.
- Each condition row is tagged as `C1.1`, `C1.2`, etc.
- IF and ELSE blocks use distinct color themes.
- Active selected condition group gets highlight (`cg-active`).
- OR/AND join buttons are removed automatically when adjacent condition is deleted.

## 7. Save Output Structure (high-level)
Top-level sections:
- `identity`
- `timing`
- `market_data`
- `entry`
- `adjustment`
- `exit`
- `schedule`
- `risk_management`

Combined gate storage:
- `entry.combined_conditions`
- `adjustment.combined_conditions`
- `exit.combined_conditions`

Leg/rule imports:
- `condition_imports.entry_combined`
- `condition_imports.adjustment_combined`
- `condition_imports.exit_combined`

## 8. Recommended Build Workflow
1. Fill Identity tab first.
2. Create Entry legs with IF conditions and execution params.
3. Add Combined Entry IF/ELSE blocks.
4. Add Adjustment rules and combined adjustment gate.
5. Configure Exit tab (P&L, risk, leg rules, combined exit).
6. Set Schedule tab.
7. Save, reload once, verify all blocks render exactly as created.

## 9. Validation and Common Errors
- Strategy Name missing -> save blocked.
- Adjustment rules without valid close/open pairs -> save blocked.
- `between`/`not_between` without exactly two values -> condition ignored in payload.
- If no active days selected manually, builder auto-falls back to Mon-Fri.

## 10. Best Practices for Maximum Flexibility
- Keep combined gates for context filters, and leg blocks for execution-specific logic.
- Use tags heavily in Adjustment for deterministic leg targeting.
- Prefer grouped conditions over long flat chains for readability.
- Use ELSE only when truly needed; avoid unnecessary dual-branch complexity.
- After major edits, use `Load` on saved strategy to verify round-trip fidelity.

## 11. Quick Example Patterns

### Pattern A: Basic short straddle entry with global gate
- Combined IF: `time_current >= 09:20 AND india_vix < 18`
- Entry Leg 1: SELL CE ATM
- Entry Leg 2: SELL PE ATM

### Pattern B: Delta-based adjustment
- Adj rule IF: `LEG@1 delta > 0.35`
- Action: close `LEG@1`, open new CE at `ATM+1`

### Pattern C: Multi-layer exit
- Combined Exit IF: `combined_pnl <= -3000 OR net_delta >= 0.5`
- Plus auto EOD exit at schedule `exit_time`

---

If this builder evolves again, update this file together with `perfect_strategy_builder.html` to keep UI and documentation synchronized.
