#!/Users/lou/.hammerspoon/.venv_obsws/bin/python3
"""
High-level OBS PiP panel control:

- change-channel: rebind a panel's input to a different window id
- turn-off: disable one or more panels' scene items (hide + mute)
- start: re-enable one or more panels' scene items

This script intentionally keeps "channel" as an operator-facing label.
For now, channel IDs are metadata only; the operator supplies window IDs
when rebinding. The config file records panel mappings and last-known channel.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import websocket

CONFIG_PATH = Path("/Users/lou/.hammerspoon/obs_panel_control_config.json")
OBS_WS_URL = "ws://127.0.0.1:4455"


@dataclass
class PanelConfig:
    id: str
    input_name: Optional[str] = None
    input_name_prefix: Optional[str] = None
    source_name: Optional[str] = None
    source_prefix: Optional[str] = None


class ObsClient:
    def __init__(self, url: str):
        self.url = url
        self.ws: Optional[websocket.WebSocket] = None
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

    def req(self, request_type: str, data: Optional[Dict[str, Any]] = None) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
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
        assert self.ws is not None, "WebSocket not connected"
        self.ws.send(json.dumps(payload))
        while True:
            resp = json.loads(self.ws.recv())
            d = resp.get("d", {})
            if d.get("requestId") == rid:
                status = d.get("requestStatus", {}) or {}
                ok = bool(status.get("result", False))
                return ok, status, d.get("responseData", {}) or {}

    def scene_item_id_by_source(self, scene: str, source_name: str) -> Optional[int]:
        ok, _, data = self.req("GetSceneItemList", {"sceneName": scene})
        if not ok:
            return None
        for it in data.get("sceneItems", []):
            if it.get("sourceName") == source_name:
                return it.get("sceneItemId")
        return None

    def scene_item_ids_by_prefix(self, scene: str, prefix: str) -> List[int]:
        ok, _, data = self.req("GetSceneItemList", {"sceneName": scene})
        ids: List[int] = []
        if not ok:
            return ids
        for it in data.get("sceneItems", []):
            name = it.get("sourceName") or ""
            if name.startswith(prefix):
                sid = it.get("sceneItemId")
                if isinstance(sid, int):
                    ids.append(sid)
        return ids

    def set_scene_item_enabled(self, scene: str, scene_item_id: int, enabled: bool) -> bool:
        ok, status, _ = self.req(
            "SetSceneItemEnabled",
            {"sceneName": scene, "sceneItemId": scene_item_id, "sceneItemEnabled": enabled},
        )
        if not ok:
            print(f"SetSceneItemEnabled failed for {scene_item_id}: {status}", file=sys.stderr)
        return ok

    def set_input_window_capture(self, input_name: str, window_id: int) -> bool:
        ok, status, current = self.req("GetInputSettings", {"inputName": input_name})
        if not ok:
            print(f"GetInputSettings failed for '{input_name}': {status}", file=sys.stderr)
            return False
        settings = dict(current.get("inputSettings", {}) or {})
        settings["type"] = 1
        settings["window"] = window_id
        settings["show_hidden_windows"] = True
        settings["hide_obs"] = True
        settings["show_empty_names"] = True
        settings["show_cursor"] = True
        ok, status, _ = self.req(
            "SetInputSettings",
            {"inputName": input_name, "inputSettings": settings, "overlay": True},
        )
        if not ok:
            print(f"SetInputSettings failed for '{input_name}': {status}", file=sys.stderr)
        return ok


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_panel_configs(config: Dict[str, Any]) -> Dict[str, PanelConfig]:
    panels_cfg = config.get("panels") or {}
    resolved: Dict[str, PanelConfig] = {}
    for pid, pdata in panels_cfg.items():
        resolved[pid] = PanelConfig(
            id=pid,
            input_name=pdata.get("inputName"),
            input_name_prefix=pdata.get("inputNamePrefix"),
            source_name=pdata.get("sceneItemSourceName"),
            source_prefix=pdata.get("sceneItemSourcePrefix"),
        )
    return resolved


def find_scene_items_for_panel(cli: ObsClient, scene: str, panel: PanelConfig) -> List[int]:
    if panel.source_name:
        sid = cli.scene_item_id_by_source(scene, panel.source_name)
        return [sid] if sid is not None else []
    if panel.source_prefix:
        return cli.scene_item_ids_by_prefix(scene, panel.source_prefix)
    return []


def cmd_change_channel(args: argparse.Namespace) -> int:
    cfg = load_config()
    scene = cfg.get("scene", "PiP")
    panels = resolve_panel_configs(cfg)
    panel = panels.get(args.panel)
    if not panel:
        print(json.dumps({"status": "error", "error": f"unknown panel '{args.panel}'"}))
        return 1
    if not panel.input_name:
        print(json.dumps({"status": "error", "error": f"panel '{args.panel}' has no fixed inputName in config"}))
        return 1
    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
        ok = cli.set_input_window_capture(panel.input_name, args.window_id)
        if not ok:
            print(json.dumps({"status": "error", "panel": args.panel, "input": panel.input_name, "window_id": args.window_id}))
            return 1
        # Optionally, ensure scene item is enabled
        item_ids = find_scene_items_for_panel(cli, scene, panel)
        for sid in item_ids:
            cli.set_scene_item_enabled(scene, sid, True)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "action": "change-channel",
                    "panel": args.panel,
                    "input": panel.input_name,
                    "window_id": args.window_id,
                    "channel": args.channel or None,
                }
            )
        )
        return 0
    finally:
        cli.close()


def cmd_turn_off(args: argparse.Namespace) -> int:
    cfg = load_config()
    scene = cfg.get("scene", "PiP")
    panels = resolve_panel_configs(cfg)
    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
        results: Dict[str, Any] = {"status": "ok", "action": "turn-off", "panels": []}
        code = 0
        for pid in args.panels:
            panel = panels.get(pid)
            if not panel:
                results["panels"].append({"panel": pid, "status": "error", "error": "unknown panel"})
                code = 1
                continue
            item_ids = find_scene_items_for_panel(cli, scene, panel)
            if not item_ids:
                results["panels"].append({"panel": pid, "status": "error", "error": "no scene items found"})
                code = 1
                continue
            ok_all = True
            for sid in item_ids:
                if not cli.set_scene_item_enabled(scene, sid, False):
                    ok_all = False
            if ok_all:
                results["panels"].append({"panel": pid, "status": "off"})
            else:
                results["panels"].append({"panel": pid, "status": "error", "error": "failed to disable one or more scene items"})
                code = 1
        print(json.dumps(results))
        return code
    finally:
        cli.close()


def cmd_start(args: argparse.Namespace) -> int:
    cfg = load_config()
    scene = cfg.get("scene", "PiP")
    panels = resolve_panel_configs(cfg)
    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
        results: Dict[str, Any] = {"status": "ok", "action": "start", "panels": []}
        code = 0
        for pid in args.panels:
            panel = panels.get(pid)
            if not panel:
                results["panels"].append({"panel": pid, "status": "error", "error": "unknown panel"})
                code = 1
                continue
            item_ids = find_scene_items_for_panel(cli, scene, panel)
            if not item_ids:
                results["panels"].append({"panel": pid, "status": "error", "error": "no scene items found"})
                code = 1
                continue
            ok_all = True
            for sid in item_ids:
                if not cli.set_scene_item_enabled(scene, sid, True):
                    ok_all = False
            if ok_all:
                results["panels"].append({"panel": pid, "status": "on"})
            else:
                results["panels"].append({"panel": pid, "status": "error", "error": "failed to enable one or more scene items"})
                code = 1
        print(json.dumps(results))
        return code
    finally:
        cli.close()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="OBS PiP panel control")
    sub = ap.add_subparsers(dest="command", required=True)

    ch = sub.add_parser("change-channel", help="Change channel on a panel by rebinding its window capture")
    ch.add_argument("--panel", required=True, choices=["main", "aux_left", "aux_right", "aux_center"], help="Logical panel id")
    ch.add_argument("--window-id", type=int, required=True, help="Target window id for the new channel")
    ch.add_argument("--channel", help="Optional channel id/label for logging only")
    ch.set_defaults(func=cmd_change_channel)

    toff = sub.add_parser("turn-off", help="Turn off (hide) one or more panels")
    toff.add_argument("panels", nargs="+", help="Logical panel ids to turn off")
    toff.set_defaults(func=cmd_turn_off)

    st = sub.add_parser("start", help="Start (show) one or more panels")
    st.add_argument("panels", nargs="+", help="Logical panel ids to start")
    st.set_defaults(func=cmd_start)

    return ap


def main() -> int:
    ap = build_arg_parser()
    args = ap.parse_args()
    func = getattr(args, "func", None)
    if not func:
        ap.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())

