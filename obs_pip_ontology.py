#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pyshacl import validate as pyshacl_validate
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SH, XSD

ROOT = Path(__file__).resolve().parent
EVIDENCE_DIR = ROOT / "evidence"
ONTOLOGY_PATH = EVIDENCE_DIR / "obs_pip_findings.ttl"
SHACL_PATH = EVIDENCE_DIR / "obs_pip_findings.shacl.ttl"
LAYOUT_JSON_PATH = EVIDENCE_DIR / "obs_pip_layout_authoritative.json"
SOURCE_URLS_JSON_PATH = EVIDENCE_DIR / "obs_pip_source_urls.json"
PANEL_CONTROL_CONFIG_JSON_PATH = ROOT / "obs_panel_control_config.json"

OBS = Namespace("urn:lou:obs-pip#")


@dataclass(frozen=True)
class TransformSpec:
    position_x: float
    position_y: float
    scale_x: float
    scale_y: float
    bounds_width: float
    bounds_height: float
    bounds_type: str
    bounds_alignment: int
    alignment: int
    rotation: float = 0.0
    crop_top: int = 0
    crop_bottom: int = 0
    crop_left: int = 0
    crop_right: int = 0

    def as_obs_transform(self) -> dict[str, Any]:
        return {
            "positionX": self.position_x,
            "positionY": self.position_y,
            "scaleX": self.scale_x,
            "scaleY": self.scale_y,
            "boundsWidth": self.bounds_width,
            "boundsHeight": self.bounds_height,
            "boundsType": self.bounds_type,
            "boundsAlignment": self.bounds_alignment,
            "alignment": self.alignment,
            "rotation": self.rotation,
            "cropTop": self.crop_top,
            "cropBottom": self.crop_bottom,
            "cropLeft": self.crop_left,
            "cropRight": self.crop_right,
        }


@dataclass(frozen=True)
class SlotSpec:
    role: str
    slot_uri: URIRef
    input_uri: URIRef
    feed_uri: URIRef
    transform_uri: URIRef
    label: str
    input_name: str | None = None
    input_name_prefix: str | None = None
    scene_item_source_name: str | None = None
    scene_item_source_prefix: str | None = None
    source_url: str | None = None
    source_url_alt: str | None = None
    dynamic_feed: bool = False
    transform: TransformSpec | None = None

    @property
    def stack_id(self) -> str:
        return {
            "main": "main",
            "lowerLeft": "auxLeft",
            "lowerRight": "auxRight",
            "center": "auxCenter",
        }[self.role]

    @property
    def match_mode(self) -> str:
        return "exact" if self.scene_item_source_name else "prefix"

    @property
    def match_value(self) -> str:
        return self.scene_item_source_name or self.scene_item_source_prefix or ""


CANVAS_WIDTH = 3840.0
CANVAS_HEIGHT = 2254.0
SMALL_LOGICAL_SOURCE_WIDTH = 1920.0
SMALL_LOGICAL_SOURCE_HEIGHT = 1080.0
SMALL_TOP_Y = 1421.0
LEFT_MARGIN_X = 20.0
RIGHT_INSET_X = 540.0
# In thirds mode, let each small panel occupy most of its third.
SMALL_THIRD_OCCUPANCY = 0.82
SMALL_WIDTH_CANVAS = (CANVAS_WIDTH / 3.0) * SMALL_THIRD_OCCUPANCY
SMALL_HEIGHT_CANVAS = SMALL_WIDTH_CANVAS * (9.0 / 16.0)
SMALL_SCALE_X = SMALL_WIDTH_CANVAS / SMALL_LOGICAL_SOURCE_WIDTH
SMALL_SCALE_Y = SMALL_HEIGHT_CANVAS / SMALL_LOGICAL_SOURCE_HEIGHT
SCENE_NAME = "PiP"
FIT_MODE_TO_BOUNDS_TYPE = {
    "stretch": "OBS_BOUNDS_STRETCH",
    "contain": "OBS_BOUNDS_SCALE_INNER",
    "cover": "OBS_BOUNDS_SCALE_OUTER",
}
SMALL_FIT_MODE = "cover"
SMALL_BOUNDS_TYPE = FIT_MODE_TO_BOUNDS_TYPE[SMALL_FIT_MODE]
LAYOUT_STRATEGY = "rule_of_thirds"


def _small_slot_positions(strategy: str) -> tuple[float, float, float]:
    if strategy == "rule_of_thirds":
        # Three equal supporting panels centered within each horizontal third.
        third = CANVAS_WIDTH / 3.0
        centers = (third * 0.5, third * 1.5, third * 2.5)
        return tuple(c - (SMALL_WIDTH_CANVAS / 2.0) for c in centers)
    if strategy == "golden_ratio":
        # Designerly asymmetric option kept ready for future use.
        phi = (1.0 + 5.0**0.5) / 2.0
        left_center = CANVAS_WIDTH * (1.0 / (phi * phi))
        center_center = CANVAS_WIDTH * 0.5
        right_center = CANVAS_WIDTH * (1.0 - 1.0 / (phi * phi))
        return (
            left_center - (SMALL_WIDTH_CANVAS / 2.0),
            center_center - (SMALL_WIDTH_CANVAS / 2.0),
            right_center - (SMALL_WIDTH_CANVAS / 2.0),
        )
    # Back-compat geometry.
    center_x = (CANVAS_WIDTH - SMALL_WIDTH_CANVAS) / 2.0
    right_x = CANVAS_WIDTH - RIGHT_INSET_X - SMALL_WIDTH_CANVAS
    return (LEFT_MARGIN_X, center_x, right_x)


LEFT_X, CENTER_X, RIGHT_X = _small_slot_positions(LAYOUT_STRATEGY)

