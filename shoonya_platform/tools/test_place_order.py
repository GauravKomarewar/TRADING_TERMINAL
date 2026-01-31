from shoonya_platform.core.config import Config
from shoonya_platform.brokers.shoonya.client import ShoonyaClient


# --------------------------------------------------
# 1️⃣ Login
# --------------------------------------------------
client = ShoonyaClient(Config())
assert client.login(), "Login failed"
print("✅ Logged in successfully")

# --------------------------------------------------
# 2️⃣ EXACT params expected by *your* NorenApi
# --------------------------------------------------
order_params = {
    "exchange": "NFO",
    "tradingsymbol": "NIFTY27JAN26C25700",
    "quantity": 65,
    "buy_or_sell": "S",       # BUY / SELL → B / S handled internally
    "product_type": "M",      # MCX intraday
    "price_type": "LMT",      # LMT / MKT
    "price": 30,
    "discloseqty": 0,
    "retention": "DAY",
    "remarks": "direct_test",
}

# # --------------------------------------------------
# # 2️⃣ EXACT params expected by *your* NorenApi
# # --------------------------------------------------
# order_params = {
#     "exchange": "MCX",
#     "tradingsymbol": "CRUDEOILM17FEB26C5850",
#     "quantity": 10,
#     "buy_or_sell": "S",       # BUY / SELL → B / S handled internally
#     "product_type": "M",      # MCX intraday
#     "price_type": "LMT",      # LMT / MKT
#     "price": 150.05,
#     "discloseqty": 0,
#     "retention": "DAY",
#     "remarks": "direct_mcx_test",
# }

print("📤 Placing order:")
for k, v in order_params.items():
    print(f"  {k}: {v}")


# --------------------------------------------------
# 3️⃣ CALL (through your wrapper)
# --------------------------------------------------
result = client.place_order(order_params)

print("\n📥 RESULT:")
print(result)
