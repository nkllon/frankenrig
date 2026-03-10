#!/usr/bin/env python3
"""
Bind OBS input Aux2 (lower-left PiP) to the Chrome window showing the URL.
Correct flow: YOU open the lower-left feed (e.g. Bloomberg URL) in YOUR Chrome logged in,
then run without --open-new-window. Script finds that window by URL only.
Do NOT use --open-new-window for PiP: new windows are not your session and binding can
put BBC (or any large window) into the Bloomberg slot by mistake.
Uses robust OBS request handling (unique request IDs, short delays) to avoid connection resets.

Usage:
  .venv_obsws/bin/python3 obs_bind_aux2_by_url.py
  .venv_obsws/bin/python3 obs_bind_aux2_by_url.py --url "https://..."
  # Avoid: --open-new-window (no login / wrong feed)
  # If lower-left stays empty (OBS reports Aux2 0×0), get ID by click then:
  .venv_obsws/bin/python3 obs_bind_aux2_by_url.py --window-id N

Dump after apply showed Aux2 width/height 0 while Aux3/Aux4 non-zero — wrong window ID for
OBS screen_capture, not layout. --window-id must be the window OBS can actually capture.
"""

import argparse
import json
import subprocess
import sys
import time
import websocket

from obs_pip_ontology import get_lower_left_url

OBS_WS_URL = "ws://127.0.0.1:4455"
SCENE = "PiP"
INPUT_AUX2 = "Aux2"
INPUT_MAIN = "PiP Capture"


def max_chrome_window_id() -> int:
    from Quartz import CGWindowListCopyWindowInfo, kCGNullWindowID
    wins = CGWindowListCopyWindowInfo(0, kCGNullWindowID)
    m = 0
    for w in wins:
        if (w.get("kCGWindowOwnerName") or "").strip() != "Google Chrome":
            continue
        wid = w.get("kCGWindowNumber")
        if wid and int(wid) > m:
            m = int(wid)
    return m


def open_new_chrome_window_with_url(url: str, wait_sec: float = 4.0) -> None:
    """Ask the *running* Chrome for a new window and load URL—no second process.
    AppleScript tell application "Google Chrome" targets the existing instance; make new window
    is the standard API (see e.g. https://superuser.com/questions/104180/ ).
    If the new window still isn't logged in, cause is profile/session—not launching a new binary."""
    # Escape double quotes for AppleScript string
    safe = url.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "Google Chrome"
  activate
  set w to make new window
  set URL of active tab of w to "{safe}"
end tell
delay 1
tell application "Google Chrome"
  -- Prefer a normal window size; fullscreen captures often fail in OBS
  try
    set bounds of front window to {{100, 100, 1100, 850}}
  end try
end tell
'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or "osascript failed")
    time.sleep(wait_sec)


def youtube_video_id(url: str) -> str | None:
    if "v=" not in url:
        return None
    return url.split("v=")[-1].split("&")[0].strip() or None


def url_matches(candidate: str, desired: str) -> bool:
    if candidate == desired:
        return True
    desired_id = youtube_video_id(desired)
    candidate_id = youtube_video_id(candidate)
    if desired_id and candidate_id:
        return desired_id == candidate_id
    return desired.rstrip("/") == candidate.rstrip("/")


def _run_osascript(script: str) -> str:
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "osascript failed").strip())
    return (proc.stdout or "").strip()


def _apple_script_window_for_url(url: str) -> dict[str, object]:
    safe = url.replace("\\", "\\\\").replace('"', '\\"')
    match_text = youtube_video_id(url) or safe
    safe_match = match_text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "Google Chrome" to activate
delay 0.3
tell application "Google Chrome"
  repeat with w in every window
    try
      set u to URL of active tab of w
      if u contains "{safe_match}" then
        set index of w to 1
        delay 0.2
        set fw to front window
        set fu to URL of active tab of fw
        set ft to title of active tab of fw
        set {{x1, y1, x2, y2}} to bounds of fw
        set ww to x2 - x1
        set hh to y2 - y1
        return fu & linefeed & ft & linefeed & x1 & linefeed & y1 & linefeed & ww & linefeed & hh
      end if
    end try
  end repeat
