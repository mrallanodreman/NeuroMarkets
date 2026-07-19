#!/usr/bin/env python3
"""tick_publisher.py
Minimal, efficient publisher that polls CapitalOP.get_last_price and
writes momentum_tick.json atomically when price changes.

Designed to be low CPU: simple loop with `time.sleep(interval)` and
no extra threads. Use `--once` to run a single check for testing.
"""
import time
import os
import json
import signal
import argparse
from EthSession import CapitalOP

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICK_IPC_PATH = os.path.join(SCRIPT_DIR, "momentum_tick.json")


def main(interval=1.0, once=False):
    cap = CapitalOP()
    # Try to reuse existing auth if present
    try:
        cap.ensure_authenticated()
    except Exception:
        # proceed anyway; get_last_price may reauthenticate internally
        pass

    last_price = None
    stop = False

    def _handle(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    error_backoff = 1
    while not stop:
        try:
            price = cap.get_last_price("ETHUSD")
            if price is not None:
                price_f = float(price)
                # Only write when price changes to minimize I/O
                if last_price is None or price_f != last_price:
                    tmp = TICK_IPC_PATH + ".tmp"
                    try:
                        with open(tmp, 'w') as f:
                            json.dump({"price": price_f, "ts": time.time()}, f)
                        os.replace(tmp, TICK_IPC_PATH)
                        print(f"[PUBLISH] price={price_f}")
                    except Exception as e:
                        print(f"[ERROR] Failed writing IPC: {e}")
                    last_price = price_f
                # reset backoff on success
                error_backoff = 1
            else:
                print("[WARN] get_last_price returned None")

            if once:
                break

            time.sleep(max(0.1, float(interval)))

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(min(10, error_backoff))
            error_backoff = min(10, error_backoff * 2)

    print("tick_publisher exiting")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Minimal tick publisher for momentum IPC')
    parser.add_argument('--interval', '-i', type=float, default=1.0, help='Polling interval seconds (default 1.0)')
    parser.add_argument('--once', action='store_true', help='Run a single poll and exit')
    args = parser.parse_args()
    main(interval=args.interval, once=args.once)
