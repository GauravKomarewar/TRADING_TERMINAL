# 🚀 QUICK START GUIDE - 5 MINUTE SETUP

**Your strategies folder is clean and production-ready!**

---

## 🎯 ACCESS YOUR DASHBOARD

### Step 1: Open Browser
```
URL: http://localhost:8000/dashboard/web/strategy_new.html
```

### Step 2: See Three Tabs
- **📂 Strategies** - Create, edit, validate strategies
- **🎮 Control** - Start/stop runner
- **📋 Logs** - Watch execution logs live

---

## 🔧 CREATE YOUR FIRST STRATEGY (2 MIN)

### Go to "Strategies" Tab
1. Click **[+ New Strategy]**
2. Fill in the form:
   ```
   Strategy Name: NIFTY_DNSS
   Market Type: database_market
   Exchange: NFO
   Symbol: NIFTY
   DB Path: /path/to/option_chain.db
   Entry Time: 09:15
   Exit Time: 15:30
   Entry CE Delta: 0.30
   Entry PE Delta: 0.30
   Profit Target: 100
   Max Loss: 50
   Quantity: 1
   ```
3. Click **[✓ Validate]** - should show "✅ Configuration is valid!"
4. Click **[💾 Save Strategy]**

✅ **Done!** Strategy saved to `saved_configs/NIFTY_DNSS.json`

---

## ▶️ RUN YOUR STRATEGY (1 MIN)

### Go to "Control" Tab
1. Click **[▶ START RUNNER]**
   - See "Strategies Loaded: 1"
   - Status changes to "🟢 RUNNING"
2. Active strategies appear in table below

### Watch Execution
1. Go to **[Logs]** tab
2. See live logs streaming
3. Filter by strategy or log level

### Stop When Done
1. Go to **[Control]** tab
2. Click **[⏹ STOP RUNNER]**

✅ **Done!** Execution complete, all logs saved.

---

## 📊 API ENDPOINTS (For Developers)

### Strategy Management
```bash
# List all strategies
curl -X GET "http://localhost:8000/dashboard/strategy/list"

# Get specific strategy
curl -X GET "http://localhost:8000/dashboard/strategy/NIFTY_DNSS"

# Validate config before saving
curl -X POST "http://localhost:8000/dashboard/strategy/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "market_config": {"market_type": "database_market", "exchange": "NFO"},
    "entry": {"time": "09:15"},
    "exit": {"time": "15:30"}
  }'

# Create new strategy
curl -X POST "http://localhost:8000/dashboard/strategy/create" \
  -H "Content-Type: application/json" \
  -d '{"market_config": {...}, "entry": {...}, "exit": {...}}'

# Update existing strategy
curl -X PUT "http://localhost:8000/dashboard/strategy/NIFTY_DNSS" \
  -H "Content-Type: application/json" \
  -d '{...updated config...}'

# Delete strategy
curl -X DELETE "http://localhost:8000/dashboard/strategy/NIFTY_DNSS"
```

### Runner Control
```bash
# Start runner
curl -X POST "http://localhost:8000/dashboard/runner/start"

# Stop runner
curl -X POST "http://localhost:8000/dashboard/runner/stop"

# Get status
curl -X GET "http://localhost:8000/dashboard/runner/status"
```

### Logging
```bash
# Get combined logs
curl -X GET "http://localhost:8000/dashboard/runner/logs"

# Get strategy-specific logs
curl -X GET "http://localhost:8000/dashboard/strategy/NIFTY_DNSS/logs?lines=100"
```

---

## 📁 FILE LOCATIONS

### Strategies Saved Here
```
shoonya_platform/strategies/saved_configs/
├── NIFTY_DNSS.json
├── BANKNIFTY_THETA.json
└── STRATEGY_CONFIG_SCHEMA.json
```

### Logs Saved Here
```
logs/strategies/
├── NIFTY_DNSS.log
├── BANKNIFTY_THETA.log
└── ...
```

### Services Used
```
shoonya_platform/strategies/
├── strategy_config_validator.py  ← Validates configs
├── strategy_logger.py            ← Logs execution
├── strategy_runner.py            ← Runs strategies
└── find_option.py                ← Option lookup
```

---

## ✅ VALIDATION FEEDBACK

### When You Click [✓ Validate]

**Valid Config Shows:**
```
✅ Configuration is valid!
```

