#!/usr/bin/env python3
"""
Comprehensive API Endpoint Testing Script
Tests all dashboard endpoints and identifies errors
"""

import requests
import json
import sys
from typing import Dict, List
from urllib.parse import urljoin

BASE_URL = "http://localhost:8000"
PASSWORD = "1234"

# Track results
results = {
    "passed": [],
    "failed": [],
    "errors": []
}

session = requests.Session()

def test_endpoint(method: str, path: str, description: str, **kwargs) -> Dict:
    """Test a single endpoint"""
    url = urljoin(BASE_URL, path)
    print("\n" + "="*70)
    print("[TEST] " + description)
    print("   Method: " + method.upper())
    print("   URL: " + url)
    
    try:
        if method.lower() == "get":
            resp = session.get(url, timeout=5, **kwargs)
        elif method.lower() == "post":
            resp = session.post(url, timeout=5, **kwargs)
        else:
            resp = session.request(method, url, timeout=5, **kwargs)
        
        print("   Status: " + str(resp.status_code))
        
        if resp.status_code < 400:
            results["passed"].append(method.upper() + " " + path)
            print("   [OK] SUCCESS")
            try:
                data = resp.json()
                print("   Response (first 200 chars): " + str(data)[:200])
                return {"status": "success", "code": resp.status_code, "data": data}
            except:
                print("   Response: " + resp.text[:200])
                return {"status": "success", "code": resp.status_code, "data": None}
        else:
            results["failed"].append(method.upper() + " " + path + " - " + str(resp.status_code))
            print("   [FAIL] FAILED with " + str(resp.status_code))
            print("   Response: " + resp.text[:300])
            return {"status": "failed", "code": resp.status_code, "error": resp.text}
    
    except Exception as e:
        results["errors"].append(method.upper() + " " + path + " - " + str(e))
        print("   [ERR] ERROR: " + str(e))
        return {"status": "error", "error": str(e)}

# ========================================================================
# TEST UNPROTECTED ENDPOINTS
# ========================================================================
print("\n" + "="*70)
print("[PHASE 1] UNPROTECTED ENDPOINTS")
print("="*70)

test_endpoint("GET", "/", "Homepage")
test_endpoint("GET", "/health", "Health Check")

# ========================================================================
# LOGIN
# ========================================================================
print("\n" + "="*70)
print("[PHASE 2] AUTHENTICATION")
print("="*70)

login_result = test_endpoint(
    "POST", "/auth/login",
    "Dashboard Login",
    data={"username": "admin", "password": PASSWORD}
)

if login_result["status"] != "success":
    print("\n[FAIL] LOGIN FAILED - Cannot test protected endpoints")
    sys.exit(1)

print("\n[OK] LOGIN SUCCESSFUL - Session established")
print("   Cookies: " + str(session.cookies.get_dict()))

# ========================================================================
# PROTECTED ENDPOINTS - MAIN PAGES
# ========================================================================
print("\n" + "="*70)
print("[PHASE 3] MAIN PAGES (PROTECTED)")
print("="*70)

test_endpoint("GET", "/dashboard/home", "Dashboard Home Page")
test_endpoint("GET", "/dashboard/status", "Dashboard Status")

# ========================================================================
# PROTECTED ENDPOINTS - HOME/STATUS
# ========================================================================
print("\n" + "="*70)
print("[PHASE 4] HOME/STATUS API")
print("="*70)

test_endpoint("GET", "/dashboard/home/status", "Home Status")

# ========================================================================
# PROTECTED ENDPOINTS - STRATEGIES
# ========================================================================
print("\n" + "="*70)
print("[PHASE 5] STRATEGIES API")
print("="*70)

test_endpoint("GET", "/dashboard/strategies/list", "List All Strategies")
test_endpoint("GET", "/dashboard/strategy/configs", "Strategy Configs")
test_endpoint("GET", "/dashboard/monitoring/all-strategies-status", "All Strategies Status")

