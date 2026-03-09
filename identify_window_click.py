#!/usr/bin/env python3
# Run with: /Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/identify_window_click.py
"""
Block until user clicks a window (or 7s timeout). Print window id, title, app.
Uses Quartz for window list. Prefers pynput for click; fallback: move cursor and press Enter.
"""
import sys
import select

try:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
except ImportError:
    print("error: need pyobjc: pip install pyobjc-framework-Quartz", file=sys.stderr)
    sys.exit(1)

try:
    from pynput import mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


def get_mouse_position():
    """Current mouse (x, y); Cocoa screen coords (origin bottom-left)."""
    try:
        from Quartz import CGEventCreate, CGEventGetLocation
        e = CGEventCreate(None)
        if e is None:
            return None
        loc = CGEventGetLocation(e)
        return (loc.x, loc.y) if loc else None
    except Exception:
        return None


def get_windows():
    """List of window dicts from Quartz (bounds, pid, kCGWindowNumber, kCGWindowName, etc.)."""
    opts = kCGWindowListOptionOnScreenOnly
    wins = CGWindowListCopyWindowInfo(opts, kCGNullWindowID)
    return wins if wins else []


def window_at_point(windows, x, y_quartz, app_only=True):
    """
    macOS Quartz: origin bottom-left. Bounds are (X, Y from bottom, Width, Height).
    List from CGWindowListCopyWindowInfo is front-to-back; return first (topmost) match.
    If app_only, skip system windows (Window Server, etc.) so we get the topmost app window.
    """
    for w in windows:
        if app_only and not _is_app_window(w):
            continue
        b = w.get("kCGWindowBounds")
        if b is None:
            continue
        try:
            wx, wy = b["X"], b["Y"]
            ww, wh = b["Width"], b["Height"]
        except (TypeError, KeyError):
            continue
        if wx <= x <= wx + ww and wy <= y_quartz <= wy + wh:
            return w
    return None


def _is_desktop(win):
    """Heuristic: Finder-owned window with no name is often the desktop."""
    return (
        win.get("kCGWindowOwnerName") == "Finder"
        and (win.get("kCGWindowName") or "") == ""
    )


# Skip system/UI windows; we want the topmost app window (e.g. OBS, Chrome).
_SKIP_OWNERS = frozenset({"Window Server", "Control Center", "SystemUIServer"})


def _is_app_window(win):
    return (win.get("kCGWindowOwnerName") or "") not in _SKIP_OWNERS


def main():
    timeout = 7.0
    # Try click-first (needs Accessibility for the process running this script)
    if HAS_PYNPUT:
        print("Click a window (or wait 7s to timeout)...", flush=True)
        result = [None]
        def on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.left:
                result[0] = (x, y)
                return False
        try:
            with mouse.Listener(on_click=on_click) as listener:
                listener.join(timeout=timeout)
        except Exception as e:
            if "not trusted" in str(e).lower() or "accessibility" in str(e).lower():
                result[0] = None
            else:
                raise
        if result[0] is not None:
            x, y = result[0]
            # pynput on macOS: use y as Quartz (bottom-left); if we get desktop, try flipped y.
            from Quartz import CGDisplayBounds, CGMainDisplayID
            h = CGDisplayBounds(CGMainDisplayID()).size.height
            windows = get_windows()
            win = window_at_point(windows, x, y)
            if not win or _is_desktop(win):
                win = window_at_point(windows, x, h - y)
            if win:
                wid = win.get("kCGWindowNumber", "")
                name = win.get("kCGWindowName") or ""
                owner = win.get("kCGWindowOwnerName") or "?"
                pid = win.get("kCGWindowOwnerPID", "")
                print(f"id={wid}  title={name!s}  app={owner}  pid={pid}")
            else:
                print("no_window_at_click")
            return
        print("(no click seen; try move cursor over window and press Enter)", flush=True)

    # Fallback: move cursor over window, press Enter (no Accessibility needed)
    print("Move cursor over the window, then press Enter (or wait 7s)...", flush=True)
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        print("timeout_7s")
        return
    sys.stdin.readline()
    pos = get_mouse_position()
    if pos is None:
        print("error: could not get mouse position")
        return
    x, y_quartz = pos

    windows = get_windows()
    win = window_at_point(windows, x, y_quartz)
    if win is None:
        print("no_window_at_click")
        return

    wid = win.get("kCGWindowNumber", "")
    name = win.get("kCGWindowName") or ""
    owner = win.get("kCGWindowOwnerName") or "?"
    pid = win.get("kCGWindowOwnerPID", "")
    print(f"id={wid}  title={name!s}  app={owner}  pid={pid}")


if __name__ == "__main__":
    main()
