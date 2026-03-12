# 🔍 DB File Migration Audit Report

## 📋 Executive Summary

Found **OLD VERSION** references to `db_file` and `db_path` in:
- ✅ 6 saved config JSON files
- ⚠️ 3 Python runner files (executor.py, config_schema.py, strategy_executor_service.py)

All need updating to support **auto-resolution** based on `exchange + symbol + expiry_mode`.

---

## 📁 Files Requiring Updates

### 🟡 **1. SAVED CONFIGS** (6 files)

All configs have redundant `db_file` + `db_path` fields that should be removed:

```
./saved_configs/test.json
./saved_configs/gamma_scalping_rolling_straddle.json
./saved_configs/momentum_scalping_with_greeks.json
./saved_configs/nat_test.json
./saved_configs/volatility_mean_reversion_strangle.json
./saved_configs/banknifty_dnss.json
```

**Example OLD format:**
```json
{
  "identity": {
    "exchange": "MCX",
    "underlying": "CRUDEOILM",
    "db_file": "MCX_CRUDEOILM_17-MAR-2026.sqlite",
    "db_path": "shoonya_platform/market_data/option_chain/data/MCX_CRUDEOILM_17-MAR-2026.sqlite",
    ...
  },
  "market_data": {
    "source": "sqlite",
    "db_file": "MCX_CRUDEOILM_17-MAR-2026.sqlite"
  }
}
```

**NEW format (remove db_file/db_path):**
```json
{
  "identity": {
    "exchange": "MCX",
    "underlying": "CRUDEOILM",
    ...
  },
  "market_data": {
    "source": "sqlite"
  }
}
```

---

### 🔴 **2. PYTHON RUNNER FILES** (3 critical files)

#### **A. executor.py**
**Lines with db_file references:**
```python
Line 122: self._fixed_expiry_date = self._extract_expiry_from_db_file()
Line 289: def _extract_expiry_from_db_file(self) -> Optional[str]:
Line 293: db_file = str(identity.get("db_file") or market_data.get("db_file") or "").strip()
Line 294: if not db_file:
Line 296: match = _DB_FILE_EXPIRY_RE.match(db_file)
Line 299-301: Logger warnings about db_file
Line 306: "Using custom db_file expiry: %s"
Line 310: "schedule.expiry_mode=custom but db_file expiry is missing/invalid"
Line 319: "Ignoring db_file expiry because mode=%s is dynamic"
```

**Required Changes:**
- Remove `_extract_expiry_from_db_file()` method entirely
- Remove logic that tries to parse expiry from db_file
- Let `expiry_mode` (weekly_auto, weekly_current, etc.) drive expiry selection
- Market reader already handles auto-resolution via `_resolve_db_path()`

---

#### **B. config_schema.py**
**Lines with db_file references:**
```python
Line 145: # db_file / db_path (optional, but if present check existence)
Line 146: db_file = identity.get("db_file")
Line 147-148: if db_file and not isinstance(db_file, str):
Line 149: errors.append(ValidationError(f"{prefix}.db_file", "db_file must be a string"))

Line 190-193: Same validation for market_data.db_file
```

**Required Changes:**
- Remove validation checks for `db_file` and `db_path`
- These fields are now DEPRECATED and should be ignored if present
- Add comment: `# NOTE: db_file/db_path deprecated – auto-resolved from exchange+symbol+expiry_mode`

---

#### **C. strategy_executor_service.py**
**Lines with db_file references:**
```python
Line 87: db_file = str(identity.get("db_file") or (config.get("market_data", {}) or {}).get("db_file") or "").strip()
Line 88-90: if db_file: m = _DB_FILE_EXPIRY_RE.match(db_file)

Line 156: self._fixed_expiry_date = self._extract_expiry_from_db_file(config)
Line 302: def _extract_expiry_from_db_file(self, config: Dict[str, Any]) -> Optional[str]:
Line 306: db_file = str(identity.get("db_file") or market_data.get("db_file") or "").strip()
Line 307: if not db_file:
Line 309: match = _DB_FILE_EXPIRY_RE.match(db_file)
Line 312-314: Logger warnings
Line 319: "Using custom db_file expiry for %s: %s"
Line 324: "schedule.expiry_mode=custom but db_file expiry is missing/invalid"
Line 333: "Ignoring db_file expiry for %s because mode=%s is dynamic"
```

**Required Changes:**
- Same as executor.py: remove all db_file parsing logic
- Remove `_extract_expiry_from_db_file()` method
- Rely on schedule.expiry_mode for all expiry decisions

---

## ✅ **3. FILES THAT ARE ALREADY CORRECT**

### ✅ market_reader.py
**Already supports auto-resolution!** No changes needed.

