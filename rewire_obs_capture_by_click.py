#!/Users/lou/.hammerspoon/.venv_obsws/bin/python3
"""
Rewire OBS window capture input to a clicked target window.

Default flow:
1) Ask user to click target window (via identify_window_click.py).
2) Parse returned window id.
3) Set OBS input settings for selected input to window capture bound to that id.
4) Ensure program scene is selected and scene item is enabled.

Usage examples:
  /Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/rewire_obs_capture_by_click.py
  /Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/rewire_obs_capture_by_click.py --window-id 14767
  /Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/rewire_obs_capture_by_click.py --dry-run
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import websocket

OBS_WS_URL = "ws://127.0.0.1:4455"
DEFAULT_INPUT = "PiP Capture"
DEFAULT_SCENE = "PiP"
IDENT_SCRIPT = Path("/Users/lou/.hammerspoon/identify_window_click.py")
IDENT_PY = Path("/Users/lou/.hammerspoon/.venv_obsws/bin/python3")


def parse_window_id(text: str) -> int:
    m = re.search(r"\bid\s*=\s*(\d+)\b", text)
    if not m:
        raise ValueError(f"Could not parse window id from output: {text!r}")
    return int(m.group(1))


def identify_window_by_click() -> int:
    if not IDENT_SCRIPT.exists():
        raise FileNotFoundError(f"Missing script: {IDENT_SCRIPT}")

    proc = subprocess.run(
        [str(IDENT_PY), str(IDENT_SCRIPT)],
        check=False,
        text=True,
        capture_output=True,
    )

    # Prefer stdout; fallback to stderr if needed.
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"identify script failed (code {proc.returncode}):\n{output.strip()}")

    return parse_window_id(output)


class ObsClient:
    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.req_id = 0

    def connect(self) -> None:
        self.ws = websocket.create_connection(self.url, timeout=4)
        _ = json.loads(self.ws.recv())  # Hello
        self.ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
        _ = json.loads(self.ws.recv())  # Identified

    def close(self) -> None:
        if self.ws:
            self.ws.close()
            self.ws = None

    def req(self, request_type: str, data=None):
        self.req_id += 1
        rid = f"r{self.req_id}"
        payload = {
            "op": 6,
            "d": {
                "requestType": request_type,
                "requestId": rid,
                "requestData": data or {},
            },
        }
        self.ws.send(json.dumps(payload))
        resp = json.loads(self.ws.recv())
        d = resp.get("d", {})
        status = d.get("requestStatus", {})
        ok = status.get("result", False)
        return ok, status, d.get("responseData", {})


def ensure_scene_item_enabled(cli: ObsClient, scene_name: str, source_name: str) -> None:
    ok, status, data = cli.req("GetSceneItemList", {"sceneName": scene_name})
    if not ok:
        raise RuntimeError(f"GetSceneItemList failed: {status}")

    item_id = None
    for item in data.get("sceneItems", []):
        if item.get("sourceName") == source_name:
            item_id = item.get("sceneItemId")
            break

    if item_id is None:
        raise RuntimeError(f"Source '{source_name}' not found in scene '{scene_name}'")

    ok, status, _ = cli.req(
        "SetSceneItemEnabled",
        {"sceneName": scene_name, "sceneItemId": item_id, "sceneItemEnabled": True},
    )
    if not ok:
        raise RuntimeError(f"SetSceneItemEnabled failed: {status}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT, help="OBS input to rebind")
    ap.add_argument("--scene", default=DEFAULT_SCENE, help="OBS scene to keep active")
    ap.add_argument("--window-id", type=int, help="Use explicit window id instead of click flow")
    ap.add_argument("--dry-run", action="store_true", help="Report actions without applying")
    args = ap.parse_args()

    if args.window_id is None:
        print("Identify target window: click it now (or move cursor and press Enter).", flush=True)
        window_id = identify_window_by_click()
    else:
        window_id = args.window_id

    print(f"target_window_id={window_id}")

    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()

        ok, status, current = cli.req("GetInputSettings", {"inputName": args.input})
        if not ok:
            raise RuntimeError(f"GetInputSettings failed for '{args.input}': {status}")

        merged = dict(current.get("inputSettings", {}))
        merged["type"] = 1
        merged["window"] = window_id
        merged["show_hidden_windows"] = True

        plan = {
            "scene": args.scene,
            "input": args.input,
            "new_settings": merged,
        }
        print(json.dumps({"plan": plan}, indent=2))

        if args.dry_run:
            return 0

        ok, status, _ = cli.req(
            "SetInputSettings",
            {"inputName": args.input, "inputSettings": merged, "overlay": True},
        )
        if not ok:
            raise RuntimeError(f"SetInputSettings failed: {status}")

        ok, status, _ = cli.req("SetCurrentProgramScene", {"sceneName": args.scene})
        if not ok:
            raise RuntimeError(f"SetCurrentProgramScene failed: {status}")

        ensure_scene_item_enabled(cli, args.scene, args.input)

        # Optional convenience: ensure a preview projector exists.
        cli.req("OpenVideoMixProjector", {"videoMixType": "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PREVIEW"})

        print("status=ok")
        return 0

    except Exception as e:
        print(f"status=error error={e}", file=sys.stderr)
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    raise SystemExit(main())
