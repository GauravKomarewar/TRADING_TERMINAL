#!/usr/bin/env python3
"""
Session Diagnostics Tool
=========================

Run this to diagnose the current session state and identify issues.

Usage:
    python session_diagnostics.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient


def print_section(title):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def check_session_state(client):
    """Check current session state"""
    print_section("SESSION STATE")
    
    print(f"Logged In: {client._logged_in}")
    print(f"Session Token: {client.session_token[:20] if client.session_token else None}...")
    print(f"Last Login: {client.last_login_time}")
    print(f"Login Attempts: {client.login_attempts}")
    
    if hasattr(client, '_last_session_validation'):
        print(f"Last Validation: {client._last_session_validation}")
        if client._last_session_validation:
            age = (datetime.now() - client._last_session_validation).total_seconds()
            print(f"Validation Age: {age:.0f}s")
    
    if client.last_login_time:
        age = (datetime.now() - client.last_login_time).total_seconds()
        print(f"Session Age: {age:.0f}s ({age/3600:.1f}h)")
        
        if age > 21600:  # 6 hours
            print("⚠️  WARNING: Session age > 6 hours - likely expired")


def test_session_validation(client):
    """Test session validation"""
    print_section("SESSION VALIDATION TEST")
    
    try:
        print("Calling ensure_session()...")
        result = client.ensure_session()
        print(f"Result: {result}")
        
        if result:
            print("✅ Session is valid")
        else:
            print("❌ Session validation failed")
    except Exception as e:
        print(f"❌ Exception during validation: {e}")


def test_get_limits(client):
    """Test get_limits API call"""
    print_section("GET LIMITS TEST")
    
    try:
        print("Calling get_limits()...")
        limits = client.get_limits()
        
        if limits:
            print(f"Response type: {type(limits)}")
            
            if isinstance(limits, dict):
                print(f"Status: {limits.get('stat')}")
                print(f"Error: {limits.get('emsg')}")
                
                if limits.get('stat') == 'Not_Ok':
                    print("❌ API returned error")
                    return False
                
                print(f"Cash: {limits.get('cash')}")
                print(f"Margin Used: {limits.get('marginused')}")
                print("✅ get_limits() working")
                return True
            else:
                print(f"⚠️  Unexpected response type: {type(limits)}")
                return False
        else:
            print("❌ get_limits() returned None")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


def test_get_positions(client):
    """Test get_positions API call"""
    print_section("GET POSITIONS TEST")
    
    try:
        print("Calling get_positions()...")
        positions = client.get_positions()
        
        print(f"Response type: {type(positions)}")
        print(f"Position count: {len(positions) if positions else 0}")
        
        if positions:
            print("\nPositions:")
            for p in positions:
                if isinstance(p, dict):
                    symbol = p.get('tsym', 'UNKNOWN')
                    qty = p.get('netqty', '0')
                    pnl = float(p.get('rpnl', 0)) + float(p.get('urmtom', 0))
                    print(f"  {symbol}: qty={qty}, pnl={pnl:.2f}")
            print("✅ get_positions() working")
            return True
        else:
            print("⚠️  No positions (this might be correct if account is flat)")
            print("   BUT if you know you have positions, this is the BUG!")
            return len(positions) == 0  # Empty list is OK if truly flat
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_login(client):
    """Test fresh login"""
    print_section("FRESH LOGIN TEST")
    
    try:
        # Force logout first
        print("Forcing logout...")
        client.logout()
        
        print("Attempting fresh login...")
        result = client.login()
        
        if result:
            print("✅ Fresh login successful")
            return True
        else:
            print("❌ Fresh login failed")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 70)
    print(" SHOONYA SESSION DIAGNOSTICS")
    print("=" * 70)
    print(f" Time: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Initialize client
    print("\nInitializing ShoonyaClient...")
    config = Config()
    client = ShoonyaClient(config, enable_auto_recovery=True)
    
    # Run diagnostic tests
    results = {}
    
    # 1. Check current state
    check_session_state(client)
    
    # 2. Test session validation
    test_session_validation(client)
    
    # 3. Test get_limits
    results['get_limits'] = test_get_limits(client)
    
    # 4. Test get_positions
    results['get_positions'] = test_get_positions(client)
    
    # 5. Test fresh login
    results['fresh_login'] = test_login(client)
    
    # 6. Re-test positions after fresh login
    if results['fresh_login']:
        print_section("RETEST AFTER FRESH LOGIN")
        print("\nRetesting get_limits()...")
        results['get_limits_after'] = test_get_limits(client)
        
        print("\nRetesting get_positions()...")
        results['get_positions_after'] = test_get_positions(client)
    
    # Summary
    print_section("DIAGNOSTIC SUMMARY")
    
    print("\nTest Results:")
    for test, passed in results.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {test}")
    
    # Diagnosis
    print("\n" + "=" * 70)
    print(" DIAGNOSIS")
    print("=" * 70)
    
    if not results.get('get_limits'):
        print("\n❌ CRITICAL: get_limits() is failing")
        print("   This indicates a session problem.")
        print("   Likely causes:")
        print("   - Session expired (age > 6 hours)")
        print("   - Invalid credentials")
        print("   - Network issues")
        print("   - Broker API down")
    
    if not results.get('get_positions'):
        print("\n❌ CRITICAL: get_positions() is failing or returning []")
        print("   This is the root cause of your blind trading issue.")
        print("   When get_positions() returns [], your system thinks there are")
        print("   no positions and cannot take protective actions.")
    
    if results.get('fresh_login') and results.get('get_positions_after'):
        print("\n✅ GOOD: Fresh login fixes the issue")
        print("   This confirms the problem is session expiration.")
        print("   Solution: Apply the session fix patches.")
    elif results.get('fresh_login') and not results.get('get_positions_after'):
        print("\n❌ BAD: Even fresh login doesn't work")
        print("   This suggests a deeper problem:")
        print("   - Account might actually have no positions")
        print("   - Broker API issue")
        print("   - Network/firewall blocking")
    
    print("\n" + "=" * 70)
    print(" RECOMMENDED ACTIONS")
    print("=" * 70)
    
    if not results.get('get_limits'):
        print("\n1. Check your credentials in .env file")
        print("2. Verify TOTP key is correct")
        print("3. Check network connectivity to Shoonya API")
        print("4. Check if broker API is operational")
    
    if results.get('get_limits') and not results.get('get_positions'):
        print("\n1. Apply the immediate_hotfix.py patch")
        print("2. This will add aggressive session validation")
        print("3. Restart your service")
        print("4. Monitor logs for session validation messages")
    
    if results.get('fresh_login'):
        print("\n5. The session fix will prevent future occurrences")
        print("6. Session will auto-recover before expiration")
        print("7. Emergency re-login will trigger if needed")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()