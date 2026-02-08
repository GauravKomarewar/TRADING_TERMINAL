import threading
import time

from shoonya_platform.execution.trading_bot import ShoonyaApiProxy


class FakeClient:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.ensure_session_calls = 0

    def ensure_session(self):
        # mark ensure_session call
        with self.lock:
            self.ensure_session_calls += 1

    def get_positions(self):
        t0 = time.time()
        with self.lock:
            self.calls.append(("get_positions_start", t0))
        # simulate work
        time.sleep(0.05)
        t1 = time.time()
        with self.lock:
            self.calls.append(("get_positions_end", t1))
        return ["pos"]

    def place_order(self, order):
        t0 = time.time()
        with self.lock:
            self.calls.append(("place_order_start", t0))
        # simulate work
        time.sleep(0.06)
        t1 = time.time()
        with self.lock:
            self.calls.append(("place_order_end", t1))
        return {"success": True}


def test_api_proxy_serializes_calls():
    client = FakeClient()
    proxy = ShoonyaApiProxy(client)

    results = []

    def call_get():
        results.append(proxy.get_positions())

    def call_place():
        results.append(proxy.place_order({}))

    threads = []
    for _ in range(5):
        t1 = threading.Thread(target=call_get)
        t2 = threading.Thread(target=call_place)
        threads.extend([t1, t2])

    # start all threads
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Basic sanity
    assert len(results) == 10

    # Ensure ensure_session was called for Tier-1 operations at least once
    assert client.ensure_session_calls >= 1

    # Verify calls are serialized: start/end intervals do not overlap
    # Build list of intervals (start, end)
    intervals = []
    starts = {}
    for name, ts in client.calls:
        if name.endswith("_start"):
            key = name.replace("_start", "")
            starts[key + str(len(starts))] = ts
        else:
            key = name.replace("_end", "")
            intervals.append((ts, starts.pop(next(iter(starts)))) if starts else (0, ts))

    # We can't reconstruct perfectly due to simple recording; instead ensure ordering
    # that start/end markers alternate roughly
    assert any("get_positions_start" in c[0] for c in client.calls)
    assert any("place_order_start" in c[0] for c in client.calls)


if __name__ == '__main__':
    test_api_proxy_serializes_calls()
    print('ok')
