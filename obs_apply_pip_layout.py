#!/usr/bin/env python3
"""
Apply PiP scene layout from the authoritative Turtle ontology.

No runtime discovery of layout authority; stack order, transforms, and slot intent
come from evidence/obs_pip_findings.ttl via obs_pip_ontology.py. Legacy JSON files
are regenerated as derived exports only.

After apply, always writes a screenshot and a paired proof bundle containing:
- screenshot
- scene-state dump
- input-settings dump
- computed rectangles
- ontology parse + SHACL validation report

The command exits non-zero if the screenshot or validation proof fails.
"""

import json
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Reuse WebSocket client and screenshot from existing module
from obs_rebuild_pip_arrangement import (
    INPUT_PIP_CENTER_PREFIX,
    INPUT_PIP_RIGHT_PREFIX,
    OBS_WS_URL,
    SCENE,
    ObsClient,
)
from obs_pip_ontology import (
    EVIDENCE_DIR,
    LAYOUT_JSON_PATH,
    ONTOLOGY_PATH,
    compute_rectangles_from_scene_items,
    export_derived_json_files,
    get_layout_payload,
    load_graph,
    load_shapes_graph,
    save_graph,
    update_latest_proof_bundle,
    update_observed_bindings,
    validate_graphs,
)

DEFAULT_SCREENSHOT = Path(__file__).resolve().parent / "evidence" / "obs_pip_verify.png"
DEFAULT_SCENE_DUMP = Path(__file__).resolve().parent / "evidence" / "obs_pip_scene_state_after_apply.json"
DEFAULT_INPUT_SETTINGS = Path(__file__).resolve().parent / "evidence" / "obs_pip_input_settings_latest.json"
DEFAULT_RECTANGLES = Path(__file__).resolve().parent / "evidence" / "obs_pip_rectangles_latest.json"
DEFAULT_VALIDATION = Path(__file__).resolve().parent / "evidence" / "obs_pip_validation_latest.json"


def resolve_scene_item_id(cli: ObsClient, entry: dict) -> tuple[int | None, str | None]:
    """Return (scene_item_id, source_name) or (None, None) if missing."""
    match = entry.get("match", "exact")
    source = entry["source"]
    if match == "exact":
        sid = cli.scene_item_id(source)
        return (sid, source if sid else None)
    if match == "prefix":
        sid = cli.scene_item_id_by_prefix(source)
        if sid is None:
            return (None, None)
        ok, _, data = cli.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            return (sid, None)
        for it in data.get("sceneItems", []):
            if (it.get("sourceName") or "").startswith(source):
                return (sid, it.get("sourceName"))
        return (sid, None)
    return (None, None)