URI = {
    "state_current": OBS["State_Current"],
    "config_current": OBS["Config_Current"],
    "layout_current": OBS["Layout_Current"],
    "proof_bundle_latest": OBS["ProofBundle_Latest"],
    "proof_screenshot_latest": OBS["Ev_ProofScreenshot_Latest"],
    "proof_scene_state_latest": OBS["Ev_ProofSceneState_Latest"],
    "proof_input_settings_latest": OBS["Ev_ProofInputSettings_Latest"],
    "proof_rectangles_latest": OBS["Ev_ProofRectangles_Latest"],
    "proof_validation_latest": OBS["Ev_ProofValidation_Latest"],
    "row_rule_top_edge": OBS["RowRule_TopEdge"],
    "scene_current": OBS["Scene_PiP_Current"],
    "input_main": OBS["Input_PiPCapture_Current"],
    "input_aux2": OBS["Input_Aux2_Current"],
    "input_aux3": OBS["Input_ThirdSource_Current"],
    "input_aux4": OBS["Input_FourthSource_Current"],
    "slot_main": OBS["Slot_Main"],
    "slot_left": OBS["Slot_LowerLeft"],
    "slot_right": OBS["Slot_LowerRight"],
    "slot_center": OBS["Slot_Center"],
    "feed_main": OBS["Feed_MainDynamic"],
    "feed_left": OBS["Feed_BloombergLive"],
    "feed_right": OBS["Feed_France24English"],
    "feed_center": OBS["Feed_BBCNewsLive"],
    "transform_main": OBS["Transform_Main_Current"],
    "transform_left": OBS["Transform_LowerLeft_Current"],
    "transform_right": OBS["Transform_LowerRight_Current"],
    "transform_center": OBS["Transform_Center_Current"],
    "ev_source_urls": OBS["Ev_SourceUrls"],
    "source_url_discovery": OBS["SourceUrlDiscovery"],
}


MAIN_TRANSFORM = TransformSpec(
    position_x=0.0,
    position_y=-95.0,
    scale_x=1.0,
    scale_y=1.0,
    bounds_width=CANVAS_WIDTH,
    bounds_height=CANVAS_HEIGHT,
    bounds_type="OBS_BOUNDS_STRETCH",
    bounds_alignment=0,
    alignment=5,
)

SMALL_TRANSFORM_BASE = {
    "scale_x": 1.0,
    "scale_y": 1.0,
    "bounds_width": SMALL_WIDTH_CANVAS,
    "bounds_height": SMALL_HEIGHT_CANVAS,
    "bounds_type": SMALL_BOUNDS_TYPE,
    "bounds_alignment": 0,
    "alignment": 5,
}

SLOT_SPECS = {
    "main": SlotSpec(
        role="main",
        slot_uri=URI["slot_main"],
        input_uri=URI["input_main"],
        feed_uri=URI["feed_main"],
        transform_uri=URI["transform_main"],
        label="Main panel",
        input_name="PiP Capture",
        scene_item_source_name="PiP Capture",
        dynamic_feed=True,
        transform=MAIN_TRANSFORM,
    ),
    "lowerLeft": SlotSpec(
        role="lowerLeft",
        slot_uri=URI["slot_left"],
        input_uri=URI["input_aux2"],
        feed_uri=URI["feed_left"],
        transform_uri=URI["transform_left"],
        label="Lower-left panel",
        input_name="Aux2",
        scene_item_source_name="Aux2",
        source_url="https://www.youtube.com/watch?v=DxmDPrfinXY",
        transform=TransformSpec(position_x=LEFT_X, position_y=SMALL_TOP_Y, **SMALL_TRANSFORM_BASE),
    ),
    "lowerRight": SlotSpec(
        role="lowerRight",
        slot_uri=URI["slot_right"],
        input_uri=URI["input_aux3"],
        feed_uri=URI["feed_right"],
        transform_uri=URI["transform_right"],
        label="Lower-right panel",
        input_name_prefix="Aux3LR",
        scene_item_source_prefix="Aux3LR",
        source_url="https://www.youtube.com/c/FRANCE24English/live",
        source_url_alt="https://www.youtube.com/c/FRANCE24English/streams",
        transform=TransformSpec(position_x=RIGHT_X, position_y=SMALL_TOP_Y, **SMALL_TRANSFORM_BASE),
    ),
    "center": SlotSpec(
        role="center",
        slot_uri=URI["slot_center"],
        input_uri=URI["input_aux4"],
        feed_uri=URI["feed_center"],
        transform_uri=URI["transform_center"],
        label="Bottom-center panel",
        input_name_prefix="Aux4Center",
        scene_item_source_prefix="Aux4Center",
        source_url="http://www.bbc.co.uk/iplayer/live/bbcnews",
        source_url_alt="https://www.bbc.com/watch-live-news/",
        transform=TransformSpec(position_x=CENTER_X, position_y=SMALL_TOP_Y, **SMALL_TRANSFORM_BASE),
    ),
}


def bind_namespaces(graph: Graph) -> Graph:
    graph.bind("obs", OBS)
    graph.bind("dct", DCTERMS)
    graph.bind("rdfs", RDFS)
    graph.bind("rdf", RDF)
    graph.bind("xsd", XSD)
    graph.bind("sh", SH)
    return graph


def load_graph(path: Path = ONTOLOGY_PATH) -> Graph:
    graph = bind_namespaces(Graph())
    graph.parse(path)
    return graph


def load_shapes_graph(path: Path = SHACL_PATH) -> Graph:
    graph = bind_namespaces(Graph())
    graph.parse(path)
    return graph


def save_graph(graph: Graph, path: Path = ONTOLOGY_PATH) -> None:
    bind_namespaces(graph)
    path.write_text(graph.serialize(format="turtle"), encoding="utf-8")


def save_shapes_graph(graph: Graph, path: Path = SHACL_PATH) -> None:
    bind_namespaces(graph)
    path.write_text(graph.serialize(format="turtle"), encoding="utf-8")


