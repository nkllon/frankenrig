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
    runtime_pricing_path.write_text(pricing_base_path.read_text(encoding="utf-8"), encoding="utf-8")
    runtime_coverage_path.write_text(coverage_base_path.read_text(encoding="utf-8"), encoding="utf-8")

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

    validation_checks: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    try:
        run_cmd(start_cmd, root)
        status_payload = run_cmd(status_cmd, root)
        write_json(bundle / "health_status_output.json", {"status_stdout": status_payload["stdout"], "status_stderr": status_payload["stderr"]})

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
        write_json(bundle / "proxy_call_responses.json", responses)

        db_path = runtime / "token_proxy.db"
        raw_count_before_direct = db_count_events(db_path)

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

        usage_report = json.loads(run_cmd(usage_cmd, root)["stdout"])
        top_clients_report = json.loads(run_cmd(top_cmd, root)["stdout"])
        unknown_pricing_report = json.loads(run_cmd(unknown_cmd, root)["stdout"])
        coverage_report = json.loads(run_cmd(coverage_cmd, root)["stdout"])

        write_json(bundle / "usage_by_provider_model.json", usage_report)
        write_json(bundle / "top_token_consumers_by_client.json", top_clients_report)
        write_json(bundle / "unknown_uncosted_calls.json", unknown_pricing_report)
        write_json(bundle / "coverage_gaps_report.json", coverage_report)

        samples = collect_db_samples(db_path)
        write_json(bundle / "sample_raw_events.json", samples["events_raw_sample"])
        write_json(bundle / "normalized_events_sample.json", samples["events_normalized_sample"])
        write_json(bundle / "daily_rollup_sample.json", samples["daily_rollups_sample"])

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
        validation_checks.append(
            {
                "id": "two_distinct_provider_model_calls",
                "pass": len(distinct_provider_models) >= 2,
                "details": {"distinct_provider_models": sorted([f"{p}/{m}" for p, m in distinct_provider_models])},
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

        validation_checks.append(
            {
                "id": "unknown_pricing_none_for_configured_models",
                "pass": len(unknown_pricing_report) == 0,
                "details": {"unknown_pricing_count": len(unknown_pricing_report)},
            }
        )

        coverage_validation = coverage_report.get("validation") or []
        coverage_ok = all(bool(item.get("pass")) for item in coverage_validation)
        validation_checks.append(
            {
                "id": "coverage_matrix_claims_supported",
                "pass": coverage_ok,
                "details": {"coverage_validation": coverage_validation},
            }
        )

        per_turn_status = (
            (((snapshot.get("derived_signals") or {}).get("per_turn_model_attribution") or {}).get("status"))
            if isinstance(snapshot, dict)
            else None
        )
        no_overclaim = per_turn_status in ("unknown", "partially_known")
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
        write_json(
            bundle / "validation_checks.json",
            {
                "generated_at_utc": utc_now_iso(),
                "overall_pass": overall_pass,
                "checks": validation_checks,
            },
        )

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

    finally:
        try:
            run_cmd(stop_cmd, root)
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
