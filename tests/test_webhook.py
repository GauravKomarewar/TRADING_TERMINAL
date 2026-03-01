import os
import time
import calendar
from datetime import datetime, timedelta

import requests
from requests.exceptions import ConnectionError, ReadTimeout

URL = "http://13.201.178.26/webhook"


def get_next_expiry() -> str:
    """Compute the next monthly expiry string in DDMMMYY format (e.g., '27MAR26').
    Monthly expiry = last Thursday of the current or next month.
    """
    today = datetime.now()
    year, month = today.year, today.month
    # If past the 20th, target next month
    if today.day > 20:
        month += 1
        if month > 12:
            month, year = 1, year + 1
    last_day = calendar.monthrange(year, month)[1]
    last_date = datetime(year, month, last_day)
    while last_date.weekday() != 3:  # Thursday
        last_date -= timedelta(days=1)
    return last_date.strftime("%d%b%y").upper()


def send(payload, label):
    print(f"\nSending {label}")
    try:
        r = requests.post(URL, json=payload, timeout=3)
        print("HTTP Status:", r.status_code)
        print("Response:", r.text)
    except ReadTimeout:
        print("TIMEOUT - webhook processing asynchronously (EXPECTED)")
    except ConnectionError as e:
        print("CONNECTION ERROR:", e)
    except Exception as e:
        print("UNEXPECTED ERROR:", e)


def main() -> int:
    # SECURITY: Load webhook secret from environment
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    if not webhook_secret:
        print("ERROR: WEBHOOK_SECRET not set in environment")
        print("Set in .env: WEBHOOK_SECRET=<your-secret>")
        return 1

    expiry = get_next_expiry()

    base = {
        "secret_key": webhook_secret,
        "strategy_name": "nifty_live_test",
        "exchange": "NFO",
        "underlying": "NIFTY",
        "expiry": expiry,
    }

    leg = {
        "tradingsymbol": f"NIFTY{expiry}C25700",
        "direction": "SELL",
        "qty": 65,
        "product_type": "M",
    }

    payload_test_entry = {
        **base,
        "strategy_name": "NIFTY_test_mode",
        "execution_type": "entry",
        "test_mode": "SUCCESS",
        "legs": [leg],
    }
    payload_test_exit = {
        **base,
        "strategy_name": "NIFTY_test_mode",
        "execution_type": "exit",
        "test_mode": "SUCCESS",
        "legs": [leg],
    }
    payload_entry_real = {**base, "execution_type": "entry", "legs": [leg]}
    payload_duplicate_entry = {**base, "execution_type": "entry", "legs": [leg]}
    payload_exit_real = {**base, "execution_type": "exit", "legs": [leg]}
    payload_duplicate_exit = {**base, "execution_type": "exit", "legs": [leg]}

    print("Waiting for service warm-up...")
    time.sleep(5)

    send(payload_test_entry, "TEST MODE ENTRY")
    time.sleep(5)
    send(payload_test_exit, "TEST MODE EXIT")
    send(payload_entry_real, "REAL ENTRY")
    time.sleep(8)
    send(payload_duplicate_entry, "DUPLICATE ENTRY (EXPECT BLOCK)")
    time.sleep(8)
    print("\nHOLDING POSITION FOR 20 SECONDS - WATCH LOGS & WATCHER\n")
    time.sleep(20)
    send(payload_exit_real, "REAL EXIT")
    time.sleep(8)
    send(payload_duplicate_exit, "DUPLICATE EXIT (SAFE IGNORE)")
    time.sleep(8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
