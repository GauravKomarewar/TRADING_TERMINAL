"""
Simple stress test for live_feed per-token locking and janitor.
Run as: python -m tests.live_feed_stress_test
"""
import sys
import time
import threading
import random

# Ensure package path
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shoonya_platform.market_data.feeds import live_feed

NUM_THREADS = 8
TICKS_PER_THREAD = 2000
TOKENS = [str(10000 + i) for i in range(200)]

latencies = []


def worker(tid):
    start = time.time()
    for i in range(TICKS_PER_THREAD):
        tk = random.choice(TOKENS)
        tick = {
            "tk": f"NFO|{tk}",
            "lp": round(1000 + random.random() * 50, 2),
            "v": random.randint(1, 1000),
            "oi": random.randint(0, 10000),
            "ft": int(time.time() * 1000),
        }
        s = time.time()
        live_feed.event_handler_feed_update(tick)
        latencies.append(time.time() - s)
    dur = time.time() - start
    print(f"Thread {tid} done in {dur:.2f}s")


threads = []
for t in range(NUM_THREADS):
    th = threading.Thread(target=worker, args=(t,))
    th.start()
    threads.append(th)

for th in threads:
    th.join()

print("All threads completed")
print("Total tokens stored:", len(live_feed.get_all_tick_data()))
print("Feed stats:", live_feed.get_feed_stats())
print(f"Avg process latency per tick: {sum(latencies)/len(latencies):.6f}s")
