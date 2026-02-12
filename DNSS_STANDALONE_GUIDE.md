# DNSS Standalone Execution Guide

## Overview

The DNSS (Delta Neutral Short Strangle) strategy can now run **standalone** directly from a configuration file, without needing the dashboard or API.

This enables:
- ✅ Standalone automated trading
- ✅ Service-based execution (systemd, Windows services)
- ✅ Testing and development
- ✅ Multi-strategy parallel execution
- ✅ Command-line control

---

## Prerequisites

1. **Virtual Environment**: Must be set up with bootstrap.py
   ```bash
   python bootstrap.py
   ```

2. **Broker Configuration**: `config_env/primary.env` must be set with:
   ```env
   DASHBOARD_PASSWORD=<your_password>
   # Broker credentials
   SHO_USERNAME=<broker_username>
   SHO_PASSWORD=<broker_password>
   SHO_TWO_FA=<2FA_token>
   ```

3. **Strategy Configuration**: JSON config file (saved from dashboard or created manually)
   - Default location: `shoonya_platform/strategies/saved_configs/dnss_nifty_weekly.json`
   - Or any custom path

---

## Quick Start

### 1. Create/Configure Strategy in Dashboard

Go to Dashboard → Create Strategy → Configure all sections:
- **Identity**: Symbol, Exchange, Product type, Order type, Lot size
- **Entry**: Entry time, Timing conditions
- **Adjustment**: Delta triggers, profit targets
- **Exit**: Exit time, Stop loss, Profit targets
- **Risk Management**: Limits, position caps
- **Schedule**: Active days, frequency

Click **Save Strategy** → generates `saved_configs/{strategy_name}.json`

### 2. Run Directly from Command Line

```bash
# Activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
# or
source ./venv/bin/activate   # Linux/macOS

# Run DNSS with config
python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/dnss_nifty_weekly.json
```

#### Options:
```bash
# Run with custom config file
python -m shoonya_platform.strategies.delta_neutral \
  --config /path/to/config.json

# Run for limited time (30 minutes)
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/config.json \
  --duration 30

# Customize polling interval (default: 2.0 seconds)
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/config.json \
  --poll-interval 1.0

# Enable verbose logging
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/config.json \
  --verbose
```

---

## Service-Based Execution

### Windows Service (PowerShell)

```powershell
# Run standalone service
.\run_dnss_service.ps1

# Or specify custom config via environment variable
$env:DNSS_CONFIG = ".\saved_configs\my_custom_config.json"
.\run_dnss_service.ps1
```

**Features:**
- ✅ Validates virtual environment
- ✅ Validates broker configuration
- ✅ Graceful shutdown on Ctrl+C
- ✅ Loads config from `DNSS_CONFIG` env var or default
- ✅ Color-coded console output

### Linux/macOS Service (Systemd)

```bash
# Copy service file
sudo cp deployment/dnss.service /etc/systemd/system/

# Update config path in service file (if needed)
sudo nano /etc/systemd/system/dnss.service

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable dnss
sudo systemctl start dnss

# Monitor logs
sudo journalctl -u dnss -f

# Stop service
sudo systemctl stop dnss
```

**Service File:**
```ini
[Unit]
Description=DNSS Strategy Service
After=network.target

[Service]
Type=simple
User=trading
WorkingDirectory=/opt/shoonya_platform
Environment="DNSS_CONFIG=/opt/shoonya_platform/saved_configs/dnss_nifty_weekly.json"
EnvironmentFile=/opt/shoonya_platform/config_env/primary.env
ExecStart=/opt/shoonya_platform/venv/bin/python -m shoonya_platform.strategies.delta_neutral --config $DNSS_CONFIG
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
StandardOutput=journal
```

---

## Configuration File Format

Strategy configs are JSON files saved in `saved_configs/` directory:

