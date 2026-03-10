#!/usr/bin/env python3
"""
Diagnostic: enumerate OBS inputs/scene items and attempt GetSourceScreenshot for candidates.
Saves any returned screenshots to /private/tmp and prints results.
"""
import json, base64, sys, time, re
try:
    import websocket
except Exception as e:
    print("Missing websocket-client. Install in venv: pip install websocket-client", file=sys.stderr)
    raise

OBS_WS = "ws://127.0.0.1:4455"

class ObsClient:
    def __init__(self, url=OBS_WS):
        self.url = url
        self.ws = None
        self.req_id = 0

    def connect(self):
        self.ws = websocket.create_connection(self.url, timeout=4)
        self.ws.recv()
        self.ws.send(json.dumps({"op":1,"d":{"rpcVersion":1}}))
        self.ws.recv()

    def close(self):
        if self.ws:
            try: self.ws.close()
            except: pass
            self.ws = None

    def req(self, rt, data=None, timeout=4):
        self.req_id += 1
        rid = f"r{self.req_id}"
        payload = {"op":6, "d":{"requestType": rt, "requestId": rid, "requestData": data or {}}}
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
            d = r.get("d",{})
            if d.get("requestId") == rid:
                st = d.get("requestStatus",{})
                return st.get("result", False), st, d.get("responseData", {})
        return False, {"comment":"timeout"}, {}

def safe_name(n):
    return re.sub(r'[^0-9A-Za-z._-]+','_', n)[:120]

def main():
    cli = ObsClient()
    try:
        cli.connect()
    except Exception as e:
        print("ERROR: could not connect to obs-websocket:", e, file=sys.stderr)
        return 2

    try:
        ok, st, data = cli.req("GetInputList", {})
        inputs = []
        if ok and data:
            inputs = [i.get("inputName") for i in data.get("inputs", []) if i.get("inputName")]
        print("Inputs:", inputs)

        ok2, st2, scene = cli.req("GetSceneItemList", {"sceneName":"PiP"})
        scene_items = []
        if ok2 and scene:
            scene_items = [it.get("sourceName") for it in scene.get("sceneItems", []) if it.get("sourceName")]
        print("PiP scene items:", scene_items)

        candidates = []
        # prefer PiP Capture, Aux2, Aux3*, Aux4* etc.
        for pref in ["PiP Capture","Aux2"]:
            if pref in inputs: candidates.append(pref)
        for nm in inputs:
            if nm not in candidates and (nm.startswith("Aux3") or nm.startswith("Aux4") or "Deutsche" in nm or "cowboy" in nm.lower()):
                candidates.append(nm)
        # fallback to scene items
        for nm in scene_items:
            if nm not in candidates:
                candidates.append(nm)
        # limit to 6
        candidates = candidates[:6]
        print("Candidates for screenshot:", candidates)

        for name in candidates:
            print("Requesting screenshot for:", name)
            ok, st, resp = cli.req("GetSourceScreenshot", {"sourceName": name, "imageFormat":"png", "imageWidth":1280}, timeout=8)
            if ok and resp and resp.get("imageData"):
                b64 = resp["imageData"]
                # strip data URI prefix if present
                if b64.startswith("data:"):
                    comma = b64.find(",")
                    if comma != -1:
                        b64 = b64[comma+1:]
                out = f"/private/tmp/obs_ss_{safe_name(name)}.png"
                with open(out, "wb") as f:
                    f.write(base64.b64decode(b64))
                print("Saved:", out)
            else:
                print("No imageData returned for:", name, "status:", st)
    finally:
        cli.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())

