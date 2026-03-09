# OBS cleanup after aux projector experiment

## What you have now (observed via API)

- **Inputs:** `PiP Capture` (good), `Aux Capture` (leftover).
- **PiP scene:** Only one scene item — `PiP Capture`. `Aux Capture` is not in the scene.
- **Projector windows:** OBS has opened several (e.g. two preview projectors + one source projector for Aux). The WebSocket API has **no request to close projector windows**; they must be closed manually.

`RemoveInput` for `Aux Capture` returns success but the input can still appear in `GetInputList` (e.g. while a projector is showing that source). So cleanup order matters.

## Manual steps (do these first)

1. **Close every extra OBS projector window**  
   Use **Cmd+W** or the window’s close button until only **one** preview window remains (the one that shows your live PiP).

2. **Optional:** If anything still looks wrong, quit OBS and reopen it. You should then have: one scene “PiP”, one input “PiP Capture”, one preview projector.

## After you’ve closed the extra projectors

Run the cleanup script so it can remove the `Aux Capture` input (with no projector using it, removal should stick):

```bash
/Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/obs_cleanup_remove_aux.py
```

Then confirm in OBS: **Settings → hotkeys** or the **Sources** list that only **PiP Capture** remains.

## Why the mess happened

- **Multiple preview projectors:** The script called `OpenVideoMixProjector` (preview) more than once; each call can create another preview window.
- **Aux source projector:** `OpenSourceProjector` for “Aux Capture” opened a separate window. That source was left in place and (on your system) showed a static image.
- **No close API:** There is no WebSocket “close projector” or “destroy output” for these windows, so they stay until you close them or quit OBS.

## Last known good (target state)

- One input: **PiP Capture** (window capture, your chosen window).
- One scene: **PiP**, with that one source.
- One preview projector window (or none, if you prefer to open it from the OBS menu when needed).