def _lit(value: Any, datatype: URIRef | None = None) -> Literal:
    if datatype is None:
        return Literal(value)
    return Literal(value, datatype=datatype)


def _clear_subject(graph: Graph, subject: URIRef, preserve_types: bool = False) -> None:
    for predicate, obj in list(graph.predicate_objects(subject)):
        if preserve_types and predicate == RDF.type:
            continue
        graph.remove((subject, predicate, obj))


def _replace_literal(graph: Graph, subject: URIRef, predicate: URIRef, value: Any, datatype: URIRef | None = None) -> None:
    graph.remove((subject, predicate, None))
    graph.add((subject, predicate, _lit(value, datatype)))


def _replace_refs(graph: Graph, subject: URIRef, predicate: URIRef, refs: list[URIRef]) -> None:
    graph.remove((subject, predicate, None))
    for ref in refs:
        graph.add((subject, predicate, ref))


def _ensure_property(graph: Graph, local_name: str) -> URIRef:
    prop = OBS[local_name]
    graph.add((prop, RDF.type, RDF.Property))
    return prop


def _ensure_class(graph: Graph, local_name: str) -> URIRef:
    cls = OBS[local_name]
    graph.add((cls, RDF.type, RDFS.Class))
    return cls


def active_slot_specs() -> list[SlotSpec]:
    return [SLOT_SPECS["main"], SLOT_SPECS["lowerLeft"], SLOT_SPECS["lowerRight"], SLOT_SPECS["center"]]


def get_slot_spec(role: str) -> SlotSpec:
    return SLOT_SPECS[role]


def get_lower_left_url(graph: Graph | None = None) -> str:
    if graph is None:
        graph = load_graph()
    return literal_string(graph, URI["feed_left"], OBS.sourceUrl) or SLOT_SPECS["lowerLeft"].source_url or ""


def get_panel_control_config(graph: Graph | None = None) -> dict[str, Any]:
    if graph is None:
        graph = load_graph()
    slots = active_slot_specs()
    panels: dict[str, Any] = {}
    for slot in slots:
        panel_id = {
            "main": "main",
            "lowerLeft": "aux_left",
            "lowerRight": "aux_right",
            "center": "aux_center",
        }[slot.role]
        entry: dict[str, Any] = {}
        if slot.input_name:
            entry["inputName"] = slot.input_name
        if slot.input_name_prefix:
            entry["inputNamePrefix"] = slot.input_name_prefix
        if slot.scene_item_source_name:
            entry["sceneItemSourceName"] = slot.scene_item_source_name
        if slot.scene_item_source_prefix:
            entry["sceneItemSourcePrefix"] = slot.scene_item_source_prefix
        panels[panel_id] = entry
    return {"scene": SCENE_NAME, "panels": panels}


def get_layout_payload(graph: Graph | None = None) -> dict[str, Any]:
    if graph is None:
        graph = load_graph()
    return {
        "$schema": "obs-pip-layout/derived-from-ontology",
        "version": 4,
        "_source": "Generated from evidence/obs_pip_findings.ttl via obs_pip_ontology.py",
        "scene": SCENE_NAME,
        "layoutStrategy": LAYOUT_STRATEGY,
        "canvasRef": {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT},
        "stackOrder": [
            {"id": slot.stack_id, "source": slot.match_value, "match": slot.match_mode}
            for slot in active_slot_specs()
        ],
        "transforms": {
            slot.stack_id: slot.transform.as_obs_transform() if slot.transform else {}
            for slot in active_slot_specs()
        },
        "assignSceneItemIndices": False,
        "scaleYIfCanvasHeightDiffers": False,
        "screenshotAfterApply": {"defaultPath": "evidence/obs_pip_verify.png", "required": True},
    }


def get_source_urls_payload(graph: Graph | None = None) -> dict[str, Any]:
    if graph is None:
        graph = load_graph()
    return {
        "description": "Generated from evidence/obs_pip_findings.ttl. This JSON is derived telemetry, not authoritative configuration.",
        "client": "Google Chrome (all four sources)",
        "views": "View 1 = main; View 2 = lower-left; View 3 = lower-right; View 4 = bottom center (Control-Left/Right)",
        "sources": {
            "window1_main": {
                "label": "PiP Capture (main)",
                "url": "",
                "note": "Main panel is intentionally dynamic in the ontology. Distinctness from lower-left is enforced; exact URL is recorded in proof bundles when captured.",
            },
            "window2_lowerLeft": {
                "label": "Aux2 (lower-left)",
                "url": get_lower_left_url(graph),
                "note": "Bloomberg Live. Derived from ontology feed assignment.",
            },
            "window3_lowerRight": {
                "label": "Aux3LR_* (lower-right)",
                "url": literal_string(graph, URI["feed_right"], OBS.sourceUrl) or SLOT_SPECS["lowerRight"].source_url,
                "url_alt": literal_string(graph, URI["feed_right"], OBS.sourceUrlAlt) or SLOT_SPECS["lowerRight"].source_url_alt,
                "note": "France 24 English. Derived from ontology feed assignment.",
            },
            "window4_center": {
                "label": "Aux4Center_* (bottom center)",
                "url": literal_string(graph, URI["feed_center"], OBS.sourceUrl) or SLOT_SPECS["center"].source_url,
                "url_alt": literal_string(graph, URI["feed_center"], OBS.sourceUrlAlt) or SLOT_SPECS["center"].source_url_alt,
                "note": "BBC News live. Derived from ontology feed assignment.",
            },
        },
    }


def export_derived_json_files(graph: Graph | None = None) -> None:
    if graph is None:
        graph = load_graph()
    LAYOUT_JSON_PATH.write_text(json.dumps(get_layout_payload(graph), indent=2) + "\n", encoding="utf-8")
    SOURCE_URLS_JSON_PATH.write_text(json.dumps(get_source_urls_payload(graph), indent=2) + "\n", encoding="utf-8")
    PANEL_CONTROL_CONFIG_JSON_PATH.write_text(json.dumps(get_panel_control_config(graph), indent=2) + "\n", encoding="utf-8")


