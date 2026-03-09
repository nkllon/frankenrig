# frankenrig

Hammerspoon + OBS PiP automation: config and scripts for projector/capture control, with evidence and ontology documenting the current stable state.

## Before you use or change anything

**Have your trusted LLM evaluate this repo.** The layout, scripts, and evidence are designed to work together; the “build” is implicit (Hammerspoon loads `init.lua`, Python scripts use `.venv_obsws`, OBS must be running with obs-websocket). Constraints and design decisions are documented in the ontology, runbooks, and evidence—not in a traditional build system.

**Don’t modify this setup unless you know what you’re doing.** It’s a Frankenrig: multiple connection paths, environment-dependent behavior, and window-ID drift. Changing scripts or config without understanding the documented state and recovery procedures can break the whole thing.

## What’s here

- **init.lua** — Hammerspoon entry point (hotkeys, OBS triggers).
- **Scripts** — Python (identify/rewire capture, rebuild PiP, discover, open projector) and shell (Chrome URL capture, channel switching). Run from repo root; Python uses `.venv_obsws`.
- **evidence/** — Ontology (TTL/SHACL), narrative runbooks, API discovery snapshots, scene geometry, verification prompts, screenshots. Authoritative current state: `evidence/obs_api_discovery_review_now.json`.
- **Runbooks** — `evidence/obs_pip_findings.md`, `OBS_PIP_DISCOVERY_REPORT_2026-03-08.md`, `OBS_PIP_RECOVERY_MODEL.md` describe structure, recovery, and “reconstruct from scratch.”

## Quick orientation

- Current window IDs and input list: **evidence/obs_api_discovery_review_now.json** (drifts after rebinds).
- How things work and how to recover: **evidence/obs_pip_findings.md**.
- Rewire PiP capture to a new window: `./.venv_obsws/bin/python3 rewire_obs_capture_by_click.py` (or with `--window-id N` from review_now).

## 1Password / credentials

This repo does not store secrets. For full instructions on using 1Password (e.g. `op` CLI, `get_creds`, agent guardrails), see the **Eudorus** repository. Deployments on this machine: **`/Volumes/lemon/cursor/eudorus`** or **`/Volumes/lemon/codex/eudorus`** (or under `/Volumes/lemon/gemini/eudorus`). Key docs: `.kiro/steering/credentials.md`, `AGENTS.md` (1Password access guardrails).
