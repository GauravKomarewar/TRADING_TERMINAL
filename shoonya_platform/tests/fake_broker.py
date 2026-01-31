class FakeBroker:
    def __init__(self):
        self.positions = []
        self.orders = []
        self.ltp = {}

    def get_positions(self):
        return self.positions

    def get_order_book(self):
        return self.orders

    def get_ltp(self, exch, symbol):
        return self.ltp.get(symbol)

    def place_order(self, params):
        self.orders.append({
            "norenordno": f"OID{len(self.orders)}",
            "status": "COMPLETE"
        })
        # Return a simple result object expected by callers
        class Result:
            def __init__(self, order_id):
                self.success = True
                self.order_id = order_id
                self.error_message = None

        return Result(self.orders[-1]["norenordno"]) 
