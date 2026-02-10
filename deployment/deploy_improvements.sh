#!/bin/bash

# ============================================
# DEPLOYMENT SCRIPT FOR SESSION & SCHEDULER IMPROVEMENTS
# ============================================

echo "🚀 Deploying Shoonya Platform Improvements..."
echo "=============================================="
echo ""

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from shoonya_platform root directory"
    exit 1
fi

# Step 1: Reload systemd daemon
echo "📋 Step 1: Reloading systemd daemon..."
sudo systemctl daemon-reload
if [ $? -eq 0 ]; then
    echo "✅ Systemd reloaded"
else
    echo "❌ Failed to reload systemd"
    exit 1
fi

# Step 2: Update main service file
echo ""
echo "🔧 Step 2: Updating main service file..."
sudo cp deployment/trading.service /etc/systemd/system/trading.service
if [ $? -eq 0 ]; then
    echo "✅ Service file updated"
else
    echo "❌ Failed to update service file"
    exit 1
fi

# Step 3: Install scheduler timers
echo ""
echo "⏰ Step 3: Installing scheduler timers..."
chmod +x deployment/install_schedulers.sh
./deployment/install_schedulers.sh
if [ $? -eq 0 ]; then
    echo "✅ Schedulers installed"
else
    echo "❌ Failed to install schedulers"
    exit 1
fi

# Step 4: Reload systemd again to pick up all changes
echo ""
echo "📋 Step 4: Final systemd reload..."
sudo systemctl daemon-reload

# Step 5: Restart the service
echo ""
echo "🔄 Step 5: Restarting trading..."
sudo systemctl restart trading
sleep 3

# Step 6: Check service status
echo ""
echo "📊 Step 6: Checking service status..."
sudo systemctl status trading --no-pager -l

# Step 7: Verify timers
echo ""
echo "⏰ Step 7: Verifying timers..."
echo ""
sudo systemctl list-timers shoonya_* --no-pager

echo ""
echo "=============================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "=============================================="
echo ""
echo "📊 Monitor the system:"
echo "   journalctl -u trading -f"
echo ""
echo "💓 Check telegram for heartbeat (5 min intervals)"
echo ""
echo "📋 Next heartbeat: ~5 minutes from now"
echo "📊 Next status report: ~10 minutes from now"
echo ""
echo "🕐 Auto-Start: Mon-Fri at 8:45 AM"
echo "🛑 Auto-Stop: Daily at 12:00 AM"
echo ""
