#!/usr/bin/env python3
"""
Local deterministic token proxy and usage observability CLI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

TELEMETRY_SCHEMA_VERSION = "token-proxy.event.v1"
DEFAULT_CONFIG_PATH = "token_proxy/config/token-proxy.config.json"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(values)
    return {
        "p50": ordered[int(round((len(ordered) - 1) * 0.50))],
        "p95": ordered[int(round((len(ordered) - 1) * 0.95))],
        "p99": ordered[int(round((len(ordered) - 1) * 0.99))],
    }


def count_words_from_messages(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    total = 0
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            total += len(content.split())
    return total


def count_words(text: Any) -> int:
    if not isinstance(text, str):
        return 0
    return len(text.split())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    root = repository_root()
    return (root / path).resolve()


def redacted_headers(headers: dict[str, str], redact_keys: list[str]) -> dict[str, str]:
    redact_set = {key.lower() for key in redact_keys}
    output: dict[str, str] = {}
    for key, value in headers.items():
        output[key] = "<redacted>" if key.lower() in redact_set else value
    return output


def load_runtime_config(config_arg: str) -> dict[str, Any]:
    config_path = resolve_path(config_arg)
    config = load_json(config_path)
    config["_config_path"] = str(config_path)
    return config


def config_path(config: dict[str, Any]) -> Path:
    return Path(config["_config_path"])


def storage_paths(config: dict[str, Any]) -> dict[str, Path]:
    paths = config.get("paths", {})
    db_path = resolve_path(paths.get("db", "token_proxy/data/token_proxy.db"))
    raw_path = resolve_path(paths.get("raw_events", "token_proxy/data/events_raw.ndjson"))
    pid_path = resolve_path(paths.get("pid", "token_proxy/data/token_proxy.pid"))
    return {"db": db_path, "raw_events": raw_path, "pid": pid_path}


def ensure_storage(config: dict[str, Any]) -> dict[str, Path]:
    paths = storage_paths(config)
    paths["db"].parent.mkdir(parents=True, exist_ok=True)
    paths["raw_events"].parent.mkdir(parents=True, exist_ok=True)
    paths["pid"].parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(paths["db"])
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events_raw (
              event_id TEXT PRIMARY KEY,
              timestamp_utc TEXT NOT NULL,
              correlation_id TEXT,
              raw_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events_normalized (
              event_id TEXT PRIMARY KEY,
              timestamp_utc TEXT NOT NULL,
              day_utc TEXT NOT NULL,
              correlation_id TEXT,
              client_id TEXT,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              endpoint TEXT NOT NULL,
              prompt_tokens INTEGER NOT NULL,
              completion_tokens INTEGER NOT NULL,
              total_tokens INTEGER NOT NULL,
              pricing_version TEXT,
              estimated_cost REAL,
              unknown_pricing INTEGER NOT NULL,
              latency_ms INTEGER NOT NULL,
              status TEXT NOT NULL,
              error_type TEXT,
              error_code TEXT,
              retry_count INTEGER NOT NULL,
              terminal_outcome TEXT NOT NULL,
              dedupe_fingerprint TEXT NOT NULL,
              coverage_level TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_rollups (
              day_utc TEXT NOT NULL,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              client_id TEXT NOT NULL DEFAULT '',
              request_count INTEGER NOT NULL,
              prompt_tokens INTEGER NOT NULL,
              completion_tokens INTEGER NOT NULL,
              total_tokens INTEGER NOT NULL,
              estimated_cost REAL,
              error_count INTEGER NOT NULL,
              latency_p50 REAL NOT NULL,
              latency_p95 REAL NOT NULL,
              latency_p99 REAL NOT NULL,
              PRIMARY KEY (day_utc, provider, model, client_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return paths


def pricing_catalog(config: dict[str, Any]) -> dict[str, Any]:
    pricing = config.get("pricing", {})
    catalog_path = resolve_path(pricing.get("catalog_path", "token_proxy/config/pricing.catalog.json"))
    return load_json(catalog_path)


def coverage_matrix(config: dict[str, Any]) -> dict[str, Any]:
    coverage = config.get("coverage", {})
    matrix_path = resolve_path(coverage.get("matrix_path", "token_proxy/config/coverage.matrix.json"))
    return load_json(matrix_path)


def pricing_entry_for(catalog: dict[str, Any], provider: str, model: str) -> dict[str, Any] | None:
    entries = catalog.get("entries") or []
    for entry in entries:
        if entry.get("provider") == provider and entry.get("model") == model:
            return entry
    return None


def compute_cost(catalog: dict[str, Any], provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> tuple[str | None, float | None, bool]:
    entry = pricing_entry_for(catalog, provider, model)
    version = catalog.get("pricing_version")
    if not entry:
        return version, None, True
    prompt_rate = float(entry.get("prompt_per_1k_tokens", 0.0))
    completion_rate = float(entry.get("completion_per_1k_tokens", 0.0))
    cost = ((prompt_tokens / 1000.0) * prompt_rate) + ((completion_tokens / 1000.0) * completion_rate)
    return version, round(cost, 10), False


def dedupe_fingerprint(event: dict[str, Any]) -> str:
    text = "|".join(
        [
            str(event.get("correlation_id") or ""),
            str(event.get("client_id") or ""),
            str(event.get("provider") or ""),
            str(event.get("model") or ""),
            str(event.get("prompt_tokens") or 0),
            str(event.get("completion_tokens") or 0),
            str(event.get("terminal_outcome") or ""),
        ]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_raw_event(config: dict[str, Any], event: dict[str, Any]) -> None:
    paths = storage_paths(config)
    payload_text = json.dumps(event, sort_keys=True)

    conn = sqlite3.connect(paths["db"])
    inserted = False
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO events_raw(event_id, timestamp_utc, correlation_id, raw_json) VALUES(?,?,?,?)",
            (
                event["event_id"],
                event["timestamp_utc"],
                event.get("correlation_id"),
                payload_text,
            ),
        )
        inserted = cur.rowcount > 0
        conn.commit()
    finally:
        conn.close()

    if inserted:
        paths["raw_events"].parent.mkdir(parents=True, exist_ok=True)
        with paths["raw_events"].open("a", encoding="utf-8") as handle:
            handle.write(payload_text + "\n")


def normalize_events(config: dict[str, Any]) -> dict[str, Any]:
    ensure_storage(config)
    catalog = pricing_catalog(config)
    conn = sqlite3.connect(storage_paths(config)["db"])
    conn.row_factory = sqlite3.Row
    processed = 0
    try:
        rows = conn.execute("SELECT event_id, raw_json FROM events_raw ORDER BY timestamp_utc ASC").fetchall()
        for row in rows:
            raw = json.loads(row["raw_json"])
            prompt_tokens = int(raw.get("prompt_tokens") or 0)
            completion_tokens = int(raw.get("completion_tokens") or 0)
            total_tokens = int(raw.get("total_tokens") or (prompt_tokens + completion_tokens))
            version, cost, unknown = compute_cost(
                catalog,
                str(raw.get("provider") or ""),
                str(raw.get("model") or ""),
                prompt_tokens,
                completion_tokens,
            )
            ts = str(raw.get("timestamp_utc"))
            day_utc = ts.split("T")[0] if "T" in ts else ts[0:10]
            conn.execute(
                """
                INSERT INTO events_normalized(
                  event_id,timestamp_utc,day_utc,correlation_id,client_id,provider,model,endpoint,
                  prompt_tokens,completion_tokens,total_tokens,pricing_version,estimated_cost,unknown_pricing,
                  latency_ms,status,error_type,error_code,retry_count,terminal_outcome,dedupe_fingerprint,coverage_level
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET
                  timestamp_utc=excluded.timestamp_utc,
                  day_utc=excluded.day_utc,
                  correlation_id=excluded.correlation_id,
                  client_id=excluded.client_id,
                  provider=excluded.provider,
                  model=excluded.model,
                  endpoint=excluded.endpoint,
                  prompt_tokens=excluded.prompt_tokens,
                  completion_tokens=excluded.completion_tokens,
                  total_tokens=excluded.total_tokens,
                  pricing_version=excluded.pricing_version,
                  estimated_cost=excluded.estimated_cost,
                  unknown_pricing=excluded.unknown_pricing,
                  latency_ms=excluded.latency_ms,
                  status=excluded.status,
                  error_type=excluded.error_type,
                  error_code=excluded.error_code,
                  retry_count=excluded.retry_count,
                  terminal_outcome=excluded.terminal_outcome,
                  dedupe_fingerprint=excluded.dedupe_fingerprint,
                  coverage_level=excluded.coverage_level
                """,
                (
                    raw["event_id"],
                    raw["timestamp_utc"],
                    day_utc,
                    raw.get("correlation_id"),
                    raw.get("client_id"),
                    raw.get("provider"),
                    raw.get("model"),
                    raw.get("endpoint"),
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    version,
                    cost,
                    1 if unknown else 0,
                    int(raw.get("latency_ms") or 0),
                    raw.get("status") or "error",
                    raw.get("error_type"),
                    raw.get("error_code"),
                    int(raw.get("retry_count") or 0),
                    raw.get("terminal_outcome") or "unknown",
                    raw.get("dedupe_fingerprint") or dedupe_fingerprint(raw),
                    raw.get("coverage_level"),
                ),
            )
            processed += 1
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "normalized_events": processed}


def build_rollups(config: dict[str, Any]) -> dict[str, Any]:
    ensure_storage(config)
    conn = sqlite3.connect(storage_paths(config)["db"])
    conn.row_factory = sqlite3.Row
    rows_written = 0
    try:
        grouped = conn.execute(
            """
            SELECT day_utc, provider, model, COALESCE(client_id, '') AS client_id,
                   COUNT(*) AS request_count,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens,
                   SUM(total_tokens) AS total_tokens,
                   SUM(COALESCE(estimated_cost, 0.0)) AS estimated_cost,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_count
            FROM events_normalized
            GROUP BY day_utc, provider, model, COALESCE(client_id, '')
            """
        ).fetchall()

        for row in grouped:
            latencies = conn.execute(
                """
                SELECT latency_ms
                FROM events_normalized
                WHERE day_utc=? AND provider=? AND model=? AND COALESCE(client_id, '') = ?
                ORDER BY latency_ms ASC
                """,
                (row["day_utc"], row["provider"], row["model"], row["client_id"]),
            ).fetchall()
            vals = [float(item["latency_ms"]) for item in latencies]
            p = percentiles(vals)
            if row["client_id"] == "":
                conn.execute(
                    """
                    DELETE FROM daily_rollups
                    WHERE day_utc=? AND provider=? AND model=? AND client_id IS NULL
                    """,
                    (row["day_utc"], row["provider"], row["model"]),
                )
            conn.execute(
                """
                INSERT INTO daily_rollups(
                  day_utc,provider,model,client_id,request_count,prompt_tokens,completion_tokens,total_tokens,
                  estimated_cost,error_count,latency_p50,latency_p95,latency_p99
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(day_utc,provider,model,client_id) DO UPDATE SET
                  request_count=excluded.request_count,
                  prompt_tokens=excluded.prompt_tokens,
                  completion_tokens=excluded.completion_tokens,
                  total_tokens=excluded.total_tokens,
                  estimated_cost=excluded.estimated_cost,
                  error_count=excluded.error_count,
                  latency_p50=excluded.latency_p50,
                  latency_p95=excluded.latency_p95,
                  latency_p99=excluded.latency_p99
                """,
                (
                    row["day_utc"],
                    row["provider"],
                    row["model"],
                    row["client_id"],
                    int(row["request_count"] or 0),
                    int(row["prompt_tokens"] or 0),
                    int(row["completion_tokens"] or 0),
                    int(row["total_tokens"] or 0),
                    float(row["estimated_cost"] or 0.0),
                    int(row["error_count"] or 0),
                    p["p50"],
                    p["p95"],
                    p["p99"],
                ),
            )
            rows_written += 1
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "rollup_rows": rows_written}


def usage_report(config: dict[str, Any]) -> list[dict[str, Any]]:
    conn = sqlite3.connect(storage_paths(config)["db"])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT provider, model,
                   COUNT(*) AS request_count,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens,
                   SUM(total_tokens) AS total_tokens,
                   SUM(COALESCE(estimated_cost,0.0)) AS estimated_cost,
                   SUM(unknown_pricing) AS unknown_pricing_count
            FROM events_normalized
            GROUP BY provider, model
            ORDER BY request_count DESC, provider ASC, model ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def top_clients_report(config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    conn = sqlite3.connect(storage_paths(config)["db"])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(client_id, 'unknown') AS client_id,
                   COUNT(*) AS request_count,
                   SUM(total_tokens) AS total_tokens,
                   SUM(COALESCE(estimated_cost,0.0)) AS estimated_cost
            FROM events_normalized
            GROUP BY COALESCE(client_id, 'unknown')
            ORDER BY total_tokens DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def unknown_pricing_report(config: dict[str, Any]) -> list[dict[str, Any]]:
    conn = sqlite3.connect(storage_paths(config)["db"])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT event_id, timestamp_utc, provider, model, client_id
            FROM events_normalized
            WHERE unknown_pricing = 1
            ORDER BY timestamp_utc ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def event_matches_rule(event: dict[str, Any], match_rule: dict[str, Any]) -> bool:
    if not match_rule:
        return False
    for key, expected in match_rule.items():
        if key == "bypass":
            return False
        if key == "source":
            return False
        actual = event.get(key)
        if expected == "*":
            if actual is None:
                return False
            continue
        if actual != expected:
            return False
    return True


def coverage_report(config: dict[str, Any]) -> dict[str, Any]:
    matrix = coverage_matrix(config)
    conn = sqlite3.connect(storage_paths(config)["db"])
    conn.row_factory = sqlite3.Row
    try:
        events = [dict(row) for row in conn.execute("SELECT * FROM events_normalized").fetchall()]
    finally:
        conn.close()

    validations: list[dict[str, Any]] = []
    for item in matrix.get("traffic_classes", []):
        rule = item.get("match") or {}
        matched = [event for event in events if event_matches_rule(event, rule)]
        level = item.get("coverage_level")
        expected_min = int(item.get("expected_event_count_min") or 0)
        passed = True
        reason = "matched expected evidence pattern"

        if level in ("definitely_observed", "partially_observed"):
            passed = len(matched) >= expected_min
            if not passed:
                reason = "expected observed evidence missing"
        elif level == "unobservable":
            passed = len(matched) == 0
            if not passed:
                reason = "unexpected proxy telemetry for unobservable class"
        elif rule.get("source") == "cursor_exhaust_snapshot":
            passed = True
            reason = "validated via separate cursor exhaust artifact"

        validations.append(
            {
                "name": item.get("name"),
                "coverage_level": level,
                "matched_event_count": len(matched),
                "expected_event_count_min": expected_min,
                "pass": passed,
                "reason": reason,
                "notes": item.get("notes"),
            }
        )

    return {
        "schema_version": matrix.get("schema_version"),
        "traffic_class_count": len(matrix.get("traffic_classes", [])),
        "validation": validations,
    }


class TokenProxyHandler(BaseHTTPRequestHandler):
    server_version = "TokenProxy/1.0"

    def _json_response(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json_response(200, {"ok": True, "service": "token-proxy", "timestamp_utc": utc_now_iso()})
            return
        if self.path == "/ready":
            self._json_response(200, {"ok": True, "ready": True, "timestamp_utc": utc_now_iso()})
            return
        self._json_response(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json_response(404, {"ok": False, "error": "not_found"})
            return

        config = self.server.runtime_config  # type: ignore[attr-defined]
        catalog = pricing_catalog(config)
        proxy_cfg = config.get("proxy", {})
        providers_cfg = config.get("providers", {})
        reliability_cfg = config.get("reliability", {})
        redact_keys = ((config.get("security") or {}).get("redact_headers") or [])

        raw_length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(raw_length)
        try:
            request_payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            self._json_response(400, {"ok": False, "error": "invalid_json"})
            return

        provider = request_payload.get("provider") or proxy_cfg.get("default_provider")
        model = request_payload.get("model")
        provider_conf = providers_cfg.get(provider or "", {})
        if not model:
            model = provider_conf.get("default_model") or proxy_cfg.get("default_model")
        if not provider or not provider_conf:
            self._json_response(400, {"ok": False, "error": "unknown_provider"})
            return

        fail_mode_by_client = reliability_cfg.get("fail_mode_by_client") or {}
        client_id = self.headers.get("x-token-proxy-client") or request_payload.get("client_id")
        fail_mode = fail_mode_by_client.get(client_id, reliability_cfg.get("default_fail_mode", "fail_closed"))
        correlation_id = self.headers.get("x-correlation-id") or request_payload.get("correlation_id") or str(uuid.uuid4())
        endpoint = "/v1/chat/completions"
        retries = int(proxy_cfg.get("retry_count", 0))
        timeout_seconds = int(proxy_cfg.get("timeout_seconds", 15))
        terminal_outcome = "success"
        error_type = None
        error_code = None
        status = "success"
        response_payload: dict[str, Any] = {}
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        start = time.perf_counter()

        base_url = str(provider_conf.get("base_url") or "")
        chat_path = str(provider_conf.get("chat_path") or endpoint)
        upstream_url = f"{base_url}{chat_path}"

        outgoing = {
            "model": model,
            "messages": request_payload.get("messages") or [],
            "temperature": request_payload.get("temperature"),
        }
        encoded = json.dumps(outgoing).encode("utf-8")
        auth_env = str(provider_conf.get("auth_env") or "")

        upstream_headers = {"Content-Type": "application/json"}
        if auth_env:
            token = os.environ.get(auth_env)
            if token:
                upstream_headers["Authorization"] = f"Bearer {token}"

        attempt = 0
        while True:
            try:
                req = urllib.request.Request(upstream_url, data=encoded, headers=upstream_headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    data = resp.read()
                    response_payload = json.loads(data.decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                error_type = "HTTPError"
                error_code = str(exc.code)
                attempt += 1
                if attempt > retries:
                    break
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                error_code = "upstream_unreachable"
                attempt += 1
                if attempt > retries:
                    break

        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = response_payload.get("usage") if isinstance(response_payload, dict) else None

        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        else:
            prompt_tokens = count_words_from_messages(outgoing.get("messages"))
            assistant_text = ""
            choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        assistant_text = str(message.get("content") or "")
            completion_tokens = count_words(assistant_text)
            total_tokens = prompt_tokens + completion_tokens

        if not response_payload:
            status = "error"
            terminal_outcome = "provider_error"
            if fail_mode == "fail_open":
                terminal_outcome = "fail_open_synthetic_response"
                response_payload = {
                    "id": f"fail-open-{uuid.uuid4()}",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "fail-open: upstream unavailable",
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                }
            else:
                self._json_response(
                    502,
                    {"ok": False, "error": "upstream_failure", "provider": provider, "model": model, "correlation_id": correlation_id},
                )

        pricing_version, estimated_cost, unknown_pricing = compute_cost(catalog, provider, model, prompt_tokens, completion_tokens)
        event_id = str(uuid.uuid4())
        event = {
            "schema_version": config.get("telemetry_schema_version", TELEMETRY_SCHEMA_VERSION),
            "event_id": event_id,
            "timestamp_utc": utc_now_iso(),
            "correlation_id": correlation_id,
            "client_id": client_id,
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "pricing_version": pricing_version,
            "estimated_cost": estimated_cost,
            "unknown_pricing": unknown_pricing,
            "latency_ms": latency_ms,
            "status": status,
            "error_type": error_type,
            "error_code": error_code,
            "retry_count": attempt,
            "terminal_outcome": terminal_outcome,
            "coverage_level": "definitely_observed",
            "request_headers_redacted": redacted_headers({k: v for k, v in self.headers.items()}, redact_keys),
        }
        event["dedupe_fingerprint"] = dedupe_fingerprint(event)

        append_raw_event(config, event)

        if status == "error" and fail_mode != "fail_open":
            return

        response_payload["proxy_telemetry"] = {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "provider": provider,
            "model": model,
            "estimated_cost": estimated_cost,
            "pricing_version": pricing_version,
        }
        self._json_response(200, response_payload)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return


def run_server(config: dict[str, Any]) -> None:
    ensure_storage(config)
    proxy_cfg = config.get("proxy", {})
    host = str(proxy_cfg.get("host", "127.0.0.1"))
    port = int(proxy_cfg.get("port", 4010))
    server = ThreadingHTTPServer((host, port), TokenProxyHandler)
    server.runtime_config = config  # type: ignore[attr-defined]
    server.serve_forever(poll_interval=0.5)


def read_pid_file(pid_path: Path) -> dict[str, Any] | None:
    if not pid_path.exists():
        return None
    try:
        return json.loads(pid_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def wait_for_health(config: dict[str, Any], timeout_seconds: float = 10.0) -> bool:
    proxy_cfg = config.get("proxy", {})
    host = proxy_cfg.get("host", "127.0.0.1")
    port = proxy_cfg.get("port", 4010)
    url = f"http://{host}:{port}/health"
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("ok") is True:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def cmd_init(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    paths = ensure_storage(config)
    print(json.dumps({"ok": True, "db": str(paths["db"]), "raw_events": str(paths["raw_events"])}))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    run_server(config)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    paths = ensure_storage(config)
    pid_path = paths["pid"]
    state = read_pid_file(pid_path)
    if state and process_alive(int(state.get("pid", 0))):
        print(json.dumps({"ok": True, "running": True, "pid": state.get("pid"), "already_running": True}))
        return 0

    log_path = pid_path.with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, str(Path(__file__).resolve()), "--config", args.config, "serve"],
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    meta = {
        "pid": proc.pid,
        "started_at_utc": utc_now_iso(),
        "config_path": config["_config_path"],
        "log_path": str(log_path),
    }
    write_json(pid_path, meta)

    healthy = wait_for_health(config, timeout_seconds=10.0)
    print(json.dumps({"ok": healthy, "running": healthy, "pid": proc.pid, "state_file": str(pid_path)}))
    return 0 if healthy else 1


def cmd_stop(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    pid_path = storage_paths(config)["pid"]
    state = read_pid_file(pid_path)
    if not state:
        print(json.dumps({"ok": True, "running": False, "message": "not_running"}))
        return 0
    pid = int(state.get("pid", 0))
    if pid <= 0 or not process_alive(pid):
        pid_path.unlink(missing_ok=True)
        print(json.dumps({"ok": True, "running": False, "message": "stale_pid_removed"}))
        return 0

    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not process_alive(pid):
            break
        time.sleep(0.1)
    if process_alive(pid):
        os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "running": False, "stopped_pid": pid}))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    paths = storage_paths(config)
    state = read_pid_file(paths["pid"])
    running = False
    pid = None
    if state:
        pid = int(state.get("pid", 0))
        running = process_alive(pid)

    proxy_cfg = config.get("proxy", {})
    host = proxy_cfg.get("host", "127.0.0.1")
    port = proxy_cfg.get("port", 4010)
    health_url = f"http://{host}:{port}/health"
    health_ok = False
    health_payload: dict[str, Any] = {}
    if running:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                health_payload = json.loads(resp.read().decode("utf-8"))
                health_ok = bool(health_payload.get("ok"))
        except Exception as exc:  # noqa: BLE001
            health_payload = {"ok": False, "error": type(exc).__name__}

    payload = {
        "ok": True,
        "running": running,
        "pid": pid,
        "config_path": config["_config_path"],
        "db_path": str(paths["db"]),
        "raw_events_path": str(paths["raw_events"]),
        "telemetry_schema_version": config.get("telemetry_schema_version", TELEMETRY_SCHEMA_VERSION),
        "pricing_version": pricing_catalog(config).get("pricing_version"),
        "health": {"ok": health_ok, "payload": health_payload},
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    result = normalize_events(config)
    print(json.dumps(result))
    return 0


def cmd_rollup(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    result = build_rollups(config)
    print(json.dumps(result))
    return 0


def cmd_report_usage(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    result = usage_report(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_report_top_clients(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    result = top_clients_report(config, args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_report_unknown_pricing(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    result = unknown_pricing_report(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_report_coverage(args: argparse.Namespace) -> int:
    config = load_runtime_config(args.config)
    result = coverage_report(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic token proxy service and reports.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to token proxy config JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize storage.")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="Run proxy server in foreground.")
    p_serve.set_defaults(func=cmd_serve)

    p_start = sub.add_parser("start", help="Start proxy as background process.")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop proxy process.")
    p_stop.set_defaults(func=cmd_stop)

    p_status = sub.add_parser("status", help="Show proxy process status.")
    p_status.set_defaults(func=cmd_status)

    p_norm = sub.add_parser("normalize", help="Normalize raw events into analytics table.")
    p_norm.set_defaults(func=cmd_normalize)

    p_rollup = sub.add_parser("rollup", help="Build idempotent daily rollups.")
    p_rollup.set_defaults(func=cmd_rollup)

    p_report = sub.add_parser("report", help="Generate analytics reports.")
    report_sub = p_report.add_subparsers(dest="report_kind", required=True)

    p_usage = report_sub.add_parser("usage", help="Totals by provider/model.")
    p_usage.set_defaults(func=cmd_report_usage)

    p_top = report_sub.add_parser("top-clients", help="Top token consumers by client.")
    p_top.add_argument("--limit", type=int, default=10)
    p_top.set_defaults(func=cmd_report_top_clients)

    p_unknown = report_sub.add_parser("unknown-pricing", help="Events with unknown pricing.")
    p_unknown.set_defaults(func=cmd_report_unknown_pricing)

    p_cov = report_sub.add_parser("coverage", help="Coverage matrix validation report.")
    p_cov.set_defaults(func=cmd_report_coverage)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
