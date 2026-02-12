# 🚀 DNSS Strategy Execution Guide
**Delta Neutral Short Strangle (DNSS) — Python & Web Interface**

---

## Overview

The **DNSS (Delta Neutral Short Strangle)** strategy can be executed in **two ways**:
1. **Direct Python Execution** — Standalone bot, full control
2. **Web Dashboard** — Browser-based control, intent-driven execution

Both methods support:
- ✅ Entry with delta-neutral short strangle
- ✅ Automatic adjustments when delta exceeds threshold
- ✅ Profit stepping (progressive exits)
- ✅ Real-time orphan leg monitoring
- ✅ Graceful error handling

---

## Method 1: Direct Python Execution

### 1.1 Quick Start (Legacy Bot)

**File:** `shoonya_platform/strategies/legacy/run.py`

```bash
# Activate environment
.\venv\Scripts\Activate.ps1

# Run with strategy module path
python shoonya_platform/strategies/legacy/run.py \
  "delta_neutral.dnss"
```

**What happens:**
1. Loads DNSS configuration from `delta_neutral/dnss.py`
2. Initializes broker connection
3. Fetches live option chain
4. Starts entry/adjustment loop
5. Monitors positions in real-time

### 1.2 Configuration (Python Way)

Create a config file: `shoonya_platform/strategies/delta_neutral/dnss_config.py`

```python
# Strategy metadata
STRATEGY_NAME = "NIFTY_DNSS_v1"
META = {
    "exchange": "NFO",
    "symbol": "NIFTY",
    "lot_size": 50,
}

# DNSS-specific parameters
CONFIG = {
    "entry_time": "09:20",
    "exit_time": "15:30",
    
    # Delta thresholds
    "target_entry_delta": 0.20,      # Target: ~20 delta short
    "delta_adjust_trigger": 0.50,     # Adjust if delta > 50
    "max_leg_delta": 0.65,            # Hard stop if delta > 65
    
    # Profit management
    "profit_step": 1500,              # Exit 1 leg after 1500 profit
    "cooldown_seconds": 60,           # Wait after adjustment
    
    # Order execution
    "order_type": "LIMIT",            # MARKET or LIMIT
    "product": "NRML",                # NRML or MIS
    "lot_qty": 1,                     # Number of lots
}

# Engine configuration
ENGINE = {
    "max_retries": 3,
    "retry_delay": 5,
}
```

### 1.3 Full Python Script (Standalone)

**File:** `scripts/run_dnss_bot.py` (create new)

```python
#!/usr/bin/env python3
"""
Standalone DNSS Bot Execution
Runs independently without dashboard
"""

import time
import logging
from datetime import datetime
from pathlib import Path

from shoonya_platform.execution.trading_bot import ShoonyaBot
from shoonya_platform.execution.market import DBBackedMarket
from shoonya_platform.core.config import Config
from shoonya_platform.strategies.delta_neutral.dnss import (
    DeltaNeutralShortStrangleStrategy,
    StrategyConfig as DnssStrategyConfig,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("DNSS_BOT")

# ====================================================================
# CONFIGURATION
# ====================================================================

STRATEGY_CONFIG = DnssStrategyConfig(
    entry_time='09:20',
    exit_time='15:30',
    
    # Delta control
    target_entry_delta=0.20,
    delta_adjust_trigger=0.50,
    max_leg_delta=0.65,
    
    # Profit stepping
    profit_step=1500,
    cooldown_seconds=60,
    
    # Execution
    order_type="LIMIT",
    product="NRML",
    lot_qty=1,
)

MARKET_CONFIG = {
    "exchange": "NFO",
    "symbol": "NIFTY",
}

# ====================================================================
# BOT EXECUTION
# ====================================================================

def main():
    logger.info("🚀 Starting DNSS Bot")
    
    # 1. Initialize bot
    bot = ShoonyaBot()
    broker = bot.broker
    
    logger.info(f"✅ Broker connected: {broker}")
    
    # 2. Initialize market (DB-backed option chain)
    market = DBBackedMarket(
        broker=broker,
        exchange=MARKET_CONFIG["exchange"],
        symbol=MARKET_CONFIG["symbol"],
    )
    
    logger.info(f"📊 Market initialized: {MARKET_CONFIG['symbol']}")
    
    # 3. Create strategy instance
    strategy = DeltaNeutralShortStrangleStrategy(
        exchange=MARKET_CONFIG["exchange"],
        symbol=MARKET_CONFIG["symbol"],
        expiry=market.expiry,
        get_option_func=market.get_nearest_option,
        config=STRATEGY_CONFIG,
    )
    
    logger.info("🎯 DNSS Strategy initialized")
    
    # 4. Run strategy loop
    try:
        while True:
            # Check if within trading hours
            now = datetime.now().time()
            entry_time = datetime.strptime(STRATEGY_CONFIG.entry_time, "%H:%M").time()
            exit_time = datetime.strptime(STRATEGY_CONFIG.exit_time, "%H:%M").time()
            
            if now < entry_time:
                logger.info(f"⏰ Waiting for entry time: {STRATEGY_CONFIG.entry_time}")
                time.sleep(60)
                continue
            
            if now > exit_time:
                logger.warning(f"⛔ Past exit time: {STRATEGY_CONFIG.exit_time}")
                if strategy.state.has_any_leg():
                    logger.warning("🛑 Exiting all positions")
                    strategy.exit_all_legs(broker)
                break
            
            # Main strategy loop
            logger.info("📈 Running strategy tick")
            strategy.on_tick(
                current_price=market.get_spot_price(),
                greeks_df=market.get_live_greeks(),
                broker=broker,
            )
            
            # Sleep before next tick
            time.sleep(30)  # Every 30 seconds
    
    except KeyboardInterrupt:
        logger.warning("⛔ User interrupted")
    except Exception as e:
        logger.exception(f"❌ Error: {e}")
    finally:
        # Cleanup
        if strategy.state.has_any_leg():
            logger.info("🛑 Closing all legs")
            strategy.exit_all_legs(broker)
        logger.info("✅ Bot stopped")

if __name__ == "__main__":
    main()
```

