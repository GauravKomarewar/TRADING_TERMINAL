# TRADING_TERMINAL – Complete User Guide & GitHub Sync Documentation

**Last Updated**: January 31, 2026  
**Repository**: https://github.com/GauravKomarewar/TRADING_TERMINAL  
**Project Version**: 1.0.0

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Project Features & Structure](#project-features--structure)
3. [GitHub Sync Workflow](#github-sync-workflow)
4. [Automation: Auto-Sync Daily Changes](#automation-auto-sync-daily-changes)
5. [Rollback & Version Recovery](#rollback--version-recovery)
6. [Dashboard Features](#dashboard-features)
7. [Execution Engine Features](#execution-engine-features)
8. [Common Tasks & Troubleshooting](#common-tasks--troubleshooting)
9. [Best Practices](#best-practices)

---

## Quick Start

### 1. Clone Repository on Any Machine

```bash
# Clone the repo
git clone https://github.com/GauravKomarewar/TRADING_TERMINAL.git
cd shoonya_platform

# Create virtual environment
python -m venv env

# Activate environment
# On Windows:
env\Scripts\activate
# On Linux/Mac:
source env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run tests to verify
pytest shoonya_platform/tests/ -v
```

### 2. Start Dashboard

```bash
# From project root with virtual env activated
python -c "from shoonya_platform.api.dashboard.dashboard_app import create_app; app = create_app(); app.run(host='0.0.0.0', port=8000)"

# Or use FastAPI directly
uvicorn shoonya_platform.api.dashboard.dashboard_app:app --host 0.0.0.0 --port 8000 --reload
```

Visit: `http://localhost:8000/dashboard/web/home.html`

---

## Project Features & Structure

### Directory Overview

```
TRADING_TERMINAL/
├── shoonya_platform/
│   ├── api/
│   │   ├── dashboard/           # Web UI & REST API
│   │   │   ├── web/             # HTML pages (home, option_chain, place_order, etc.)
│   │   │   ├── api/             # API endpoints (router.py, schemas.py)
│   │   │   └── services/        # Business logic (intent, broker, symbols)
│   │   └── http/                # HTTP controllers (execution, telegram)
│   │
│   ├── execution/               # Core trading engine
│   │   ├── trading_bot.py       # Strategy lifecycle management
│   │   ├── command_service.py   # Command routing
│   │   ├── engine.py            # Execution engine
│   │   └── validation.py        # Risk & validation
│   │
│   ├── market_data/             # Market data & option chains
│   │   ├── option_chain/        # Option chain DB & supervisor
│   │   └── feeds/               # Live market feeds
│   │
│   ├── persistence/             # Database & ORM
│   │   ├── database.py          # SQLite models
│   │   └── repository.py        # Data access layer
│   │
│   ├── strategies/              # Trading strategies
│   │   ├── delta_neutral/       # Delta-neutral short strangles
│   │   └── run.py               # Strategy runner
│   │
│   ├── risk/                    # Risk management
│   │   └── supreme_risk.py      # Position & loss limits
│   │
│   ├── tests/                   # Unit & integration tests
│   │   └── 257+ test cases
│   │
│   └── utils/                   # Utilities (Greeks, JSON builders)
│
├── scripts/                     # Helper scripts (ScriptMaster)
├── notifications/               # Alert notifications (Telegram)
├── env/                         # Virtual environment (EXCLUDED from Git)
├── logs/                        # Log files (EXCLUDED from Git)
├── .gitignore                   # Files to exclude from Git
└── GITHUB_SETUP.md              # GitHub setup guide

```

### Key Features

#### 🎛️ Dashboard (Web UI)

- **Home Page**: Real-time positions, orders, risk status, option chain heartbeat
- **Place Order**: Manual order entry with symbol autocomplete (NFO default)
- **Option Chain**: Live NIFTY options with Greeks (defaults to latest expiry)
- **Orderbook**: View system orders and broker orders
- **Symbol Search**: Autocomplete across all exchanges (NFO, NSE, BSE, MCX, BFO, CDS)

#### 🤖 Execution Engine

- **Strategy Lifecycle**: ENTRY → ADJUST → EXIT / FORCE_EXIT
- **Command Routing**: Intent-based command dispatch
- **Validation**: Risk checks, position limits, stop-loss validation
- **Recovery**: Automatic restart recovery on failures
- **Trailing Stops**: Dynamic stop-loss adjustment
- **Multi-Strategy**: Run multiple strategies simultaneously

#### 💾 Persistence

- **SQLite Database**: `persistence/data/orders.db`
  - Orders, trades, control intents, strategy states
- **Option Chain Data**: `market_data/option_chain/data/` (SQLite)
  - NIFTY, BANKNIFTY, FINNIFTY contracts with Greeks

#### 🧪 Testing

- **257+ Tests**: Full coverage of entry, exit, adjustment paths
- **Fake Broker**: Mock broker for testing without real account
- **Integration Tests**: Multi-client, recovery, risk scenarios

---

## GitHub Sync Workflow

### Daily Development Workflow

#### Before You Start Work

```bash
# Navigate to project
cd TRADING_TERMINAL

# Activate virtual environment
source env/bin/activate  # Linux/Mac
# or
env\Scripts\activate     # Windows

# Get latest changes from GitHub
git pull origin main
```

#### While Working

```bash
# Check status
git status

# View changes before committing
git diff

# Stage changes
git add .

# Or stage specific files
git add shoonya_platform/api/dashboard/
git add shoonya_platform/execution/
```

#### After Making Changes

```bash
# Commit with clear message
git commit -m "Fix: dashboard symbol autocomplete bug"

# Or with detailed description
git commit -m "Fix: dashboard symbol autocomplete bug

- Fixed fetch call to include credentials
- Updated default exchange to NFO
- Added error handling for empty results"

# Push to GitHub
git push origin main
```

### Useful Git Commands

#### View History

```bash
# See last 10 commits
git log --oneline -10

# See what changed in last commit
git show

# See changes on a specific file
git log -p shoonya_platform/api/dashboard/api/router.py

# Visual graph of branches
git log --graph --oneline --all
```

#### Branching (For Feature Development)

```bash
# Create feature branch
git checkout -b feature/add-telegram-alerts

# Work on feature...
git add .
git commit -m "Add: Telegram alert notifications"

# Push branch to GitHub
git push -u origin feature/add-telegram-alerts

# Create Pull Request on GitHub (merge to main later)
```

#### Sync Multiple Machines

**Machine A (Desktop)**:
```bash
git add .
git commit -m "Update risk limits"
git push origin main
```

**Machine B (EC2)**:
```bash
git pull origin main  # Get latest from Machine A
```

---

## Automation: Auto-Sync Daily Changes

### Option 1: Windows Task Scheduler (Auto-Commit & Push)

Create a PowerShell script `C:\sync_trading_terminal.ps1`:

```powershell
# Navigate to project
cd C:\Users\gaura\OneDrive\Desktop\shoonya\shoonya_platform

# Activate environment
.\env\Scripts\Activate.ps1

# Only commit if there are changes
$status = git status --porcelain
if ($status) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    git add .
    git commit -m "Auto-sync: $timestamp"
    git push origin main
    Write-Host "Synced successfully at $timestamp"
} else {
    Write-Host "No changes to sync"
}
```

**Schedule it to run every 2 hours**:
1. Open **Task Scheduler**
2. Click **Create Basic Task**
3. Name: `Trading Terminal Auto-Sync`
4. Trigger: Daily, repeat every 2 hours
5. Action: Run script
   - Program: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -File C:\sync_trading_terminal.ps1`
6. Click OK

### Option 2: Linux/EC2 (Cron Job)

Create a bash script `~/sync_trading_terminal.sh`:

```bash
#!/bin/bash

PROJECT_DIR="/home/ec2-user/TRADING_TERMINAL"
cd $PROJECT_DIR

# Activate virtual environment
source env/bin/activate

# Check for changes
if [ -n "$(git status --porcelain)" ]; then
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    git add .
    git commit -m "Auto-sync: $TIMESTAMP"
    git push origin main
    echo "Synced at $TIMESTAMP" >> ~/trading_terminal_sync.log
else
    echo "No changes to sync at $(date)" >> ~/trading_terminal_sync.log
fi
```

**Make it executable and schedule**:
```bash
chmod +x ~/sync_trading_terminal.sh

# Edit crontab
crontab -e

# Add this line (runs every 2 hours):
0 */2 * * * ~/sync_trading_terminal.sh

# View cron jobs
crontab -l
```

### Option 3: GitHub Actions (Automated Testing on Push)

Create `.github/workflows/auto-test.yml` in your repo root:

```yaml
name: Auto Test on Push

on:
  push:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.8'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
    
    - name: Run tests
      run: |
        pytest shoonya_platform/tests/ -v --tb=short
    
    - name: Comment on PR if tests fail
      if: failure()
      run: echo "⚠️ Tests failed! Check logs above."
```

Every `git push origin main` will automatically run tests!

---

## Rollback & Version Recovery

### Scenario 1: Undo Recent Uncommitted Changes

```bash
# See what you changed
git diff

# Discard changes to specific file
git checkout -- shoonya_platform/api/dashboard/router.py

# Discard ALL uncommitted changes
git checkout -- .
# or
git reset --hard
```

### Scenario 2: Undo Last Commit (Before Push)

```bash
# Undo last commit, keep changes
git reset --soft HEAD~1

# Undo last commit, discard changes
git reset --hard HEAD~1
```

### Scenario 3: Undo Pushed Commit (After Push to GitHub)

```bash
# See commit hash you want to revert to
git log --oneline -10

# Revert specific commit (creates new "undo" commit)
git revert 7ee3014

# Or go back to older version (destructive)
git reset --hard 7ee3014
git push origin main --force  # ⚠️ Only if you're sure!
```

### Scenario 4: Recover Deleted File

```bash
# See all commits that touched the file
git log -- shoonya_platform/execution/trading_bot.py

# Restore the file from a specific commit
git checkout 7ee3014 -- shoonya_platform/execution/trading_bot.py

# This will restore the file and you can commit it
git add shoonya_platform/execution/trading_bot.py
git commit -m "Restore: trading_bot.py from commit 7ee3014"
git push origin main
```

### Scenario 5: Create Backup Before Major Changes

```bash
# Create a backup branch
git branch backup-2026-01-31

# Later, if something goes wrong, switch to backup
git checkout backup-2026-01-31

# Or merge backup into main
git checkout main
git merge backup-2026-01-31
```

### Scenario 6: See All Changes Since Last Sync

```bash
# Compare current branch with remote
git diff origin/main

# See commits not yet pushed
git log origin/main..HEAD
```

---

## Dashboard Features

### 1. Place Order (Manual Order Entry)

**URL**: `http://localhost:8000/dashboard/web/place_order.html`

**Features**:
- Exchange selection (NFO default)
- Symbol autocomplete (starts with "NI" → NIFTY, NIFTYNXT200, etc.)
- Side: BUY / SELL
- Execution type: ENTRY / EXIT / TEST (SUCCESS/FAILURE)
- Order type: MARKET / LIMIT
- Quantity with lot size auto-fill
- Trigger orders with conditional execution
- Target & Stop Loss
- Trailing stop support
- Basket orders (multiple orders)
- Advanced multi-leg orders

**Example**: Buy 1 lot NIFTY 100 strike CALL, ENTRY, MARKET order:
1. Exchange: NFO
2. Symbol: NIFTY
3. Side: BUY
4. Execution: ENTRY
5. Qty: 75 (auto-fills for NIFTY)
6. Order Type: MARKET
7. Click "Submit" or "Add to Basket"

### 2. Option Chain Dashboard

**URL**: `http://localhost:8000/dashboard/web/option_chain_dashboard.html`

**Features**:
- Defaults to NFO / NIFTY / Latest Expiry
- Loads all call & put options with strikes
- Displays: LTP, Volume, IV, Open Interest, Greeks (Delta, Gamma, Theta, Vega)
- Refresh button to reload

**Data Source**: `shoonya_platform/market_data/option_chain/data/`

### 3. Orderbook

**URL**: `http://localhost:8000/dashboard/web/orderbook.html`

**Features**:
- System orders (from OMS)
- Broker orders (from exchange)
- Real-time status updates
- Filter by strategy

### 4. Home/Status Page

**URL**: `http://localhost:8000/dashboard/home`

**Displays**:
- Broker positions (current holdings)
- Positions summary (PnL, risk metrics)
- Holdings (cash & securities)
- System orders (last 200)
- Control intents (strategy commands queued)
- Risk state (current loss, max loss limit)
- Option chain heartbeat (data freshness)
- Signal activity (strategies running)

---

## Execution Engine Features

### Trading Strategies

Located in `shoonya_platform/strategies/`

#### Delta-Neutral Short Strangles (Recommended)

**Strategy**: Sell OTM calls & puts, profit from time decay

**Config Files**:
- `delta_neutral/configs/nifty.py` – NIFTY strategy
- `delta_neutral/configs/natgasmini.py` – Natural Gas strategy
- `delta_neutral/configs/crudeoilm.py` – Crude Oil strategy

**Parameters**:
```python
# Example from nifty.py
UNDERLYING = "NIFTY"
EXCHANGE = "NFO"
STRATEGY_NAME = "NIFTY_DELTA_NEUTRAL"

# Entry conditions
ENTRY_DELTA_THRESHOLD = 0.20  # Sell 20-delta options
ENTRY_IV_PERCENTILE = 70       # Wait for high IV

# Exit conditions
MAX_LOSS_PER_TRADE = 5000      # Exit if loss > ₹5000
PROFIT_TARGET = 2000           # Exit if profit > ₹2000
TIME_EXIT_DAYS = 5             # Exit after 5 days

# Risk limits
MAX_POSITION_SIZE = 10         # Max open positions
DAILY_LOSS_LIMIT = 20000       # Stop trading if daily loss > ₹20k
```

### Running a Strategy

```bash
# Activate environment
source env/bin/activate

# Run NIFTY strategy
python -m shoonya_platform.strategies.run delta_neutral.configs.nifty

# Run with custom config
python -m shoonya_platform.strategies.run delta_neutral.configs.natgasmini

# From dashboard (optional supervisor)
# POST http://localhost:8000/dashboard/strategy/start
# {"config_path": "delta_neutral.configs.nifty"}
```

### Strategy Lifecycle

```
START
  ↓
WAITING FOR ENTRY CONDITIONS
  ├─ Check market conditions, IV levels, Greeks
  ↓
ON_ENTRY (Place orders, open positions)
  ↓
MANAGING POSITION
  ├─ Monitor Greeks, P&L, time decay
  ├─ ADJUST if needed (add/remove legs)
  ↓
EXIT OR FORCE_EXIT
  ├─ Exit: Profit target hit / Time expired
  ├─ Force Exit: Loss limit hit / Manual command
  ↓
CLOSED (Reconcile trades, log PnL)
```

---

## Common Tasks & Troubleshooting

### Task 1: Add New Exchange Symbol

1. Update ScriptMaster cache:
   ```bash
   python scripts/scriptmaster.py --update
   ```

2. Restart dashboard (cache reloads on startup)

### Task 2: Change Risk Limits

Edit `shoonya_platform/risk/supreme_risk.py`:
```python
MAX_DAILY_LOSS = 50000      # Change this
MAX_POSITION_SIZE = 5        # Or this
```

Commit and push:
```bash
git add shoonya_platform/risk/
git commit -m "Update: daily loss limit to ₹50k"
git push origin main
```

### Task 3: Run Tests Locally

```bash
# All tests
pytest shoonya_platform/tests/ -v

# Specific test file
pytest shoonya_platform/tests/test_command_service.py -v

# Specific test function
pytest shoonya_platform/tests/test_command_service.py::test_command_registration -v

# Show print statements
pytest -v -s

# Stop on first failure
pytest -x
```

### Task 4: View Database

```bash
# Install SQLite browser (or use Python)
python

import sqlite3
conn = sqlite3.connect('shoonya_platform/persistence/data/orders.db')
cursor = conn.cursor()

# See all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(cursor.fetchall())

# View orders
cursor.execute("SELECT * FROM orders LIMIT 10;")
for row in cursor.fetchall():
    print(row)

conn.close()
```

### Task 5: Debug Market Data Issues

```bash
# Check option chain data freshness
ls -lh shoonya_platform/market_data/option_chain/data/

# View option chain heartbeat
cat shoonya_platform/market_data/option_chain/data/.supervisor_heartbeat

# Manually query option chain
python
from shoonya_platform.market_data.option_chain.db_access import OptionChainDB
db = OptionChainDB()
contracts = db.get_contracts("NFO", "NIFTY", "03-FEB-2026")
print(contracts)
```

### Troubleshooting: Git Issues

#### "fatal: bad revision 'HEAD~1'"
```bash
# Repo is corrupted or empty
git log  # Check if any commits exist
git status
```

#### "permission denied" when pushing
```bash
# Check remote URL
git remote -v

# If using HTTPS, you need GitHub token in password
# If using SSH, check SSH keys:
ssh -T git@github.com
```

#### "merge conflict"
```bash
# If you pull and have conflicts
git status  # See conflicted files

# Edit files manually, then:
git add .
git commit -m "Resolve: merge conflicts"
git push origin main
```

#### "committed wrong file"
```bash
# Undo last commit
git reset --soft HEAD~1

# Unstage wrong file
git reset HEAD wrong_file.py

# Stage correct files and re-commit
git add .
git commit -m "Correct commit message"
```

---

## Best Practices

### 1. Commit Messages

✅ **Good**:
```
Fix: dashboard symbol autocomplete bug

- Added credentials to fetch calls
- Fixed error handling for empty results
- Tested with NFO exchange
```

❌ **Bad**:
```
fixes stuff
updated
changes
```

### 2. Before Pushing

```bash
# Always pull first to avoid conflicts
git pull origin main

# Review changes
git diff

# Test locally
pytest shoonya_platform/tests/ -q

# Then push
git push origin main
```

### 3. Branch Strategy (For Teams)

```
main (production)
  ↑
  ├── feature/add-alerts (feature branch)
  ├── bugfix/fix-orderbook (bugfix branch)
  └── hotfix/critical-error (hotfix branch)
```

**Workflow**:
1. Create feature branch: `git checkout -b feature/my-feature`
2. Make commits: `git commit -m "..."`
3. Push: `git push -u origin feature/my-feature`
4. Create Pull Request on GitHub
5. Review & merge to main
6. Delete feature branch

### 4. Never Push Sensitive Data

Files in `.gitignore` (already excluded):
- `env/` – virtual environment
- `.env` – API keys, credentials
- `logs/` – log files
- `cookies.txt` – session tokens

**If you accidentally commit secrets**:
```bash
# Remove from history
git rm --cached secrets.txt
git add .gitignore
git commit -m "Remove: secrets.txt"
git push origin main

# Or use BFG for deep cleanup (advanced)
bfg --delete-files secrets.txt
```

### 5. Keep Local Environment Clean

```bash
# Remove uncommitted changes
git clean -fd

# Remove .pyc files
find . -type f -name "*.pyc" -delete

# Rebuild virtual environment
rm -rf env/
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

### 6. Sync Between Multiple Machines

**Order of Operations**:
1. **Machine A** (finish work): `git add . → git commit → git push origin main`
2. **Machine B** (start work): `git pull origin main`
3. **Machine B** (finish work): `git add . → git commit → git push origin main`
4. **Machine A** (resume work): `git pull origin main`

---

## Quick Reference

| Task | Command |
|------|---------|
| Clone repo | `git clone https://github.com/GauravKomarewar/TRADING_TERMINAL.git` |
| Pull latest | `git pull origin main` |
| View changes | `git status` or `git diff` |
| Commit | `git add . && git commit -m "message"` |
| Push | `git push origin main` |
| View history | `git log --oneline -10` |
| Undo changes | `git checkout -- .` |
| Undo commit | `git reset --soft HEAD~1` |
| Create branch | `git checkout -b feature/name` |
| Switch branch | `git checkout main` |
| Delete branch | `git branch -d feature/name` |
| Stash changes | `git stash` (save for later) |
| Apply stash | `git stash pop` |
| Force push (⚠️ risky) | `git push origin main --force` |

---

## Support & Resources

- **GitHub Repo**: https://github.com/GauravKomarewar/TRADING_TERMINAL
- **Git Documentation**: https://git-scm.com/doc
- **GitHub Help**: https://docs.github.com/en
- **Shoonya Broker Docs**: https://shoonya.python-docs.example
- **Project README**: See `README.md` in repo root

---

## Summary

✅ **You now have**:
- ✓ Automated daily sync (via cron/task scheduler)
- ✓ Easy rollback (git revert/reset)
- ✓ Multi-machine sync (pull/push)
- ✓ Full project documentation
- ✓ Testing framework (257+ tests)
- ✓ Dashboard with all features
- ✓ Execution engine ready to use

🚀 **Next Steps**:
1. Set up auto-sync (Option 1, 2, or 3 above)
2. Clone on EC2 / Azure
3. Configure strategy parameters
4. Run backtests
5. Deploy live trading

Happy trading! 📈

