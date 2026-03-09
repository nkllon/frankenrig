# frankenrig

Automation-first OBS PiP rig for macOS using Hammerspoon + OBS WebSocket, with evidence-backed operating model and recovery runbooks.

## Start Here

- [Project README](../README.md)
- [Latest release](https://github.com/nkllon/frankenrig/releases/latest)
- [All releases](https://github.com/nkllon/frankenrig/releases)
- [Evidence package](../evidence/obs_pip_findings.md)
- [Ontology (TTL)](../evidence/obs_pip_findings.ttl)
- [SHACL constraints](../evidence/obs_pip_findings.shacl.ttl)
- [Verification prompt](../evidence/VERIFICATION_PROMPT_obs_window_identification.md)

## What This Project Provides

- Deterministic hotkey and script-driven OBS projector/capture control.
- Click-to-identify and click-to-rewire workflows for window-bound capture drift.
- Rebuild scripts for multi-source PiP layout (main + lower-left + lower-right + bottom-center).
- Evidence artifacts (API snapshots, screenshots, ontology, and validation prompts).

## Core Components

- `init.lua`: Hammerspoon hotkeys and orchestration.
- `obs_panel_control.py`: panel-level OBS control API wrapper.
- `rewire_obs_capture_by_click.py`: rebinds PiP capture to selected window.
- `obs_rebuild_pip_arrangement.py`: reconstructs multi-source layout from window IDs.

## Notes

This site is published from the repository `docs/` directory via GitHub Pages.
