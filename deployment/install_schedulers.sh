#!/bin/bash

# ============================================
# SYSTEMD SCHEDULER SETUP GUIDE
# ============================================
# This script installs systemd timers for automatic
# service start/stop on weekdays

echo "🕐 Installing Trading Platform Systemd Schedulers..."

# Copy service and timer files
sudo cp deployment/systemd/trading_start.timer /etc/systemd/system/
sudo cp deployment/systemd/trading_stop.timer /etc/systemd/system/
sudo cp deployment/systemd/trading_start.service /etc/systemd/system/
sudo cp deployment/systemd/trading_stop.service /etc/systemd/system/
sudo cp deployment/systemd/trading_weekend_check.service /etc/systemd/system/
sudo cp deployment/systemd/trading_weekend_check.timer /etc/systemd/system/

# Update systemd registry
echo "📋 Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable timers (they will start on boot)
echo "⏰ Enabling auto-start timer (Mon-Fri 8:45 AM)..."
sudo systemctl enable trading_start.timer

echo "⏰ Enabling auto-stop timer (Daily 12:00 AM)..."
sudo systemctl enable trading_stop.timer

echo "⏰ Enabling weekend check timer (Sat-Sun 9:00 AM)..."
sudo systemctl enable trading_weekend_check.timer

# Start the timers immediately
echo "▶️ Starting timers..."
sudo systemctl start trading_start.timer
sudo systemctl start trading_stop.timer
sudo systemctl start trading_weekend_check.timer

echo ""
echo "✅ Installation complete!"
echo ""
echo "📊 Check timer status:"
echo "   sudo systemctl list-timers trading_*"
echo ""
echo "📋 View timer details:"
echo "   sudo systemctl status trading_start.timer"
echo "   sudo systemctl status trading_stop.timer"
echo "   sudo systemctl status trading_weekend_check.timer"
echo ""
echo "🛑 Disable all timers:"
echo "   sudo systemctl stop trading_start.timer"
echo "   sudo systemctl stop trading_stop.timer"
echo "   sudo systemctl stop trading_weekend_check.timer"
echo "   sudo systemctl disable trading_start.timer"
echo "   sudo systemctl disable trading_stop.timer"
echo "   sudo systemctl disable trading_weekend_check.timer"
echo ""
echo "🔧 Schedule Details:"
echo "   • Auto-Start: Monday-Friday at 8:45 AM"
echo "   • Auto-Stop:  Daily at 12:00 AM (midnight)"
echo "   • Weekend Check: Saturday-Sunday at 9:00 AM"
echo ""
