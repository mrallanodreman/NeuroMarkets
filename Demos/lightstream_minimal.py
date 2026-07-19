#!/usr/bin/env python3
"""lightstream_minimal.py
Minimal Lightstreamer client for Capital.com that subscribes to ETHUSD BID
and pushes ticks to MomentumHub + momentum_tick.json (atomic write).

Requires: websocket-client
Run: pip install websocket-client
"""
import time
import os
import json
import signal
import threading
import requests
from EthSession import CapitalOP
from MomentumHub import add_tick, get_metrics

try:
    import websocket
except Exception:
    websocket = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICK_IPC_PATH = os.path.join(SCRIPT_DIR, "momentum_tick.json")


class LightMinimal:
    def __init__(self, epic="ETHUSD", host=None, schema=("BID","CHANGE_PCT","EPIC"), log_fn=None, tick_fn=None):
        self.epic = epic
        self.host = host
        self.schema = schema
        self.cap = CapitalOP()
        self.ws = None
        self.stop_flag = threading.Event()
        self.log_fn = log_fn
        # tick_fn(price, timestamp) -> called on each received tick
        self.tick_fn = tick_fn

    def log(self, msg):
        try:
            if self.log_fn:
                # ensure string
                try:
                    self.log_fn(str(msg))
                    return
                except Exception:
                    pass
            print(msg)
        except Exception:
            try:
                print(msg)
            except Exception:
                pass

    def ensure_tokens(self):
        try:
            self.cap.ensure_authenticated()
        except Exception:
            # try authenticate
            try:
                self.cap.authenticate()
            except Exception:
                pass
        # Attempt to discover streaming endpoint from account summary (recommended)
        try:
            acct = self.cap.get_account_summary()
            if acct and isinstance(acct, dict):
                se = acct.get('streamingHost') or acct.get('streamEndpoint') or acct.get('streamEndpointURL')
                if se:
                    # Preserve exactly the value provided by the API (do not trim slash)
                    self.host = se
                    self.log(f"[INFO] ✅ streamingHost obtenido desde get_account_summary(): {self.host}")
                else:
                    self.log("[WARN] ❗ get_account_summary() no devolvió streamingHost.")
        except Exception:
            # Fallback: leave self.host as-is
            pass

        # If still no host, try direct session endpoint as a second source
        if not self.host:
            try:
                session_url = f"{self.cap.base_url}/api/v1/session"
                headers = {
                    "Content-Type": "application/json",
                    "X-CAP-API-KEY": self.cap.api_key,
                    "CST": self.cap.session_token,
                    "X-SECURITY-TOKEN": self.cap.x_security_token,
                }
                resp = requests.get(session_url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    js = resp.json()
                    se = js.get('streamEndpoint') or js.get('streamingHost') or js.get('streamEndpointURL')
                    if se:
                        if se.startswith('wss://') or se.startswith('ws://'):
                            self.host = se
                        else:
                            self.host = 'wss://' + se
                        self.log(f"[INFO] ✅ streamingHost obtenido desde /api/v1/session: {self.host}")
                    else:
                        self.log(f"[DEBUG] /api/v1/session respondió pero sin streamingHost: {json.dumps(js)[:400]}")
                else:
                    print(f"[WARN] /api/v1/session status: {resp.status_code}")
            except Exception as e:
                print(f"[WARN] Error consultando /api/v1/session para stream host: {e}")

    def build_bind_message(self):
        # Legacy helper kept for compatibility (unused in JSON WS mode)
        return None

    def build_subscribe(self):
        return None

    def on_message(self, ws, message):
        # JSON-based streaming: expect messages with 'destination' and 'payload'
        try:
            if not message:
                return
            try:
                js = json.loads(message)
                # Guardar mensaje crudo para debugging
                try:
                    with open(os.path.join(SCRIPT_DIR, 'stream_messages.log'), 'a') as sm:
                        sm.write(message.replace('\n','') + '\n')
                except Exception:
                    pass
            except Exception:
                return

            dest = js.get('destination')
            payload = js.get('payload') or {}
            # Accept both 'quote' destination or payloads that include 'bid'
            if dest == 'quote' or (isinstance(payload, dict) and ('bid' in payload or 'BID' in payload)):
                bid = payload.get('bid') or payload.get('BID')
                if bid is None:
                    return
                try:
                    price = float(bid)
                except Exception:
                    return
                ts = payload.get('timestamp') or time.time()
                try:
                    add_tick(price, timestamp=ts)
                except Exception:
                    pass
                try:
                    tmp = TICK_IPC_PATH + ".tmp"
                    with open(tmp, 'w') as f:
                        json.dump({"price": price, "ts": ts}, f)
                    os.replace(tmp, TICK_IPC_PATH)
                except Exception:
                    pass
                # Append to plain log for easy external verification
                try:
                    with open(os.path.join(SCRIPT_DIR, 'momentum_prices.log'), 'a') as lf:
                        lf.write(f"{int(ts)},{price}\n")
                except Exception:
                    pass
                # Llamar callback opcional para actualización en tiempo real (UI)
                try:
                    if hasattr(self, 'tick_fn') and callable(self.tick_fn):
                        try:
                            self.tick_fn(price, ts)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            return

    def on_open(self, ws):
        try:
            # For JSON WebSocket protocol send subscribe message for epic
            self.log(f"[INFO] WS connected, sending JSON subscribe for epic: {self.epic}")
            msg = {
                "destination": "marketData.subscribe",
                "correlationId": "1",
                "cst": self.cap.session_token,
                "securityToken": self.cap.x_security_token,
                "payload": {"epics": [self.epic]}
            }
            ws.send(json.dumps(msg))
        except Exception as e:
            self.log(f"[WARN] on_open send subscribe failed: {e}")

    def on_error(self, ws, err):
        self.log(f"[ERROR] WS error: {err}")

    def on_close(self, ws, code, reason):
        self.log(f"[INFO] WS closed: {code} {reason}")

    def run(self):
        if websocket is None:
            raise RuntimeError("websocket-client not installed. Install with: pip install websocket-client")

        self.ensure_tokens()
        # Build websocket handshake headers using tokens (some servers expect these in the WS handshake)
        # Do not inject extra headers by default; Radar2 works without WS headers.
        headers = None
        # If we don't have a host yet, build candidate hosts
        def generate_candidates():
            cand = []
            if self.host:
                cand.append(self.host)
            # derive from base_url heuristics
            try:
                b = self.cap.base_url.rstrip('/')
                # replace api-... with api-streaming-...
                if 'api-' in b:
                    cand_host = b.replace('https://', 'wss://').replace('http://', 'ws://')
                    cand_host = cand_host.replace('api-', 'api-streaming-')
                    # append common paths
                    cand.append(cand_host + '/connect')
                    cand.append(cand_host + '/lightstreamer')
                # common known host
                cand.append('wss://push.capital.com/lightstreamer')
            except Exception:
                pass
            # ensure uniqueness
            seen = set()
            uniq = []
            for c in cand:
                if not c:
                    continue
                if c.endswith('/'):
                    c = c.rstrip('/')
                if c not in seen:
                    seen.add(c)
                    uniq.append(c)
            return uniq

        candidates = generate_candidates()
        if not candidates:
            raise RuntimeError("No streaming host candidates available. Provide host explicitly or ensure API returns streamingHost.")

        # Try candidates in a loop until stop_flag or success
        while not self.stop_flag.is_set():
            for candidate in candidates:
                if self.stop_flag.is_set():
                    break
                self.host = candidate
                self.log(f"[INFO] Intentando conectar a streaming host: {self.host}")
                try:
                    # Ensure using /connect path for the JSON WS API
                    connect_url = self.host
                    if connect_url.endswith('/'):
                        if not connect_url.endswith('/connect'):
                            connect_url = connect_url.rstrip('/') + '/connect'
                    elif not connect_url.endswith('/connect'):
                        connect_url = connect_url + '/connect'

                    ws = websocket.WebSocketApp(connect_url,
                                                on_message=self.on_message,
                                                on_open=self.on_open,
                                                on_error=self.on_error,
                                                on_close=self.on_close)
                    self.ws = ws

                    # Start a keep-alive ping thread that sends JSON ping frames
                    def ping_loop():
                        while not self.stop_flag.is_set():
                            try:
                                ping = {"destination": "ping", "correlationId": "ping", "cst": self.cap.session_token, "securityToken": self.cap.x_security_token}
                                if self.ws and getattr(self.ws, 'send', None):
                                    self.ws.send(json.dumps(ping))
                            except Exception:
                                pass
                            time.sleep(25)
                    ping_thread = threading.Thread(target=ping_loop, daemon=True)
                    ping_thread.start()

                    ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    self.log(f"[WARN] WS loop exception para {self.host}: {e}")
                # refresh tokens and possibly re-query hosts before next candidate
                try:
                    self.ensure_tokens()
                except Exception:
                    pass
                time.sleep(1.0)

    def stop(self):
        self.stop_flag.set()
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass


def main():
    import sys
    host_arg = None
    if len(sys.argv) > 1:
        host_arg = sys.argv[1]
    epic_arg = None
    if len(sys.argv) > 2:
        epic_arg = sys.argv[2]
    lm = LightMinimal(epic=(epic_arg or "ETHUSD"), host=host_arg)
    def _sig(sig, frame):
        lm.stop()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    print("[INFO] Starting lightstream minimal (ETHUSD)")
    lm.run()


if __name__ == '__main__':
    main()
