# Verification prompt: OBS window-identification and rewire mitigation

Give this prompt to the **other agent** (or a fresh session) to verify the ontology and implementation.

---

## Instructions for the verifying agent

Please check the following and report back with **confirmations** or **discrepancies**.

### 1. Ontology (TTL)

- Open **`/Users/lou/.hammerspoon/evidence/obs_pip_findings.ttl`**.
- Confirm that:
  - **`obs:Act_IdentifyWindowByClick`** exists as an `obs:Action` with a label and note describing the click-to-identify-window flow and use of the output ID for OBS; **`obs:hasEvidence obs:Ev_IdentifyWindowScript`**.
  - **`obs:Act_RewireCaptureByClick`** exists as an `obs:Action` with a label and note describing: get window ID (identify script or `--window-id`), SetInputSettings for PiP Capture (type=1, window=id), set program scene to PiP, enable scene item, open preview projector; **`obs:hasEvidence obs:Ev_RewireScript`**.
  - **`obs:Ev_IdentifyWindowScript`** has **`obs:artifactPath`** `/Users/lou/.hammerspoon/identify_window_click.py` and a note (7s timeout, Accessibility/Enter fallback; may mention historical verification IDs—window IDs drift).
  - **`obs:Ev_RewireScript`** has **`obs:artifactPath`** `/Users/lou/.hammerspoon/rewire_obs_capture_by_click.py` and a note (optional `--window-id`, `--dry-run`, OBS websocket rebind).
  - **`obs:Issue_WindowBindingRisk`** has **`obs:mitigatedBy obs:Act_IdentifyWindowByClick, obs:Act_RewireCaptureByClick`** (both).
  - **`obs:State_Current`** is a rolling state (note/lastVerifiedAt; no single observedAt); includes **`obs:Act_IdentifyWindowByClick`** and **`obs:Act_RewireCaptureByClick`** in **`obs:hasAction`**; has **`obs:hasEvidence obs:Ev_ApiDiscovery_ReviewNow`**.
  - **`obs:Input_PiPCapture_Current`** has **`obs:windowId`** equal to the PiP Capture `window` value in **`obs_api_discovery_review_now.json`** `inputs_with_settings` (current authoritative evidence; ID may change after re-binds).

### 2. Narrative (MD)

- Open **`/Users/lou/.hammerspoon/evidence/obs_pip_findings.md`**.
- Confirm that:
  - **"Window-identification mitigation (2026-03-08)"** states risk is remediable by click-identify; script path, run command, output format; verification framed as historical (current window ID in Ev_ApiDiscovery_ReviewNow); aligns with Act_IdentifyWindowByClick and mitigatedBy.
  - **"Rewire capture by click (draft, 2026-03-08)"** describes the rewire script path, behavior (get ID → SetInputSettings → set scene → enable item → open projector), and run commands (dry-run with `--window-id` set to **current** ID from obs_api_discovery_review_now.json, interactive without args); ontology refs Act_RewireCaptureByClick, Ev_RewireScript, and Issue_WindowBindingRisk mitigatedBy both actions.

### 3. Identify script

- **`/Users/lou/.hammerspoon/identify_window_click.py`**: 7s timeout; click path + Enter fallback; filters system windows; coordinate handling (y / height-y for desktop); output `id=N title= app= pid=`.

### 4. Rewire script

- **`/Users/lou/.hammerspoon/rewire_obs_capture_by_click.py`**: exists; gets window ID via identify script or `--window-id`; calls OBS API (SetInputSettings for PiP Capture with type=1, window=id; SetCurrentProgramScene PiP; SetSceneItemEnabled; OpenVideoMixProjector preview); supports `--dry-run`.

### 5. Consistency (rolling state)

- **Current window ID** for PiP Capture is taken from **obs_api_discovery_review_now.json** (`inputs_with_settings` → PiP Capture `window`). **`obs:Input_PiPCapture_Current`** `obs:windowId` matches that file. Narrative dry-run example uses the same current ID (not a hard-coded historical value). After re-binds, update the evidence file and ontology or narrative so they stay aligned.

Report: list what you **confirmed** and any **discrepancies**. If you can run the scripts, note whether they run and whether output/behavior matches the docs.
