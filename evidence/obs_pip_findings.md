# OBS PiP Findings Narrative

Date: 2026-03-08

## Purpose
Capture the verified OBS/Projector/PiP findings from this debugging session as machine-readable ontology + SHACL, with a human-readable interpretation of what is stable now and what still carries risk.

## What We Actually Observed
- OBS API is available and usable through `obs-websocket` on port `4455`.
- A known-good operator state was reached and user-verified (`"youtube in a projector yay"`).
- Hotkey behavior and projector behavior were previously noisy because multiple projector windows accumulated.
- Duplicate projector windows were reduced to a singleton.
- `VM Window` input was removed because it was unused and confusing.
- The remaining source was renamed from `macOS Screen Capture` to `PiP Capture`.

## Current Live State (from API discovery)
- OBS version: `32.0.4`
- RPC version: `1`
- Program scene: `PiP`
- Canvas: 3840×2254 (base resolution from GetVideoSettings)
- **Intended inputs (in PiP scene):** `PiP Capture` (main), `Aux2` (lower-left), `Aux3LR_<timestamp>` (lower-right), `Aux4Center_<timestamp>` (bottom center)
- **Full input inventory:** OBS may also list orphan/stuck inputs not in the scene (e.g. `Aux3`, `Aux3 Capture`, `Aux3LR`). For current window IDs and full input list use **obs_api_discovery_review_now.json** (see Evidence Artifacts).
- Scene items in `PiP`: `PiP Capture` (full-size), `Aux2` (lower-left, scale ~0.25), third (lower-right, same scale, alignment 8), fourth (bottom center, same scale, alignment 36)
- Capture method: window-bound (`type=1`) for all
- Lower-right geometry (verified): position from canvas with insets X=540, Y=125; alignment 8 (bottom-right corner); scale same as Aux2 (~0.25). See `obs_pip_scene_geometry.json`.
- Fourth (bottom center): positionX = canvas width/2, positionY scaled with canvas; alignment 36 (center horizontal | center vertical) so the *center* of the source is at that position.

## Interpretation
The configuration is operational and currently stable from user perspective.  
However, technically it still uses a window-bound capture target, which can drift when window IDs change.

This is why the ontology records both:
- `Current known-good operational state`
- `Window-binding risk` as a still-present issue

## Actions Completed
- Enabled WebSocket control for deterministic API operations.
- Removed unused input `VM Window`.
- Renamed active source to `PiP Capture`.
- Reduced projector-window sprawl to one active projector.
- Simplified hotkeys to main + fallback OBS toggle and browser PiP toggle.

## Evidence Artifacts
- **Authoritative for current state (window IDs, full input list, scene items):** `obs_api_discovery_review_now.json` — use for operational checks and to keep ontology aligned with live OBS.
- API before cleanup: `/Users/lou/.hammerspoon/evidence/obs_api_discovery.json`
- API after VM input removal: `/Users/lou/.hammerspoon/evidence/obs_api_discovery_after_vm_remove.json`
- API rename verification: `/Users/lou/.hammerspoon/evidence/obs_api_discovery_rename_check.json`
- API current runtime snapshot: `/Users/lou/.hammerspoon/evidence/obs_api_discovery_current.json`
- API after rewire success: `/Users/lou/.hammerspoon/evidence/obs_api_after_rewire_success.json`
- Window inventory before/after: `obs_windows_before.txt`, `obs_windows_after.txt`
- Screenshot before/after: `obs_before.png`, `obs_after.png`
- PiP screenshots: `obs_pip_current.png`, `obs_pip_screenshot_before.png`, `obs_pip_screenshot_after.png`
- Cleanup narrative: `obs_cleanup_after_aux.md`
- Scripts: `identify_window_click.py`, `rewire_obs_capture_by_click.py`, `open_aux_projector_by_click.py`, `obs_rebuild_pip_arrangement.py`
- Scene geometry snapshot: `obs_pip_scene_geometry.json` (canvas size, position/scale/alignment per source for PiP scene)
- Source URLs: `capture_chrome_window_urls.sh` (list Chrome windows’ active tab URL/title); optional `evidence/obs_pip_source_urls.json` and `evidence/obs_pip_source_urls.txt` (captured URLs for the four views)