```python
def _resolve_db_path(self, expiry: Optional[str] = None) -> Optional[str]:
    """Resolve full path to SQLite file; if expiry None, pick nearest future."""
    folder = DB_FOLDER
    if expiry is not None:
        filename = f"{self.exchange}_{self.symbol}_{expiry}.sqlite"
        file_path = folder / filename
        return str(file_path) if file_path.exists() else None
    
    # Auto-resolve to nearest future expiry
    pattern = f"{self.exchange}_{self.symbol}_*.sqlite"
    ...
```

This already implements the desired behavior! ✨

---

## 🛠️ **RECOMMENDED MIGRATION PLAN**

### Phase 1: Update Runner Code (Priority: HIGH)
1. **executor.py** - Remove `_extract_expiry_from_db_file()` method
2. **strategy_executor_service.py** - Remove `_extract_expiry_from_db_file()` method
3. **config_schema.py** - Remove db_file/db_path validation (mark as deprecated)
4. **executor.py / strategy_executor_service.py** - No change needed: resolved expiry is already cached at strategy start in `StrategyExecutor.__init__` via `_resolve_cycle_expiry()` (stored in `_cycle_expiry_date`) and in `PerStrategyExecutor.__init__` via `_resolve_cycle_expiry()`; ensure this behavior remains.

### Phase 2: Update Saved Configs (Priority: MEDIUM)
Batch update all 6 config files:
```bash
# Python script to strip db_file/db_path from all configs
for f in saved_configs/*.json; do
  jq 'del(.identity.db_file, .identity.db_path, .market_data.db_file)' "$f" > "${f}.new"
  mv "${f}.new" "$f"
done
```

### Phase 3: Test & Verify (Priority: HIGH)
1. Run each strategy with updated configs
2. Verify market_reader auto-resolves DB files correctly
3. Check logs for any db_file warnings
4. Confirm expiry_mode (weekly_auto, monthly_current, etc.) works as expected

---

## 🎯 **EXPECTED BEHAVIOR AFTER MIGRATION**

### How Expiry Resolution Will Work:

**OLD (deprecated):**
```
Config has db_file="NFO_NIFTY_27MAR2025.sqlite" 
→ Parse expiry from filename 
→ Use that fixed expiry
```

**NEW (correct):**
```
Config has:
  identity.exchange = "NFO"
  identity.underlying = "NIFTY"
  schedule.expiry_mode = "weekly_auto"

→ market_reader._resolve_db_path() called with expiry=None or computed_expiry
→ Auto-finds: NFO_NIFTY_{nearest_future_date}.sqlite
→ Dynamic expiry resolution every run! 🎉
```

### Expiry Mode Behavior:
- `weekly_auto` → picks closest weekly, rolls to next on expiry day
- `weekly_current` → current week expiry
- `weekly_next` → next week expiry  
- `monthly_current` → current month expiry
- `monthly_next` → next month expiry
- `custom` → now REMOVED (was parsed from db_file, no longer supported)

---

## 📊 **MIGRATION IMPACT SUMMARY**

| File Type | Files Affected | Severity | Effort |
|-----------|---------------|----------|--------|
| Saved Configs | 6 | LOW | Automated script |
| Python Runners | 3 | HIGH | Manual code review |
| Market Reader | 1 | NONE | Already correct ✅ |
| **TOTAL** | **10** | **MEDIUM** | **~2 hours** |

---

## 🚨 **RISKS & MITIGATION**

### Risk 1: Configs with `expiry_mode=custom`
**Impact:** Custom expiry mode relied on db_file parsing
**Mitigation:** Convert all to weekly_auto or weekly_current

### Risk 2: Hardcoded db_file in legacy configs
**Impact:** Old configs may fail to load
**Mitigation:** Schema validator should IGNORE (not error) on db_file fields

### Risk 3: Expiry date changes mid-day
**Impact:** Strategy might switch DB files during active positions
**Mitigation:** Executor should cache resolved expiry at strategy start

---

## ✅ **VALIDATION CHECKLIST**

- [ ] Remove db_file parsing from executor.py
- [ ] Remove db_file parsing from strategy_executor_service.py  
- [ ] Update config_schema.py to ignore db_file/db_path
- [ ] Verify expiry is cached once per strategy run (StrategyExecutor.__init__ and PerStrategyExecutor.__init__ set `_cycle_expiry_date` once and reuse it)
- [ ] Add/verify tests that assert `_cycle_expiry_date` does not change mid-run (e.g., simulate multiple ticks and confirm expiry remains constant)
- [ ] Strip db_file/db_path from all 6 saved configs
- [ ] Test auto-resolution with weekly_auto mode
- [ ] Test auto-resolution with monthly_current mode
- [ ] Verify no db_file warnings in logs
- [ ] Confirm strategies enter/exit correctly with new system
- [ ] Update documentation to reflect new behavior

---

**Generated:** 2026-03-12
**Files Scanned:** 10 Python files, 6 JSON configs
**Status:** 🔴 Migration Required
