# Project Structure - Reorganization Summary

**Date:** 2026-02-09  
**Status:** ✅ Complete

This document summarizes the recent project reorganization for better clarity and maintainability.

---

## 📋 Changes Made

### 1. Documentation Organization

**Moved to `DOCS/` folder:**
- ✅ `SERVICE_INSTALLATION_LINUX.md` → `DOCS/SERVICE_INSTALLATION_LINUX.md`
- ✅ `SERVICE_INSTALLATION_WINDOWS.md` → `DOCS/SERVICE_INSTALLATION_WINDOWS.md`
- ✅ `UTILITY_COMMANDS.md` → `DOCS/UTILITY_COMMANDS.md`

**Updated:**
- ✅ `COMPLETE_DOCUMENT_BOOK.md` - Added new documentation links in alphabetical order

### 2. Deployment Files Organization

**Created `deployment/` folder:**
```
deployment/
├── README.md                    # Deployment documentation
├── shoonya_service.service      # Main systemd service
├── deploy_improvements.sh       # Deployment helper
├── install_schedulers.sh        # Timer installation script
└── systemd/                     # Systemd timers
    ├── shoonya_start.service
    ├── shoonya_start.timer
    ├── shoonya_stop.service
    ├── shoonya_stop.timer
    ├── shoonya_weekend_check.service
    └── shoonya_weekend_check.timer
```

### 3. Strategy Files Cleanup

**Created `shoonya_platform/strategies/legacy/` folder:**

**Moved legacy files:**
- ✅ `run.py` → `legacy/run.py` (deprecated runner)
- ✅ `db_run.py` → `legacy/db_run.py` (old DB runner)
- ✅ `db_based_run.py` → `legacy/db_based_run.py` (old DB-based runner)

**Active strategy files (kept in main folder):**
- ✅ `strategy_runner.py` - Production OMS-compliant runner
- ✅ `strategy_run_writer.py` - DB persistence writer
- ✅ `delta_neutral/` - Active delta neutral strategy
- ✅ `reporting/` - Strategy reporting
- ✅ `runner_adv/` - Advanced runner
- ✅ `universal_config/` - Universal config system

### 4. Root Folder Cleanup

**Moved test files to `tests/`:**
- ✅ `test.py` → `tests/test.py`
- ✅ `test2.py` → `tests/test2.py`

**Moved utility scripts to `scripts/`:**
- ✅ `verify_orders.py` → `scripts/verify_orders.py`
- ✅ `weekend_market_check.py` → `scripts/weekend_market_check.py`

**Removed obsolete log files:**
- ✅ `signal_processor.log` (removed)
- ✅ `signal_processor.err` (removed)
- ✅ `trading_bot.log` (removed)

---

## 📁 New Project Structure

