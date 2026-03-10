#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from obs_pip_ontology import (
    EVIDENCE_DIR,
    ONTOLOGY_PATH,
    SHACL_PATH,
    export_derived_json_files,
    load_graph,
    load_shapes_graph,
    save_graph,
    save_shapes_graph,
    sync_authoritative_ontology,
    update_latest_proof_bundle,
    validate_graphs,
    build_shapes_graph,
)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Sync OBS PiP ontology + SHACL authority and derived JSON exports")
    ap.add_argument("--skip-exports", action="store_true", help="Do not regenerate derived JSON exports")
    ap.add_argument(
        "--validation-report",
        type=Path,
        default=EVIDENCE_DIR / "obs_pip_validation_latest.json",
        help="Where to write validation report JSON",
    )
    args = ap.parse_args()

    graph = sync_authoritative_ontology()
    save_graph(graph, ONTOLOGY_PATH)

    # Re-parse immediately to ensure syntax validity from disk serialization.
    reparsed = load_graph(ONTOLOGY_PATH)
    print("RDFLIB_PARSE_OK")

    shapes_graph = build_shapes_graph()
    save_shapes_graph(shapes_graph, SHACL_PATH)
    shapes_graph = load_shapes_graph(SHACL_PATH)

    if not args.skip_exports:
        export_derived_json_files(reparsed)

    validation = validate_graphs(reparsed, shapes_graph)
    report_path = args.validation_report.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

    update_latest_proof_bundle(
        reparsed,
        screenshot_path=EVIDENCE_DIR / "obs_pip_verify.png",
        scene_state_path=EVIDENCE_DIR / "obs_pip_scene_state_after_apply.json",
        input_settings_path=EVIDENCE_DIR / "obs_pip_input_settings_latest.json",
        rectangles_path=EVIDENCE_DIR / "obs_pip_rectangles_latest.json",
        validation_path=report_path,
        validation=validation,
    )
    save_graph(reparsed, ONTOLOGY_PATH)
    reparsed = load_graph(ONTOLOGY_PATH)
    print("RDFLIB_PARSE_OK")

    validation = validate_graphs(reparsed, shapes_graph)
    report_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(f"shacl_conforms={validation['shacl_conforms']}")
    print(f"validation_report={report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("RDFLIB_PARSE_FAIL", file=sys.stderr)
        print(f"error={exc}", file=sys.stderr)
        raise
