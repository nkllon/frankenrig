#!/usr/bin/env python3
"""
Reconstruct the working PiP arrangement from scratch given window IDs.

- PiP Capture -> window_1 (main, full canvas)
- Aux2 -> window_2 (small PiP lower-left)
- Aux3 -> Aux3LR_<timestamp> (optional, small PiP lower-right)
- Aux4 -> Aux4Center_<timestamp> (optional, small PiP bottom center between the two)
- Opens preview projector.

Usage:
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --window1 ID1 --window2 ID2
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py   # prompts for two clicks
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --lower-right   # one click -> add that window as Aux3 lower-right
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --window3 ID3   # add third window lower-right (with full rebuild if window1/2 set)
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --add-fourth-center --window4 ID4   # add fourth window bottom center
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --fix-aux3   # re-apply lower-right transform
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --fix-aux4   # re-apply bottom-center transform (alignment 36)
  .venv_obsws/bin/python3 obs_apply_pip_layout.py   # authoritative only: ontology + mandatory proof bundle (no discovery)
  .venv_obsws/bin/python3 obs_rebuild_pip_arrangement.py --reset-view # delegates to obs_apply_pip_layout.py
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import websocket
from obs_pip_ontology import get_layout_payload, load_graph

OBS_WS_URL = "ws://127.0.0.1:4455"
SCENE = "PiP"
INPUT_MAIN = "PiP Capture"
INPUT_PIP = "Aux2"
INPUT_PIP_RIGHT_PREFIX = "Aux3LR"  # base name; we use Aux3LR_<timestamp> so CreateInput always succeeds (stuck names can't be removed)
INPUT_PIP_CENTER_PREFIX = "Aux4Center"  # fourth source, between the two bottom PiPs
IDENT_SCRIPT = Path("/Users/lou/.hammerspoon/identify_window_click.py")
IDENT_PY = Path("/Users/lou/.hammerspoon/.venv_obsws/bin/python3")

# Main transform matches the ontology-backed full-canvas layout.
TRANSFORM_MAIN = {
    "positionX": 0.0,
    "positionY": -95.0,
    "scaleX": 1.0,
    "scaleY": 1.0,
    "boundsWidth": 3840.0,
    "boundsHeight": 2254.0,
    "boundsType": "OBS_BOUNDS_STRETCH",
    "boundsAlignment": 0,
    "alignment": 5,
    "rotation": 0.0,
    "cropTop": 0,
    "cropBottom": 0,
    "cropLeft": 0,
    "cropRight": 0,
}
# Legacy row-math constants are retained for compatibility comments only; runtime
# transforms now come from the ontology-backed layout payload.
PIP_SCALE_X = 0.3128255158662796
PIP_SCALE_Y = 0.3127772733569145
# Reference canvas and single-row layout. All three small PiPs use the same anchor: top-left (alignment 5).
REF_CANVAS_WIDTH = 3840.0
REF_CANVAS_HEIGHT = 2254.0
REF_SOURCE_WIDTH = 1920.0   # typical capture size for pip_width in canvas space
REF_SOURCE_HEIGHT = 1080.0
REF_PIP_TOP_Y = 1421.0     # top edge of bottom row
REF_LEFT_MARGIN_X = 20.0
REF_RIGHT_INSET_X = 540.0  # from right edge of canvas to right edge of right PiP
# Derived: pip size in canvas space (same for all three)
PIP_WIDTH_CANVAS = REF_SOURCE_WIDTH * PIP_SCALE_X   # ~600.6
PIP_HEIGHT_CANVAS = REF_SOURCE_HEIGHT * PIP_SCALE_Y  # ~337.8


def _pip_row_scale(canvas_height: float) -> float:
    """Scale factor for Y when canvas height differs from reference."""
    return canvas_height / REF_CANVAS_HEIGHT


def _pip_transform(canvas_width: float, canvas_height: float, position_x: float, position_y: float) -> dict:
    """Shared transform for all three small PiPs: same scale, same anchor (top-left = 5)."""
    return {
        "positionX": position_x,
        "positionY": position_y,
        "scaleX": PIP_SCALE_X,
        "scaleY": PIP_SCALE_Y,
        "boundsWidth": 1.0,
        "boundsHeight": 1.0,
        "boundsType": "OBS_BOUNDS_NONE",
        "boundsAlignment": 0,
        "alignment": 5,  # OBS_ALIGN_LEFT | OBS_ALIGN_TOP — same anchor for all three
        "rotation": 0.0,
        "cropTop": 0,
        "cropBottom": 0,
        "cropLeft": 0,
        "cropRight": 0,
    }


def _ontology_transforms() -> dict:
    return get_layout_payload(load_graph())["transforms"]


def transform_pip_left(canvas_width: float, canvas_height: float) -> dict:
    """Lower-left PiP transform from ontology authority."""
    return dict(_ontology_transforms()["auxLeft"])


def transform_pip_right(canvas_width: float, canvas_height: float) -> dict:
    """Lower-right PiP transform from ontology authority."""
    return dict(_ontology_transforms()["auxRight"])


def transform_pip_center(canvas_width: float, canvas_height: float) -> dict:
    """Bottom-center PiP transform from ontology authority."""
    return dict(_ontology_transforms()["auxCenter"])


def parse_window_id(text: str) -> int:
    m = re.search(r"\bid\s*=\s*(\d+)\b", text)
    if not m:
        raise ValueError(f"Could not parse window id from: {text!r}")
    return int(m.group(1))


def identify_by_click() -> int:
    proc = subprocess.run([str(IDENT_PY), str(IDENT_SCRIPT)], capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"identify script failed: {out.strip()}")
    return parse_window_id(out)


class ObsClient:
    def __init__(self, url: str):
        self.ws = None
        self.url = url
        self.req_id = 0

    def connect(self):
        self.ws = websocket.create_connection(self.url, timeout=4)
        self.ws.recv()
        self.ws.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
        self.ws.recv()

    def close(self):
        if self.ws:
            self.ws.close()
            self.ws = None

    def req(self, request_type: str, data=None):
        self.req_id += 1
        rid = f"r{self.req_id}"
        self.ws.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": rid, "requestData": data or {}}}))
        while True:
            r = json.loads(self.ws.recv())
            d = r.get("d", {})
            if d.get("requestId") == rid:
                break
        st = d.get("requestStatus", {})
        return st.get("result", False), st, d.get("responseData", {})

    def get_canvas_size(self) -> tuple[float, float]:
        """Return (baseWidth, baseHeight) from OBS video settings."""
        ok, _, data = self.req("GetVideoSettings", {})
        if not ok:
            return 3840.0, 2254.0  # fallback
        w = data.get("baseWidth") or data.get("outputWidth") or 3840
        h = data.get("baseHeight") or data.get("outputHeight") or 2254
        return float(w), float(h)

    def input_exists(self, name: str) -> bool:
        ok, _, data = self.req("GetInputList", {})
        if not ok:
            return False
        return any(i.get("inputName") == name for i in data.get("inputs", []))

    def remove_input(self, name: str) -> None:
        """Remove input if it exists. Ignore if not found."""
        if not self.input_exists(name):
            return
        ok, st, _ = self.req("RemoveInput", {"inputName": name})
        if not ok:
            comment = (st.get("comment") or "").lower()
            if "not found" in comment or "does not exist" in comment:
                return
            raise RuntimeError(f"RemoveInput {name}: {st.get('comment', st)}")

    def ensure_input(self, name: str, window_id: int) -> int | None:
        """Ensure input exists and is configured. For third source (name starting with prefix), creates with unique name and returns sceneItemId."""
        settings = {"type": 1, "window": window_id, "show_hidden_windows": True, "hide_obs": True, "show_empty_names": True, "show_cursor": True}
        # Third/fourth sources: unique name so CreateInput always succeeds (RemoveInput often doesn't actually remove)
        if name.startswith(INPUT_PIP_RIGHT_PREFIX) or name.startswith(INPUT_PIP_CENTER_PREFIX):
            ok, st, data = self.req("CreateInput", {"sceneName": SCENE, "inputName": name, "inputKind": "screen_capture", "inputSettings": settings})
            if not ok:
                raise RuntimeError(f"CreateInput {name}: {st.get('comment', st)}")
            return data.get("sceneItemId")
        if self.input_exists(name):
            ok, st, _ = self.req("SetInputSettings", {"inputName": name, "inputSettings": settings, "overlay": True})
            if not ok:
                raise RuntimeError(f"SetInputSettings {name}: {st.get('comment', st)}")
        else:
            ok, st, _ = self.req("CreateInput", {"sceneName": SCENE, "inputName": name, "inputKind": "screen_capture", "inputSettings": settings})
            if not ok:
                comment = st.get("comment", str(st))
                if "already exists" in str(comment).lower() or self.input_exists(name):
                    ok2, st2, _ = self.req("SetInputSettings", {"inputName": name, "inputSettings": settings, "overlay": True})
                    if not ok2:
                        raise RuntimeError(f"SetInputSettings (after CreateInput conflict) {name}: {st2.get('comment', st2)}")
                else:
                    raise RuntimeError(f"CreateInput {name}: {comment}")
        return None

    def scene_item_id(self, source_name: str) -> int | None:
        # Try GetSceneItemId first (OBS 5)
        ok, _, data = self.req("GetSceneItemId", {"sceneName": SCENE, "sourceName": source_name})
        if ok and data.get("sceneItemId") is not None:
            return data.get("sceneItemId")
        ok, _, data = self.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return None
        for it in data.get("sceneItems", []):
            if it.get("sourceName") == source_name:
                return it.get("sceneItemId")
        return None

    def scene_item_id_by_prefix(self, prefix: str) -> int | None:
        """Return scene item id of first source whose name starts with prefix."""
        ok, _, data = self.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return None
        for it in data.get("sceneItems", []):
            if (it.get("sourceName") or "").startswith(prefix):
                return it.get("sceneItemId")
        return None

    def ensure_scene_item(self, source_name: str) -> int:
        for _ in range(5):
            sid = self.scene_item_id(source_name)
            if sid is not None:
                return sid
            time.sleep(0.15)
        ok, st, data = self.req("CreateSceneItem", {"sceneName": SCENE, "sourceName": source_name, "sceneItemEnabled": True})
        if not ok:
            if st.get("code") == 700 and source_name.startswith(INPUT_PIP_RIGHT_PREFIX):
                raise RuntimeError(
                    f"CreateSceneItem {source_name}: {st.get('comment')}. "
                    f"Add the source to the PiP scene in OBS (Sources → Add → Existing), then run --fix-aux3."
                )
            raise RuntimeError(f"CreateSceneItem {source_name}: {st}")
        return data.get("sceneItemId")

    def set_transform(self, scene_item_id: int, transform: dict) -> None:
        ok, st, _ = self.req("SetSceneItemTransform", {"sceneName": SCENE, "sceneItemId": scene_item_id, "sceneItemTransform": transform})
        if not ok:
            raise RuntimeError(f"SetSceneItemTransform: {st}")

    def move_scene_item_to_top(self, scene_item_id: int) -> None:
        """Move scene item to top of stack (higher index = drawn on top)."""
        ok, _, data = self.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return
        items = data.get("sceneItems", [])
        if not items:
            return
        max_index = max(it.get("sceneItemIndex", 0) for it in items)
        ok, st, _ = self.req("SetSceneItemIndex", {"sceneName": SCENE, "sceneItemId": scene_item_id, "sceneItemIndex": max_index + 1})
        if not ok:
            raise RuntimeError(f"SetSceneItemIndex: {st.get('comment', st)}")

    def move_scene_item_to_bottom(self, scene_item_id: int) -> None:
        """Move scene item to bottom of stack so it is drawn first (behind others).
        In OBS, index 0 can mean 'first in list'; draw order may be list order or reverse.
        We set main to index 0; if the three PiPs still get covered, try last index instead."""
        ok, st, _ = self.req("SetSceneItemIndex", {"sceneName": SCENE, "sceneItemId": scene_item_id, "sceneItemIndex": 0})
        if not ok:
            raise RuntimeError(f"SetSceneItemIndex (to bottom): {st.get('comment', st)}")

    def move_scene_item_to_back_last(self, scene_item_id: int) -> None:
        """Move scene item to last position in list (max index). Use when list order = draw order and first item is on top."""
        ok, _, data = self.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return
        items = data.get("sceneItems", [])
        if not items:
            return
        max_index = max(it.get("sceneItemIndex", 0) for it in items)
        ok, st, _ = self.req("SetSceneItemIndex", {"sceneName": SCENE, "sceneItemId": scene_item_id, "sceneItemIndex": max_index})
        if not ok:
            raise RuntimeError(f"SetSceneItemIndex (to back/last): {st.get('comment', st)}")

    def save_scene_screenshot(self, scene_name: str, file_path: Path) -> None:
        """Capture scene as PNG via SaveSourceScreenshot; OBS writes file directly."""
        path_str = str(file_path.resolve())
        ok, st, _ = self.req(
            "SaveSourceScreenshot",
            {
                "sourceName": scene_name,
                "imageFilePath": path_str,
                "imageFormat": "png",
                "imageCompressionQuality": 90,
            },
        )
        if not ok:
            raise RuntimeError(f"SaveSourceScreenshot: {st.get('comment', st)}")
        if not file_path.exists():
            raise RuntimeError(f"SaveSourceScreenshot did not create {path_str}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconstruct PiP arrangement from window IDs")
    ap.add_argument("--window1", type=int, help="Main window ID (PiP Capture)")
    ap.add_argument("--window2", type=int, help="Second window ID (Aux2, lower-left)")
    ap.add_argument("--window3", type=int, help="Third window ID (Aux3, lower-right)")
    ap.add_argument("--window4", type=int, help="Fourth window ID (Aux4, bottom center between the two PiPs)")
    ap.add_argument("--lower-right", action="store_true", help="Only add one window to lower-right (prompt for one click)")
    ap.add_argument("--add-fourth-center", action="store_true", help="Add one window as fourth PiP (bottom center); requires --window4")
    ap.add_argument("--diagnose", action="store_true", help="Print PiP scene items and video settings, then exit")
    ap.add_argument("--fix-aux3", action="store_true", help="Re-apply lower-right transform to existing Aux3 and move to top (no click)")
    ap.add_argument("--fix-aux4", action="store_true", help="Re-apply bottom-center transform to existing Aux4 (e.g. after alignment fix)")
    ap.add_argument("--reset-view", action="store_true", help="Re-apply all four PiP transforms from shared row math (main, Aux2, Aux3, Aux4); fix alignment and ensure lower-left visible")
    ap.add_argument("--screenshot", type=str, metavar="PATH", help="After applying transforms, save PiP scene screenshot to PATH (use with --reset-view to verify)")
    ap.add_argument("--dry-run", action="store_true", help="Do not apply")
    args = ap.parse_args()

    if args.add_fourth_center:
        if args.window4 is None:
            print("error: --add-fourth-center requires --window4 ID", file=sys.stderr)
            sys.exit(1)
        aux4_name = f"{INPUT_PIP_CENTER_PREFIX}_{int(time.time())}"
        cli = ObsClient(OBS_WS_URL)
        try:
            cli.connect()
            cw, ch = cli.get_canvas_size()
            print(f"canvas={cw:.0f}x{ch:.0f} -> bottom center ({aux4_name})", flush=True)
            id_center = cli.ensure_input(aux4_name, args.window4)
            if id_center is None:
                raise RuntimeError("CreateInput did not return sceneItemId")
            cli.set_transform(id_center, transform_pip_center(cw, ch))
            cli.move_scene_item_to_top(id_center)
            cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_center, "sceneItemEnabled": True})
            cli.req("SetCurrentProgramScene", {"sceneName": SCENE})
            print(f"status=ok (fourth source {aux4_name}, window_id={args.window4})")
        except Exception as e:
            print(f"error={e}", file=sys.stderr)
            sys.exit(1)
        finally:
            cli.close()
        return 0

    if args.fix_aux3:
        cli = ObsClient(OBS_WS_URL)
        try:
            cli.connect()
            cw, ch = cli.get_canvas_size()
            id_right = cli.scene_item_id_by_prefix(INPUT_PIP_RIGHT_PREFIX)
            if id_right is None:
                print(f"No source starting with '{INPUT_PIP_RIGHT_PREFIX}' in PiP scene. Run --lower-right first, then --fix-aux3.", file=sys.stderr)
                sys.exit(1)
            cli.set_transform(id_right, transform_pip_right(cw, ch))
            cli.move_scene_item_to_top(id_right)
            cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_right, "sceneItemEnabled": True})
            print(f"status=ok (Aux3 transform updated, canvas {cw:.0f}x{ch:.0f})")
        except Exception as e:
            print(f"error={e}", file=sys.stderr)
            sys.exit(1)
        finally:
            cli.close()
        return 0

    if args.fix_aux4:
        cli = ObsClient(OBS_WS_URL)
        try:
            cli.connect()
            cw, ch = cli.get_canvas_size()
            id_center = cli.scene_item_id_by_prefix(INPUT_PIP_CENTER_PREFIX)
            if id_center is None:
                print(f"No source starting with '{INPUT_PIP_CENTER_PREFIX}' in PiP scene. Run --add-fourth-center first.", file=sys.stderr)
                sys.exit(1)
            cli.set_transform(id_center, transform_pip_center(cw, ch))
            cli.move_scene_item_to_top(id_center)
            cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_center, "sceneItemEnabled": True})
            print(f"status=ok (Aux4 center transform updated, canvas {cw:.0f}x{ch:.0f})")
        except Exception as e:
            print(f"error={e}", file=sys.stderr)
            sys.exit(1)
        finally:
            cli.close()
        return 0

    if args.reset_view:
        # No discovery here—single source of truth is evidence/obs_pip_layout_authoritative.json
        apply_script = Path(__file__).resolve().parent / "obs_apply_pip_layout.py"
        cmd = [str(IDENT_PY.parent / "python3"), str(apply_script)]
        if args.screenshot:
            cmd.extend(["--screenshot", args.screenshot])
        proc = subprocess.run(cmd, cwd=str(apply_script.parent))
        return proc.returncode

    if args.screenshot and not args.reset_view:
        cli = ObsClient(OBS_WS_URL)
        try:
            cli.connect()
            out_path = Path(args.screenshot).expanduser().resolve()
            cli.save_scene_screenshot(SCENE, out_path)
            print(f"screenshot={out_path}")
            if out_path.exists():
                subprocess.run(["open", "-a", "Preview", str(out_path)], check=False)
        except Exception as e:
            print(f"error={e}", file=sys.stderr)
            sys.exit(1)
        finally:
            cli.close()
        return 0

    if args.diagnose:
        cli = ObsClient(OBS_WS_URL)
        try:
            cli.connect()
            cw, ch = cli.get_canvas_size()
            print(f"Video: base {cw:.0f} x {ch:.0f}")
            ok, _, data = cli.req("GetSceneItemList", {"sceneName": SCENE})
            if not ok:
                print("Could not get scene list")
            else:
                for it in data.get("sceneItems", []):
                    t = it.get("sceneItemTransform", {}) or {}
                    print(f"  {it.get('sourceName')!r} id={it.get('sceneItemId')} index={it.get('sceneItemIndex')} enabled={it.get('sceneItemEnabled')} pos=({t.get('positionX')}, {t.get('positionY')}) scale=({t.get('scaleX')}, {t.get('scaleY')})")
            # Show lower-right source input(s) if any
            ok, _, inputs_data = cli.req("GetInputList", {})
            if ok:
                for inp in inputs_data.get("inputs", []):
                    nm = inp.get("inputName") or ""
                    if nm.startswith(INPUT_PIP_RIGHT_PREFIX):
                        ok2, _, set_data = cli.req("GetInputSettings", {"inputName": nm})
                        if ok2:
                            s = set_data.get("inputSettings", {})
                            print(f"  {nm!r} input: type={s.get('type')} window={s.get('window')} kind={inp.get('inputKind')!r}")
        finally:
            cli.close()
        return 0

    if args.lower_right:
        if args.window3 is None:
            print("Click the window for LOWER RIGHT...", flush=True)
            args.window3 = identify_by_click()
        print(f"window3 (lower-right)={args.window3}")
        if args.dry_run:
            print("Dry run: would create/update Aux3 and set lower-right layout.")
            return 0
        aux3_name = f"{INPUT_PIP_RIGHT_PREFIX}_{int(time.time())}"
        cli = ObsClient(OBS_WS_URL)
        try:
            cli.connect()
            cw, ch = cli.get_canvas_size()
            print(f"canvas={cw:.0f}x{ch:.0f} -> lower-right ({aux3_name})", flush=True)
            id_right = cli.ensure_input(aux3_name, args.window3)
            if id_right is None:
                raise RuntimeError("CreateInput did not return sceneItemId")
            cli.set_transform(id_right, transform_pip_right(cw, ch))
            cli.move_scene_item_to_top(id_right)
            cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_right, "sceneItemEnabled": True})
            cli.req("SetCurrentProgramScene", {"sceneName": SCENE})
            print(f"status=ok (lower-right source {aux3_name})")
            return 0
        except Exception as e:
            print(f"error={e}", file=sys.stderr)
            return 1
        finally:
            cli.close()

    if args.window1 is None:
        print("Click the MAIN window (full canvas)...", flush=True)
        args.window1 = identify_by_click()
    if args.window2 is None:
        print("Click the SECOND window (small PiP, lower-left)...", flush=True)
        args.window2 = identify_by_click()
    if args.window3 is None:
        # optional third: don't prompt by default for backward compat
        pass

    print(f"window1={args.window1} window2={args.window2} window3={args.window3}")

    if args.dry_run:
        print("Dry run: would set inputs and layout, open preview.")
        return 0

    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
        cw, ch = cli.get_canvas_size()
        cli.ensure_input(INPUT_MAIN, args.window1)
        cli.ensure_input(INPUT_PIP, args.window2)
        id_main = cli.ensure_scene_item(INPUT_MAIN)
        id_pip = cli.ensure_scene_item(INPUT_PIP)
        cli.set_transform(id_main, TRANSFORM_MAIN)
        cli.set_transform(id_pip, transform_pip_left(cw, ch))
        cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_main, "sceneItemEnabled": True})
        cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_pip, "sceneItemEnabled": True})
        cli.move_scene_item_to_top(id_pip)
        if args.window3 is not None:
            aux3_name = f"{INPUT_PIP_RIGHT_PREFIX}_{int(time.time())}"
            id_right = cli.ensure_input(aux3_name, args.window3)
            if id_right is not None:
                cli.set_transform(id_right, transform_pip_right(cw, ch))
                cli.move_scene_item_to_top(id_right)
                cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": id_right, "sceneItemEnabled": True})
        cli.req("SetCurrentProgramScene", {"sceneName": SCENE})
        cli.req("OpenVideoMixProjector", {"videoMixType": "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PREVIEW"})
        print("status=ok")
        return 0
    except Exception as e:
        print(f"error={e}", file=sys.stderr)
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
