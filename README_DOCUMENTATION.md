# 📚 SHOONYA PLATFORM - DOCUMENTATION INDEX

## 🎯 START HERE

You have 4 comprehensive documents analyzing all **entry and exit order execution paths** plus **which files generate intents**.

---

## 📖 DOCUMENTS CREATED

### 1. **EXECUTION_SUMMARY.md** ← START HERE FIRST
**Best for**: Quick understanding of all paths at a glance
- 7 entry paths summarized
- 4 exit paths summarized
- Which files generate intents (tables)
- FAQ section
- Quick reference

**Read this first** if you want a 10-minute overview.

---

### 2. **EXECUTION_FLOW_ANALYSIS.md** 
**Best for**: Deep technical understanding
- System architecture overview
- Entry order paths: 5 detailed flows with code
- Exit order paths: 4 detailed flows with code
- Database flow with tables
- Command service routing
- Critical rules & guards
- Execution lifecycle
- Detailed intent generation mapping (line numbers)

**Read this second** for complete technical details.

---

### 3. **EXECUTION_FLOW_DIAGRAMS.md**
**Best for**: Visual understanding
- High-level system architecture (ASCII diagram)
- 5 detailed entry paths with flows
- 4 detailed exit paths with flows
- Intent flow quick matrix
- Database flow diagram
- Command service routing diagram

**Read this** if you prefer visual diagrams over text.

---

### 4. **INTENT_GENERATION_REFERENCE.md**
**Best for**: Finding specific information
- Files that generate ENTRY intents (table)
- Files that generate EXIT intents (table)
- Detailed entry paths with code snippets
- Detailed exit paths with code snippets
- Synchronous vs Asynchronous explanation
- Register vs Submit explanation
- Verification checklist
- Cross-references for modifications

**Read this** when you need to find specific details or add new functionality.

---

### 5. **COMPLETE_FILE_MAP.md**
**Best for**: Understanding file relationships
- Complete file listing by tier (11 tiers)
- Each file with functions and line numbers
- Intent flow by file (visual text map)
- Key concepts definitions

**Read this** when you need to navigate the codebase.

---

## 🗺️ HOW TO USE THESE DOCUMENTS

### **If you're new to the project:**
1. Read **EXECUTION_SUMMARY.md** (10 mins) 
2. Read **EXECUTION_FLOW_DIAGRAMS.md** (10 mins)
3. Skim **COMPLETE_FILE_MAP.md** (5 mins)

### **If you need to understand a specific path:**
Go to **EXECUTION_FLOW_ANALYSIS.md**, find the path, see the flow.

### **If you need line numbers and files:**
Go to **INTENT_GENERATION_REFERENCE.md**, see tables and code snippets.

### **If you need to add new functionality:**
1. Check **EXECUTION_SUMMARY.md** for similar path
2. Follow pattern in **INTENT_GENERATION_REFERENCE.md**
3. Update using files from **COMPLETE_FILE_MAP.md**

### **If you need to find a file:**
Go to **COMPLETE_FILE_MAP.md**, use Ctrl+F to search.

---

## 🔍 QUICK ANSWERS

**Q: Where do ENTRY orders come from?**  
A: See **EXECUTION_SUMMARY.md** → "7 Entry Paths" section

**Q: Where do EXIT orders come from?**  
A: See **EXECUTION_SUMMARY.md** → "4 Exit Paths" section

**Q: Which files generate intents?**  
A: See **INTENT_GENERATION_REFERENCE.md** → "Intent Generation Summary Table"

**Q: How does TradingView webhook work?**  
A: See **EXECUTION_FLOW_ANALYSIS.md** → "Path 1: TradingView Webhook" + **EXECUTION_FLOW_DIAGRAMS.md** → "PATH 1"

**Q: How does Dashboard work?**  
A: See **EXECUTION_FLOW_ANALYSIS.md** → "Path 2-5" section

**Q: How do SL/Trailing exits work?**  
A: See **EXECUTION_FLOW_ANALYSIS.md** → "Path 4: OrderWatcherEngine" 

**Q: What's the database flow?**  
A: See **EXECUTION_FLOW_ANALYSIS.md** → "Database Flow" section

**Q: Where's the file xyz?**  
A: See **COMPLETE_FILE_MAP.md**, search for filename

**Q: How does risk forcing exit work?**  
A: See **EXECUTION_FLOW_ANALYSIS.md** → "Path 3: Risk Manager Force EXIT"

**Q: I want to add a new entry path, where do I start?**  
A: See **INTENT_GENERATION_REFERENCE.md** → "If you need to add a NEW entry path"

---

## 📊 DOCUMENT QUICK REFERENCE

