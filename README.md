# frankenrig

Hammerspoon + OBS PiP automation: config and scripts for projector/capture control, with evidence and ontology documenting the current stable state.

## Demo

Short clip of the rig running in context (OBS with all panels + control surface in the upper-right):

<video src="obs_clip.mp4" controls loop muted playsinline style="max-width: 100%; height: auto;">
  Your browser does not support the video tag. You can download the clip from
  <a href="obs_clip.mp4">obs_clip.mp4</a>.
</video>

## What’s here

- **init.lua** — Hammerspoon entry point (hotkeys, OBS triggers).
- **OBS control scripts** — Python helpers for identify/rewire capture, rebuild PiP, and panel-level control (`obs_panel_control.py`).
- **evidence/** — Ontology (TTL/SHACL), narrative runbooks, API discovery snapshots, scene geometry, verification prompts, screenshots. Authoritative current state: `evidence/obs_api_discovery_review_now.json` and `evidence/obs_pip_findings.{md,ttl}`.