# ========================================================================
# PROTECTED ENDPOINTS - ORDERBOOK
# ========================================================================
print("\n" + "="*70)
print("[PHASE 6] ORDERBOOK API")
print("="*70)

test_endpoint("GET", "/dashboard/orderbook", "Get Orderbook")
test_endpoint("GET", "/dashboard/orderbook/system", "System Orderbook")
test_endpoint("GET", "/dashboard/orderbook/broker", "Broker Orderbook")

# ========================================================================
# PROTECTED ENDPOINTS - OPTION CHAINS
# ========================================================================
print("\n" + "="*70)
print("[PHASE 7] OPTION CHAINS API")
print("="*70)

test_endpoint("GET", "/dashboard/option-chain/active-symbols", "Active Option Symbols")
test_endpoint("GET", "/dashboard/option-chain/active-expiries?exchange=NFO&symbol=NIFTY", "Active Option Expiries")
test_endpoint("GET", "/dashboard/option-chain?exchange=NFO&symbol=NIFTY&expiry=17-FEB-2026", "Option Chain for NIFTY")
test_endpoint("GET", "/dashboard/option-chain?exchange=NFO&symbol=BANKNIFTY&expiry=24-FEB-2026", "Option Chain for BANKNIFTY")
test_endpoint("GET", "/dashboard/option-chain/nearest?exchange=NFO&symbol=NIFTY&expiry=17-FEB-2026&target=26000&metric=ltp", "Nearest Option for NIFTY")

# ========================================================================
# PROTECTED ENDPOINTS - RUNNER CONTROL
# ========================================================================
print("\n" + "="*70)
print("[PHASE 8] RUNNER CONTROL API")
print("="*70)

test_endpoint("GET", "/dashboard/runner/status", "Runner Status")
test_endpoint("POST", "/dashboard/runner/start", "Start Runner")
test_endpoint("GET", "/dashboard/runner/status", "Runner Status After Start")
test_endpoint("POST", "/dashboard/runner/stop", "Stop Runner")
test_endpoint("GET", "/dashboard/runner/status", "Runner Status After Stop")

# ========================================================================
# PROTECTED ENDPOINTS - ORPHAN POSITIONS
# ========================================================================
print("\n" + "="*70)
print("[PHASE 9] ORPHAN POSITIONS API")
print("="*70)

test_endpoint("GET", "/dashboard/orphan-positions", "List Orphan Positions")
test_endpoint("GET", "/dashboard/orphan-positions/summary", "Orphan Positions Summary")

# ========================================================================
# PROTECTED ENDPOINTS - SYMBOLS
# ========================================================================
print("\n" + "="*70)
print("[PHASE 10] SYMBOLS API")
print("="*70)

test_endpoint("GET", "/dashboard/symbols/search?q=NIFTY", "Search Symbols")
test_endpoint("GET", "/dashboard/symbols/expiries?exchange=NFO&symbol=NIFTY", "Get Expiries")
test_endpoint("GET", "/dashboard/symbols/contracts?exchange=NFO&symbol=NIFTY&expiry=17-FEB-2026", "Get Contracts")

# ========================================================================
# SUMMARY REPORT
# ========================================================================
print("\n" + "="*70)
print("[SUMMARY] TEST RESULTS")
print("="*70)

total = len(results["passed"]) + len(results["failed"]) + len(results["errors"])
print("\n[PASSED] " + str(len(results['passed'])) + "/" + str(total))
for p in results["passed"]:
    print("   OK: " + p)

if results["failed"]:
    print("\n[FAILED] " + str(len(results['failed'])) + "/" + str(total))
    for f in results["failed"]:
        print("   ERR: " + f)

if results["errors"]:
    print("\n[ERRORS] " + str(len(results['errors'])) + "/" + str(total))
    for e in results["errors"]:
        print("   EXC: " + e)

print("\n" + "="*70)
print("Overall Success Rate: {:.1f}%".format(len(results['passed'])*100/total if total > 0 else 0))
print("="*70 + "\n")