**Run it:**
```bash
python scripts/run_dnss_bot.py
```

### 1.4 Parameters Reference

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `entry_time` | str | "09:20" | Strategy starts after this time (HH:MM) |
| `exit_time` | str | "15:30" | Force exit all legs at this time |
| `target_entry_delta` | float | 0.20 | Target delta when entering (20% short) |
| `delta_adjust_trigger` | float | 0.50 | Trigger adjustment if delta becomes 50% |
| `max_leg_delta` | float | 0.65 | Hard stop, don't let leg exceed 65% delta |
| `profit_step` | float | 1500 | Exit one leg after ₹1500 profit |
| `cooldown_seconds` | int | 60 | Wait seconds before next adjustment |
| `order_type` | str | "LIMIT" | LIMIT or MARKET |
| `product` | str | "NRML" | NRML (normal) or MIS (intraday) |
| `lot_qty` | int | 1 | Number of lots to trade |

---

## Method 2: Web Dashboard Execution

### 2.1 Access Dashboard

**URL:** `http://localhost:8000/dashboard/`

**Login:** Use your broker credentials

### 2.2 Create DNSS Strategy in GUI

**Step 1: Open Strategy Builder**
```
Dashboard → Strategies → Create New Strategy
```

**Step 2: Fill Identity Section**
```
Name: "NIFTY_DNSS_Daily"
ID: "NIFTY_DNSS_DAILY"
Underlying: NIFTY
Exchange: NFO
Product: NRML
```

**Step 3: Configure Entry Section**
```
First Leg: 
  - Side: SELL
  - Type: Strangle (ATM ±2 strikes)
  - Strike: Automatically selected by delta
  - Quantity: 50 units (1 lot)
  - Delta Target: 0.20
  
Second Leg:
  - Auto-paired (opposite leg created)
  - Same delta target
```

**Step 4: Set Adjustment Rules**
```
Add Adjustment Condition:
  Trigger: Delta > 0.50 (on any leg)
  Action: Replace leg with new delta target 0.25
  Cooldown: 60 seconds
  Max retries: 3
```

**Step 5: Configure Exit**
```
Profit Target Method: Stepping
  - After ₹1500 profit: Close 1 leg
  - After ₹3000 profit: Close remaining
  
OR Fixed Time:
  - Exit all at 15:30
```

**Step 6: Risk Management**
```
Daily P&L Limit: -₹5000 (stop if daily loss exceeds)
Max Position Delta: 0.65 (hard stop)
Per-Leg Max Theta: -₹100/hour (soft warning)
```

**Step 7: Save Strategy**
```
Click "Save Strategy"
→ Stored in: /strategies/saved_configs/nifty_dnss_daily.json
```

### 2.3 Launch Strategy from Dashboard

**Step 1: View Strategies**
```
Strategies → My Strategies
(Shows saved DNSS configuration)
```