```
shoonya_platform/
├── 📄 Root Files (Essential)
│   ├── bootstrap.py                     # Environment setup
│   ├── main.py                          # Main entry point
│   ├── run_windows_service.ps1          # Windows service runner
│   ├── setup_powershell_commands.ps1    # PowerShell setup
│   ├── COMPLETE_DOCUMENT_BOOK.md        # Documentation index
│   ├── pyproject.toml                   # Python project config
│   └── pytest.ini                       # Test configuration
│
├── 📂 config_env/                       # Configuration
│   ├── primary.env                      # User credentials (gitignored)
│   └── primary.env.example              # Template
│
├── 📂 deployment/                       # 🆕 Deployment files
│   ├── README.md                        # Deployment guide
│   ├── shoonya_service.service          # Systemd service
│   ├── *.sh scripts                     # Deployment helpers
│   └── systemd/                         # Timer configs
│
├── 📂 DOCS/                             # Documentation (67 files)
│   ├── SERVICE_INSTALLATION_LINUX.md    # 🆕 Linux guide
│   ├── SERVICE_INSTALLATION_WINDOWS.md  # 🆕 Windows guide
│   ├── UTILITY_COMMANDS.md              # 🆕 Command reference
│   └── ... (all other documentation)
│
├── 📂 scripts/                          # Utility scripts
│   ├── scriptmaster.py                  # Script management
│   ├── verify_orders.py                 # 🔄 Moved here
│   └── weekend_market_check.py          # 🔄 Moved here
│
├── 📂 tests/                            # Test files
│   ├── test.py                          # 🔄 Moved here
│   ├── test2.py                         # 🔄 Moved here
│   └── live_feed_stress_test.py
│
├── 📂 shoonya_platform/                 # Main application
│   ├── api/                             # API layer
│   ├── brokers/                         # Broker integrations
│   ├── core/                            # Core logic
│   ├── execution/                       # Order execution
│   ├── strategies/                      # Strategy implementations
│   │   ├── strategy_runner.py           # ✅ Production runner
│   │   ├── strategy_run_writer.py       # ✅ DB writer
│   │   ├── delta_neutral/               # ✅ Active strategy
│   │   ├── reporting/                   # ✅ Reporting
│   │   ├── runner_adv/                  # ✅ Advanced runner
│   │   ├── universal_config/            # ✅ Config system
│   │   └── legacy/                      # 🆕 Deprecated files
│   │       ├── README.md                # Migration guide
│   │       ├── run.py
│   │       ├── db_run.py
│   │       └── db_based_run.py
│   └── ... (other modules)
│
└── 📂 logs/                             # Runtime logs
    ├── execution_service.log
    ├── dashboard.log
    └── ... (generated at runtime)
```

---

## 🎯 Benefits

### Clarity
- ✅ Root folder is now clean and focused on essential files
- ✅ All documentation centralized in `DOCS/`
- ✅ Deployment files grouped in `deployment/`
- ✅ Legacy code clearly separated from active code

### Maintainability
- ✅ Easy to identify which strategy files are in active use
- ✅ Clear migration path documented in `legacy/README.md`
- ✅ All deployment scripts in one place
- ✅ Test files properly organized in `tests/`

### Developer Experience
- ✅ New developers can quickly find what they need
- ✅ No confusion about which files to use
- ✅ Clear documentation references
- ✅ Logical folder structure

---

## 🔗 Quick Links

### For Development
- [bootstrap.py](bootstrap.py) - First-time setup
- [main.py](main.py) - Run the platform
- [shoonya_platform/strategies/strategy_runner.py](shoonya_platform/strategies/strategy_runner.py) - Production runner

### For Deployment
- [deployment/README.md](deployment/README.md) - Deployment guide
- [DOCS/SERVICE_INSTALLATION_LINUX.md](DOCS/SERVICE_INSTALLATION_LINUX.md) - Linux/EC2 setup
- [DOCS/SERVICE_INSTALLATION_WINDOWS.md](DOCS/SERVICE_INSTALLATION_WINDOWS.md) - Windows setup

### For Documentation
- [COMPLETE_DOCUMENT_BOOK.md](COMPLETE_DOCUMENT_BOOK.md) - All documentation index
- [DOCS/UTILITY_COMMANDS.md](DOCS/UTILITY_COMMANDS.md) - Command reference

---

## 📝 Migration Notes

### If you have bookmarks or scripts referencing old paths:

**Documentation:**
```bash
# OLD
./SERVICE_INSTALLATION_LINUX.md

# NEW
./DOCS/SERVICE_INSTALLATION_LINUX.md
```

**Deployment:**
```bash
# OLD
./shoonya_service.service

# NEW
./deployment/shoonya_service.service
```

**Strategies:**
```python
# OLD (deprecated)
from shoonya_platform.strategies.run import ...

# NEW (production)
from shoonya_platform.strategies.strategy_runner import StrategyRunner
```

**Scripts:**
```bash
# OLD
./verify_orders.py

# NEW
./scripts/verify_orders.py
```

---

**Last Updated:** 2026-02-09  
**Reorganization:** Complete ✅