def scale_transform_y(transform: dict, canvas_h: float, ref_h: float) -> dict:
    if canvas_h == ref_h:
        return dict(transform)
    sy = canvas_h / ref_h
    out = dict(transform)
    out["positionY"] = float(out["positionY"]) * sy
    if out.get("boundsType") == "OBS_BOUNDS_STRETCH" and "boundsHeight" in out:
        out["boundsHeight"] = float(out["boundsHeight"]) * sy
    return out


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def copy_to_bundle(src: Path, bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    dst = bundle_dir / src.name
    shutil.copy2(src, dst)
    return dst


def collect_input_settings(cli: ObsClient, stack_order: list[dict]) -> tuple[dict[str, dict], dict]:
    role_map = {"main": "main", "auxLeft": "lowerLeft", "auxRight": "lowerRight", "auxCenter": "center"}
    observed_bindings: dict[str, dict] = {}
    payload: dict[str, dict] = {"inputs": {}}
    for entry in stack_order:
        tid = entry["id"]
        role = role_map.get(tid)
        if role is None:
            continue
        _sid, src_name = resolve_scene_item_id(cli, entry)
        input_name = src_name or entry["source"]
        ok, _st, data = cli.req("GetInputSettings", {"inputName": input_name})
        if not ok:
            payload["inputs"][role] = {"inputName": input_name, "error": "GetInputSettings failed"}
            continue
        settings = data.get("inputSettings", {}) or {}
        payload["inputs"][role] = {"inputName": input_name, "inputSettings": settings}
        observed_bindings[role] = {
            "inputName": input_name,
            "windowId": settings.get("window"),
        }
    return observed_bindings, payload


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Apply PiP layout from authoritative ontology")
    ap.add_argument("--ontology", type=Path, default=ONTOLOGY_PATH, help="Authoritative ontology TTL")
    ap.add_argument("--screenshot", type=Path, default=DEFAULT_SCREENSHOT, help="Where to write screenshot after apply")
    ap.add_argument("--dump-state", type=Path, metavar="PATH", help="After apply, write GetSceneItemList JSON to PATH")
    ap.add_argument("--no-preview", action="store_true", help="Do not open screenshot in Preview after write")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ontology_path = args.ontology.expanduser().resolve()
    if not ontology_path.exists():
        print(f"error: ontology file not found: {ontology_path}", file=sys.stderr)
        return 1

    graph = load_graph(ontology_path)
    export_derived_json_files(graph)
    layout = get_layout_payload(graph)

    if layout.get("scene") != SCENE:
        print(f"error: layout scene must be {SCENE!r}", file=sys.stderr)
        return 1

    ref = layout.get("canvasRef") or {}
    ref_w = float(ref.get("width", 3840))
    ref_h = float(ref.get("height", 2254))
    stack_order = layout["stackOrder"]
    transforms = layout["transforms"]
    scale_y = layout.get("scaleYIfCanvasHeightDiffers", True)

    cli = ObsClient(OBS_WS_URL)
    try:
        cli.connect()
        cw, ch = cli.get_canvas_size()
        print(f"layout={LAYOUT_JSON_PATH.name} canvas={cw:.0f}x{ch:.0f}")

        if args.dry_run:
            print("dry-run: would set transforms and stack order from ontology")
            return 0

        # Collect (scene_item_id, transform_key) in stack order
        applied = []
        for i, entry in enumerate(stack_order):
            tid = entry["id"]
            if tid not in transforms:
                print(f"error: stackOrder entry id {tid!r} has no transforms block", file=sys.stderr)
                return 1
            sid, src_name = resolve_scene_item_id(cli, entry)
            if sid is None:
                print(f"warning: scene item not found for {entry} — skip", file=sys.stderr)
                continue
            t = dict(transforms[tid])
            if scale_y and ch != ref_h:
                t = scale_transform_y(t, ch, ref_h)
            cli.set_transform(sid, t)
            cli.req("SetSceneItemEnabled", {"sceneName": SCENE, "sceneItemId": sid, "sceneItemEnabled": True})
            applied.append((sid, src_name or entry["source"], i))

        # Optional: assign explicit indices (can put main on top of PiPs on some OBS builds)
        if layout.get("assignSceneItemIndices", True):
            for sid, _name, index in applied:
                ok, st, _ = cli.req(
                    "SetSceneItemIndex",
                    {"sceneName": SCENE, "sceneItemId": sid, "sceneItemIndex": index},
                )
                if not ok:
                    print(f"error: SetSceneItemIndex {index}: {st.get('comment', st)}", file=sys.stderr)
                    return 1
        else:
            # Push main to back only, then PiPs on top (no full renumber)
            id_main = cli.scene_item_id("PiP Capture")
            if id_main is not None:
                try:
                    cli.move_scene_item_to_bottom(id_main)
                except Exception:
                    pass

        # Main full-screen layer must stay back; explicit move-to-top for each PiP so Aux2
        # is not covered after SetSceneItemIndex (same as obs_bind_aux2_by_url.py after rebind).
        for entry in stack_order[1:]:
            sid, _ = resolve_scene_item_id(cli, entry)
            if sid is not None:
                cli.move_scene_item_to_top(sid)

        cli.req("SetCurrentProgramScene", {"sceneName": SCENE})

        shot = args.screenshot.expanduser().resolve()
        shot.parent.mkdir(parents=True, exist_ok=True)
        cli.save_scene_screenshot(SCENE, shot)
        if not shot.exists() or shot.stat().st_size < 1000:
            print(f"error: screenshot missing or too small: {shot}", file=sys.stderr)
            return 1
        print(f"screenshot={shot} size={shot.stat().st_size}")

        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        bundle_dir = EVIDENCE_DIR / "proof" / timestamp

        ok, _, scene_data = cli.req("GetSceneItemList", {"sceneName": SCENE})
        if not ok:
            print("error: failed to read scene state after apply", file=sys.stderr)
            return 1

        write_json(DEFAULT_SCENE_DUMP, scene_data)
        if args.dump_state:
            write_json(args.dump_state.expanduser().resolve(), scene_data)
            print(f"dump_state={args.dump_state.expanduser().resolve()}")
        observed_bindings, input_payload = collect_input_settings(cli, stack_order)
        input_payload["capturedAt"] = timestamp
        write_json(DEFAULT_INPUT_SETTINGS, input_payload)

        rectangles_payload = {
            "capturedAt": timestamp,
            "rowRule": "top-edge",
            "rectangles": compute_rectangles_from_scene_items(scene_data.get("sceneItems", [])),
        }
        write_json(DEFAULT_RECTANGLES, rectangles_payload)

        screenshot_bundle = copy_to_bundle(shot, bundle_dir)
        scene_bundle = copy_to_bundle(DEFAULT_SCENE_DUMP, bundle_dir)
        input_bundle = copy_to_bundle(DEFAULT_INPUT_SETTINGS, bundle_dir)
        rectangles_bundle = copy_to_bundle(DEFAULT_RECTANGLES, bundle_dir)

        update_observed_bindings(graph, observed_bindings)
        save_graph(graph, ontology_path)
        graph = load_graph(ontology_path)

        shapes_graph = load_shapes_graph()
        validation = validate_graphs(graph, shapes_graph)
        write_json(DEFAULT_VALIDATION, validation)
        validation_bundle = copy_to_bundle(DEFAULT_VALIDATION, bundle_dir)

        update_latest_proof_bundle(
            graph,
            screenshot_path=screenshot_bundle,
            scene_state_path=scene_bundle,
            input_settings_path=input_bundle,
            rectangles_path=rectangles_bundle,
            validation_path=validation_bundle,
            validation=validation,
        )
        save_graph(graph, ontology_path)
        graph = load_graph(ontology_path)
        print("RDFLIB_PARSE_OK")

        validation = validate_graphs(graph, shapes_graph)
        write_json(DEFAULT_VALIDATION, validation)
        validation_bundle = copy_to_bundle(DEFAULT_VALIDATION, bundle_dir)
        update_latest_proof_bundle(
            graph,
            screenshot_path=screenshot_bundle,
            scene_state_path=scene_bundle,
            input_settings_path=input_bundle,
            rectangles_path=rectangles_bundle,
            validation_path=validation_bundle,
            validation=validation,
        )
        save_graph(graph, ontology_path)
        graph = load_graph(ontology_path)
        print("RDFLIB_PARSE_OK")
        export_derived_json_files(graph)

        print(f"validation_report={DEFAULT_VALIDATION}")
        print(f"proof_bundle={bundle_dir}")
        if not validation.get("shacl_conforms", False):
            print("error: SHACL validation failed after apply", file=sys.stderr)
            return 1
        if not args.no_preview:
            # Open in Preview so the proof is visible without file:// links or manual hunting
            r = subprocess.run(
                ["open", "-a", "Preview", str(shot)],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                subprocess.run(["open", str(shot)], check=False)  # default app
            else:
                print("preview=opened")
        print("status=ok (apply authoritative ontology layout + proof bundle written)")
        return 0
    except Exception as e:
        print(f"error={e}", file=sys.stderr)
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