**Step 2: Click Start**
```
Strategy Card → [▶ Start] button
→ Creates intent: ENTRY action
→ Queued to execution consumer
```

**Step 3: Monitor in Real-Time**
```
Live Monitor Panel:
  - Orphan Legs: Shows unhedged positions
  - Combined Greeks: Overall delta/gamma/theta
  - P&L Ladder: Shows profit stepping progress
  - Status: RUNNING / PAUSED / STOPPED
```

**Step 4: Manual Control**
```
During Execution:
  [⏸ Pause] → ADJUST intent (advisory, stops new entries)
  [🛑 Stop] → EXIT intent (gracefully closes all)
  [Force Exit] → FORCE_EXIT (immediate liquidation)
```

### 2.4 Dashboard Configuration JSON Format

**File created automatically:** `/strategies/saved_configs/nifty_dnss_daily.json`

```json
{
  "schema_version": "2.0",
  "name": "NIFTY_DNSS_Daily",
  "id": "NIFTY_DNSS_DAILY",
  "status": "IDLE",
  "created_at": "2026-02-11T09:00:00",
  "updated_at": "2026-02-11T14:30:00",
  
  "identity": {
    "underlying": "NIFTY",
    "exchange": "NFO",
    "product": "NRML",
    "expiry": "28FEB2026"
  },
  
  "entry": {
    "entry_time": "09:20",
    "exit_time": "15:30",
    "legs": [
      {
        "side": "SELL",
        "type": "CE",
        "strike": "ATM",
        "quantity": 50,
        "target_delta": 0.20
      },
      {
        "side": "SELL",
        "type": "PE",
        "strike": "ATM",
        "quantity": 50,
        "target_delta": 0.20
      }
    ]
  },
  
  "adjustment": {
    "enabled": true,
    "rules": [
      {
        "trigger": "delta_exceeds",
        "threshold": 0.50,
        "action": "replace_leg",
        "target_delta": 0.25,
        "cooldown_seconds": 60,
        "max_retries": 3
      }
    ]
  },
  
  "exit": {
    "method": "profit_stepping",
    "targets": [
      { "profit": 1500, "action": "close_one_leg" },
      { "profit": 3000, "action": "close_all" }
    ]
  },
  
  "rms": {
    "daily_loss_limit": -5000,
    "max_position_delta": 0.65,
    "per_leg_max_theta": -100
  }
}
```

---

## Comparison: Python vs Web

| Aspect | Python (Direct) | Web Dashboard |
|--------|---|---|
| **Setup** | Code only | GUI form builder |
| **Real-time Control** | Modify code + restart | Live buttons |
| **Monitoring** | Console logs | Rich charts + tables |
| **Flexibility** | Full code access | Pre-configured options |
| **Learning Curve** | Steeper | Beginner-friendly |
| **Scalability** | Single instance | Multi-strategy support |
| **Backup/Version** | Manual git | Auto-saved JSON files |
| **Parameter Testing** | Edit config + rerun | Save multiple configs |
| **Live Adjustment** | Pause + code change | Click "Pause" button |

---

## Execution Flow (Both Methods)

```
┏═══════════════════════════════════════════════════════════┓
┃              DNSS Strategy Execution Pipeline              ┃
┗═══════════════════════════════════════════════════════════┛

METHOD 1: PYTHON
─────────────────────────────────────────────────────────────
run.py or run_dnss_bot.py
  ↓
Initialize Broker Connection
  ↓
Load Option Chain (NFO/NIFTY)
  ↓
Resolve Expiry (nearest weekly/monthly)
  ↓
Create DeltaNeutralShortStrangleStrategy instance
  ↓
Loop: on_tick() every 30 seconds
  ├─ Fetch current Greeks
  ├─ Check entry time window
  ├─ Execute ENTRY if conditions met
  ├─ Monitor positions
  ├─ Check adjustment triggers
  ├─ Execute ADJUST if delta exceeded
  └─ Check profit targets → Exit legs
  ↓
At exit time: Force close all legs
  ↓
Bot stops


METHOD 2: WEB DASHBOARD
─────────────────────────────────────────────────────────────
1. Create Strategy (Web UI)
   ↓
2. Save to /strategies/saved_configs/
   ↓
3. Click [Start] Button
   ↓
4. POST /dashboard/intent/strategy {
      "strategy_name": "NIFTY_DNSS_DAILY",
      "action": "ENTRY"
   }
   ↓
5. DashboardIntentService receives intent
   ↓
6. Persists intent to control_intents SQLite table
   ↓
7. strategy_control_consumer polls table
   ↓
8. Loads saved strategy config
   ↓
9. Creates UniversalStrategyConfig
   ↓
10. Calls strategy_manager.start_strategy()
   ↓
11. Creates DeltaNeutralShortStrangleStrategy
   ↓
12. Execution Loop (same as Method 1)
   ↓
13. Live monitor updates in dashboard
   ↓
14. User can [Pause] or [Stop] via web buttons
```

