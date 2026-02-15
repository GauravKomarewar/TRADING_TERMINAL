#!/bin/bash
#
# Delta Neutral Short Strangle (DNSS) Strategy Service Runner
# For manual execution on Linux/macOS
#

set -e

echo "ðŸš€ Starting DNSS Strategy Service..."
echo ""

# Get script directory (project root)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Validate prerequisites
echo "ðŸ” Validating prerequisites..."

if [ ! -f "./venv/bin/activate" ]; then
    echo "âŒ Virtual environment not found!"
    echo "ðŸ‘‰ Run: python bootstrap.py"
    exit 1
fi

if [ ! -f "./config_env/primary.env" ]; then
    echo "âŒ Configuration file not found!"
    echo "ðŸ‘‰ Create config_env/primary.env with your broker credentials"
    exit 1
fi

# Activate virtual environment
echo "ðŸ”§ Activating virtual environment..."
source ./venv/bin/activate

echo "âœ… Prerequisites validated"
echo ""

# Set environment variables
export PYTHONUNBUFFERED=1
export DASHBOARD_ENV=primary

# Load config
set -a
source ./config_env/primary.env
set +a

# Display service info
echo "======================================================================"
echo "DNSS STRATEGY SERVICE STARTING"
echo "======================================================================"
echo "ðŸ“Š Strategy: Delta Neutral Short Strangle (DNSS)"
echo "â¹ï¸  Press Ctrl+C to stop gracefully"
echo "ðŸ“ Config: config_env/primary.env"
echo "======================================================================"
echo ""

# Get config file path (default or from environment variable)
DNSS_CONFIG="${DNSS_CONFIG:-./shoonya_platform/strategy_runner/saved_configs/dnss_nifty_weekly.json}"

if [ ! -f "$DNSS_CONFIG" ]; then
    echo "âŒ Config file not found: $DNSS_CONFIG"
    echo "   Set DNSS_CONFIG environment variable or create config at:"
    echo "   ./shoonya_platform/strategy_runner/saved_configs/dnss_nifty_weekly.json"
    exit 1
fi

# Run DNSS strategy with config
trap 'echo ""; echo "ðŸ›‘ DNSS service stopped"; deactivate' EXIT

echo "â–¶ï¸  Starting trading service (strategy_runner mode)..."
echo "   Strategy config path (for dashboard start): $DNSS_CONFIG"
python main.py