```json
{
  "schema_version": "2.0",
  "name": "DNSS NIFTY Weekly",
  "id": "DNSS_NIFTY_WEEKLY",
  "description": "Delta Neutral Short Strangle...",
  
  "identity": {
    "strategy_type": "dnss",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "instrument_type": "OPTIDX",
    "product_type": "NRML",
    "order_type": "LIMIT"
  },
  
  "entry": {
    "timing": {
      "entry_time": "09:20",
      "exit_time": "15:15"
    },
    "position": {
      "lots": 1
    },
    "legs": {
      "target_entry_delta": 0.20
    }
  },
  
  "adjustment": {
    "delta": {
      "trigger": 0.50,
      "target": 0.20,
      "max_leg_delta": 0.65
    },
    "pnl": {
      "profit_lock_trigger": 1500
    },
    "general": {
      "cooldown_seconds": 60
    }
  },
  
  "exit": {
    "time": {
      "exit_time": "15:15"
    }
  }
}
```

---

## Execution Flow

### What Happens During Standalone Execution:

1. **Loading**
   - Reads JSON config from disk
   - Validates all required fields
   - Converts dashboard schema → execution schema

2. **Initialization**
   - Connects to market data source (SQLite DB)
   - Creates DNSS strategy instance with config
   - Initializes state and leggers

3. **Polling Loop** (runs every 2 seconds by default)
   - Fetches latest market data
   - Calls `strategy.prepare()` → updates greeks, prices
   - Calls `strategy.on_tick()` → logic execution
   - Generates orders if entry/adjustment/exit conditions met
   - Logs status every 60 ticks (2 minutes)

4. **Termination** (on Ctrl+C or duration limit)
   - Prints execution summary
   - Exits gracefully
   - Shows final PnL and state

---

## Output Examples

### Startup
```
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | 📂 Loading config from: ./saved_configs/dnss_nifty_weekly.json
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | ✅ Config loaded: DNSS NIFTY Weekly
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | ✅ Config validated | NIFTY | Entry: 09:20 | Exit: 15:15
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | 🔧 Initializing market and strategy...
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | 📊 Creating DBBackedMarket | NFO NIFTY
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | 🚀 Creating DNSS strategy | NIFTY
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | ✅ Strategy initialized | Expiry: NIFTY26FEB2026
2026-02-12 10:15:30 | INFO     | DNSS_STANDALONE  | ▶️  Starting execution loop | poll_interval=2.0s
```

### During Execution
```
2026-02-12 10:15:40 | INFO     | DNSS_STANDALONE  | 📊 Strategy Status | Ticks: 60 | State: IDLE | PnL: 0.00
2026-02-12 10:16:10 | WARNING  | DNSS_STANDALONE  | ⚠️  Strategy generated 2 command(s)
2026-02-12 10:16:10 | INFO     | DNSS_STANDALONE  |    → SELL NIFTY26FEB2650CE qty=50
2026-02-12 10:16:10 | INFO     | DNSS_STANDALONE  |    → SELL NIFTY26FEB2750PE qty=50
```

### Shutdown
```
======================================================================
EXECUTION SUMMARY
  Ticks executed: 120
  Errors: 0
  Final State: ACTIVE
  Unrealized PnL: -1250.00
  Realized PnL: 0.00
======================================================================
```

---

## Troubleshooting

### Config file not found
```
❌ Config file not found: ./saved_configs/dnss_nifty_weekly.json
   Set DNSS_CONFIG environment variable or create config at:
   ./saved_configs/dnss_nifty_weekly.json
```

**Solution:** 
1. Create strategy in dashboard first
2. Or pass full path: `--config /full/path/to/config.json`

### Missing environment configuration
```
❌ Failed to load environment: ...
```

**Solution:**
1. Ensure `config_env/primary.env` exists
2. Run `python bootstrap.py` to set up environment

### Invalid JSON config
```
❌ Invalid JSON: Expecting value: line 1 column 1 (char 0)
```

**Solution:**
1. Validate JSON syntax: `python -m json.tool saved_configs/config.json`
2. Use config from dashboard (guaranteed valid)

### Market data unavailable
```
❌ Initialization failed: Cannot connect to market data source
```

**Solution:**
1. Ensure SQLite market data is available
2. Check broker connection
3. Verify `config_env/primary.env` credentials

---

## Running Multiple Strategies Simultaneously

