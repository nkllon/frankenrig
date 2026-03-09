# OBS Floating PiP Recovery Model (Deterministic)

## Goal
Provide two concurrent video views on macOS:
- Native browser PiP for primary video
- OBS floating projector for secondary video (e.g., YouTube TV)

## Truth hierarchy
1. `Hotkey pulse shown` (Hammerspoon event fired)
2. `Projector window shown/hidden` (window management path works)
3. `OBS preview shows live pixels` (capture path works)
4. `Projector shows live pixels` (render path works)

If 1-2 are true but 3-4 are false, issue is capture/permission/DRM, not automation.

## State machine
- `S0_IDLE`: No action yet
- `S1_HOTKEY_OK`: Hammerspoon hotkey fires (`OBS float hotkey` pulse)
- `S2_PROJECTOR_OK`: Projector window exists and can toggle
- `S3_CAPTURE_OK`: OBS preview shows non-black live video
- `S4_FLOAT_OK`: Projector shows non-black live video
- `S_ERR_CAPTURE_BLACK`: Projector exists but content black

## Deterministic transitions
1. `S0 -> S1`
- Trigger: press `alt+cmd+o`
- Evidence: pulse appears

2. `S1 -> S2`
- Trigger: projector found or auto-created
- Evidence: pulse `OBS projector shown` or `OBS projector hidden`

3. `S2 -> S3`
- Required configuration (in OBS scene):
  - Source type: `macOS Screen Capture` (Display Capture), not Window Capture for DRM streams
  - Correct display selected
  - Source visible in scene
- Evidence: OBS main preview is live (not black)

4. `S3 -> S4`
- Trigger: open `Windowed Projector (Preview)` on same scene
- Evidence: projector shows same live preview

## Error policy
### `S_ERR_CAPTURE_BLACK`
Apply in order, stop at first success:
1. Ensure source is `macOS Screen Capture` (Display Capture)
2. Verify macOS Screen Recording permission for OBS
3. Restart OBS after permission changes
4. Disable Chrome hardware acceleration and relaunch Chrome
5. If still black only on YouTube TV, classify as DRM/protected path

## Operational controls
- `ctrl+alt+cmd+p`: native Chrome PiP toggle
- `alt+cmd+o`: OBS projector show/hide + snap
- `ctrl+alt+cmd+o`: same as above (secondary binding)

## Definition of done
- You can press `ctrl+alt+cmd+p` for primary PiP
- You can press `alt+cmd+o` to show floating OBS window
- Secondary stream remains visible and non-black for >30s
