from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.core.config import Config


def main() -> int:
    client = ShoonyaClient(Config())
    assert client.login(), "Login failed"
    print("Logged in successfully")

    order_params = {
        "exchange": "NFO",
        "tradingsymbol": "NIFTY27JAN26C25700",
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

    result = client.place_order(order_params)
    print("\nRESULT:")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
