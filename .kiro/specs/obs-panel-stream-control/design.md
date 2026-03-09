# Design: OBS Panel Stream Control

## Overview
**Purpose:** This feature provides deterministic control over the four-panel PiP scene so the operator can change channels on individual panels, temporarily turn panels off, and restart streaming on those panels without manual reconfiguration or layout drift.
**Users:** The primary user is the human operator running OBS and Chrome on this machine. Scripts will be invoked from the terminal, Hammerspoon, or future SDD-driven commands.
**Impact:** The design extends the existing OBS WebSocket control scripts (`obs_rebuild_pip_arrangement.py`, `rewire_obs_capture_by_click.py`, etc.) with higher-level panel operations that work in terms of “panels” and “channels” instead of raw window IDs.

### Goals
- Provide a single, consistent abstraction for panels (PiP Capture, Aux2, Aux3LR\_\*, Aux4Center\_\*) and their channels.
- Allow channel changes and on/off operations without changing panel geometry or breaking the PiP layout.
- Surface clear, script-friendly status for each operation (per panel success/failure with reasons).

### Non-Goals
- Redesigning the PiP layout or adding new panel positions.
- Managing Chrome window lifecycle or view assignment beyond what is required to change channels.
- Implementing a full UI; this design assumes CLI or automation entry points.

## Architecture

### High-Level Architecture
- **Panel Control Script Layer**: New Python (or Lua) scripts that expose operations:
  - `change_panel_channel(panel_id, channel_descriptor)`
  - `turn_off_panels(panel_ids)`
  - `start_panels(panel_ids)`
- **OBS WebSocket Adapter**: Uses the existing `.venv_obsws` environment and OBS WebSocket API to:
  - Map logical `panel_id` values to OBS input names and scene item IDs.
  - Enable/disable scene items and adjust input settings.
- **Channel Registry**: A small configuration file that maps human-friendly channel identifiers (e.g., `dw_live`, `bbc_live`) to concrete stream URLs or Chrome window selectors.

The scripts operate only through the OBS WebSocket API and existing PiP scene, preserving the “one canvas per display” constraint documented in the OBS PiP findings.

### Technology Alignment
- **Language/Runtime**: Reuse Python + `obs-websocket-py` stack already used by `obs_rebuild_pip_arrangement.py`.
- **Configuration**: Store panel→input mappings and channel registry in a simple JSON or TOML file under `.hammerspoon/obs_panel_control/`.
- **Invocation**: Design commands so they can be called from:
  - Direct CLI (`python obs_panel_control.py --change-channel ...`)
  - Hammerspoon keybindings
  - Future SDD `spec-impl` tasks.

### Key Design Decisions
- **Decision:** Represent panels as stable logical IDs (`main`, `aux_left`, `aux_right`, `aux_center`) that are resolved to OBS input names at runtime.
  - **Context:** Current scripts work directly with OBS input names and window IDs, which are brittle when inputs are recreated.
  - **Selected Approach:** Introduce a small panel registry that records the mapping from logical IDs to current input names/scene item IDs, refreshed from OBS when needed.
  - **Rationale:** Keeps operational scripts stable even as underlying inputs are regenerated (e.g., `Aux3LR_<timestamp>`).
  - **Trade-offs:** Requires a lightweight discovery step and some error handling when mappings go stale.

- **Decision:** Use explicit “turn off” / “start” operations that toggle scene item `enabled` flags rather than destroying and recreating inputs.
  - **Context:** Removing inputs in OBS is unreliable and can leave orphaned sources.
  - **Selected Approach:** Maintain inputs but disable their scene items to hide them and mute audio.
  - **Rationale:** Aligns with findings that `RemoveInput` can be flaky and avoids recreating geometry.
  - **Trade-offs:** Inputs for turned-off panels remain in OBS; needs periodic cleanup if unused.

## System Flows

### Change Channel on Panel
1. Operator invokes `change_panel_channel` with `panel_id` and `channel_id` or URL.
2. Script resolves `panel_id` to OBS input name and scene item via panel registry + OBS API.
3. Script resolves `channel_id` to underlying stream (URL or window binding).
4. Script updates the OBS input settings for that panel to bind to the new stream.
5. Script verifies that the scene item remains enabled and positioned correctly.
6. Script returns structured status per requirement (success/failure with diagnostics).

### Turn Off Selected Panels
1. Operator invokes `turn_off_panels` with a list of `panel_id` values.
2. For each panel:
   - Resolve to scene item ID.
   - Disable the scene item and ensure associated audio sources are muted.
3. Preserve channel metadata so that `start_panels` can restore it.
4. Return per-panel status summarizing which panels are now off.

### Start Streaming Selected Panels
1. Operator invokes `start_panels` with a list of `panel_id` values.
2. For each panel:
   - Resolve to scene item ID.
   - If previous channel is known, attempt to restore it.
   - If channel is unknown, request a new channel or apply a default as defined in configuration.
   - Enable the scene item and confirm it is visible in the PiP layout.
3. Return per-panel status including any panels that failed to start.

## Requirements Traceability
- Requirement 1 (Change channel on a panel) is primarily realized by `change_panel_channel` and the panel + channel registries.
- Requirement 2 (Turn off selected panels) is realized by `turn_off_panels` and scene item enable/mute handling.
- Requirement 3 (Start streaming selected panels) is realized by `start_panels`, using preserved channel configuration where available.

## Components and Interfaces

### Panel Registry Component
**Responsibility & Boundaries**
- Maintains mapping from logical `panel_id` values to OBS input names, scene item IDs, and last known channel.

**Dependencies**
- Reads from OBS WebSocket API (`GetSceneItemList`, `GetInputList`) to refresh mappings.
- Reads/writes a small JSON/TOML file to persist last-known channels.

### OBS Panel Control Script
**Responsibility & Boundaries**
- Implements CLI commands for:
  - Changing a panel channel.
  - Turning one or more panels off.
  - Starting one or more panels.
- Delegates all direct OBS API calls to a shared adapter module.

## Error Handling
- If OBS WebSocket is unreachable, commands abort with a clear error and suggested remediation (e.g., “ensure OBS is running and WebSocket is enabled”).
- If a panel ID cannot be resolved, the script reports that panel as failed and continues with others.
- All commands are designed to be idempotent when re-run with the same arguments.

## Testing Strategy
- Unit tests for panel registry resolution and channel lookup logic.
- Integration tests against a running OBS instance (or stub) for:
  - Successful channel change without geometry drift.
  - Turning panels off and back on while preserving configuration.
  - Handling invalid channels and missing panels gracefully.

