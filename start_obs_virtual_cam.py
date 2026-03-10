#!/usr/bin/env python3
"""
Start OBS Virtual Camera via obs-websocket (v5) on localhost:4455.
"""
import json
import sys
import time

try:
    import websocket
except Exception as e:
    print(f"ERROR: missing dependency 'websocket' (websocket-client). {e}", file=sys.stderr)
    print("Install with: pip3 install websocket-client", file=sys.stderr)
    sys.exit(2)

OBS_WS_URL = "ws://127.0.0.1:4455"

class ObsClient:
    def __init__(self, url: str):
        self.ws = None
        self.url = url
        self.req_id = 0

    def connect(self, timeout=4):
        self.ws = websocket.create_connection(self.url, timeout=timeout)
        # initial hello from server
        self.ws.recv()
        # send ident with rpcVersion=1 (matches discovery evidence)
        self.ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
        # server ack
        self.ws.recv()

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def req(self, request_type: str, data=None, timeout=4):
        self.req_id += 1
        rid = f"r{self.req_id}"
        payload = {"op": 6, "d": {"requestType": request_type, "requestId": rid, "requestData": data or {}}}
        self.ws.send(json.dumps(payload))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            if not raw:
                continue
            try:
                r = json.loads(raw)
            except Exception:
                continue
            d = r.get("d", {})
            if d.get("requestId") == rid:
                st = d.get("requestStatus", {})
                return st.get("result", False), st, d.get("responseData", {})
        return False, {"comment": "timeout waiting for response"}, {}

def main():
    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
    except Exception as e:
        print(f"ERROR: could not connect to obs-websocket at {OBS_WS_URL}: {e}", file=sys.stderr)
        sys.exit(3)

    try:
        ok, status, data = cli.req("GetVirtualCamStatus", {})
        if ok:
            running = data.get("isVirtualCamActive") or False
            print("VirtualCamStatus:", data)
            if running:
                print("Virtual camera already running.")
                return 0
        # Attempt to start
        ok, status, data = cli.req("StartVirtualCam", {})
        if ok:
            print("StartVirtualCam: success")
            return 0
        else:
            print("StartVirtualCam: failed:", status, file=sys.stderr)
            return 4
    finally:
        cli.close()

if __name__ == "__main__":
    sys.exit(main())

