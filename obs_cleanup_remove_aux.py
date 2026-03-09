#!/usr/bin/env python3
"""
Remove the Aux Capture input from OBS. Run this after you have closed all
extra projector windows (so only one preview remains, or none). Otherwise
RemoveInput may report success but the input can persist while a projector uses it.

Usage:
  .venv_obsws/bin/python3 obs_cleanup_remove_aux.py
"""

import json
import sys
import websocket

URL = "ws://127.0.0.1:4455"


def main():
    ws = websocket.create_connection(URL, timeout=4)
    ws.recv()
    ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
    ws.recv()

    def req(t, d=None):
        ws.send(json.dumps({"op": 6, "d": {"requestType": t, "requestId": "r1", "requestData": d or {}}}))
        r = json.loads(ws.recv())
        return r.get("d", {}).get("requestStatus", {})

    # Remove by name
    status = req("RemoveInput", {"inputName": "Aux Capture"})
    ok = status.get("result", False)
    comment = status.get("comment", "")

    # Verify
    ws.send(json.dumps({"op": 6, "d": {"requestType": "GetInputList", "requestId": "r2", "requestData": {}}}))
    r2 = json.loads(ws.recv())
    inputs = r2.get("d", {}).get("responseData", {}).get("inputs", [])
    names = [i.get("inputName") for i in inputs]

    ws.close()

    if ok and "Aux Capture" not in names:
        print("Removed 'Aux Capture'. Inputs now:", names)
        return 0
    if ok and "Aux Capture" in names:
        print("RemoveInput reported success but 'Aux Capture' is still present. Close any projector showing Aux Capture, then run this script again.", file=sys.stderr)
        return 1
    print(f"RemoveInput failed: {comment}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
