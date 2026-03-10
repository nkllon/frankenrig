#!/usr/bin/env python3
"""
Set the second window-capture source (Aux Capture) to the window you choose.

1) Get target window ID (interactive click via identify_window_click.py, or --window-id N).
2) Create or rewire input "Aux Capture" to that window (type=1, window=id).

Does not open any projector window. In OBS, open that source's projector from the View menu
or right-click the source when you want to see it, and position the window yourself.

Usage:
  .venv_obsws/bin/python3 open_aux_projector_by_click.py
  .venv_obsws/bin/python3 open_aux_projector_by_click.py --window-id 19763
  .venv_obsws/bin/python3 open_aux_projector_by_click.py --dry-run
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import websocket
from obs_pip_ontology import get_slot_spec

OBS_WS_URL = "ws://127.0.0.1:4455"
AUX_INPUT_NAME = "Aux Capture"  # default; use --input-name Aux2 for lower-left PiP
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
        _ = json.loads(self.ws.recv())
        self.ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
        _ = json.loads(self.ws.recv())

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
        return ok, status, d.get("responseData", {}) or {}

    def get_input_window_id(self, input_name: str) -> int | None:
        ok, status, data = self.req("GetInputSettings", {"inputName": input_name})
        if not ok:
            raise RuntimeError(f"GetInputSettings failed for '{input_name}': {status}")
        settings = data.get("inputSettings", {}) or {}
        wid = settings.get("window")
        return int(wid) if wid is not None else None


def input_exists(cli: ObsClient, name: str) -> bool:
    ok, _, data = cli.req("GetInputList")
    if not ok:
        return False
    for inp in data.get("inputs", []):
        if inp.get("inputName") == name:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Open aux projector for a clicked window")
    ap.add_argument("--window-id", type=int, help="Use this window ID instead of click")
    ap.add_argument("--input-name", default=AUX_INPUT_NAME, help="OBS input to bind (default: Aux Capture; use Aux2 for lower-left PiP)")
    ap.add_argument("--scene", default=DEFAULT_SCENE, help="Scene to add Aux Capture to if creating")
    ap.add_argument("--dry-run", action="store_true", help="Do not apply changes")
    args = ap.parse_args()

    input_name = args.input_name

    if args.window_id is None:
        print(f"Click the window to bind to '{input_name}'…", flush=True)
        window_id = identify_window_by_click()
    else:
        window_id = args.window_id

    print(f"target_window_id={window_id} input={input_name}")

    # Match working PiP Capture: type=1 window capture + show_cursor so macOS keeps live capture
    settings = {
        "type": 1,
        "window": window_id,
        "show_hidden_windows": True,
        "hide_obs": True,
        "show_empty_names": True,
        "show_cursor": True,
    }

    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
        lower_left_input = get_slot_spec("lowerLeft").input_name
        main_input = get_slot_spec("main").input_name
        if input_name == lower_left_input and main_input:
            main_window_id = cli.get_input_window_id(main_input)
            if main_window_id is not None and main_window_id == window_id:
                raise RuntimeError(f"Refusing to bind {input_name} to window {window_id}: duplicates {main_input}")

        if input_exists(cli, input_name):
            ok, status, _ = cli.req(
                "SetInputSettings",
                {"inputName": input_name, "inputSettings": settings, "overlay": True},
            )
            if not ok:
                raise RuntimeError(f"SetInputSettings failed: {status}")
            print(f"Updated existing input '{input_name}' to window={window_id}")
        else:
            if args.dry_run:
                print(f"[dry-run] Would CreateInput '{input_name}' in scene '{args.scene}' with window={window_id}")
            else:
                ok, status, data = cli.req(
                    "CreateInput",
                    {
                        "sceneName": args.scene,
                        "inputName": input_name,
                        "inputKind": "screen_capture",
                        "inputSettings": settings,
                    },
                )
                if not ok:
                    comment = status.get("comment", str(status))
                    if "already exists" in comment.lower():
                        ok2, status2, _ = cli.req(
                            "SetInputSettings",
                            {"inputName": input_name, "inputSettings": settings, "overlay": True},
                        )
                        if not ok2:
                            raise RuntimeError(f"SetInputSettings failed (after create conflict): {status2}")
                        print(f"Input '{input_name}' already existed; updated to window={window_id}")
                    else:
                        raise RuntimeError(f"CreateInput failed: {comment}")
                else:
                    print(f"Created input '{input_name}' in scene '{args.scene}'")

        print("status=ok")
        if not args.dry_run:
            print(f"'{input_name}' is set. In OBS, open its projector from View menu or right-click the source when you want it.")
        return 0
    except Exception as e:
        print(f"status=error error={e}", file=sys.stderr)
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    raise SystemExit(main())