## Ontology/SHACL Files
- Ontology TTL: `/Users/lou/.hammerspoon/evidence/obs_pip_findings.ttl`
- SHACL: `/Users/lou/.hammerspoon/evidence/obs_pip_findings.shacl.ttl`

## State_Current semantics (ontology)
- **State_Current** is a **rolling** “latest known-good” node, not a point-in-time snapshot. It aggregates structure (four intended sources, scene, actions, evidence) and is updated when evidence is refreshed (e.g. after rewire or when aligning to `obs_api_discovery_review_now.json`).
- **Time:** No single `observedAt`; use **lastVerifiedAt** for when the rolling state was last aligned to evidence. For historical snapshots use **State_PreCleanup** or timestamped evidence artifacts.
- **Window IDs:** Stored values (e.g. PiP Capture `windowId`) are taken from the authoritative review evidence; they will drift. Re-check `obs_api_discovery_review_now.json` or run GetInputSettings when doing operational binding.
- **Orphan inputs:** **OrphanInputs_ReviewNow** records inputs that exist in OBS (GetInputList) but are not in the PiP scene (e.g. `Aux3`, `Aux3 Capture`, `Aux3LR`). The ontology no longer under-reports inventory; see `hasOrphanInputs` on State_Current.

## Window-identification mitigation (2026-03-08)
The **window-binding risk** (capture target ID can drift) is **remediable**: the correct window for OBS can be identified with certainty by click.

- **Script:** `/Users/lou/.hammerspoon/identify_window_click.py`
- **Run:** `./.venv_obsws/bin/python3 identify_window_click.py` (from `.hammerspoon`). Click the target window within 7s (or move cursor over it and press Enter).
- **Output:** `id=N title= app= pid=` — use `N` to configure or re-bind OBS window capture.
- **Verified (historical):** Script correctly identified OBS projector window (id=19325) and the Chrome window used as PiP capture target (id=14767 at time of that run). Current window ID is in **Ev_ApiDiscovery_ReviewNow** (obs_api_discovery_review_now.json); ontology aligns to that evidence and will drift as re-binds occur.

The ontology records this as `Act_IdentifyWindowByClick`; `Issue_WindowBindingRisk` is `mitigatedBy` that action (re-binding possible when drift occurs).

## Rewire capture by click (draft, 2026-03-08)
A **rewire** script runs the identify flow and applies the window ID to OBS in one step.

- **Script:** `/Users/lou/.hammerspoon/rewire_obs_capture_by_click.py`
- **Behavior:** (1) Get target window ID (interactive click via `identify_window_click.py`, or `--window-id N`). (2) Call OBS API: set `PiP Capture` input settings to `type=1`, `window=<id>`. (3) Set program scene to `PiP`. (4) Ensure scene item is enabled. (5) Open preview projector.
- **Run commands:**
  - Dry run with explicit ID: **read current PiP Capture `window` from obs_api_discovery_review_now.json** (`inputs_with_settings` → PiP Capture → `window`) first; the value drifts on each rebind. Example (ID is example-only, replace with current):  
    `/Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/rewire_obs_capture_by_click.py --window-id 21552 --dry-run`
  - Interactive click flow:  
    `/Users/lou/.hammerspoon/.venv_obsws/bin/python3 /Users/lou/.hammerspoon/rewire_obs_capture_by_click.py`

Ontology: `Act_RewireCaptureByClick`, `Ev_RewireScript`; `Issue_WindowBindingRisk` is `mitigatedBy` both `Act_IdentifyWindowByClick` and `Act_RewireCaptureByClick`.

## Verification: post-restart rewire (2026-03-08)
After restarting OBS and Chrome (window IDs changed), the rewire script was run in interactive mode; user clicked the desired capture window. Script reported `target_window_id=19763` and `status=ok`. OBS API snapshot taken immediately after confirms: **PiP Capture** `inputSettings` = `type=1`, `window=19763`; program scene = **PiP**; scene item **PiP Capture** enabled. User confirmed the experiment a success.

- **Evidence:** `/Users/lou/.hammerspoon/evidence/obs_api_after_rewire_success.json`
- **Ontology:** `Ev_AfterRewireSuccess`; `State_Current` includes it in `hasEvidence`.

