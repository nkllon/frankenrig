#!/usr/bin/env python3
"""
End-to-end execution harness for docs/sdd/token-proxy/session-seed-prompt.md.
"""

from __future__ import annotations

import datetime as dt
import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jsonschema


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_cmd(command: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=False)  # noqa: S603
    payload = {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(payload, indent=2))
    return payload


def find_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(values)
    return {
        "p50": ordered[int(round((len(ordered) - 1) * 0.50))],
        "p95": ordered[int(round((len(ordered) - 1) * 0.95))],
        "p99": ordered[int(round((len(ordered) - 1) * 0.99))],
    }


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json_with_status(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"status": int(resp.status), "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8")
        parsed = json.loads(data) if data else {}
        return {"status": int(exc.code), "body": parsed}


def get_json_with_status(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"status": int(resp.status), "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8")
        parsed = json.loads(data) if data else {}
        return {"status": int(exc.code), "body": parsed}


class MockProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length)
        request_payload = json.loads(body.decode("utf-8")) if body else {}

        model = request_payload.get("model") or self.server.model_name  # type: ignore[attr-defined]
        usage = self.server.usage  # type: ignore[attr-defined]
        provider = self.server.provider_name  # type: ignore[attr-defined]
        text = self.server.reply_text  # type: ignore[attr-defined]

        response_payload = {
            "id": f"{provider}-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "provider": provider,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text,
                    },
                }
            ],
            "usage": usage,
        }
        data = json.dumps(response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return


def start_mock_provider(port: int, provider_name: str, model_name: str, usage: dict[str, int], reply_text: str) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", port), MockProviderHandler)
    server.provider_name = provider_name  # type: ignore[attr-defined]
    server.model_name = model_name  # type: ignore[attr-defined]
    server.usage = usage  # type: ignore[attr-defined]
    server.reply_text = reply_text  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def db_count_events(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        value = conn.execute("SELECT COUNT(*) FROM events_raw").fetchone()[0]
        return int(value)
    finally:
        conn.close()


def collect_db_samples(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        raw_rows = conn.execute("SELECT event_id, timestamp_utc, correlation_id, raw_json FROM events_raw ORDER BY timestamp_utc ASC LIMIT 10").fetchall()
        normalized_rows = conn.execute("SELECT * FROM events_normalized ORDER BY timestamp_utc ASC LIMIT 20").fetchall()
        rollup_rows = conn.execute("SELECT * FROM daily_rollups ORDER BY day_utc ASC, provider ASC, model ASC LIMIT 20").fetchall()
    finally:
        conn.close()

    parsed_raw = []
    for row in raw_rows:
        parsed = dict(row)
        parsed["raw_json"] = json.loads(parsed["raw_json"])
        parsed_raw.append(parsed)
    return {
        "events_raw_sample": parsed_raw,
        "events_normalized_sample": [dict(row) for row in normalized_rows],
        "daily_rollups_sample": [dict(row) for row in rollup_rows],
    }


def expected_cost(prompt_tokens: int, completion_tokens: int, prompt_per_1k: float, completion_per_1k: float) -> float:
    return round((prompt_tokens / 1000.0) * prompt_per_1k + (completion_tokens / 1000.0) * completion_per_1k, 10)


def main() -> int:
    root = repo_root()
    stamp = utc_stamp()
    bundle = root / "evidence" / "token_proxy" / stamp
    runtime = bundle / "runtime"
    bundle.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)

    python_bin = Path(sys.executable)
    token_proxy_script = root / "scripts" / "token_proxy.py"
    extract_script = root / "scripts" / "extract_cursor_exhaust.py"
    schema_path = root / "docs" / "sdd" / "token-proxy" / "cursor-exhaust.schema.json"
    base_config_path = root / "token_proxy" / "config" / "token-proxy.config.json"
    pricing_base_path = root / "token_proxy" / "config" / "pricing.catalog.json"
    coverage_base_path = root / "token_proxy" / "config" / "coverage.matrix.json"

    bootstrap = {}
    bootstrap["node"] = run_cmd(["node", "-v"], root)
    bootstrap["npm"] = run_cmd(["npm", "-v"], root)
    bootstrap["cc_sdd"] = run_cmd(["cc-sdd", "--version"], root)
    write_json(bundle / "bootstrap_checks.json", bootstrap)

    openai_port = find_free_port()
    anthropic_port = find_free_port()
    proxy_port = find_free_port()

    openai_usage = {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}
    anthropic_usage = {"prompt_tokens": 90, "completion_tokens": 60, "total_tokens": 150}

    openai_server, openai_thread = start_mock_provider(
        openai_port,
        "openai_mock",
        "gpt-4.1-mini",
        openai_usage,
        "openai mock response",
    )
    anthropic_server, anthropic_thread = start_mock_provider(
        anthropic_port,
        "anthropic_mock",
        "claude-3-7-sonnet",
        anthropic_usage,
        "anthropic mock response",
    )

    runtime_pricing_path = runtime / "pricing.catalog.json"
    runtime_coverage_path = runtime / "coverage.matrix.json"
    runtime_coverage_proofs_path = runtime / "coverage.proofs.json"
    runtime_pricing_path.write_text(pricing_base_path.read_text(encoding="utf-8"), encoding="utf-8")
    runtime_coverage_path.write_text(coverage_base_path.read_text(encoding="utf-8"), encoding="utf-8")
    write_json(runtime_coverage_proofs_path, {"proof_by_class": {}})

    config = read_json(base_config_path)
    config["proxy"]["host"] = "127.0.0.1"
    config["proxy"]["port"] = proxy_port
    config["providers"]["openai_mock"]["base_url"] = f"http://127.0.0.1:{openai_port}"
    config["providers"]["anthropic_mock"]["base_url"] = f"http://127.0.0.1:{anthropic_port}"
    config["paths"]["db"] = str(runtime / "token_proxy.db")
    config["paths"]["raw_events"] = str(runtime / "events_raw.ndjson")
    config["paths"]["pid"] = str(runtime / "token_proxy.pid")
    config["pricing"]["catalog_path"] = str(runtime_pricing_path)
    config["coverage"]["matrix_path"] = str(runtime_coverage_path)
    config["coverage"]["proofs_path"] = str(runtime_coverage_proofs_path)
    runtime_config_path = runtime / "token-proxy.runtime.config.json"
    write_json(runtime_config_path, config)
    write_json(bundle / "redacted_config_snapshot.json", config)

    proxy_url = f"http://127.0.0.1:{proxy_port}/v1/chat/completions"
    openai_direct_url = f"http://127.0.0.1:{openai_port}/v1/chat/completions"
    anthropic_direct_url = f"http://127.0.0.1:{anthropic_port}/v1/chat/completions"

    start_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "start"]
    status_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "status"]
    stop_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "stop"]
    normalize_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "normalize"]
    rollup_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "rollup"]
    usage_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "report", "usage"]
    top_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "report", "top-clients", "--limit", "10"]
    unknown_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "report", "unknown-pricing"]
    coverage_cmd = [str(python_bin), str(token_proxy_script), "--config", str(runtime_config_path), "report", "coverage"]
    degraded_config_path = runtime / "token-proxy.telemetry-degraded.config.json"
    degraded_stop_cmd = [str(python_bin), str(token_proxy_script), "--config", str(degraded_config_path), "stop"]

    validation_checks: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    coverage_proof_by_class: dict[str, dict[str, Any]] = {}

    try:
        run_cmd(start_cmd, root)
        status_payload = run_cmd(status_cmd, root)
        db_path = runtime / "token_proxy.db"
        write_json(bundle / "health_status_output.json", {"status_stdout": status_payload["stdout"], "status_stderr": status_payload["stderr"]})
        ready_ok = get_json_with_status(f"http://127.0.0.1:{proxy_port}/ready")
        validation_checks.append(
            {
                "id": "ready_endpoint_reports_actual_readiness",
                "pass": ready_ok.get("status") == 200 and bool((ready_ok.get("body") or {}).get("ready")),
                "details": ready_ok,
            }
        )
        ready_count_before = db_count_events(db_path)
        for _ in range(3):
            get_json_with_status(f"http://127.0.0.1:{proxy_port}/ready")
        ready_count_after = db_count_events(db_path)
        ready_side_effect_pass = ready_count_before == ready_count_after
        validation_checks.append(
            {
                "id": "ready_endpoint_side_effects_reversible",
                "pass": ready_side_effect_pass,
                "details": {
                    "events_raw_count_before": ready_count_before,
                    "events_raw_count_after": ready_count_after,
                },
            }
        )
        write_json(
            bundle / "readiness_side_effects_check.json",
            {
                "pass": ready_side_effect_pass,
                "events_raw_count_before": ready_count_before,
                "events_raw_count_after": ready_count_after,
            },
        )

        call_one_payload = {
            "provider": "openai_mock",
            "model": "gpt-4.1-mini",
            "messages": [{"role": "user", "content": "Summarize today in one sentence."}],
        }
        call_two_payload = {
            "provider": "anthropic_mock",
            "model": "claude-3-7-sonnet",
            "messages": [{"role": "user", "content": "List two reliability controls."}],
        }
        call_unknown_model_payload = {
            "provider": "openai_mock",
            "model": "unknown-model-x",
            "messages": [{"role": "user", "content": "Respond with one token."}],
        }
        resp_one = post_json(
            proxy_url,
            call_one_payload,
            headers={"x-token-proxy-client": "seed-runner-a", "x-correlation-id": "seed-call-openai"},
        )
        resp_two = post_json(
            proxy_url,
            call_two_payload,
            headers={"x-token-proxy-client": "seed-runner-b", "x-correlation-id": "seed-call-anthropic"},
        )
        responses.append(resp_one)
        responses.append(resp_two)
        resp_unknown = post_json(
            proxy_url,
            call_unknown_model_payload,
            headers={"x-token-proxy-client": "seed-runner-unknown", "x-correlation-id": "seed-call-unknown-model"},
        )
        responses.append(resp_unknown)
        write_json(bundle / "proxy_call_responses.json", responses)

        unknown_provider_payload = {
            "provider": "missing_provider",
            "model": "x",
            "messages": [{"role": "user", "content": "test"}],
        }
        unknown_provider_result = post_json_with_status(
            proxy_url,
            unknown_provider_payload,
            headers={"x-token-proxy-client": "seed-runner-protocol", "x-correlation-id": "seed-protocol-unknown-provider"},
        )
        unknown_provider_pass = (
            unknown_provider_result.get("status") == 400
            and (unknown_provider_result.get("body") or {}).get("error") == "unknown_provider"
        )
        validation_checks.append(
            {
                "id": "unknown_provider_rejected",
                "pass": unknown_provider_pass,
                "details": unknown_provider_result,
            }
        )

        unsupported_path_result = post_json_with_status(
            f"http://127.0.0.1:{proxy_port}/v1/unsupported",
            call_one_payload,
            headers={"x-token-proxy-client": "seed-runner-protocol", "x-correlation-id": "seed-protocol-unsupported-path"},
        )
        unsupported_path_pass = (
            unsupported_path_result.get("status") == 404
            and (unsupported_path_result.get("body") or {}).get("error") == "not_found"
        )
        validation_checks.append(
            {
                "id": "unsupported_path_returns_404",
                "pass": unsupported_path_pass,
                "details": unsupported_path_result,
            }
        )
        write_json(
            bundle / "protocol_behavior.json",
            {
                "unknown_provider_result": unknown_provider_result,
                "unsupported_path_result": unsupported_path_result,
            },
        )

        raw_count_before_direct = db_count_events(db_path)
        
        # Negative proof for proxy_chat_observed: /health calls are not logged
        get_json_with_status(f"http://127.0.0.1:{proxy_port}/health")
        count_after_health = db_count_events(db_path)
        
        coverage_proof_by_class["proxy_chat_observed"] = {
            "positive_proof": raw_count_before_direct >= 2,
            "negative_proof": raw_count_before_direct == count_after_health,
            "details": {
                "raw_count_before_direct": raw_count_before_direct,
                "count_after_health": count_after_health
            },
        }

        direct_latencies: list[float] = []
        for idx in range(20):
            if idx % 2 == 0:
                target = openai_direct_url
                payload = call_one_payload
            else:
                target = anthropic_direct_url
                payload = call_two_payload
            start = time.perf_counter()
            post_json(target, payload)
            direct_latencies.append((time.perf_counter() - start) * 1000.0)

        raw_count_after_direct = db_count_events(db_path)
        bypass_unchanged = raw_count_before_direct == raw_count_after_direct
        validation_checks.append(
            {
                "id": "coverage_direct_bypass_not_logged",
                "pass": bypass_unchanged,
                "details": {
                    "raw_count_before_direct": raw_count_before_direct,
                    "raw_count_after_direct": raw_count_after_direct,
                },
            }
        )
        coverage_proof_by_class["direct_provider_bypass"] = {
            "positive_proof": bypass_unchanged,
            "negative_proof": raw_count_before_direct > 0,
            "details": {
                "raw_count_before_direct": raw_count_before_direct,
                "raw_count_after_direct": raw_count_after_direct,
            },
        }

        proxy_latencies: list[float] = []
        for idx in range(20):
            if idx % 2 == 0:
                payload = call_one_payload
                client = "perf-proxy-openai"
            else:
                payload = call_two_payload
                client = "perf-proxy-anthropic"
            start = time.perf_counter()
            post_json(proxy_url, payload, headers={"x-token-proxy-client": client})
            proxy_latencies.append((time.perf_counter() - start) * 1000.0)

        run_cmd(normalize_cmd, root)
        run_cmd(rollup_cmd, root)
        samples_first = collect_db_samples(db_path)
        run_cmd(normalize_cmd, root)
        run_cmd(rollup_cmd, root)
        samples_second = collect_db_samples(db_path)
        idempotent = (
            samples_first["events_normalized_sample"] == samples_second["events_normalized_sample"]
            and samples_first["daily_rollups_sample"] == samples_second["daily_rollups_sample"]
        )
        validation_checks.append(
            {
                "id": "normalize_rollup_idempotent_rerun",
                "pass": idempotent,
                "details": {
                    "normalized_rows_first": len(samples_first["events_normalized_sample"]),
                    "normalized_rows_second": len(samples_second["events_normalized_sample"]),
                    "rollup_rows_first": len(samples_first["daily_rollups_sample"]),
                    "rollup_rows_second": len(samples_second["daily_rollups_sample"]),
                },
            }
        )
        write_json(bundle / "idempotency_rerun_check.json", {"pass": idempotent})

        usage_report = json.loads(run_cmd(usage_cmd, root)["stdout"])
        top_clients_report = json.loads(run_cmd(top_cmd, root)["stdout"])
        unknown_pricing_report = json.loads(run_cmd(unknown_cmd, root)["stdout"])

        write_json(bundle / "usage_by_provider_model.json", usage_report)
        write_json(bundle / "top_token_consumers_by_client.json", top_clients_report)
        write_json(bundle / "unknown_uncosted_calls.json", unknown_pricing_report)

        samples = collect_db_samples(db_path)
        write_json(bundle / "sample_raw_events.json", samples["events_raw_sample"])
        write_json(bundle / "normalized_events_sample.json", samples["events_normalized_sample"])
        write_json(bundle / "daily_rollup_sample.json", samples["daily_rollups_sample"])

        secret_probe = post_json(
            proxy_url,
            call_one_payload,
            headers={
                "x-token-proxy-client": "secret-injector",
                "x-correlation-id": "secret-header-injection",
                "authorization": "Bearer NEVER_PERSIST_THIS",
                "x-api-key": "NEVER_PERSIST_KEY",
            },
        )
        write_json(bundle / "secret_header_injection_result.json", secret_probe)
        prove_secrets_cmd = [
            str(python_bin),
            str(token_proxy_script),
            "--config",
            str(runtime_config_path),
            "prove-secrets",
        ]
        prove_secrets_result = json.loads(run_cmd(prove_secrets_cmd, root)["stdout"])
        secret_count = int(prove_secrets_result.get("count") or 0)
        secret_found = secret_count > 0
        write_json(bundle / "prove_secrets_output.json", prove_secrets_result)
        validation_checks.append(
            {
                "id": "secret_header_injection_non_persistence",
                "pass": not secret_found,
                "details": {
                    "secret_found_in_persisted_events": secret_found,
                    "prove_secrets_count": secret_count,
                },
            }
        )
        write_json(bundle / "secret_header_non_persistence.json", {"pass": not secret_found})

        direct_p = percentiles(direct_latencies)
        proxy_p = percentiles(proxy_latencies)
        overhead = {
            "p50": round(proxy_p["p50"] - direct_p["p50"], 3),
            "p95": round(proxy_p["p95"] - direct_p["p95"], 3),
            "p99": round(proxy_p["p99"] - direct_p["p99"], 3),
        }
        write_json(
            bundle / "performance_overhead.json",
            {
                "direct_ms": direct_p,
                "proxy_ms": proxy_p,
                "proxy_minus_direct_ms": overhead,
                "sample_size": 20,
            },
        )

        run_cmd(stop_cmd, root)
        degraded_cfg = read_json(runtime_config_path)
        degraded_cfg["paths"]["raw_events"] = str(runtime / "sink_down")
        (runtime / "sink_down").mkdir(parents=True, exist_ok=True)
        degraded_cfg["reliability"]["default_fail_mode"] = "fail_closed"
        degraded_cfg["reliability"]["fail_mode_by_client"] = {
            "telemetry-open": "fail_open",
            "telemetry-closed": "fail_closed",
        }
        write_json(degraded_config_path, degraded_cfg)
        degraded_start_cmd = [str(python_bin), str(token_proxy_script), "--config", str(degraded_config_path), "start"]
        run_cmd(degraded_start_cmd, root)
        degrade_open = post_json_with_status(
            proxy_url,
            call_one_payload,
            headers={"x-token-proxy-client": "telemetry-open", "x-correlation-id": "telemetry-sink-open"},
        )
        degrade_closed = post_json_with_status(
            proxy_url,
            call_one_payload,
            headers={"x-token-proxy-client": "telemetry-closed", "x-correlation-id": "telemetry-sink-closed"},
        )
        telemetry_pass = (
            degrade_open.get("status") == 200
            and bool(((degrade_open.get("body") or {}).get("proxy_telemetry") or {}).get("telemetry_sink_degraded"))
            and degrade_closed.get("status") == 503
            and (degrade_closed.get("body") or {}).get("error") == "telemetry_sink_failure"
        )
        validation_checks.append(
            {
                "id": "telemetry_sink_degradation_fail_open_and_fail_closed",
                "pass": telemetry_pass,
                "details": {"fail_open_result": degrade_open, "fail_closed_result": degrade_closed},
            }
        )
        write_json(
            bundle / "telemetry_sink_degradation.json",
            {"pass": telemetry_pass, "fail_open_result": degrade_open, "fail_closed_result": degrade_closed},
        )
        run_cmd(degraded_stop_cmd, root)

        not_ready_cfg = read_json(runtime_config_path)
        not_ready_cfg["pricing"]["catalog_path"] = str(runtime / "missing-pricing.catalog.json")
        not_ready_config_path = runtime / "token-proxy.not-ready.config.json"
        write_json(not_ready_config_path, not_ready_cfg)
        not_ready_start_cmd = [str(python_bin), str(token_proxy_script), "--config", str(not_ready_config_path), "start"]
        not_ready_stop_cmd = [str(python_bin), str(token_proxy_script), "--config", str(not_ready_config_path), "stop"]
        run_cmd(not_ready_start_cmd, root)
        ready_bad = get_json_with_status(f"http://127.0.0.1:{proxy_port}/ready")
        ready_bad_pass = ready_bad.get("status") == 503 and not bool((ready_bad.get("body") or {}).get("ready"))
        validation_checks.append(
            {
                "id": "ready_endpoint_detects_dependency_failure",
                "pass": ready_bad_pass,
                "details": ready_bad,
            }
        )
        write_json(bundle / "readiness_probe.json", {"ready_ok": ready_ok, "ready_bad": ready_bad, "pass": ready_bad_pass})
        run_cmd(not_ready_stop_cmd, root)

        extract_cmd = [
            str(python_bin),
            str(extract_script),
            "--output",
            str(bundle / "cursor_exhaust_snapshot.json"),
            "--prometheus-textfile",
            str(bundle / "cursor_exhaust.prom"),
            "--neo4j-cypher",
            str(bundle / "cursor_exhaust.cypher"),
        ]
        run_cmd(extract_cmd, root)

        snapshot = read_json(bundle / "cursor_exhaust_snapshot.json")
        schema = read_json(schema_path)
        schema_ok = True
        schema_error = None
        try:
            jsonschema.Draft202012Validator(schema).validate(snapshot)
        except Exception as exc:  # noqa: BLE001
            schema_ok = False
            schema_error = str(exc)

        write_json(
            bundle / "cursor_exhaust_schema_validation.json",
            {
                "schema_path": str(schema_path),
                "snapshot_path": str(bundle / "cursor_exhaust_snapshot.json"),
                "pass": schema_ok,
                "error": schema_error,
            },
        )

        distinct_provider_models = {(item.get("provider"), item.get("model")) for item in usage_report}
        distinct_providers = {item.get("provider") for item in usage_report}
        validation_checks.append(
            {
                "id": "two_distinct_provider_model_calls",
                "pass": len(distinct_provider_models) >= 2,
                "details": {"distinct_provider_models": sorted([f"{p}/{m}" for p, m in distinct_provider_models])},
            }
        )
        validation_checks.append(
            {
                "id": "two_distinct_providers",
                "pass": len(distinct_providers) >= 2,
                "details": {"distinct_providers": sorted([p for p in distinct_providers if p is not None])},
            }
        )

        expected_rates = {
            ("openai_mock", "gpt-4.1-mini"): (0.003, 0.006),
            ("anthropic_mock", "claude-3-7-sonnet"): (0.004, 0.008),
        }
        pricing_ok = True
        mismatches: list[dict[str, Any]] = []
        for row in samples["events_normalized_sample"]:
            key = (row["provider"], row["model"])
            rates = expected_rates.get(key)
            if not rates:
                continue
            expected = expected_cost(row["prompt_tokens"], row["completion_tokens"], rates[0], rates[1])
            actual = round(float(row.get("estimated_cost") or 0.0), 10)
            if abs(expected - actual) > 1e-9:
                pricing_ok = False
                mismatches.append({"event_id": row["event_id"], "expected": expected, "actual": actual})
        validation_checks.append(
            {
                "id": "token_and_cost_accounting",
                "pass": pricing_ok,
                "details": {"mismatches": mismatches},
            }
        )

        known_unknown_ok = any(
            row.get("provider") == "openai_mock" and row.get("model") == "unknown-model-x" for row in unknown_pricing_report
        )
        validation_checks.append(
            {
                "id": "unknown_pricing_known_and_unknown_behavior",
                "pass": known_unknown_ok,
                "details": {"unknown_pricing_count": len(unknown_pricing_report), "unknown_rows": unknown_pricing_report},
            }
        )

        per_turn_status = (
            (((snapshot.get("derived_signals") or {}).get("per_turn_model_attribution") or {}).get("status"))
            if isinstance(snapshot, dict)
            else None
        )
        no_overclaim = per_turn_status in ("unknown", "partially_known")
        coverage_proof_by_class["cursor_routing_exhaust_partial"] = {
            "positive_proof": schema_ok,
            "negative_proof": no_overclaim,
            "details": {"per_turn_status": per_turn_status},
        }
        write_json(bundle / "coverage_proofs.json", {"proof_by_class": coverage_proof_by_class})
        write_json(runtime_coverage_proofs_path, {"proof_by_class": coverage_proof_by_class})
        coverage_report = json.loads(run_cmd(coverage_cmd, root)["stdout"])
        write_json(bundle / "coverage_gaps_report.json", coverage_report)
        coverage_validation = coverage_report.get("validation") or []
        coverage_ok = all(bool(item.get("pass")) for item in coverage_validation)
        validation_checks.append(
            {
                "id": "coverage_matrix_claims_supported",
                "pass": coverage_ok,
                "details": {"coverage_validation": coverage_validation},
            }
        )
        validation_checks.append(
            {
                "id": "cursor_exhaust_no_per_turn_overclaim",
                "pass": no_overclaim,
                "details": {"per_turn_status": per_turn_status},
            }
        )
        validation_checks.append(
            {
                "id": "cursor_exhaust_schema_valid",
                "pass": schema_ok,
                "details": {"error": schema_error},
            }
        )

        overall_pass = all(bool(check["pass"]) for check in validation_checks)

        limitations = [
            "Verification uses deterministic local mock providers; real provider auth/rate limits are not exercised.",
            "Only OpenAI-style chat endpoint is implemented in this milestone.",
            "Fail-open path returns synthetic response for degraded upstream state and should be revisited for production fallback strategy.",
            "Traffic that bypasses proxy remains unobservable by design and is tracked via coverage matrix, not telemetry events.",
            "Cursor routing exhaust is advisory and cannot attribute exact per-turn model/provider routing.",
        ]
        (bundle / "known_limitations_and_blind_spots.md").write_text(
            "\n".join(["# Known Limitations and Blind Spots", ""] + [f"- {item}" for item in limitations]) + "\n",
            encoding="utf-8",
        )

        report_lines = [
            "# Token Proxy End-to-End Verification Report",
            "",
            f"- Timestamp: `{stamp}`",
            f"- Overall result: `{'PASS' if overall_pass else 'FAIL'}`",
            "",
            "## Residual risks",
            "",
            "- Proxy coverage is limited to traffic routed through configured local endpoint.",
            "- Real upstream provider failure semantics are only partially represented by local mocks.",
            "- Advisory routing exhaust still leaves per-turn attribution unknown in this environment.",
        ]
        (bundle / "verification_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        check_by_id = {str(check["id"]): check for check in validation_checks}
        critical_ids = {
            "telemetry_sink_degradation_fail_open_and_fail_closed",
            "secret_header_injection_non_persistence",
        }
        critical_findings: list[dict[str, Any]] = []
        high_findings: list[dict[str, Any]] = []
        for check in validation_checks:
            if bool(check.get("pass")):
                continue
            finding = {
                "check_id": check.get("id"),
                "summary": "verification check failed",
                "details": check.get("details"),
            }
            if str(check.get("id")) in critical_ids:
                critical_findings.append(finding)
            else:
                high_findings.append(finding)
        self_review_findings = {
            "critical_count": len(critical_findings),
            "high_count": len(high_findings),
            "critical_findings": critical_findings,
            "high_findings": high_findings,
            "additional_findings": [],
        }
        additional_critical_count = 0
        additional_high_count = 0
        for item in self_review_findings["additional_findings"]:
            severity = str(item.get("severity") or "").lower()
            if severity == "critical":
                additional_critical_count += 1
            elif severity == "high":
                additional_high_count += 1
        self_review_findings["additional_critical_count"] = additional_critical_count
        self_review_findings["additional_high_count"] = additional_high_count
        write_json(bundle / "self_review_findings.json", self_review_findings)
        gate_ag1 = (
            self_review_findings["critical_count"] == 0
            and self_review_findings["high_count"] == 0
            and self_review_findings["additional_critical_count"] == 0
            and self_review_findings["additional_high_count"] == 0
        )
        gate_ag2 = all(
            bool(check["pass"])
            for check in validation_checks
            if check["id"]
            in {
                "two_distinct_provider_model_calls",
                "two_distinct_providers",
                "unknown_provider_rejected",
                "unsupported_path_returns_404",
                "coverage_direct_bypass_not_logged",
                "telemetry_sink_degradation_fail_open_and_fail_closed",
                "secret_header_injection_non_persistence",
                "normalize_rollup_idempotent_rerun",
                "unknown_pricing_known_and_unknown_behavior",
                "cursor_exhaust_schema_valid",
                "cursor_exhaust_no_per_turn_overclaim",
                "ready_endpoint_reports_actual_readiness",
                "ready_endpoint_side_effects_reversible",
                "ready_endpoint_detects_dependency_failure",
            }
        )
        claims = [
            {
                "claim_id": "dual_provider_e2e",
                "artifact": "validation_checks.json",
                "check_id": "two_distinct_provider_model_calls",
            },
            {
                "claim_id": "dual_provider_count",
                "artifact": "validation_checks.json",
                "check_id": "two_distinct_providers",
            },
            {
                "claim_id": "telemetry_degradation_behavior",
                "artifact": "validation_checks.json",
                "check_id": "telemetry_sink_degradation_fail_open_and_fail_closed",
            },
            {
                "claim_id": "secret_non_persistence",
                "artifact": "validation_checks.json",
                "check_id": "secret_header_injection_non_persistence",
            },
            {
                "claim_id": "coverage_truthfulness",
                "artifact": "validation_checks.json",
                "check_id": "coverage_matrix_claims_supported",
            },
            {
                "claim_id": "cursor_exhaust_no_overclaim",
                "artifact": "validation_checks.json",
                "check_id": "cursor_exhaust_no_per_turn_overclaim",
            },
        ]
        evaluated_claims = []
        for claim in claims:
            check = check_by_id.get(str(claim["check_id"]))
            claim_pass = bool(check and check.get("pass"))
            evaluated_claims.append({**claim, "pass": claim_pass})
        write_json(bundle / "claims_to_artifacts.json", {"claims": evaluated_claims})
        gate_ag4 = all(bool(item["pass"]) for item in evaluated_claims)

        required_artifacts = [
            "coverage_gaps_report.json",
            "telemetry_sink_degradation.json",
            "secret_header_non_persistence.json",
            "idempotency_rerun_check.json",
            "verification_report.md",
            "self_review_findings.json",
            "claims_to_artifacts.json",
        ]
        missing_artifacts = [name for name in required_artifacts if not (bundle / name).exists()]
        bundle_manifest = {
            "required_artifacts": required_artifacts,
            "missing_artifacts": missing_artifacts,
        }
        write_json(bundle / "bundle_manifest.json", bundle_manifest)
        gate_ag3 = len(missing_artifacts) == 0
        gate_ag5 = bool((bundle / "known_limitations_and_blind_spots.md").exists())
        gate_table = {
            "AG1_no_high_severity_findings": gate_ag1,
            "AG2_all_required_scenarios_pass": gate_ag2,
            "AG3_evidence_bundle_complete": gate_ag3,
            "AG4_claims_map_to_artifacts": gate_ag4,
            "AG5_residual_risks_listed": gate_ag5,
        }
        write_json(bundle / "acceptance_gates.json", gate_table)
        write_json(
            bundle / "validation_checks.json",
            {
                "generated_at_utc": utc_now_iso(),
                "overall_pass": overall_pass and all(gate_table.values()),
                "checks": validation_checks,
            },
        )

    finally:
        try:
            run_cmd(stop_cmd, root)
        except Exception:
            pass
        try:
            run_cmd(degraded_stop_cmd, root)
        except Exception:
            pass
        openai_server.shutdown()
        anthropic_server.shutdown()
        openai_thread.join(timeout=2)
        anthropic_thread.join(timeout=2)

    final_result = read_json(bundle / "validation_checks.json")
    print(
        json.dumps(
            {
                "ok": bool(final_result.get("overall_pass")),
                "bundle": str(bundle),
                "overall_pass": final_result.get("overall_pass"),
                "check_count": len(final_result.get("checks") or []),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
