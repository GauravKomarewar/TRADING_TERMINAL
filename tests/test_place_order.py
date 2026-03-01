from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.core.config import Config
from datetime import datetime, timedelta


def _next_monthly_expiry_symbol(underlying: str, strike: int, opt_type: str) -> str:
    """Build a tradingsymbol with the next monthly expiry (last Thursday of month).
    Format: NIFTY26MAR26C25700  (DDMmmYY)
    """
    today = datetime.now()
    # Start from next month if today is past the 20th
    year, month = today.year, today.month
    if today.day > 20:
        month += 1
        if month > 12:
            month, year = 1, year + 1
    # Find last Thursday of month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    last_date = datetime(year, month, last_day)
    # Walk backwards to Thursday (weekday 3)
    while last_date.weekday() != 3:
        last_date -= timedelta(days=1)
    expiry_str = last_date.strftime("%d%b%y").upper()
    return f"{underlying}{expiry_str}{opt_type}{strike}"


def main() -> int:
    client = ShoonyaClient(Config())
    if not client.login():
        raise RuntimeError("Login failed")
    print("Logged in successfully")

    symbol = _next_monthly_expiry_symbol("NIFTY", 25700, "C")

    order_params = {
        "exchange": "NFO",
        "tradingsymbol": symbol,
        "quantity": 65,
        "buy_or_sell": "S",
        "product_type": "M",
        "price_type": "LMT",
        "price": 30,
        "discloseqty": 0,
        "retention": "DAY",
        "remarks": "direct_test",
    }

    print("Placing order:")
    for k, v in order_params.items():
        print(f"  {k}: {v}")

    result = None
    order_id = None
    try:
        result = client.place_order(order_params)
        print("\nRESULT:")
        print(result)

        # Validate result
        if result is None:
            raise RuntimeError("place_order returned None")
        if isinstance(result, dict):
            if result.get("error") or result.get("stat") == "Not_Ok":
                raise RuntimeError(f"Order failed: {result.get('error') or result.get('emsg', result)}")
            order_id = result.get("norenordno") or result.get("order_id") or result.get("orderId")
        else:
            raise RuntimeError(f"Unexpected result type: {type(result)}")
    finally:
        # Cleanup: cancel the order if it was created
        if order_id:
            print(f"\nCleaning up: cancelling order {order_id}")
            try:
                cancel_result = client.cancel_order(order_id)
                print(f"Cancel result: {cancel_result}")
            except Exception as e:
                print(f"Warning: cancel failed: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
