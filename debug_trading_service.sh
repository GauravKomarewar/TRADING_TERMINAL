#!/bin/bash
# Detailed trading service debug script

echo "=== Trading Service Status ==="
sudo systemctl status trading

echo ""
echo "=== Last 300 lines of journal ==="
sudo journalctl -u trading -n 300 --no-pager

echo ""
echo "=== Python syntax check ==="
cd /home/ec2-user/shoonya_platform
source venv/bin/activate
python -m py_compile shoonya_platform/market_data/feeds/index_tokens_subscriber.py
echo "✓ index_tokens_subscriber.py syntax OK"

echo ""
echo "=== Import test ==="
python -c "from shoonya_platform.market_data.feeds import index_tokens_subscriber; print('✓ Import successful')" 2>&1

echo ""
echo "=== Main startup test ===" 
python -c "from shoonya_platform.execution.trading_bot import ShoonyaBot; print('✓ Trading bot import OK')" 2>&1 | head -100

echo ""
echo "=== Service restart with direct output ==="
cd /home/ec2-user/shoonya_platform
source venv/bin/activate
python main.py 2>&1 | head -100 &
sleep 10
pkill -f "python main.py"
