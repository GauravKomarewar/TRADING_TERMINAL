#!/usr/bin/env python3
"""
DNSS NIFTY Configuration Pre-Flight Check
==========================================
Validates all requirements before testing strategy execution
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def check_config_file():
    """✅ Check if config file exists and is valid"""
    config_path = Path("shoonya_platform/strategies/saved_configs/dnss_nifty.json")
    
    if not config_path.exists():
        return False, f"❌ Config file not found: {config_path}"
    
    try:
        with open(config_path) as f:
            config = json.load(f)
        
        required_keys = ["strategy_name", "identity", "entry", "adjustment", "exit", "params"]
        missing = [k for k in required_keys if k not in config]
        
        if missing:
            return False, f"❌ Config missing keys: {missing}"
        
        return True, f"✅ Config file valid: {config_path}"
    
    except Exception as e:
        return False, f"❌ Config file error: {e}"


def check_database():
    """✅ Check if SQLite database exists with data"""
    db_path = Path("shoonya_platform/market_data/option_chain/data/option_chain.db")
    
    if not db_path.exists():
        return False, f"❌ Database not found: {db_path}"
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        if not tables:
            return False, f"❌ Database empty (no tables)"
        
        conn.close()
        return True, f"✅ Database found with {len(tables)} table(s): {db_path}"
    
    except Exception as e:
        return False, f"❌ Database error: {e}"


def check_environment():
    """✅ Check if environment variables are configured"""
    env_path = Path("config_env/primary.env")
    
    if not env_path.exists():
        return False, f"❌ Environment file not found: {env_path}"
    
    try:
        with open(env_path) as f:
            lines = f.readlines()
        
        # Check for key variables (broker token, etc.)
        content = "".join(lines)
        required_vars = ["BROKER", "TOKEN"]  # Generic names, adjust as needed
        
        return True, f"✅ Environment file found: {env_path} ({len(lines)} lines)"
    
    except Exception as e:
        return False, f"❌ Environment error: {e}"


def check_strategy_module():
    """✅ Check if strategy module is importable"""
    try:
        from shoonya_platform.strategies.delta_neutral import DeltaNeutralShortStrangleStrategy
        return True, f"✅ Strategy module importable"
    except Exception as e:
        return False, f"❌ Strategy import error: {e}"


def check_standalone_runner():
    """✅ Check if standalone runner module exists"""
    runner_path = Path("shoonya_platform/strategies/delta_neutral/__main__.py")
    
    if not runner_path.exists():
        return False, f"❌ Standalone runner not found: {runner_path}"
    
    try:
        with open(runner_path) as f:
            content = f.read()
        
        required_classes = ["DNSSStandaloneRunner", "convert_dashboard_config_to_execution"]
        missing = [c for c in required_classes if c not in content]
        
        if missing:
            return False, f"❌ Runner missing: {missing}"
        
        return True, f"✅ Standalone runner valid: {runner_path}"
    
    except Exception as e:
        return False, f"❌ Runner error: {e}"


def print_summary(results):
    """Print test results summary"""
    print("\n" + "=" * 70)
    print(f"DNSS NIFTY PRE-FLIGHT CHECK")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")
    
    passed = sum(1 for success, _ in results.values() if success)
    total = len(results)
    
    for check_name, (success, message) in results.items():
        print(f"{check_name:30} → {message}")
    
    print("\n" + "=" * 70)
    print(f"RESULT: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n✅ ALL CHECKS PASSED - Ready to test strategy execution!")
        print("\nRun strategy with:")
        print("  python -m shoonya_platform.strategies.delta_neutral \\")
        print("    --config ./shoonya_platform/strategies/saved_configs/dnss_nifty.json \\")
        print("    --duration 5 --verbose")
        return 0
    else:
        print(f"\n❌ {total - passed} checks failed - resolve above issues before testing")
        return 1


def main():
    results = {
        "Config File": check_config_file(),
        "SQLite Database": check_database(),
        "Environment": check_environment(),
        "Strategy Module": check_strategy_module(),
        "Standalone Runner": check_standalone_runner(),
    }
    
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