**Invalid Config Shows Errors:**
```
❌ market_config.db_path: Database file not found: /invalid/path.db
❌ entry.time: Invalid time format. Use HH:MM
⚠️ entry.delta: Asymmetric deltas: CE=0.30, PE=0.40 (intentional?)
```

**Each error explains exactly what's wrong!**

---

## 🔍 LOG LEVELS

### What You See in Logs Tab
```
ℹ️ INFO    - Normal events ("Entry attempt started", "Generated 2 commands")
⚠️ WARNING - Performance issues ("Slow tick: 105.2ms")
❌ ERROR   - Failures ("Failed to place order: insufficient funds")
🐛 DEBUG   - Internal details (only shown if filter selected)
```

### Auto-Updated Every 3 Seconds
Logs tab automatically refreshes to show latest.

---

## 🧪 TEST IT NOW

### 1. Test Validation
```bash
curl -X POST "http://localhost:8000/dashboard/strategy/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "market_config": {"market_type": "database_market", "exchange": "NFO", "symbol": "NIFTY"},
    "entry": {"time": "09:15", "delta": {"CE": 0.3, "PE": 0.3}},
    "exit": {"time": "15:30", "profit_target": 100, "max_loss": 50}
  }'
```

### 2. Test Logger
```python
from shoonya_platform.strategies.strategy_logger import get_strategy_logger

logger = get_strategy_logger("TEST")
logger.info("Example message")
print(logger.get_logs_as_text())
```

### 3. Test Runner Status
```bash
curl -X GET "http://localhost:8000/dashboard/runner/status"
```

---

## 🛑 TROUBLESHOOTING

### Issue: "Strategy won't save"
**Solution:** Click [✓ Validate] first - fix any red errors before saving

### Issue: "No logs appearing"
**Solution:** 
1. Go to [Control] tab
2. Click [▶ START RUNNER]
3. Wait 5-10 seconds
4. Go to [Logs] tab
5. Logs should appear

### Issue: "database file not found"
**Solution:** Make sure db_path in your JSON points to actual file location

### Issue: "Strategy won't load on start"
**Solution:** Check validation - use [✓ Check] button in UI to see errors

---

## 💡 TIPS & TRICKS

✅ **Use real-time validation** - Click [✓ Check] while editing to catch errors early

✅ **Copy JSON** - All strategies stored as JSON in `saved_configs/` - you can version control them

✅ **Monitor performance** - Logs show "Slow tick" warnings if tick takes > 100ms

✅ **Compare strategies** - List all in Strategies tab to compare configurations

✅ **Export logs** - Log files in `logs/strategies/` folder for analysis

✅ **Filter logs** - Use Strategy dropdown and Level filter to focus on what matters

---

## 📞 COMMON QUESTIONS

**Q: Where are my strategies saved?**
A: `shoonya_platform/strategies/saved_configs/` - as JSON files

**Q: Can I edit strategies while runner is running?**
A: Yes! Edit and save in Strategies tab, runner continues with loaded strategies

**Q: How are logs stored?**
A: Two ways:
   1. **File:** `logs/strategies/{name}.log` (persistent, rotating)
   2. **Memory:** Last 1000 lines (for UI display)

**Q: Can I run multiple strategies together?**
A: Yes! Create multiple strategy files and [▶ START RUNNER] loads them all

**Q: What happens if one strategy fails?**
A: Other strategies continue running. Error logged but isolated.

**Q: How long are logs kept?**
A: Files rotate at 10MB. 5 backups kept. Memory buffer has last 1000 lines.

---

## 🎓 NEXT STEPS

1. **Create** a strategy in UI
2. **Validate** it with [✓ Check]
3. **Save** it with [💾 Save]
4. **Start** runner with [▶ START]
5. **Monitor** in Logs tab
6. **Stop** with [⏹ STOP]

**That's it! You're running strategies in production.** 🚀

---

## 📋 QUICK REFERENCE

| Task | Location | Time |
|------|----------|------|
| Create Strategy | Strategies Tab | 2 min |
| Validate Config | [✓ Check] Button | 1 sec |
| Start Runner | Control Tab [▶] | 1 sec |
| View Logs | Logs Tab | Real-time |
| Stop Runner | Control Tab [⏹] | 1 sec |
| Edit Strategy | Strategies Tab | 1 min |
| Delete Strategy | [🗑️] Button | 1 sec |

---

**Your production system is ready. Start using it now!** ✅

