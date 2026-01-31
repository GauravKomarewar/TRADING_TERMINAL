#!/usr/bin/env python3
"""
Supervisor Health Monitor
=========================

External script to monitor OptionChainSupervisor health via heartbeat file.

Usage:
    python supervisor_monitor.py [--alert] [--verbose]

Returns:
    0 = Healthy
    1 = Warning (degraded but running)
    2 = Critical (supervisor down or stalled)

Integration:
    - Run via cron every minute
    - Alert on non-zero exit codes
    - Can integrate with monitoring systems (Prometheus, Grafana, etc.)
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple

# =====================================================================
# CONFIGURATION
# =====================================================================

HEARTBEAT_FILE = Path(__file__).resolve().parent / "data" / ".supervisor_heartbeat"
HEARTBEAT_TIMEOUT = 60       # seconds - consider stale after this
FEED_STALL_THRESHOLD = 30    # seconds - feed is stalled
MAX_STALL_COUNT = 5          # consecutive stalls before critical

# =====================================================================
# MONITORING FUNCTIONS
# =====================================================================

def read_heartbeat() -> Tuple[bool, Dict[str, Any], str]:
    """
    Read and parse heartbeat file.
    
    Returns:
        (success, data_dict, error_message)
    """
    if not HEARTBEAT_FILE.exists():
        return False, {}, "Heartbeat file not found"
    
    try:
        with open(HEARTBEAT_FILE, 'r') as f:
            lines = f.readlines()
        
        if len(lines) < 5:
            return False, {}, f"Heartbeat file incomplete ({len(lines)} lines)"
        
        data = {
            "timestamp": float(lines[0].strip()),
            "chain_count": int(lines[1].strip()),
            "login_status": lines[2].strip(),
            "last_snapshot": float(lines[3].strip()),
            "stall_count": int(lines[4].strip()),
        }
        
        return True, data, ""
        
    except Exception as e:
        return False, {}, f"Failed to parse heartbeat: {e}"


def check_supervisor_health(verbose: bool = False) -> Tuple[int, str]:
    """
    Check supervisor health status.
    
    Returns:
        (exit_code, message)
        0 = Healthy
        1 = Warning
        2 = Critical
    """
    # Read heartbeat
    success, data, error = read_heartbeat()
    
    if not success:
        return 2, f"CRITICAL: {error}"
    
    now = time.time()
    issues = []
    warnings = []
    
    # Check heartbeat age
    heartbeat_age = now - data["timestamp"]
    if heartbeat_age > HEARTBEAT_TIMEOUT:
        issues.append(f"Heartbeat stale ({heartbeat_age:.0f}s old)")
    elif heartbeat_age > HEARTBEAT_TIMEOUT / 2:
        warnings.append(f"Heartbeat aging ({heartbeat_age:.0f}s old)")
    
    # Check login status
    if data["login_status"] != "logged_in":
        issues.append(f"Client not logged in: {data['login_status']}")
    
    # Check active chains
    if data["chain_count"] == 0:
        warnings.append("No active chains")
    
    # Check feed stall
    if data["last_snapshot"] > 0:
        snapshot_age = now - data["last_snapshot"]
        if snapshot_age > FEED_STALL_THRESHOLD:
            issues.append(f"Feed stalled ({snapshot_age:.0f}s since last snapshot)")
    
    # Check stall count
    if data["stall_count"] >= MAX_STALL_COUNT:
        issues.append(f"Excessive feed stalls ({data['stall_count']})")
    elif data["stall_count"] > 0:
        warnings.append(f"Recent feed stalls ({data['stall_count']})")
    
    # Determine status
    if issues:
        status_code = 2
        status = "CRITICAL"
        details = " | ".join(issues)
    elif warnings:
        status_code = 1
        status = "WARNING"
        details = " | ".join(warnings)
    else:
        status_code = 0
        status = "HEALTHY"
        details = f"{data['chain_count']} chains active"
    
    # Build message
    message = f"{status}: {details}"
    
    if verbose:
        message += f"\nHeartbeat age: {heartbeat_age:.1f}s"
        message += f"\nChains: {data['chain_count']}"
        message += f"\nLogin: {data['login_status']}"
        message += f"\nLast snapshot: {now - data['last_snapshot']:.1f}s ago"
        message += f"\nStall count: {data['stall_count']}"
    
    return status_code, message


def format_alert(exit_code: int, message: str) -> str:
    """
    Format message for alerting systems.
    
    Returns:
        Formatted alert message
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    emoji = {
        0: "✅",
        1: "⚠️ ",
        2: "🚨",
    }.get(exit_code, "❓")
    
    return f"{emoji} [{timestamp}] {message}"