def literal_string(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = graph.value(subject, predicate)
    if value is None:
        return None
    return str(value)


def sync_authoritative_ontology(graph: Graph | None = None) -> Graph:
    if graph is None:
        graph = load_graph()
    bind_namespaces(graph)

    for class_name in ("PiPConfig", "Slot", "Feed", "Transform", "LayoutSpec", "ProofBundle", "RowRule"):
        _ensure_class(graph, class_name)

    for prop_name in (
        "hasCurrentConfig",
        "hasSlot",
        "hasDesiredFeed",
        "hasDesiredTransform",
        "hasLayout",
        "hasProofBundle",
        "slotRole",
        "inputNamePrefix",
        "sceneItemSourceName",
        "sceneItemSourcePrefix",
        "fitMode",
        "layoutStrategy",
        "sceneItemMatchMode",
        "sceneItemMatchValue",
        "positionX",
        "positionY",
        "scaleX",
        "scaleY",
        "boundsType",
        "boundsWidth",
        "boundsHeight",
        "boundsAlignment",
        "alignment",
        "rotation",
        "cropTop",
        "cropBottom",
        "cropLeft",
        "cropRight",
        "isDynamicFeed",
        "hasGeneratedArtifact",
        "generatedFromOntology",
        "rowRuleName",
        "rowTopY",
        "rowLeftMarginX",
        "rowRightInsetX",
        "proofCapturedAt",
        "parsedWithRdflib",
        "shaclConforms",
        "validationSummary",
        "sourceUrlAlt",
        "hasValidationArtifact",
        "screenshotArtifact",
        "sceneStateArtifact",
        "inputSettingsArtifact",
        "rectanglesArtifact",
        "validationArtifact",
    ):
        _ensure_property(graph, prop_name)

    graph.add((URI["state_current"], OBS.hasCurrentConfig, URI["config_current"]))
    graph.add((URI["state_current"], OBS.hasProofBundle, URI["proof_bundle_latest"]))

    for uri_name in (
        "config_current",
        "layout_current",
        "proof_bundle_latest",
        "proof_screenshot_latest",
        "proof_scene_state_latest",
        "proof_input_settings_latest",
        "proof_rectangles_latest",
        "proof_validation_latest",
        "row_rule_top_edge",
        "slot_main",
        "slot_left",
        "slot_right",
        "slot_center",
        "feed_main",
        "feed_left",
        "feed_right",
        "feed_center",
        "transform_main",
        "transform_left",
        "transform_right",
        "transform_center",
    ):
        _clear_subject(graph, URI[uri_name])

    graph.add((URI["config_current"], RDF.type, OBS.PiPConfig))
    graph.add((URI["config_current"], RDFS.label, _lit("Current PiP configuration")))
    graph.add((URI["config_current"], OBS.hasScene, URI["scene_current"]))
    graph.add((URI["config_current"], OBS.hasLayout, URI["layout_current"]))
    graph.add((URI["config_current"], OBS.hasProofBundle, URI["proof_bundle_latest"]))
    graph.add((URI["config_current"], OBS.rowRule, URI["row_rule_top_edge"]))
    _replace_refs(
        graph,
        URI["config_current"],
        OBS.hasSlot,
        [URI["slot_main"], URI["slot_left"], URI["slot_right"], URI["slot_center"]],
    )

    graph.add((URI["layout_current"], RDF.type, OBS.LayoutSpec))
    graph.add((URI["layout_current"], RDFS.label, _lit("Current ontology-backed PiP layout")))
    _replace_literal(graph, URI["layout_current"], OBS.sceneName, SCENE_NAME)
    _replace_literal(graph, URI["layout_current"], OBS.layoutStrategy, LAYOUT_STRATEGY)
    _replace_literal(graph, URI["layout_current"], OBS.generatedFromOntology, True, XSD.boolean)

    graph.add((URI["row_rule_top_edge"], RDF.type, OBS.RowRule))
    graph.add((URI["row_rule_top_edge"], RDFS.label, _lit("Top-edge aligned small PiP row")))
    _replace_literal(graph, URI["row_rule_top_edge"], OBS.rowRuleName, f"top-edge/{LAYOUT_STRATEGY}")
    _replace_literal(graph, URI["row_rule_top_edge"], OBS.rowTopY, SMALL_TOP_Y, XSD.double)
    _replace_literal(graph, URI["row_rule_top_edge"], OBS.rowLeftMarginX, LEFT_X, XSD.double)
    _replace_literal(
        graph,
        URI["row_rule_top_edge"],
        OBS.rowRightInsetX,
        CANVAS_WIDTH - (RIGHT_X + SMALL_WIDTH_CANVAS),
        XSD.double,
    )

    graph.remove((URI["ev_source_urls"], OBS.note, None))
    graph.add(
        (
            URI["ev_source_urls"],
            OBS.note,
            _lit(
                "Derived export of current slot-to-feed assignments. Main feed is intentionally dynamic; lower-left is Bloomberg, lower-right is France 24, and center is BBC."
            ),
        )
    )
    graph.remove((URI["source_url_discovery"], OBS.note, None))
    graph.add(
        (
            URI["source_url_discovery"],
            OBS.note,
            _lit(
                "Current authoritative slot assignments live in the ontology config layer. Main is dynamic but must remain distinct from lower-left. Lower-left is Bloomberg, lower-right is France 24, and center is BBC."
            ),
        )
    )

    feed_specs = {
        URI["feed_main"]: {
            "label": "Main feed (dynamic operator-selected source)",
            "dynamic": True,
            "note": "Main slot is intentionally dynamic. The proof bundle must record the observed URL/title and prove it differs from lower-left.",
        },
        URI["feed_left"]: {
            "label": "Bloomberg Live",
            "source_url": SLOT_SPECS["lowerLeft"].source_url,
            "note": "Authoritative lower-left feed.",
        },
        URI["feed_right"]: {
            "label": "France 24 English live",
            "source_url": SLOT_SPECS["lowerRight"].source_url,
            "source_url_alt": SLOT_SPECS["lowerRight"].source_url_alt,
            "note": "Authoritative lower-right feed.",
        },
        URI["feed_center"]: {
            "label": "BBC News live",
            "source_url": SLOT_SPECS["center"].source_url,
            "source_url_alt": SLOT_SPECS["center"].source_url_alt,
            "note": "Authoritative bottom-center feed.",
        },
    }
    for feed_uri, spec in feed_specs.items():
        graph.add((feed_uri, RDF.type, OBS.Feed))
        graph.add((feed_uri, RDFS.label, _lit(spec["label"])))
        if spec.get("dynamic"):
            _replace_literal(graph, feed_uri, OBS.isDynamicFeed, True, XSD.boolean)
        else:
            _replace_literal(graph, feed_uri, OBS.isDynamicFeed, False, XSD.boolean)
            _replace_literal(graph, feed_uri, OBS.sourceUrl, spec["source_url"])
        if spec.get("source_url_alt"):
            _replace_literal(graph, feed_uri, OBS.sourceUrlAlt, spec["source_url_alt"])
        if spec.get("note"):
            _replace_literal(graph, feed_uri, OBS.note, spec["note"])

    input_updates = {
        URI["input_main"]: {
            "note": "Main source on the PiP canvas. Feed identity is intentionally dynamic, but it must never duplicate lower-left in the proof bundle.",
            "window_id": 21552,
        },
        URI["input_aux2"]: {
            "note": "Lower-left source. Ontology authority requires Bloomberg Live and a distinct binding from the main panel.",
            "window_id": 39251,
        },
        URI["input_aux3"]: {
            "note": "Lower-right source. Ontology authority requires France 24 and top-edge row alignment with the other small PiPs.",
            "window_id": 23187,
        },
        URI["input_aux4"]: {
            "note": "Bottom-center source. Ontology authority requires BBC and top-edge row alignment with the other small PiPs.",
            "window_id": 23720,
        },
    }
    for input_uri, spec in input_updates.items():
        if spec.get("note"):
            _replace_literal(graph, input_uri, OBS.note, spec["note"])
        if "window_id" in spec:
            _replace_literal(graph, input_uri, OBS.windowId, int(spec["window_id"]), XSD.integer)

    for slot in active_slot_specs():
        graph.add((slot.slot_uri, RDF.type, OBS.Slot))
        graph.add((slot.slot_uri, RDFS.label, _lit(slot.label)))
        _replace_literal(graph, slot.slot_uri, OBS.slotRole, slot.role)
        _replace_refs(graph, slot.slot_uri, OBS.usesInput, [slot.input_uri])
        _replace_refs(graph, slot.slot_uri, OBS.hasDesiredFeed, [slot.feed_uri])
        _replace_refs(graph, slot.slot_uri, OBS.hasDesiredTransform, [slot.transform_uri])
        _replace_literal(graph, slot.slot_uri, OBS.sceneItemMatchMode, slot.match_mode)
        _replace_literal(graph, slot.slot_uri, OBS.sceneItemMatchValue, slot.match_value)
        if slot.input_name:
            _replace_literal(graph, slot.slot_uri, OBS.inputName, slot.input_name)
            _replace_literal(graph, slot.input_uri, OBS.inputName, slot.input_name)
        if slot.input_name_prefix:
            _replace_literal(graph, slot.slot_uri, OBS.inputNamePrefix, slot.input_name_prefix)
            _replace_literal(graph, slot.input_uri, OBS.inputName, f"{slot.input_name_prefix}_*")
            _replace_literal(graph, slot.input_uri, OBS.inputNamePrefix, slot.input_name_prefix)
        if slot.scene_item_source_name:
            _replace_literal(graph, slot.slot_uri, OBS.sceneItemSourceName, slot.scene_item_source_name)
        if slot.scene_item_source_prefix:
            _replace_literal(graph, slot.slot_uri, OBS.sceneItemSourcePrefix, slot.scene_item_source_prefix)

    for slot in active_slot_specs():
        transform = slot.transform
        if transform is None:
            continue
        graph.add((slot.transform_uri, RDF.type, OBS.Transform))
        graph.add((slot.transform_uri, RDFS.label, _lit(f"{slot.label} transform")))
        _replace_literal(graph, slot.transform_uri, OBS.positionX, transform.position_x, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.positionY, transform.position_y, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.scaleX, transform.scale_x, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.scaleY, transform.scale_y, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.boundsWidth, transform.bounds_width, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.boundsHeight, transform.bounds_height, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.boundsType, transform.bounds_type)
        _replace_literal(graph, slot.transform_uri, OBS.fitMode, "stretch" if slot.role == "main" else SMALL_FIT_MODE)
        _replace_literal(graph, slot.transform_uri, OBS.boundsAlignment, transform.bounds_alignment, XSD.integer)
        _replace_literal(graph, slot.transform_uri, OBS.alignment, transform.alignment, XSD.integer)
        _replace_literal(graph, slot.transform_uri, OBS.rotation, transform.rotation, XSD.double)
        _replace_literal(graph, slot.transform_uri, OBS.cropTop, transform.crop_top, XSD.integer)
        _replace_literal(graph, slot.transform_uri, OBS.cropBottom, transform.crop_bottom, XSD.integer)
        _replace_literal(graph, slot.transform_uri, OBS.cropLeft, transform.crop_left, XSD.integer)
        _replace_literal(graph, slot.transform_uri, OBS.cropRight, transform.crop_right, XSD.integer)

    graph.add((URI["proof_bundle_latest"], RDF.type, OBS.ProofBundle))
    graph.add((URI["proof_bundle_latest"], RDFS.label, _lit("Latest PiP proof bundle")))
    _replace_literal(graph, URI["proof_bundle_latest"], OBS.parsedWithRdflib, False, XSD.boolean)
    _replace_literal(graph, URI["proof_bundle_latest"], OBS.shaclConforms, False, XSD.boolean)
    _replace_refs(
        graph,
        URI["proof_bundle_latest"],
        OBS.hasEvidence,
        [
            URI["proof_screenshot_latest"],
            URI["proof_scene_state_latest"],
            URI["proof_input_settings_latest"],
            URI["proof_rectangles_latest"],
            URI["proof_validation_latest"],
        ],
    )
    _replace_refs(graph, URI["proof_bundle_latest"], OBS.screenshotArtifact, [URI["proof_screenshot_latest"]])
    _replace_refs(graph, URI["proof_bundle_latest"], OBS.sceneStateArtifact, [URI["proof_scene_state_latest"]])
    _replace_refs(graph, URI["proof_bundle_latest"], OBS.inputSettingsArtifact, [URI["proof_input_settings_latest"]])
    _replace_refs(graph, URI["proof_bundle_latest"], OBS.rectanglesArtifact, [URI["proof_rectangles_latest"]])
    _replace_refs(graph, URI["proof_bundle_latest"], OBS.validationArtifact, [URI["proof_validation_latest"]])

    proof_artifacts = {
        URI["proof_screenshot_latest"]: ("Latest proof screenshot", str(EVIDENCE_DIR / "obs_pip_verify.png")),
        URI["proof_scene_state_latest"]: ("Latest proof scene-state dump", str(EVIDENCE_DIR / "obs_pip_scene_state_after_apply.json")),
        URI["proof_input_settings_latest"]: ("Latest proof input-settings dump", str(EVIDENCE_DIR / "obs_pip_input_settings_latest.json")),
        URI["proof_rectangles_latest"]: ("Latest proof rectangles dump", str(EVIDENCE_DIR / "obs_pip_rectangles_latest.json")),
        URI["proof_validation_latest"]: ("Latest proof validation report", str(EVIDENCE_DIR / "obs_pip_validation_latest.json")),
    }
    for artifact_uri, (label, path) in proof_artifacts.items():
        graph.add((artifact_uri, RDF.type, OBS.EvidenceArtifact))
        graph.add((artifact_uri, RDFS.label, _lit(label)))
        _replace_literal(graph, artifact_uri, OBS.artifactPath, path)

    return graph


def build_shapes_graph() -> Graph:
    graph = bind_namespaces(Graph())

    def property_shape(path: URIRef, *, min_count: int | None = None, max_count: int | None = None, has_value: Any | None = None, datatype: URIRef | None = None, node: URIRef | None = None, message: str | None = None) -> BNode:
        shape = BNode()
        graph.add((shape, SH.path, path))
        if min_count is not None:
            graph.add((shape, SH.minCount, _lit(min_count, XSD.integer)))
        if max_count is not None:
            graph.add((shape, SH.maxCount, _lit(max_count, XSD.integer)))
        if has_value is not None:
            obj = has_value if isinstance(has_value, URIRef) else _lit(has_value)
            graph.add((shape, SH.hasValue, obj))
        if datatype is not None:
            graph.add((shape, SH.datatype, datatype))
        if node is not None:
            graph.add((shape, SH["class"], node))
        if message is not None:
            graph.add((shape, SH.message, _lit(message)))
        return shape

    current_state_shape = OBS["CurrentStateShape"]
    graph.add((current_state_shape, RDF.type, SH.NodeShape))
    graph.add((current_state_shape, SH.targetNode, URI["state_current"]))
    for shape in (
        property_shape(OBS.hasScene, min_count=1, max_count=1, message="Current state must have exactly one scene."),
        property_shape(OBS.hasInput, min_count=1, message="Current state must have at least one input."),
        property_shape(OBS.hasObsInstance, min_count=1, max_count=1),
        property_shape(OBS.hasCurrentConfig, min_count=1, max_count=1, has_value=URI["config_current"]),
    ):
        graph.add((current_state_shape, SH.property, shape))

    config_shape = OBS["ConfigCurrentShape"]
    graph.add((config_shape, RDF.type, SH.NodeShape))
    graph.add((config_shape, SH.targetNode, URI["config_current"]))
    for shape in (
        property_shape(OBS.hasScene, min_count=1, max_count=1, has_value=URI["scene_current"]),
        property_shape(OBS.hasSlot, min_count=4, max_count=4, message="Current config must declare exactly four slots."),
        property_shape(OBS.hasLayout, min_count=1, max_count=1, has_value=URI["layout_current"]),
        property_shape(OBS.hasProofBundle, min_count=1, max_count=1, has_value=URI["proof_bundle_latest"]),
    ):
        graph.add((config_shape, SH.property, shape))

    layout_shape = OBS["LayoutCurrentShape"]
    graph.add((layout_shape, RDF.type, SH.NodeShape))
    graph.add((layout_shape, SH.targetNode, URI["layout_current"]))
    for shape in (
        property_shape(OBS.sceneName, min_count=1, max_count=1, has_value=SCENE_NAME),
        property_shape(OBS.generatedFromOntology, min_count=1, max_count=1, has_value=True),
        property_shape(OBS.layoutStrategy, min_count=1, max_count=1, has_value=LAYOUT_STRATEGY),
    ):
        graph.add((layout_shape, SH.property, shape))

    slot_expectations = {
        URI["slot_main"]: ("main", URI["input_main"], URI["feed_main"], URI["transform_main"]),
        URI["slot_left"]: ("lowerLeft", URI["input_aux2"], URI["feed_left"], URI["transform_left"]),
        URI["slot_right"]: ("lowerRight", URI["input_aux3"], URI["feed_right"], URI["transform_right"]),
        URI["slot_center"]: ("center", URI["input_aux4"], URI["feed_center"], URI["transform_center"]),
    }
    for slot_uri, (role, input_uri, feed_uri, transform_uri) in slot_expectations.items():
        shape_uri = OBS[f"{role[0].upper()}{role[1:]}SlotShape"]
        graph.add((shape_uri, RDF.type, SH.NodeShape))
        graph.add((shape_uri, SH.targetNode, slot_uri))
        for shape in (
            property_shape(OBS.slotRole, min_count=1, max_count=1, has_value=role),
            property_shape(OBS.usesInput, min_count=1, max_count=1, has_value=input_uri),
            property_shape(OBS.hasDesiredFeed, min_count=1, max_count=1, has_value=feed_uri),
            property_shape(OBS.hasDesiredTransform, min_count=1, max_count=1, has_value=transform_uri),
        ):
            graph.add((shape_uri, SH.property, shape))

    transform_x_expectations = {
        URI["transform_left"]: LEFT_X,
        URI["transform_right"]: RIGHT_X,
        URI["transform_center"]: CENTER_X,
    }
    for transform_uri, x_value in transform_x_expectations.items():
        shape_uri = OBS[f"{transform_uri.split('#')[-1]}PositionShape"]
        graph.add((shape_uri, RDF.type, SH.NodeShape))
        graph.add((shape_uri, SH.targetNode, transform_uri))
        graph.add(
            (
                shape_uri,
                SH.property,
                property_shape(
                    OBS.positionX,
                    min_count=1,
                    max_count=1,
                    datatype=XSD.double,
                    has_value=x_value,
                ),
            )
        )

    feed_shape = OBS["FeedShape"]
    graph.add((feed_shape, RDF.type, SH.NodeShape))
    graph.add((feed_shape, SH.targetClass, OBS.Feed))
    graph.add((feed_shape, SH.property, property_shape(RDFS.label, min_count=1)))
    or_list = BNode()
    first = BNode()
    second = BNode()
    graph.add((feed_shape, SH["or"], or_list))
    graph.add((or_list, RDF.first, first))
    rest = BNode()
    graph.add((or_list, RDF.rest, rest))
    graph.add((rest, RDF.first, second))
    graph.add((rest, RDF.rest, RDF.nil))
    graph.add((first, SH.property, property_shape(OBS.sourceUrl, min_count=1)))
    graph.add((second, SH.property, property_shape(OBS.isDynamicFeed, has_value=True)))

    small_transform_shape = OBS["SmallPiPTransformShape"]
    graph.add((small_transform_shape, RDF.type, SH.NodeShape))
    for transform_uri in (URI["transform_left"], URI["transform_right"], URI["transform_center"]):
        graph.add((small_transform_shape, SH.targetNode, transform_uri))
    for shape in (
        property_shape(OBS.alignment, min_count=1, max_count=1, has_value=5),
        property_shape(OBS.boundsType, min_count=1, max_count=1, has_value=SMALL_BOUNDS_TYPE),
        property_shape(OBS.boundsWidth, min_count=1, max_count=1, datatype=XSD.double, has_value=SMALL_WIDTH_CANVAS),
        property_shape(OBS.boundsHeight, min_count=1, max_count=1, datatype=XSD.double, has_value=SMALL_HEIGHT_CANVAS),
        property_shape(OBS.fitMode, min_count=1, max_count=1, has_value=SMALL_FIT_MODE),
        property_shape(OBS.positionY, min_count=1, max_count=1, datatype=XSD.double),
        property_shape(OBS.scaleX, min_count=1, max_count=1, datatype=XSD.double, has_value=1.0),
        property_shape(OBS.scaleY, min_count=1, max_count=1, datatype=XSD.double, has_value=1.0),
    ):
        graph.add((small_transform_shape, SH.property, shape))

    row_shape = OBS["SmallPiPRowAlignmentShape"]
    graph.add((row_shape, RDF.type, SH.NodeShape))
    graph.add((row_shape, SH.targetNode, URI["config_current"]))
    sparql = BNode()
    graph.add((row_shape, SH.sparql, sparql))
    graph.add((sparql, SH.message, _lit("All small PiPs must use alignment 5, share the same top-edge Y, and use identical fixed box dimensions.")))
    graph.add(
        (
            sparql,
            SH.select,
            _lit(
                """
PREFIX obs: <urn:lou:obs-pip#>
SELECT $this WHERE {
  obs:Slot_LowerLeft obs:hasDesiredTransform ?left .
  obs:Slot_LowerRight obs:hasDesiredTransform ?right .
  obs:Slot_Center obs:hasDesiredTransform ?center .
  ?left obs:alignment ?la ; obs:positionY ?ly ; obs:boundsWidth ?lw ; obs:boundsHeight ?lh .
  ?right obs:alignment ?ra ; obs:positionY ?ry ; obs:boundsWidth ?rw ; obs:boundsHeight ?rh .
  ?center obs:alignment ?ca ; obs:positionY ?cy ; obs:boundsWidth ?cw ; obs:boundsHeight ?ch .
  FILTER (?la != 5 || ?ra != 5 || ?ca != 5 || ?ly != ?ry || ?ly != ?cy || ?lw != ?rw || ?lw != ?cw || ?lh != ?rh || ?lh != ?ch)
}
""".strip()
            ),
        )
    )

    distinct_shape = OBS["DistinctMainLowerLeftWindowShape"]
    graph.add((distinct_shape, RDF.type, SH.NodeShape))
    graph.add((distinct_shape, SH.targetNode, URI["config_current"]))
    sparql = BNode()
    graph.add((distinct_shape, SH.sparql, sparql))
    graph.add((sparql, SH.message, _lit("Main and lower-left window bindings must be distinct.")))
    graph.add(
        (
            sparql,
            SH.select,
            _lit(
                """
PREFIX obs: <urn:lou:obs-pip#>
SELECT $this WHERE {
  obs:Input_PiPCapture_Current obs:windowId ?wid .
  obs:Input_Aux2_Current obs:windowId ?wid .
}
""".strip()
            ),
        )
    )

    proof_shape = OBS["LatestProofBundleShape"]
    graph.add((proof_shape, RDF.type, SH.NodeShape))
    graph.add((proof_shape, SH.targetNode, URI["proof_bundle_latest"]))
    for shape in (
        property_shape(OBS.screenshotArtifact, min_count=1, max_count=1, has_value=URI["proof_screenshot_latest"]),
        property_shape(OBS.sceneStateArtifact, min_count=1, max_count=1, has_value=URI["proof_scene_state_latest"]),
        property_shape(OBS.inputSettingsArtifact, min_count=1, max_count=1, has_value=URI["proof_input_settings_latest"]),
        property_shape(OBS.rectanglesArtifact, min_count=1, max_count=1, has_value=URI["proof_rectangles_latest"]),
        property_shape(OBS.validationArtifact, min_count=1, max_count=1, has_value=URI["proof_validation_latest"]),
        property_shape(OBS.parsedWithRdflib, min_count=1, max_count=1, datatype=XSD.boolean),
        property_shape(OBS.shaclConforms, min_count=1, max_count=1, datatype=XSD.boolean),
    ):
        graph.add((proof_shape, SH.property, shape))

    artifact_shape = OBS["EvidenceArtifactPathShape"]
    graph.add((artifact_shape, RDF.type, SH.NodeShape))
    graph.add((artifact_shape, SH.targetClass, OBS.EvidenceArtifact))
    graph.add((artifact_shape, SH.property, property_shape(OBS.artifactPath, min_count=1, max_count=1)))

    return graph


def validation_report_to_dict(conforms: bool, results_text: str) -> dict[str, Any]:
    return {
        "rdflib_status": "RDFLIB_PARSE_OK",
        "shacl_conforms": bool(conforms),
        "results_text": results_text,
    }


def validate_graphs(data_graph: Graph | None = None, shapes_graph: Graph | None = None) -> dict[str, Any]:
    if data_graph is None:
        data_graph = load_graph()
    if shapes_graph is None:
        shapes_graph = load_shapes_graph()
    conforms, _results_graph, results_text = pyshacl_validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        serialize_report_graph=False,
    )
    return validation_report_to_dict(bool(conforms), str(results_text))