end tell
'''
    out = _run_osascript(script)
    parts = out.splitlines()
    if len(parts) < 6:
        raise RuntimeError(f"unexpected Chrome AppleScript output: {out!r}")
    actual_url, title, x, y, width, height = parts[:6]
    if not url_matches(actual_url, url):
        raise RuntimeError(f"front window URL did not match target: {actual_url}")
    return {
        "url": actual_url,
        "title": title,
        "x": int(float(x)),
        "y": int(float(y)),
        "width": int(float(width)),
        "height": int(float(height)),
    }


def fill_chrome_window_for_url(url: str) -> dict[str, object]:
    """
    Bring the existing Chrome window for this URL to front and use the Window -> Fill
    action so OBS sees a stable fullscreen-sized capture surface.
    """
    info = _apple_script_window_for_url(url)
    if info["width"] >= 1900 and info["height"] >= 1000 and info["x"] == 0 and info["y"] == 0:
        return info
    _run_osascript(
        '''
tell application "Google Chrome" to activate
delay 0.2
tell application "System Events"
  tell process "Google Chrome"
    click menu item "Fill" of menu 1 of menu bar item "Window" of menu bar 1
  end tell
end tell
'''
    )
    time.sleep(1.0)
    return _apple_script_window_for_url(url)


def _quartz_chrome_windows() -> list[dict[str, object]]:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
    )

    wins = CGWindowListCopyWindowInfo(0, kCGNullWindowID)
    out = []
    for w in wins:
        if (w.get("kCGWindowOwnerName") or "").strip() != "Google Chrome":
            continue
        wid = w.get("kCGWindowNumber")
        if not wid:
            continue
        bounds = w.get("kCGWindowBounds") or {}
        width = int(bounds.get("Width") or 0)
        height = int(bounds.get("Height") or 0)
        if width < 320 or height < 240:
            continue
        title = (w.get("kCGWindowName") or "").strip()
        if "Picture in Picture" in title:
            continue
        out.append(
            {
                "window_id": int(wid),
                "title": title,
                "x": int(bounds.get("X") or 0),
                "y": int(bounds.get("Y") or 0),
                "width": width,
                "height": height,
            }
        )
    return out


def _bounds_close(a: dict[str, object], b: dict[str, object], tolerance: int = 6) -> bool:
    for key in ("x", "y", "width", "height"):
        if abs(int(a[key]) - int(b[key])) > tolerance:
            return False
    return True


def chrome_window_ids_large(min_w: int = 800, min_h: int = 600) -> list[int]:
    """
    After open_new_chrome_window_with_url, the new window is usually the largest
    Chrome window with the highest kCGWindowNumber among qualifying bounds.
    """
    from Quartz import CGWindowListCopyWindowInfo, kCGNullWindowID

    wins = CGWindowListCopyWindowInfo(0, kCGNullWindowID)
    candidates = []
    for w in wins:
        if (w.get("kCGWindowOwnerName") or "").strip() != "Google Chrome":
            continue
        wid = w.get("kCGWindowNumber")
        if not wid:
            continue
        b = w.get("kCGWindowBounds") or {}
        bw = int(b.get("Width") or 0)
        bh = int(b.get("Height") or 0)
        if bw < min_w or bh < min_h:
            continue
        # Skip menu bars / thin strips
        if bh < min_h:
            continue
        name = (w.get("kCGWindowName") or "").strip()
        # Optional: skip PiP floaters if we want only main frame
        if "Picture in Picture" in name:
            continue
        candidates.append((int(wid), bw * bh))
    if not candidates:
        raise RuntimeError("No large Chrome window found after open (Chrome running?)")
    candidates.sort(key=lambda x: -x[0])  # by id descending
    return [w for w, _ in candidates]


def open_and_resolve_new_window_id(url: str, wait_after_open: float, main_window_id: int | None) -> int:
    before_id = max_chrome_window_id()
    open_new_chrome_window_with_url(url, wait_sec=2.0)
    time.sleep(max(0.0, wait_after_open - 2.0))
    large_ids = chrome_window_ids_large()
    new_ids = [wid for wid in large_ids if wid > before_id]
    if not new_ids:
        raise RuntimeError("No newly opened Chrome window detected for authoritative URL")
    for wid in new_ids:
        if main_window_id is not None and wid == main_window_id:
            continue
        return wid
    raise RuntimeError("New Chrome window candidates only duplicated the main binding")




def find_chrome_window_id_for_url(url: str) -> int:
    """Resolve the specific Chrome CGWindowNumber for the URL by matching AppleScript and Quartz bounds."""
    target = _apple_script_window_for_url(url)
    quartz_windows = _quartz_chrome_windows()
    candidates = [w for w in quartz_windows if _bounds_close(w, target)]
    if not candidates:
        raise RuntimeError("No Chrome window with matching bounds found after URL match")
    title = str(target.get("title") or "").strip()
    if title:
        title_matched = [w for w in candidates if title in str(w.get("title") or "")]
        if len(title_matched) == 1:
            return int(title_matched[0]["window_id"])
        if title_matched:
            candidates = title_matched
    return int(candidates[0]["window_id"])

def list_chrome_window_ids_min_size(min_w: int = 0, min_h: int = 0) -> list[int]:
    """All on-screen Chrome window IDs with bounds >= min_w x min_h, largest area first."""
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    wins = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    chrome = []
    seen = set()
    for w in wins:
        if (w.get("kCGWindowOwnerName") or "").strip() != "Google Chrome":
            continue
        wid = w.get("kCGWindowNumber")
        if not wid or wid in seen:
            continue
        bounds = w.get("kCGWindowBounds") or {}
        bw = int(bounds.get("Width") or 0)
        bh = int(bounds.get("Height") or 0)
        if bw < min_w or bh < min_h:
            continue
        seen.add(wid)
        chrome.append((bw * bh, wid))
    chrome.sort(key=lambda x: -x[0])
    return [wid for _area, wid in chrome]


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

    def get_input_settings(self, input_name: str) -> dict:
        ok, st, data = self.req("GetInputSettings", {"inputName": input_name})
        if not ok:
            raise RuntimeError(f"GetInputSettings {input_name}: {st}")
        return data.get("inputSettings", {}) or {}

    def get_input_window_id(self, input_name: str) -> int | None:
        settings = self.get_input_settings(input_name)
        wid = settings.get("window")
        return int(wid) if wid is not None else None

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

    def aux2_has_size(self) -> bool:
        ok, _, data = self.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return False
        for it in data.get("sceneItems", []):
            if it.get("sourceName") != INPUT_AUX2:
                continue
            t = it.get("sceneItemTransform") or {}
            w, h = float(t.get("width") or 0), float(t.get("height") or 0)
            return w > 10 and h > 10
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Bind Aux2 to Chrome window with given URL")
    ap.add_argument("--url", default=get_lower_left_url(), help="URL or page containing this (defaults to ontology lower-left feed)")
    ap.add_argument(
        "--window-id",
        type=int,
        metavar="N",
        help="Skip Quartz lookup; use this ID (from identify_window_click.py if bind leaves Aux2 0×0)",
    )
    ap.add_argument(
        "--try-all-chrome",
        action="store_true",
        help="Try every on-screen Chrome window ID until Aux2 gets non-zero size (no user click)",
    )
    ap.add_argument(
        "--open-new-window",
        action="store_true",
        help="NOT for normal use: opens new Chrome window (often not logged in); can bind wrong feed. Open tab yourself then run without this flag.",
    )
    ap.add_argument(
        "--wait-after-open",
        type=float,
        default=5.0,
        help="Seconds to wait after opening new window before reading window list (default 5)",
    )
    args = ap.parse_args()

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
        main_window_id = None
        try:
            main_window_id = cli.get_input_window_id(INPUT_MAIN)
        except Exception:
            pass

        if args.open_new_window:
            print(f"open_new_window url={args.url}", flush=True)
            try:
                window_id = open_and_resolve_new_window_id(args.url, args.wait_after_open, main_window_id)
            except Exception as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(f"window_id={window_id} (new authoritative URL window)", flush=True)
            cli.set_aux2_and_refresh(window_id)
            time.sleep(1.0)
            if not cli.aux2_has_size():
                print("error: Aux2 still 0×0 after new window bind", file=sys.stderr)
                return 1
        elif args.try_all_chrome:
            if args.window_id is not None:
                ids = [args.window_id]
            else:
                try:
                    find_chrome_window_id_for_url(args.url)  # bring URL window forward first
                except Exception:
                    pass
                ids = list_chrome_window_ids_min_size()
            print(f"try_all_chrome count={len(ids)}", flush=True)
            window_id = None
            for wid in ids:
                if main_window_id is not None and wid == main_window_id:
                    print(f"aux2_skip window_id={wid} duplicate_main", flush=True)
                    continue
                cli.set_aux2_and_refresh(wid)
                time.sleep(1.0)
                if cli.aux2_has_size():
                    window_id = wid
                    print(f"aux2_ok window_id={wid}", flush=True)
                    break
                print(f"aux2_skip window_id={wid}", flush=True)
            if window_id is None:
                print("error: no Chrome window id gave Aux2 non-zero size", file=sys.stderr)
                return 1
        else:
            try:
                if args.window_id is not None:
                    window_id = args.window_id
                    print(f"window_id={window_id} (from --window-id)", flush=True)
                else:
                    try:
                        fill_info = fill_chrome_window_for_url(args.url)
                        print(
                            f"filled_url_window bounds={fill_info['x']},{fill_info['y']},{fill_info['width']},{fill_info['height']}",
                            flush=True,
                        )
                        window_id = find_chrome_window_id_for_url(args.url)
                        print(f"window_id={window_id}", flush=True)
                    except Exception:
                        window_id = open_and_resolve_new_window_id(args.url, args.wait_after_open, main_window_id)
                        print(f"window_id={window_id} (opened authoritative URL window)", flush=True)
            except Exception as e:
                print(f"error finding window: {e}", file=sys.stderr)
                return 1
            if main_window_id is not None and window_id == main_window_id:
                print(
                    "error: lower-left candidate resolves to the same window as PiP Capture",
                    file=sys.stderr,
                )
                return 1
            for attempt in range(3):
                cli.set_aux2_and_refresh(window_id)
                time.sleep(0.8)
                if cli.aux2_has_size():
                    break
                if attempt < 2:
                    print(f"retry_set_aux2 attempt={attempt + 1} (Aux2 still 0x0)", flush=True)
            if not cli.aux2_has_size():
                if args.window_id is None:
                    try:
                        window_id = open_and_resolve_new_window_id(args.url, args.wait_after_open, main_window_id)
                    except Exception as e:
                        print(f"error: Aux2 still 0×0 and could not open authoritative URL window: {e}", file=sys.stderr)
                        return 1
                    if main_window_id is not None and window_id == main_window_id:
                        print("error: opened lower-left window duplicated main", file=sys.stderr)
                        return 1
                    cli.set_aux2_and_refresh(window_id)
                    time.sleep(1.0)
                    if cli.aux2_has_size():
                        print(f"window_id={window_id} (opened authoritative URL window after 0x0)", flush=True)
                    else:
                        print("error: Aux2 still 0×0 after opening authoritative URL window", file=sys.stderr)
                        return 1
                else:
                    print(
                        "error: Aux2 still 0×0 after retries on URL window only — not binding other windows",
                        file=sys.stderr,
                    )
                    return 1
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
