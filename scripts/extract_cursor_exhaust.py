#!/usr/bin/env python3
"""
Deterministically extract local Cursor "exhaust" metadata for model-routing analysis.

This script captures only non-secret, structural telemetry hints from local artifacts:
- Cursor global state DB routing preferences
- Extension activation logs (Codex/Claude)
- Cursor app pairing extension metadata

It intentionally does NOT claim per-turn model attribution; it records that gap explicitly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "token-proxy.cursor-exhaust.v1"
STATE_KEYS = [
    "cursor/bestOfNEnsemblePreferences",
    "cursor/lastSingleModelPreference",
    "cursor/planExecUseChatModel",
    "cursor/newChatModelAutoSwitchApplied",
]
OPENAI_STATE_KEY = "openai.chatgpt"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_to_epoch_seconds(iso_utc: str) -> int:
    parsed = dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return int(parsed.timestamp())


def parse_maybe_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


def query_state_db(state_db: Path) -> dict[str, Any]:
    if not state_db.exists():
        return {}

    db_uri = f"file:{state_db}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row
    out: dict[str, Any] = {}
    try:
        placeholders = ",".join("?" for _ in STATE_KEYS)
        rows = conn.execute(
            f"SELECT key, value FROM ItemTable WHERE key IN ({placeholders})",
            STATE_KEYS,
        ).fetchall()
        for row in rows:
            out[row["key"]] = parse_maybe_json(row["value"])

        openai_row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            (OPENAI_STATE_KEY,),
        ).fetchone()
        if openai_row:
            out[OPENAI_STATE_KEY] = parse_maybe_json(openai_row["value"])
    finally:
        conn.close()
    return out


def allowlist_openai_state(openai_state: Any) -> dict[str, Any]:
    if not isinstance(openai_state, dict):
        return {}

    out: dict[str, Any] = {}
    for key in [
        "defaultApprovalDecision",
        "lastProviderId",
        "lastModelId",
        "hasSeenLatestModelBanner",
    ]:
        if key in openai_state:
            out[key] = openai_state[key]

    persisted = openai_state.get("persisted-atom-state")
    if isinstance(persisted, dict):
        persisted_out: dict[str, Any] = {}
        for key in [
            "has-seen-codex-auto-announcement",
            "composer-auto-context-enabled",
            "saw-cursor-tab-discontinue-models",
        ]:
            if key in persisted:
                persisted_out[key] = persisted[key]
        if persisted_out:
            out["persisted-atom-state"] = persisted_out

    return out


def flatten_model_candidates(value: Any) -> list[str]:
    models: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                models.add(item)
    elif isinstance(value, dict):
        for nested in value.values():
            for model in flatten_model_candidates(nested):
                models.add(model)
    elif isinstance(value, str):
        models.add(value)
    return sorted(models)


def collect_pairing_metadata(pairing_root: Path, max_entries: int) -> list[dict[str, Any]]:
    if not pairing_root.exists():
        return []

    entries: list[dict[str, Any]] = []
    for candidate in sorted(pairing_root.glob("Cursor-*")):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        entries.append(
            {
                "file": candidate.name,
                "appName": payload.get("appName"),
                "workspaceName": payload.get("workspaceName"),
                "id": payload.get("id"),
                "timestamp": payload.get("timestamp"),
            }
        )
    entries.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    return entries[:max_entries]


def extract_recent_log_summary(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"exists": False}

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    activation_count = 0
    spawn_count = 0
    first_line = None
    last_line = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if first_line is None:
            first_line = line
        last_line = line
        low = line.lower()
        if "activat" in low:
            activation_count += 1
        if "spawn" in low or "app-server" in low:
            spawn_count += 1

    return {
        "exists": True,
        "line_count": len(lines),
        "activation_line_count": activation_count,
        "spawn_or_app_server_line_count": spawn_count,
        "first_non_empty_line": first_line,
        "last_non_empty_line": last_line,
    }


def collect_extension_logs(logs_root: Path) -> dict[str, Any]:
    if not logs_root.exists():
        return {"latest_session": None, "windows": []}

    sessions = sorted([p for p in logs_root.iterdir() if p.is_dir()])
    if not sessions:
        return {"latest_session": None, "windows": []}

    latest = sessions[-1]
    windows_out: list[dict[str, Any]] = []
    for window_dir in sorted([p for p in latest.iterdir() if p.is_dir() and p.name.startswith("window")]):
        codex_log = window_dir / "exthost" / "openai.chatgpt" / "Codex.log"
        claude_log = window_dir / "exthost" / "Anthropic.claude-code" / "Claude VSCode.log"
        windows_out.append(
            {
                "window": window_dir.name,
                "codex_log": extract_recent_log_summary(codex_log),
                "claude_log": extract_recent_log_summary(claude_log),
            }
        )

    return {"latest_session": latest.name, "windows": windows_out}


def build_snapshot(state_data: dict[str, Any], pairing_data: list[dict[str, Any]], extension_logs: dict[str, Any]) -> dict[str, Any]:
    best_of_n = state_data.get("cursor/bestOfNEnsemblePreferences")
    single_pref = state_data.get("cursor/lastSingleModelPreference")
    openai_state = allowlist_openai_state(state_data.get(OPENAI_STATE_KEY))

    model_candidates = sorted(
        set(flatten_model_candidates(best_of_n) + flatten_model_candidates(single_pref) + flatten_model_candidates(openai_state.get("lastModelId")))
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": utc_now_iso(),
        "cursor_state": {
            "bestOfNEnsemblePreferences": best_of_n,
            "lastSingleModelPreference": single_pref,
            "planExecUseChatModel": state_data.get("cursor/planExecUseChatModel"),
            "newChatModelAutoSwitchApplied": state_data.get("cursor/newChatModelAutoSwitchApplied"),
            "openaiChatgptAllowlisted": openai_state,
        },
        "pairing_sessions": pairing_data,
        "extension_runtime": extension_logs,
        "derived_signals": {
            "candidate_model_pool": model_candidates,
            "per_turn_model_attribution": {
                "status": "unknown",
                "reason": "No authoritative per-turn model identifier found in captured local artifacts.",
            },
            "routing_visibility": "partially_known",
            "routing_visibility_reason": "Ensemble/single-model preference artifacts are available, but runtime per-turn routing decisions are not.",
        },
    }


def write_snapshot(snapshot: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prom_escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_prometheus_textfile(snapshot: dict[str, Any], output_path: Path) -> None:
    derived = snapshot.get("derived_signals", {})
    extension_runtime = snapshot.get("extension_runtime", {})
    windows = extension_runtime.get("windows", [])
    captured_at = snapshot.get("captured_at_utc")
    captured_epoch = iso_to_epoch_seconds(captured_at) if isinstance(captured_at, str) else 0

    candidate_models = derived.get("candidate_model_pool") or []
    pairing_sessions = snapshot.get("pairing_sessions") or []
    routing_visibility = derived.get("routing_visibility")
    per_turn_status = (derived.get("per_turn_model_attribution") or {}).get("status")

    codex_logs_present = sum(1 for w in windows if (w.get("codex_log") or {}).get("exists") is True)
    claude_logs_present = sum(1 for w in windows if (w.get("claude_log") or {}).get("exists") is True)

    lines: list[str] = []
    lines.append("# HELP cursor_exhaust_snapshot_info Snapshot metadata marker.")
    lines.append("# TYPE cursor_exhaust_snapshot_info gauge")
    lines.append(
        'cursor_exhaust_snapshot_info{schema_version="%s"} 1'
        % prom_escape_label(str(snapshot.get("schema_version", "")))
    )
    lines.append("")
    lines.append("# HELP cursor_exhaust_snapshot_captured_unix_seconds Snapshot capture time in unix seconds.")
    lines.append("# TYPE cursor_exhaust_snapshot_captured_unix_seconds gauge")
    lines.append(f"cursor_exhaust_snapshot_captured_unix_seconds {captured_epoch}")
    lines.append("")
    lines.append("# HELP cursor_exhaust_pairing_sessions_count Pairing session records included.")
    lines.append("# TYPE cursor_exhaust_pairing_sessions_count gauge")
    lines.append(f"cursor_exhaust_pairing_sessions_count {len(pairing_sessions)}")
    lines.append("")
    lines.append("# HELP cursor_exhaust_candidate_models_count Candidate model hints count.")
    lines.append("# TYPE cursor_exhaust_candidate_models_count gauge")
    lines.append(f"cursor_exhaust_candidate_models_count {len(candidate_models)}")
    lines.append("")
    lines.append("# HELP cursor_exhaust_extension_windows_count Cursor windows summarized from latest session logs.")
    lines.append("# TYPE cursor_exhaust_extension_windows_count gauge")
    lines.append(f"cursor_exhaust_extension_windows_count {len(windows)}")
    lines.append("")
    lines.append("# HELP cursor_exhaust_codex_logs_present_count Windows with Codex logs present.")
    lines.append("# TYPE cursor_exhaust_codex_logs_present_count gauge")
    lines.append(f"cursor_exhaust_codex_logs_present_count {codex_logs_present}")
    lines.append("")
    lines.append("# HELP cursor_exhaust_claude_logs_present_count Windows with Claude logs present.")
    lines.append("# TYPE cursor_exhaust_claude_logs_present_count gauge")
    lines.append(f"cursor_exhaust_claude_logs_present_count {claude_logs_present}")
    lines.append("")
    lines.append("# HELP cursor_exhaust_routing_visibility_status Routing visibility one-hot status.")
    lines.append("# TYPE cursor_exhaust_routing_visibility_status gauge")
    for status in ["known", "partially_known", "unknown"]:
        value = 1 if routing_visibility == status else 0
        lines.append(
            'cursor_exhaust_routing_visibility_status{status="%s"} %d'
            % (status, value)
        )
    lines.append("")
    lines.append("# HELP cursor_exhaust_per_turn_attribution_status Per-turn attribution visibility one-hot status.")
    lines.append("# TYPE cursor_exhaust_per_turn_attribution_status gauge")
    for status in ["known", "partially_known", "unknown"]:
        value = 1 if per_turn_status == status else 0
        lines.append(
            'cursor_exhaust_per_turn_attribution_status{status="%s"} %d'
            % (status, value)
        )
    lines.append("")
    lines.append("# HELP cursor_exhaust_candidate_model_present Candidate model hint presence.")
    lines.append("# TYPE cursor_exhaust_candidate_model_present gauge")
    for model in candidate_models:
        lines.append(
            'cursor_exhaust_candidate_model_present{model="%s"} 1'
            % prom_escape_label(str(model))
        )
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def cypher_quote(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def snapshot_id(snapshot: dict[str, Any]) -> str:
    captured_at = str(snapshot.get("captured_at_utc", "unknown"))
    return "cursor-exhaust-" + "".join(ch for ch in captured_at if ch.isalnum())


def write_neo4j_cypher(snapshot: dict[str, Any], output_path: Path) -> None:
    sid = snapshot_id(snapshot)
    derived = snapshot.get("derived_signals", {})
    cursor_state = snapshot.get("cursor_state", {})
    extension_runtime = snapshot.get("extension_runtime", {})
    windows = extension_runtime.get("windows", [])
    pairing_sessions = snapshot.get("pairing_sessions", [])

    lines: list[str] = []
    lines.append("// Generated by scripts/extract_cursor_exhaust.py")
    lines.append("MERGE (s:CursorExhaustSnapshot {id: %s})" % cypher_quote(sid))
    lines.append(
        "SET s.captured_at_utc = %s, s.schema_version = %s, s.routing_visibility = %s, s.per_turn_status = %s, s.routing_visibility_reason = %s, s.per_turn_reason = %s"
        % (
            cypher_quote(snapshot.get("captured_at_utc")),
            cypher_quote(snapshot.get("schema_version")),
            cypher_quote(derived.get("routing_visibility")),
            cypher_quote((derived.get("per_turn_model_attribution") or {}).get("status")),
            cypher_quote(derived.get("routing_visibility_reason")),
            cypher_quote((derived.get("per_turn_model_attribution") or {}).get("reason")),
        )
    )
    lines.append(
        "SET s.plan_exec_use_chat_model = %s, s.new_chat_model_auto_switch_applied = %s"
        % (
            cypher_quote(cursor_state.get("planExecUseChatModel")),
            cypher_quote(cursor_state.get("newChatModelAutoSwitchApplied")),
        )
    )
    lines.append(";")
    lines.append("")

    for model in derived.get("candidate_model_pool", []):
        lines.append("MERGE (m:CandidateModel {name: %s})" % cypher_quote(model))
        lines.append("WITH m")
        lines.append("MATCH (s:CursorExhaustSnapshot {id: %s})" % cypher_quote(sid))
        lines.append("MERGE (s)-[:CANDIDATE_MODEL]->(m);")
        lines.append("")

    latest_session = extension_runtime.get("latest_session")
    if latest_session is not None:
        lines.append("MERGE (r:CursorRuntimeSession {name: %s})" % cypher_quote(latest_session))
        lines.append("WITH r")
        lines.append("MATCH (s:CursorExhaustSnapshot {id: %s})" % cypher_quote(sid))
        lines.append("MERGE (s)-[:DERIVED_FROM_RUNTIME]->(r);")
        lines.append("")

    for w in windows:
        window_name = w.get("window")
        codex_log = w.get("codex_log") or {}
        claude_log = w.get("claude_log") or {}
        lines.append("MERGE (w:CursorWindow {name: %s})" % cypher_quote(window_name))
        lines.append(
            "SET w.codex_log_exists = %s, w.codex_log_lines = %s, w.claude_log_exists = %s, w.claude_log_lines = %s"
            % (
                cypher_quote(codex_log.get("exists")),
                cypher_quote(codex_log.get("line_count")),
                cypher_quote(claude_log.get("exists")),
                cypher_quote(claude_log.get("line_count")),
            )
        )
        lines.append("WITH w")
        lines.append("MATCH (s:CursorExhaustSnapshot {id: %s})" % cypher_quote(sid))
        lines.append("MERGE (s)-[:OBSERVED_WINDOW]->(w);")
        lines.append("")

    for p in pairing_sessions:
        session_id = p.get("id") or p.get("file")
        lines.append("MERGE (p:CursorPairingSession {id: %s})" % cypher_quote(session_id))
        lines.append(
            "SET p.file = %s, p.app_name = %s, p.workspace_name = %s, p.timestamp = %s"
            % (
                cypher_quote(p.get("file")),
                cypher_quote(p.get("appName")),
                cypher_quote(p.get("workspaceName")),
                cypher_quote(p.get("timestamp")),
            )
        )
        lines.append("WITH p")
        lines.append("MATCH (s:CursorExhaustSnapshot {id: %s})" % cypher_quote(sid))
        lines.append("MERGE (s)-[:HAS_PAIRING_SESSION]->(p);")
        lines.append("")

        workspace_name = p.get("workspaceName")
        if workspace_name:
            lines.append("MERGE (w:Workspace {name: %s})" % cypher_quote(workspace_name))
            lines.append("WITH w")
            lines.append("MATCH (p:CursorPairingSession {id: %s})" % cypher_quote(session_id))
            lines.append("MERGE (p)-[:WORKSPACE]->(w);")
            lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract local Cursor model-routing exhaust.")
    parser.add_argument(
        "--state-db",
        default=str(Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"),
        help="Path to Cursor global state SQLite DB.",
    )
    parser.add_argument(
        "--cursor-logs-root",
        default=str(Path.home() / "Library" / "Application Support" / "Cursor" / "logs"),
        help="Path to Cursor logs root.",
    )
    parser.add_argument(
        "--pairing-root",
        default=str(Path.home() / "Library" / "Application Support" / "com.openai.chat" / "app_pairing_extensions"),
        help="Path to app pairing metadata files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file path for the snapshot.",
    )
    parser.add_argument(
        "--max-pairings",
        type=int,
        default=25,
        help="Maximum number of pairing metadata records to include (most recent first).",
    )
    parser.add_argument(
        "--prometheus-textfile",
        help="Optional output path for Prometheus textfile metrics (.prom).",
    )
    parser.add_argument(
        "--neo4j-cypher",
        help="Optional output path for Neo4j import Cypher script (.cypher).",
    )
    args = parser.parse_args()

    state_db = Path(args.state_db).expanduser()
    logs_root = Path(args.cursor_logs_root).expanduser()
    pairing_root = Path(args.pairing_root).expanduser()
    output = Path(args.output).expanduser()
    prometheus_textfile = Path(args.prometheus_textfile).expanduser() if args.prometheus_textfile else None
    neo4j_cypher = Path(args.neo4j_cypher).expanduser() if args.neo4j_cypher else None

    state_data = query_state_db(state_db)
    pairing_data = collect_pairing_metadata(pairing_root, max_entries=args.max_pairings)
    extension_logs = collect_extension_logs(logs_root)
    snapshot = build_snapshot(state_data, pairing_data, extension_logs)
    write_snapshot(snapshot, output)
    if prometheus_textfile:
        write_prometheus_textfile(snapshot, prometheus_textfile)
    if neo4j_cypher:
        write_neo4j_cypher(snapshot, neo4j_cypher)

    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output),
                "schema_version": SCHEMA_VERSION,
                "prometheus_textfile": str(prometheus_textfile) if prometheus_textfile else None,
                "neo4j_cypher": str(neo4j_cypher) if neo4j_cypher else None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
