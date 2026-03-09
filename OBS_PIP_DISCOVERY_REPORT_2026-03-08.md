# OBS + PiP Discovery Report
Date: 2026-03-08 09:16 MDT
Host: `zane.local` (macOS 26.3.1, Darwin 25.3.0)

## Scope
Ground-truth discovery of why OBS floating projector is black while Hammerspoon hotkeys are firing.

## Method
Collected evidence from:
- Installed app versions and running processes
- Hammerspoon config and active model file
- OBS scene collection JSON and current profile
- OBS runtime logs from current launch
- OBS menu inventory via AppleScript/OSA
- Permissions visibility checks (where allowed)

## Evidence (Observed, not inferred)

### 1) Automation layer is alive
- `Hammerspoon` process is running.
- User confirmed hotkey pulse appears.
- This means key binding path is active and callback executes.

### 2) OBS is running and window/projector control path is active
- OBS process is running (`OBS 32.0.4`).
- Front window title observed: `OBS 32.0.4 - Profile: Untitled - Scenes: Untitled`.
- Hotkey can toggle projector show/hide state (user confirmed pulse + hide behavior).

### 3) Black screen is caused by capture target failure in OBS source config
Direct evidence from current OBS log (`2026-03-08 09-16-49.txt`):
- `09:16:50.480: [ mac-screencapture ]: init_screen_stream: Invalid target window ID: 3310`

Direct evidence from current scene JSON (`basic/scenes/Untitled.json`):
- Source `id`: `screen_capture`
- Settings include:
  - `"application": "com.google.Chrome"`
  - `"type": 1`
  - `"window": 3310`

This is a stale/invalid window binding. OBS starts with a window capture target that no longer exists. A projector can still open, but it will project black if the source is invalid.

### 4) Screen capture permission is likely not the immediate blocker
Current OBS log contains:
- `[macOS] Permission for screen capture granted.`

So the primary failure in this run is not missing screen-recording grant; it is invalid capture target window ID.

### 5) OBS menus differ from assumptions used earlier
Actual top menus include:
- `File`, `Edit`, `View`, `Docks`, `Profile`, `Scene Collection`, `Tools`

Actual `Docks` menu has:
- `Scenes`, `Sources`, `Audio Mixer`, `Controls`, etc.

Actual `View` menu does **not** expose `Windowed Projector (Preview)` directly in this build/layout path; it includes `Open Multiview`, `Always On Top`, `Reset UI`, etc.

This explains prior menu-path brittleness.

## Blockers encountered during discovery
- Reading TCC database was denied by macOS:
  - `authorization denied` for `~/Library/Application Support/com.apple.TCC/TCC.db`
- This prevents direct SQL-level proof of accessibility/screen-capture grants from terminal context.

## Root cause statement
Primary root cause in current state:
- OBS source `macOS Screen Capture` is configured to an invalid Chrome window target (`window: 3310`, `type: 1`), producing black capture.

Secondary contributing factor:
- Menu automation assumptions were based on unstable/non-matching OBS menu paths.

## Deterministic fix plan (minimal, reliable)
1. In OBS, open source `macOS Screen Capture` properties.
2. Change mode from window-targeted binding to full display capture (or re-select a valid live window each launch).
3. If using display capture, crop in scene instead of relying on fixed window IDs.
4. Keep projector toggle automation; do not rely on deep menu click chains for source setup.

## Recommended automation contract going forward
- Hammerspoon controls only:
  - hotkeys
  - projector window show/hide
  - window snap/placement
- OBS scene/source configuration handled deterministically once (or via OBS API), not via brittle UI menu traversal.

## Files discovered/verified
- `~/.hammerspoon/init.lua`
- `~/.hammerspoon/OBS_PIP_RECOVERY_MODEL.md`
- `~/Library/Application Support/obs-studio/basic/scenes/Untitled.json`
- `~/Library/Application Support/obs-studio/logs/2026-03-08 09-16-49.txt`
- `~/Library/Application Support/obs-studio/global.ini`

## Conclusion
Your skepticism is correct: prior guidance mixed assumptions with reality. On this machine, the black projector is explained by an invalid OBS source window target (`window id 3310`), not by hotkey failure.