| Need | Document | Section |
|---|---|---|
| Quick overview | EXECUTION_SUMMARY.md | Start of doc |
| Entry path details | EXECUTION_FLOW_ANALYSIS.md | Entry Order Execution Path |
| Exit path details | EXECUTION_FLOW_ANALYSIS.md | Exit Order Execution Path |
| Entry sources (tables) | INTENT_GENERATION_REFERENCE.md | Intent Generation Summary Table |
| Exit sources (tables) | INTENT_GENERATION_REFERENCE.md | Intent Generation Summary Table |
| Diagrams | EXECUTION_FLOW_DIAGRAMS.md | All sections |
| File locations | COMPLETE_FILE_MAP.md | All tiers |
| Function line numbers | INTENT_GENERATION_REFERENCE.md | Detailed paths with code |
| File relationships | COMPLETE_FILE_MAP.md | Intent flow by file |
| Database schema | EXECUTION_FLOW_ANALYSIS.md | Database Flow section |
| Adding new path | INTENT_GENERATION_REFERENCE.md | Verification checklist |

---

## 🎓 RECOMMENDED READING ORDER

### For Developers New to the Project:
1. **EXECUTION_SUMMARY.md** (overview)
2. **EXECUTION_FLOW_DIAGRAMS.md** (visual)
3. **COMPLETE_FILE_MAP.md** (navigation)
4. **EXECUTION_FLOW_ANALYSIS.md** (details as needed)
5. **INTENT_GENERATION_REFERENCE.md** (specifics as needed)

### For Debugging a Path:
1. **EXECUTION_SUMMARY.md** (find which path)
2. **EXECUTION_FLOW_ANALYSIS.md** (understand the flow)
3. **COMPLETE_FILE_MAP.md** (find files)
4. Code files (from line numbers in INTENT_GENERATION_REFERENCE.md)

### For Adding New Functionality:
1. **EXECUTION_SUMMARY.md** (find similar path)
2. **INTENT_GENERATION_REFERENCE.md** (copy pattern)
3. **COMPLETE_FILE_MAP.md** (understand structure)
4. **EXECUTION_FLOW_ANALYSIS.md** (understand execution)

### For Code Review:
1. **COMPLETE_FILE_MAP.md** (understand architecture)
2. **EXECUTION_FLOW_ANALYSIS.md** (follow the flow)
3. Code files (verify against docs)

---

## 💡 KEY INSIGHTS

### **Architecture Pattern**
```
Entry Points → Intent Generation → Async Queue → Consumers → Execution → Broker
```

### **Two Types of Execution**
- **Synchronous**: TradingView webhook (fast, immediate result)
- **Asynchronous**: Dashboard intents (slower, eventual result)

### **Two Types of Command Submission**
- **submit()**: ENTRY orders - immediate broker execution
- **register()**: EXIT orders - queued for OrderWatcherEngine

### **Three Layers of Duplicate Protection**
1. Memory check (pending_commands)
2. Database check (OrderRepository)
3. Broker check (api.get_positions)

### **OrderWatcherEngine is Sole Exit Executor**
- All exits route through CommandService.register()
- OrderWatcherEngine picks them up
- Ensures centralized exit logic
- Handles SL/Trailing triggers

---

## 🔗 FILE CROSS-REFERENCES

### Entry Points:
- TradingView: `api/http/execution_app.py:webhook()` (line ~74)
- Dashboard: `api/dashboard/api/intent_router.py` (lines ~48, ~67, ~90, ~134)
- Telegram: `api/http/telegram_controller.py:handle_message()`
- Strategy: Various strategy files

### Processors:
- Main: `execution/trading_bot.py:process_alert()` (line ~784)
- Validator: `execution/execution_guard.py:validate_and_prepare()`
- Router: `execution/command_service.py:submit()` / `register()`

### Executors:
- Entry: `brokers/shoonya/client.py:place_order()`
- Exit: `execution/order_watcher.py:_process_orders()` → `_fire_exit()`

### Storage:
- Intents: `persistence/repository.py` → `persistence/models.py:OrderRecord`
- Dashboard Queue: `control_intents` table

---

## ✅ VERIFICATION CHECKLIST

After reading the documents, you should understand:

- [ ] Where ENTRY orders come from (7 paths)
- [ ] Where EXIT orders come from (4 paths)
- [ ] Which files generate intents (11 files)
- [ ] How TradingView webhook works (synchronous)
- [ ] How Dashboard intents work (asynchronous)
- [ ] How SL/Trailing exits work (OrderWatcherEngine)
- [ ] How risk forced exits work (RiskManager)
- [ ] What ExecutionGuard does (validation)
- [ ] What CommandService does (routing)
- [ ] What OrderWatcherEngine does (exit executor)
- [ ] Database structure (two tables)
- [ ] Intent lifecycle (generation → execution)

---

## 📞 QUESTIONS?

Refer back to the appropriate document based on your question. Each document is self-contained and comprehensive for its topic.

---

## 📝 DOCUMENT VERSIONS

All documents created: January 31, 2026

Last updated: January 31, 2026

---

**Enjoy exploring the Shoonya Platform architecture!** 🚀