## One canvas per display (2026-03-08)
On a single display there is **one canvas** to work with: one scene (e.g. PiP) whose composition is shown by one preview projector. All sources (PiP Capture, Aux2) live on that same scene; you arrange them there. **OpenSourceProjector** can open a window that shows a single source, but the WebSocket API does not provide window position/size for that projector, so a second projector opened in windowed mode **overlays** the first. Using **monitorIndex** opens the projector on another monitor, not a second window on the same display. So the intended workflow: one scene, two (or more) sources on it, one preview projector; arrange sources with **SetSceneItemTransform**.

## Second source (Aux2)
The second window capture is the input **Aux2** on the same PiP scene. Set it via **open_aux_projector_by_click.py** (click or `--window-id`); the script only updates the input, it does **not** open that source’s projector (to avoid overlay). Layout: lower-left on canvas (positionX 20, positionY 1561, scale ~0.25), applied with **SetSceneItemTransform**. **SetSceneItemTransform** rejects `boundsWidth`/`boundsHeight` of 0; use at least 1 when `boundsType` is `OBS_BOUNDS_NONE`.

## Rebuild from scratch
**obs_rebuild_pip_arrangement.py** reconstructs the working arrangement. Modes:
- **Two windows:** `--window1 ID1 --window2 ID2` (or two clicks): PiP Capture, Aux2; layout main + lower-left; opens preview projector.
- **Third window (lower-right):** `--lower-right` (or `--lower-right --window3 ID`): creates a **new** input with a **unique name** `Aux3LR_<timestamp>`, adds it to the PiP scene, positions it lower-right (insets X=540, Y=125 from canvas, alignment 8), moves it on top. No click: use `--window3 23187` (or current window ID).
- **Fourth window (bottom center):** `--add-fourth-center --window4 ID`: creates input `Aux4Center_<timestamp>`, positions it **between** the two bottom PiPs (center X, same Y/scale), alignment 36 (center of source at position). Requires `--window4` with the window ID.
- **Fix position only:** `--fix-aux3`: re-applies lower-right transform to whichever scene item name starts with `Aux3LR`. `--fix-aux4`: re-applies bottom-center transform (alignment 36) to whichever scene item name starts with `Aux4Center`. Use after adding a source manually or to re-apply layout.
- **Diagnose:** `--diagnose`: prints canvas size, PiP scene items (name, id, index, enabled, position, scale), and any input whose name starts with `Aux3LR` or `Aux4Center`.

Third and fourth sources use unique names because **RemoveInput** often reports success but does not actually remove the input (it stays in use); **CreateInput** with an existing name then fails (601). **CreateSceneItem** for an existing-but-orphaned input fails with 700. So we always create with `Aux3LR_<timestamp>` or `Aux4Center_<timestamp>` so CreateInput succeeds and the source is added to the scene in one step; we use the returned `sceneItemId`.

## Third source (lower-right)
- **Name pattern:** `Aux3LR_<timestamp>` so each run gets a new input; CreateInput always succeeds and adds the source to the PiP scene (returns `sceneItemId`).
- **Layout:** Alignment 8 (bottom-right); position = (canvasWidth - 540, canvasHeight - 125); same scale as Aux2 (~0.25). Script constants: `PIP_RIGHT_INSET_X = 540`, `PIP_RIGHT_INSET_Y = 125`.
- **Lookup:** `--fix-aux3` finds the scene item by prefix `Aux3LR` (any name starting with that).

## Fourth source (bottom center)
- **Name pattern:** `Aux4Center_<timestamp>` so each run gets a new input; same unique-naming rationale as Aux3LR.
- **Layout:** Alignment **36** (OBS_ALIGN_CENTER_HORIZONTAL | OBS_ALIGN_CENTER_VERTICAL) so the **center** of the source is at the position (not the left edge). positionX = canvas width/2; positionY = same scaled Y as other small PiPs (REF_PIP_POS_Y * canvasHeight/REF_CANVAS_HEIGHT); same scale as Aux2 (~0.25).
- **Lookup:** `--fix-aux4` finds the scene item by prefix `Aux4Center`. Use after alignment or position tweaks.