# =====================================================================
# MAIN
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Monitor OptionChainSupervisor health"
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Format output for alerting systems"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed metrics"
    )
    
    args = parser.parse_args()
    
    # Check health
    exit_code, message = check_supervisor_health(verbose=args.verbose)
    
    # Format output
    if args.alert:
        output = format_alert(exit_code, message)
    else:
        output = message
    
    # Print and exit
    print(output)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()


# =====================================================================
# INTEGRATION EXAMPLES
# =====================================================================

"""
===============================================================================
CRON INTEGRATION
===============================================================================

# Check every minute, log to file
* * * * * /usr/bin/python3 /path/to/supervisor_monitor.py >> /var/log/supervisor_health.log 2>&1

# Alert via email on failure
* * * * * /usr/bin/python3 /path/to/supervisor_monitor.py --alert || mail -s "Supervisor Alert" admin@example.com

# Alert via Slack webhook
* * * * * /usr/bin/python3 /path/to/supervisor_monitor.py --alert | grep -E "WARNING|CRITICAL" && curl -X POST -H 'Content-type: application/json' --data '{"text":"'$(cat)'"}'  https://hooks.slack.com/services/YOUR/WEBHOOK/URL

===============================================================================
SYSTEMD SERVICE
===============================================================================

# /etc/systemd/system/supervisor-monitor.service
[Unit]
Description=Supervisor Health Monitor
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/supervisor_monitor.py --alert
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/supervisor-monitor.timer
[Unit]
Description=Run Supervisor Health Monitor every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target

# Enable
sudo systemctl enable supervisor-monitor.timer
sudo systemctl start supervisor-monitor.timer

===============================================================================
PROMETHEUS INTEGRATION
===============================================================================

# supervisor_exporter.py
from prometheus_client import start_http_server, Gauge
import time
import sys
sys.path.append('/path/to/script')
from supervisor_monitor import read_heartbeat, check_supervisor_health

# Metrics
supervisor_healthy = Gauge('supervisor_healthy', 'Supervisor health status (0=critical, 1=warning, 2=healthy)')
supervisor_chains = Gauge('supervisor_chains', 'Number of active chains')
supervisor_heartbeat_age = Gauge('supervisor_heartbeat_age_seconds', 'Age of heartbeat in seconds')
supervisor_feed_stalled = Gauge('supervisor_feed_stalled', 'Feed stalled (0=no, 1=yes)')
supervisor_stall_count = Gauge('supervisor_stall_count', 'Feed stall count')

def collect_metrics():
    success, data, error = read_heartbeat()
    
    if not success:
        supervisor_healthy.set(0)
        return
    
    exit_code, _ = check_supervisor_health()
    supervisor_healthy.set(2 - exit_code)  # Invert: 2=healthy, 1=warning, 0=critical
    
    supervisor_chains.set(data['chain_count'])
    supervisor_heartbeat_age.set(time.time() - data['timestamp'])
    
    if data['last_snapshot'] > 0:
        age = time.time() - data['last_snapshot']
        supervisor_feed_stalled.set(1 if age > 30 else 0)
    
    supervisor_stall_count.set(data['stall_count'])

if __name__ == '__main__':
    start_http_server(9100)
    
    while True:
        collect_metrics()
        time.sleep(15)

===============================================================================
NAGIOS/ICINGA CHECK
===============================================================================

# /usr/lib/nagios/plugins/check_supervisor
#!/usr/bin/env python3
import sys
sys.path.append('/path/to/script')
from supervisor_monitor import check_supervisor_health

exit_code, message = check_supervisor_health()

# Nagios exit codes: 0=OK, 1=WARNING, 2=CRITICAL
print(message)
sys.exit(exit_code)

# Nagios config
# define service {
#     use                     generic-service
#     host_name               trading-server
#     service_description     Supervisor Health
#     check_command           check_supervisor
#     check_interval          1
#     retry_interval          1
# }

===============================================================================
"""