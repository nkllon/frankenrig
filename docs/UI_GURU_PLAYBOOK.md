# UI Guru Playbook (OBS PiP)

This is the practical system for evolving the PiP layout without regressions.

## Core Model

- **Authority:** `evidence/obs_pip_findings.ttl`
- **Constraints:** `evidence/obs_pip_findings.shacl.ttl`
- **Compiler/runtime:** `obs_pip_ontology.py`, `obs_sync_pip_ontology.py`, `obs_apply_pip_layout.py`
- **Strategy:** `rule_of_thirds` (current default)

## Design Knobs (safe to tune)

- `LAYOUT_STRATEGY` - composition policy (`rule_of_thirds`, optional `golden_ratio`)
- `SMALL_THIRD_OCCUPANCY` - visual prominence of small panels
- `SMALL_TOP_Y` - vertical row placement
- `SMALL_FIT_MODE` - image fitting behavior (`cover`, `contain`, `stretch`)

## Deterministic Workflow

1. Change only model-level constants/strategy in `obs_pip_ontology.py`.
2. Run: `.venv_obsws/bin/python3 obs_sync_pip_ontology.py`
3. Run: `.venv_obsws/bin/python3 obs_apply_pip_layout.py --no-preview`
4. Confirm:
   - `RDFLIB_PARSE_OK`
   - `shacl_conforms=True`
5. Open visual evidence:
   - `evidence/obs_pip_verify.png`
   - latest `evidence/proof/<timestamp>/`

## Non-Negotiables

- Keep all three small panels on one anchor model and one row rule.
- Keep `main` distinct from `lowerLeft` binding.
- Never hand-edit ontology geometry in scattered JSON files.
- If feedback is visual ("too small", "misaligned"), update one knob and re-run the full pipeline.

## What "serious" means

- You have a repeatable layout engine, not ad-hoc tweaks.
- Every change is model-backed, validated, and evidenced.
- Visual quality decisions become explicit parameters instead of hidden side effects.