## API findings
- **OpenSourceProjector**: `monitorIndex` -1 = windowed (OS places window, typically on top); `monitorIndex` N = fullscreen on monitor N (GetMonitorList). No same-display position control.
- **SetSceneItemTransform**: `boundsWidth` and `boundsHeight` must be >= 1; request fails with code 402 if sent as 0.
- **CreateInput** / **RemoveInput**: RemoveInput can report success while the input remains (e.g. still in use); CreateInput with that name then fails 601. CreateSceneItem for an existing input not in the scene can fail 700. Workaround: use a unique name per create (e.g. Aux3LR_&lt;timestamp&gt;).
- **Response matching:** When sending requests, read responses until `requestId` matches the sent request (events may be interleaved).

## Underlying window sources (URLs and views)
The four OBS sources are all **Chrome** windows showing specific streams. Two are stable live-news URLs; one is a YouTube video from a contributor; one is Deutsche Welle Live.

- **Window 1 (main, PiP Capture):** YouTube video from contributor **bootybunt**. Exact URL can vary (specific video). Capture from the running window (see below) or set manually.
- **Window 2 (lower-left, Aux2):** **Deutsche Welle Live** (YouTube). URL: [https://www.youtube.com/user/deutschewelleenglish/live](https://www.youtube.com/user/deutschewelleenglish/live)
- **Window 3 (lower-right, Aux3LR_*):** **French news** live (e.g. France 24 English). Stable entry points:
  - France 24 English: [https://www.youtube.com/c/FRANCE24English/streams](https://www.youtube.com/c/FRANCE24English/streams) or [https://www.youtube.com/c/FRANCE24English/live](https://www.youtube.com/c/FRANCE24English/live)
  - Current live example: `https://www.youtube.com/live/h3MuIUNCCzI`
- **Window 4 (bottom center, Aux4Center_*):** **BBC News Live**. Use BBC website (e.g. [http://www.bbc.co.uk/iplayer/live/bbcnews](http://www.bbc.co.uk/iplayer/live/bbcnews) or [BBC watch-live news](https://www.bbc.com/watch-live-news/)); center feed is no longer YouTube.

**How they are instantiated on this machine:** Four full-screen **Chrome** windows in separate **views** (virtual desktops). User switches with **Control-Left** / **Control-Right**. View 1 = main (e.g. bootybunt), View 2 = Deutsche Welle, View 3 = French news, View 4 = BBC News. Each view has one full-screen window; OBS captures that window by ID.

**Capturing the exact URLs:** All four are Chrome, so run `./capture_chrome_window_urls.sh` from `.hammerspoon` (or `capture_chrome_window_urls.sh evidence/obs_pip_source_urls.txt` to save). Script uses AppleScript to list every Chrome window’s active tab URL and title. Switch to each view in order (1–4) and run once, or run per view and record which URL is in which view. Save the output to `evidence/obs_pip_source_urls.txt` and optionally add the four URLs to `evidence/obs_pip_source_urls.json` (see below) for reconstruction.

## Reconstruct arrangement from scratch (from URLs)
1. **Open the four URLs** in Chrome, each in its own full-screen window in the correct view:
   - View 1 (main): bootybunt YouTube video (or your chosen main source URL).
   - View 2: Al Jazeera English live (e.g. [https://www.youtube.com/@aljazeeraenglish/streams](https://www.youtube.com/@aljazeeraenglish/streams) then start the live stream).
   - View 3: French news live (e.g. [https://www.youtube.com/c/FRANCE24English/live](https://www.youtube.com/c/FRANCE24English/live)).
   - View 4: Deutsche Welle Live ([https://www.youtube.com/user/deutschewelleenglish/live](https://www.youtube.com/user/deutschewelleenglish/live))—not 5hRGqR6a3s4 (that is Al Jazeera).
2. **Get window IDs** for those four windows. Either:
   - Run `obs_rebuild_pip_arrangement.py` with no args and **click** main, then lower-left; then add third via `--lower-right` and click lower-right; then add fourth via `--add-fourth-center --window4 ID` (get ID from `identify_window_click.py` on the fourth window); or
   - Run `identify_window_click.py` four times (switch to each view, run, click the window) and note the four IDs; then run  
     `obs_rebuild_pip_arrangement.py --window1 ID1 --window2 ID2 --window3 ID3` and separately  
     `obs_rebuild_pip_arrangement.py --add-fourth-center --window4 ID4`.
3. **Run the rebuild script** with those window IDs. It will set PiP Capture → window1, Aux2 → window2, create Aux3LR_<timestamp> → window3 (lower-right), create Aux4Center_<timestamp> → window4 (bottom center), apply layout (main full, Aux2 lower-left, third lower-right with insets 540/125, fourth bottom center with alignment 36), and open the preview projector.

So **reconstruction from scratch** = open the four URLs in the four views → obtain four window IDs (by click or identify script) → run rebuild with `--window1`, `--window2`, `--window3`, and `--add-fourth-center --window4 ID4`.

## Limitations (observed)
- **VM windows**: Capturing windows from a VM is unreliable; the VM often does not update off-screen content, so OBS sees nothing or a static frame.
- **YouTube / YouTube TV**: DRM and platform behavior affect what can be captured and how.

## Ontology updates
- **State_Current**: Rolling aggregate (not a single-timestamp snapshot). **lastVerifiedAt** instead of single **observedAt**; **hasOrphanInputs** → OrphanInputs_ReviewNow; evidence includes **Ev_ApiDiscovery_ReviewNow** (authoritative for current window IDs and full input list). Four intended inputs (PiP Capture, Aux2, third/lower-right, fourth/bottom center); PiP Capture **windowId** set from review evidence (21552 in review_now; update when re-binding).
- **OrphanInputs_ReviewNow**: Inputs in GetInputList but not in PiP scene (Aux3, Aux3 Capture, Aux3LR); ontology no longer under-reports inventory.
- **Input_ThirdSource_Current** (Aux3LR_*), **Input_FourthSource_Current** (Aux4Center_*), **Act_AddThirdSourceLowerRight**, **Act_FixAux3**, **Act_AddFourthSourceCenter**, **Act_FixAux4**.
- **SourceUrlDiscovery**: documents underlying window sources (bootybunt YouTube, Al Jazeera English, French news, Deutsche Welle Live), four-view instantiation (Control-Left/Right), stable URLs, and reconstruct-from-URLs procedure.
- **Ev_SourceUrls**, **Ev_CaptureChromeUrlsScript**: evidence for canonical URLs (obs_pip_source_urls.json) and Chrome URL/title capture script (capture_chrome_window_urls.sh).
- **Ev_ApiDiscovery_ReviewNow**: Evidence artifact for obs_api_discovery_review_now.json; use for operational alignment of window IDs and input inventory.
- **Ev_RebuildScript** note extended for --lower-right, --fix-aux3, --add-fourth-center, --fix-aux4, --window4, unique naming, insets, alignment 36 for center.
- **Ev_PipCurrentScreenshot**, **Ev_PipScreenshotBefore**, **Ev_PipScreenshotAfter**, **Ev_CleanupAfterAux**: Evidence for obs_pip_current.png, obs_pip_screenshot_before.png, obs_pip_screenshot_after.png, obs_cleanup_after_aux.md; linked from State_Current.
- **Dry-run ID:** Narrative and rewire example mark window ID as example-only; always read current PiP Capture `window` from obs_api_discovery_review_now.json before running with `--window-id`.

## What Can Be Done Next
If desired, convert `PiP Capture` to display capture (`type=0`) to remove window-ID drift risk entirely.  
When drift occurs, run the rewire script or rebuild script (window IDs) to re-bind.  
To reproduce the layout: **obs_rebuild_pip_arrangement.py** with window IDs or clicks (two, three, or four). For the third (lower-right) source: `--lower-right` (and optionally `--window3 ID`); then `--fix-aux3` to re-apply position if needed. For the fourth (bottom center): `--add-fourth-center --window4 ID`; then `--fix-aux4` to re-apply center transform (e.g. after alignment fix).  
Geometry reference: **obs_pip_scene_geometry.json** for exact position/scale/alignment of all PiP sources.  
**Reconstruct from URLs:** Open the four source URLs in four full-screen Chrome windows (one per view, Control-Left/Right); capture window IDs (click or identify script); run **obs_rebuild_pip_arrangement.py** with `--window1 ID1 --window2 ID2 --window3 ID3` and **obs_rebuild_pip_arrangement.py --add-fourth-center --window4 ID4**. Capture exact URLs with **capture_chrome_window_urls.sh**; record in **evidence/obs_pip_source_urls.json** or **obs_pip_source_urls.txt**.
