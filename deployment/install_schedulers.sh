#!/bin/bash

# ============================================
# SYSTEMD SCHEDULER SETUP GUIDE
# ============================================
# This script installs systemd timers for automatic
# service start/stop on weekdays

echo "🕐 Installing Shoonya Platform Systemd Schedulers..."

# Copy service and timer files
sudo  cp systemd/shoonya_start.timer /etc/systemd/system/
sudo cp systemd/shoonya_stop.timer /etc/systemd/system/
sudo cp systemd/shoonya_start.service /etc/systemd/system/
sudo cp systemd/shoonya_stop.service /etc/systemd/system/

# Update systemd registry
echo "📋 Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable timers (they will start on boot)
echo "⏰ Enabling auto-start timer (Mon-Fri 8:45 AM)..."
sudo systemctl enable shoonya_start.timer

echo "⏰ Enabling auto-stop timer (Daily 12:00 AM)..."
sudo systemctl enable shoonya_stop.timer

# Start the timers immediately
echo "▶️ Starting timers..."
sudo systemctl start shoonya_start.timer
sudo systemctl start shoonya_stop.timer

echo ""
echo "✅ Installation complete!"
echo ""
echo "📊 Check timer status:"
echo "   sudo systemctl list-timers shoonya_*"
echo ""
echo "📋 View timer details:"
echo "   sudo systemctl status shoonya_start.timer"
echo "   sudo systemctl status shoonya_stop.timer"
echo ""
echo "🛑 Disable auto-start/stop:"
echo "   sudo systemctl stop shoonya_start.timer"
echo "   sudo systemctl stop shoonya_stop.timer"
echo "   sudo systemctl disable shoonya_start.timer"
echo "   sudo systemctl disable shoonya_stop.timer"
echo ""
echo "🔧 Schedule Details:"
echo "   • Auto-Start: Monday-Friday at 8:45 AM"
echo "   • Auto-Stop:  Daily at 12:00 AM (midnight)"
echo ""