You can run multiple DNSS instances with different configs:

```bash
# Terminal 1: NIFTY strategy
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_nifty_weekly.json &

# Terminal 2: BANKNIFTY strategy
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_banknifty_daily.json &

# Terminal 3: FINNIFTY strategy
python -m shoonya_platform.strategies.delta_neutral \
  --config ./saved_configs/dnss_finnifty_weekly.json &
```

Or use systemd with multiple service instances:

```bash
# Copy service file for each instance
sudo cp /etc/systemd/system/dnss.service /etc/systemd/system/dnss-nifty.service
sudo cp /etc/systemd/system/dnss.service /etc/systemd/system/dnss-banknifty.service

# Edit each service file with different config paths
sudo nano /etc/systemd/system/dnss-nifty.service
# Change: Environment="DNSS_CONFIG=.../dnss_nifty_weekly.json"

# Enable and start
sudo systemctl enable dnss-nifty dnss-banknifty
sudo systemctl start dnss-nifty dnss-banknifty

# Monitor all logs
sudo journalctl -u dnss-nifty -u dnss-banknifty -f
```

---

## Integration with Dashboard

**Standalone execution and Dashboard are NOT mutually exclusive:**

1. **Create strategy in dashboard** (GUI, full validation, testing)
   ↓
2. **Activate via dashboard** OR **run standalone**
   ↓
3. **Dashboard polls execution service** for real-time updates
   ↓
4. **View live PnL, positions, status in dashboard**

The standalone mode is just an alternative activation method. All positions and state are managed by the same broker connection and visible in the dashboard.

---

## Performance Considerations

| Setting | Default | Impact |
|---------|---------|--------|
| **Poll Interval** | 2.0s | How often strategy logic runs. Increase for low-frequency strategies, decrease for high-frequency |
| **Config Load Time** | ~100ms | Only happens once at startup |
| **Per-Tick Overhead** | ~50-200ms | Market data fetch + strategy logic. Monitor in logs |
| **Memory Usage** | ~200-300MB | Depends on market data cache size |

Monitor the logs:
```
📊 Strategy Status | Ticks: 60 | State: IDLE | PnL: 0.00
```

If tick duration exceeds poll interval, consider:
- Increasing `--poll-interval`
- Reducing market data refresh frequency
- Moving to separate machine for strategy isolation

---

## Advanced: Custom Configuration

To create a custom config file programmatically:

```python
import json
from pathlib import Path

# Create strategy config
config = {
    "schema_version": "2.0",
    "name": "My DNSS Strategy",
    "id": "MY_DNSS",
    
    "identity": {
        "exchange": "NFO",
        "underlying": "NIFTY",
        "instrument_type": "OPTIDX",
        "product_type": "NRML",
        "order_type": "LIMIT",
    },
    
    "entry": {
        "timing": {
            "entry_time": "09:20",
            "exit_time": "15:15",
        },
        "position": {"lots": 1},
        "legs": {"target_entry_delta": 0.20},
    },
    
    "adjustment": {
        "delta": {
            "trigger": 0.50,
            "target": 0.20,
            "max_leg_delta": 0.65,
        },
        "pnl": {"profit_lock_trigger": 1500},
        "general": {"cooldown_seconds": 60},
    },
}

# Save to file
config_path = Path("saved_configs/my_config.json")
config_path.write_text(json.dumps(config, indent=2))

# Run strategy
import subprocess
subprocess.run([
    "python", "-m", "shoonya_platform.strategies.delta_neutral",
    "--config", str(config_path),
])
```

---

## Next Steps

1. ✅ Create strategy in dashboard
2. ✅ Test via `python -m shoonya_platform.strategies.delta_neutral --config ./saved_configs/...`
3. ✅ Set up as service (systemd/PowerShell)
4. ✅ Configure monitoring/alerts
5. ✅ Monitor via dashboard or logs

---

For more information, see:
- [Strategy Configuration Guide](DNSS_EXECUTION_GUIDE.md)
- [Architecture Overview](ARCHITECTURE_DIAGRAMS.md)
- [API Reference](DOCS/API_REFERENCE.json)