---

## Key Features (Both Methods)

### Entry Phase
- Scans option chain for ATM strikes
- Calculates delta for each strike
- Selects strikes with delta closest to target (0.20)
- Places SELL orders simultaneously for both legs
- Confirms entry when both filled

### Adjustment Phase
```python
# From dnss.py code:
if strategy.state.total_delta() > config.delta_adjust_trigger:
    # 2-phase atomic adjustment
    # Phase 1: Exit high-delta leg
    # Phase 2: Enter new low-delta leg
    # Ensures no naked exposure during adjustment
```

### Exit Phase
```python
# Profit stepping example:
if unrealized_pnl >= 1500:
    close_one_leg()  # Reduce exposure
    next_target = 3000

if unrealized_pnl >= 3000:
    close_all_legs()  # Full exit
```

### Orphan Leg Detection
- Tracks position state from broker
- Identifies positions without matching hedge
- Shows in real-time monitor
- Can be manually closed

---

## Troubleshooting

### Python Method Issues

**Issue: Strategy not starting**
```
Check:
1. Broker login credentials valid
2. Trading session started (9:15 AM - 3:30 PM)
3. Option chain available for symbol
4. Sufficient margin in account
```

**Issue: Delta not converging**
```
Possible causes:
- Target delta too aggressive (try 0.30 instead of 0.20)
- Illiquid options (try ATM strikes)
- Market volatility too high (wait for calm)
```

**Issue: Adjustment stuck**
```
Check cooldown_seconds setting:
- Increase if too many consecutive adjustments
- Default 60 seconds is usually sufficient
```

### Web Dashboard Issues

**Issue: Strategy not appearing in list**
```
Check:
1. Strategy saved (look for file in /strategies/saved_configs/)
2. Refresh browser (F5)
3. Check browser console for errors
```

**Issue: Start button doesn't work**
```
Check:
1. All required parameters filled
2. Valid entry/exit times
3. Network connection to backend (check Network tab)
4. Backend service running
```

**Issue: Monitor shows no data**
```
Check:
1. Strategy is RUNNING (not IDLE)
2. Positions actually exist (broker shows them)
3. Check "STALE" indicator (API timeout)
4. Backend logs for errors
```

---

## Production Checklist

- [ ] Test on paper trading first
- [ ] Verify delta thresholds with live option chain
- [ ] Check profit stepping levels with recent volatility
- [ ] Confirm exit times match market hours
- [ ] Set up risk limits (daily loss, max position size)
- [ ] Monitor first 3-5 runs manually
- [ ] Set up alerting for adjustment frequency
- [ ] Backup strategy configs regularly
- [ ] Have manual exit plan ready
- [ ] Document parameter changes

---

## Advanced: Multi-Strategy Execution

**Web Dashboard supports running multiple DNSS strategies simultaneously:**

```json
[
  {
    "name": "NIFTY_DNSS_Morning",
    "symbol": "NIFTY",
    "entry_time": "09:20",
    "exit_time": "12:00"
  },
  {
    "name": "NIFTY_DNSS_Afternoon",
    "symbol": "NIFTY",
    "entry_time": "13:00",
    "exit_time": "15:30"
  },
  {
    "name": "BANKNIFTY_DNSS_Daily",
    "symbol": "BANKNIFTY",
    "entry_time": "09:20",
    "exit_time": "15:30"
  }
]
```

Each runs independently with own state tracking and risk limits.

---

## Resources

- **Strategy Code:** `shoonya_platform/strategies/delta_neutral/dnss.py`
- **Legacy Runner:** `shoonya_platform/strategies/legacy/run.py`
- **Web Integration:** `shoonya_platform/api/dashboard/web/strategy.html`
- **API Router:** `shoonya_platform/api/dashboard/api/router.py`
- **Execution Consumer:** `shoonya_platform/execution/strategy_control_consumer.py`

---

**Last Updated:** 2026-02-11  
**DNSS Version:** v1.1.0 (Production Frozen)  
**Status:** Production Ready ✅
