import requests
import time
from requests.exceptions import ReadTimeout, ConnectionError

URL = "http://13.201.178.26/webhook"

def send(payload, label):
    print(f"\n🚀 Sending {label}")
    try:
        r = requests.post(URL, json=payload, timeout=3)
        print("✅ HTTP Status:", r.status_code)
        print("📨 Response:", r.text)
    except ReadTimeout:
        print("⏳ TIMEOUT — webhook processing asynchronously (EXPECTED)")
    except ConnectionError as e:
        print("❌ CONNECTION ERROR:", e)
    except Exception as e:
        print("❌ UNEXPECTED ERROR:", e)


# =================================================
# COMMON BASE
# =================================================
BASE = {
    "secret_key": "GK_TRADINGVIEW_BOT_2408",
    "strategy_name": "nifty_live_test",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "expiry": "27JAN26",
}

LEG = {
    "tradingsymbol": "NIFTY27JAN26C25700",
    "direction": "SELL",
    "qty": 65,
    "product_type": "M",
    # "order_type": "LMT", ##comment for market order
    # "price": "39"    ##comment for market order
}

# =================================================
# 1️⃣ REAL ENTRY
# =================================================
payload_entry_real = {
    **BASE,
    "execution_type": "entry",
    "legs": [LEG],
}

# =================================================
# 2️⃣ DUPLICATE ENTRY (SHOULD BLOCK)
# =================================================
payload_duplicate_entry = {
    **BASE,
    "execution_type": "entry",
    "legs": [LEG],
}

# =================================================
# 3️⃣ REAL EXIT
# =================================================
payload_exit_real = {
    **BASE,
    "execution_type": "exit",
    "legs": [LEG],  # ORIGINAL direction, bot will invert
}

# =================================================
# 4️⃣ DUPLICATE EXIT (SHOULD IGNORE / SAFE FAIL)
# =================================================
payload_duplicate_exit = {
    **BASE,
    "execution_type": "exit",
    "legs": [LEG],
}

# =================================================
# 5️⃣ TEST MODE ENTRY
# =================================================
payload_test_entry = {
    **BASE,
    "strategy_name": "NIFTY_test_mode",
    "execution_type": "entry",
    "test_mode": "SUCCESS",
    "legs": [LEG],
}

# =================================================
# 6️⃣ TEST MODE EXIT
# =================================================
payload_test_exit = {
    **BASE,
    "strategy_name": "NIFTY_test_mode",
    "execution_type": "exit",
    "test_mode": "SUCCESS",
    "legs": [LEG],
}

# =================================================
# 🚀 EXECUTION FLOW
# =================================================
print("⏳ Waiting for service warm-up...")
time.sleep(5)

# TEST MODE ENTRY
send(payload_test_entry, "TEST MODE ENTRY")
time.sleep(5)

# TEST MODE EXIT
send(payload_test_exit, "TEST MODE EXIT")

# REAL ENTRY
send(payload_entry_real, "REAL ENTRY")
time.sleep(8)

# DUPLICATE ENTRY
send(payload_duplicate_entry, "DUPLICATE ENTRY (EXPECT BLOCK)")
time.sleep(8)

# HOLD POSITION
print("\n⏱ HOLDING POSITION FOR 20 SECONDS — WATCH LOGS & WATCHER\n")
time.sleep(20)

# REAL EXIT
send(payload_exit_real, "REAL EXIT")
time.sleep(8)

# DUPLICATE EXIT
send(payload_duplicate_exit, "DUPLICATE EXIT (SAFE IGNORE)")
time.sleep(8)
