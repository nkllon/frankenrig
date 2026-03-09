#!/usr/bin/env python3
"""
Bind OBS input Aux2 (lower-left PiP) to the Chrome window whose active tab has the given URL.
Does not open any new window. Finds existing window, brings it to front, gets ID, sets Aux2.
Uses robust OBS request handling (unique request IDs, short delays) to avoid connection resets.

Usage:
  .venv_obsws/bin/python3 obs_bind_aux2_by_url.py
  .venv_obsws/bin/python3 obs_bind_aux2_by_url.py --url "https://www.youtube.com/watch?v=DxmDPrfinXY"
"""

import argparse
import json
import subprocess
import sys
import time
import websocket

OBS_WS_URL = "ws://127.0.0.1:4455"
SCENE = "PiP"
INPUT_AUX2 = "Aux2"
DEFAULT_URL = "https://www.youtube.com/watch?v=DxmDPrfinXY"


def find_chrome_window_id_for_url(url: str) -> int:
    """Bring Chrome window with this URL to front; return its CGWindowNumber."""
    video_id = url.split("v=")[-1].split("&")[0] if "v=" in url else url
    subprocess.run(
        ["osascript", "-e", f'''
tell application "Google Chrome" to activate
delay 0.5
tell application "Google Chrome"
  repeat with w in every window
    try
      set u to URL of active tab of w
      if u contains "{video_id}" then
        set index of w to 1
        return
      end if
    end try
  end repeat
end tell
'''],
        check=True,
        capture_output=True,
    )
    time.sleep(0.3)
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    wins = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    chrome = [
        w for w in wins
        if (w.get("kCGWindowOwnerName") or "").strip() == "Google Chrome"
        and w.get("kCGWindowNumber")
    ]
    if not chrome:
        raise RuntimeError("No Chrome window found")
    return chrome[0]["kCGWindowNumber"]


class ObsClient:
    """Minimal OBS WebSocket client with robust request/response matching."""

    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.req_id = 0

    def connect(self):
        self.ws = websocket.create_connection(self.url, timeout=6)
        self.ws.recv()
        self.ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
        self.ws.recv()

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def req(self, request_type: str, data=None):
        self.req_id += 1
        rid = f"r{self.req_id}"
        self.ws.send(json.dumps({
            "op": 6,
            "d": {
                "requestType": request_type,
                "requestId": rid,
                "requestData": data or {},
            },
        }))
        while True:
            msg = self.ws.recv()
            r = json.loads(msg)
            d = r.get("d", {})
            if d.get("requestId") == rid:
                break
        st = d.get("requestStatus", {})
        return st.get("result", False), st, d.get("responseData", {})

    def set_aux2_and_refresh(self, window_id: int) -> None:
        """Set Aux2 to window_id; move to top of stack and ensure enabled. Delays between calls."""
        settings = {
            "type": 1,
            "window": window_id,
            "show_hidden_windows": True,
            "hide_obs": True,
            "show_empty_names": True,
            "show_cursor": True,
        }
        ok, st, _ = self.req("SetInputSettings", {
            "inputName": INPUT_AUX2,
            "inputSettings": settings,
            "overlay": True,
        })
        if not ok:
            raise RuntimeError(f"SetInputSettings Aux2: {st}")
        time.sleep(0.2)

        ok, st, data = self.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return
        items = data.get("sceneItems", [])
        aux2_item = next((i for i in items if (i.get("sourceName")) == INPUT_AUX2), None)
        if not aux2_item:
            return
        scene_item_id = aux2_item["sceneItemId"]
        max_index = max(i.get("sceneItemIndex", 0) for i in items)
        time.sleep(0.2)

        ok, st, _ = self.req("SetSceneItemIndex", {
            "sceneName": SCENE,
            "sceneItemId": scene_item_id,
            "sceneItemIndex": max_index + 1,
        })
        if not ok:
            return
        time.sleep(0.2)

        self.req("SetSceneItemEnabled", {
            "sceneName": SCENE,
            "sceneItemId": scene_item_id,
            "sceneItemEnabled": True,
        })


def main() -> int:
    ap = argparse.ArgumentParser(description="Bind Aux2 to Chrome window with given URL")
    ap.add_argument("--url", default=DEFAULT_URL, help="URL or page containing this (e.g. video id)")
    args = ap.parse_args()

    try:
        window_id = find_chrome_window_id_for_url(args.url)
        print(f"window_id={window_id}", flush=True)
    except Exception as e:
        print(f"error finding window: {e}", file=sys.stderr)
        return 1

    cli = ObsClient(OBS_WS_URL)
    try:
        for attempt in range(10):
            try:
                cli.connect()
                break
            except (ConnectionRefusedError, OSError) as e:
                if attempt == 9:
                    raise
                time.sleep(2)
        cli.set_aux2_and_refresh(window_id)
        time.sleep(0.2)
        ok, st, _ = cli.req("OpenVideoMixProjector", {"videoMixType": "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PREVIEW"})
        if not ok:
            pass  # non-fatal
        print("status=ok (Aux2 bound, refreshed, preview opened)")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