def update_observed_bindings(graph: Graph, bindings: dict[str, dict[str, Any]]) -> None:
    slot_to_input = {
        "main": URI["input_main"],
        "lowerLeft": URI["input_aux2"],
        "lowerRight": URI["input_aux3"],
        "center": URI["input_aux4"],
    }
    for role, values in bindings.items():
        input_uri = slot_to_input.get(role)
        if input_uri is None:
            continue
        if "windowId" in values and values["windowId"] is not None:
            _replace_literal(graph, input_uri, OBS.windowId, int(values["windowId"]), XSD.integer)
        if "inputName" in values and values["inputName"]:
            _replace_literal(graph, input_uri, OBS.inputName, values["inputName"])
        if "note" in values and values["note"]:
            _replace_literal(graph, input_uri, OBS.note, values["note"])


def update_latest_proof_bundle(
    graph: Graph,
    *,
    screenshot_path: Path,
    scene_state_path: Path,
    input_settings_path: Path,
    rectangles_path: Path,
    validation_path: Path,
    validation: dict[str, Any],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    _replace_literal(graph, URI["proof_bundle_latest"], OBS.proofCapturedAt, now, XSD.dateTime)
    _replace_literal(graph, URI["proof_bundle_latest"], OBS.parsedWithRdflib, validation.get("rdflib_status") == "RDFLIB_PARSE_OK", XSD.boolean)
    _replace_literal(graph, URI["proof_bundle_latest"], OBS.shaclConforms, bool(validation.get("shacl_conforms")), XSD.boolean)
    _replace_literal(graph, URI["proof_bundle_latest"], OBS.validationSummary, validation.get("results_text", ""))
    artifact_paths = {
        URI["proof_screenshot_latest"]: screenshot_path,
        URI["proof_scene_state_latest"]: scene_state_path,
        URI["proof_input_settings_latest"]: input_settings_path,
        URI["proof_rectangles_latest"]: rectangles_path,
        URI["proof_validation_latest"]: validation_path,
    }
    for artifact_uri, artifact_path in artifact_paths.items():
        _replace_literal(graph, artifact_uri, OBS.artifactPath, str(artifact_path.resolve()))
        _replace_literal(graph, artifact_uri, OBS.observedAt, now, XSD.dateTime)


def compute_rectangles_from_scene_items(scene_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rectangles: list[dict[str, Any]] = []
    for item in scene_items:
        transform = item.get("sceneItemTransform") or {}
        bounds_type = str(transform.get("boundsType") or "")
        if bounds_type and bounds_type != "OBS_BOUNDS_NONE":
            width = float(transform.get("boundsWidth") or transform.get("width") or 0.0)
            height = float(transform.get("boundsHeight") or transform.get("height") or 0.0)
        else:
            width = float(transform.get("width") or 0.0)
            height = float(transform.get("height") or 0.0)
        x = float(transform.get("positionX") or 0.0)
        y = float(transform.get("positionY") or 0.0)
        alignment = int(transform.get("alignment") or 0)
        if alignment == 5:
            left = x
            top = y
        elif alignment == 8:
            left = x - width
            top = y - height
        elif alignment == 36:
            left = x - (width / 2.0)
            top = y - (height / 2.0)
        else:
            left = x
            top = y
        rectangles.append(
            {
                "sourceName": item.get("sourceName"),
                "sceneItemId": item.get("sceneItemId"),
                "alignment": alignment,
                "boundsType": bounds_type,
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "width": width,
                "height": height,
            }
        )
    return rectangles

