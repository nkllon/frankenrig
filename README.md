# frankenrig

[![GitHub Pages](https://img.shields.io/badge/Live%20Docs-GitHub%20Pages-1f883d?logo=github)](https://nkllon.github.io/frankenrig/)

**Live site:** [https://nkllon.github.io/frankenrig/](https://nkllon.github.io/frankenrig/)

Hammerspoon + OBS PiP automation: config and scripts for projector/capture control, with evidence and ontology documenting the current stable state.

## Demo

Short clip of the rig running in context (OBS with all panels + control surface in the upper-right):

![OBS PiP frankenrig demo](obs_clip.gif)

## What’s here

- **init.lua** — Hammerspoon entry point (hotkeys, OBS triggers).
- **OBS control scripts** — Python helpers for identify/rewire capture, rebuild PiP, and panel-level control (`obs_panel_control.py`).
- **evidence/** — Ontology (TTL/SHACL), narrative runbooks, API discovery snapshots, scene geometry, verification prompts, screenshots. Authoritative current state/model: `evidence/obs_pip_findings.ttl` + `evidence/obs_pip_findings.shacl.ttl`. JSON files under `evidence/` are derived exports or raw OBS telemetry.
