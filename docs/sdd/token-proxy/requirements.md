# Token Proxy Requirements

## Purpose and scope

This document captures the requirements for a **production-grade token proxy and usage observability layer** implemented in this repository. The goal is to provide deterministic, auditable visibility into language-model usage initiated from this environment (CLI tools, automation scripts, Hammerspoon/OBS integrations, and future services) without breaking existing workflows.

The proxy will sit on the request path between local clients and external model providers, emitting structured telemetry for every call while forwarding requests and responses with minimal, bounded overhead.

## Objectives

- **Deterministic observability**: For any request handled by the proxy, it must be possible to reconstruct token, cost, and latency metrics from persisted logs alone.
- **Coverage truthfulness**: Clearly distinguish between traffic that is:
  - definitely observed (goes through the proxy),
  - partially observed (some dimensions missing or approximated),
  - unobservable (bypasses the proxy or cannot be measured).
- **Cost correctness**: Provide versioned, explainable cost estimates per call based on explicit pricing tables, never silent guesses.
- **Non-disruptive integration**: Allow existing OBS/Hammerspoon and CLI workflows to continue working, with proxy adoption driven by explicit configuration rather than implicit global side effects.
- **Attribution-gap observability**: Capture local IDE/client "routing exhaust" artifacts to model what can be known about model selection when per-turn provider telemetry is unavailable.

## In scope

- A **local token proxy service** (HTTP/gRPC or similar) running on the same host as clients.
- **Configuration-driven routing** of LLM calls to:
  - specific providers (for example OpenAI, Anthropic, Gemini),
  - specific models (for example `gpt-4.1`, `claude-3.7-sonnet`).
- **Per-call telemetry capture**, including at minimum:
  - timestamp (UTC),
  - request/correlation id,
  - client identity (when available),
  - provider, model, endpoint,
  - prompt_tokens, completion_tokens, total_tokens,
  - cost estimate + pricing source/version,
  - latency,
  - success/error status,
  - retries and terminal outcome,
  - dedupe fingerprint (non-sensitive hash).
- An **append-only raw event log** with a strictly versioned schema.
- A **normalized analytics store** suitable for queries and aggregations.
- **Daily rollups** derived from raw events in an idempotent way.
- **CLI/command-line reports** that answer, at minimum:
  - totals by provider/model,
  - top token consumers by client,
  - calls with unknown/uncosted pricing,
  - coverage gaps (traffic outside the proxy or missing dimensions).
- A **versioned local exhaust snapshot model** for Cursor/session routing hints sourced from local state DBs/logs and pairing metadata.
- A deterministic **local exhaust extractor** that produces machine-readable snapshots for downstream enrichment.
- An explicit **coverage matrix** describing which traffic classes are definitely observed, partially observed, or unobservable.
- **Security and privacy controls** for redaction, sampling, and secret handling.

## Out of scope (initial phase)

- Multi-tenant, multi-user authentication/authorization beyond a single-trust-domain host.
- Centralized, multi-machine aggregation (beyond shipping local artifacts if needed).
- Provider-specific advanced features (for example fine-tuning management, batch jobs) except as required to support basic completion/chat calls with telemetry.
- Real-time dashboards or hosted UI (initially satisfied by CLI queries and locally inspectable artifacts).

These may become future milestones but are explicitly out of scope for the initial delivery.

## Stakeholders and clients

- **Local automation scripts and tools** in this repository that call LLM providers.
- **OBS/Hammerspoon automations** that may use LLMs for layout, captioning, or control flows.
- **The repository owner/operator**, who needs:
  - accurate usage and cost accounting,
  - evidence of coverage and blind spots,
  - simple operational controls and runbooks.

## Functional requirements

### FR-1: Proxy request handling

- The system SHALL provide a local endpoint for clients to send LLM requests (for example HTTP `POST /v1/chat/completions` analogues).
- The proxy SHALL forward each accepted request to the configured upstream provider/model, preserving semantics (input/output) except for:
  - transport details (for example local URL vs provider URL),
  - optional, configured redactions in telemetry, not in the upstream payload unless explicitly enabled.
- The proxy SHALL emit a structured event for each call, whether successful or failed.

### FR-2: Telemetry capture

- For every proxied call, the system SHALL record at least the fields listed under **Functional Minimum** in the session seed prompt:
  - timestamp (UTC),
  - request/correlation id,
  - client identity (when available),
  - provider, model, endpoint,
  - prompt_tokens, completion_tokens, total_tokens,
  - estimated cost + pricing source/version,
  - latency and success/error status,
  - retries and terminal outcome,
  - dedupe fingerprint (non-sensitive hash).
- The system SHALL use a versioned event schema with an explicit `schema_version` field.

### FR-3: Storage and rollups

- The system SHALL maintain:
  - an append-only raw event log (for example newline-delimited JSON or a raw events table),
  - a normalized analytics store/table tuned for querying,
  - daily rollups derived from the raw events.
- The rollup process SHALL be **idempotent**: re-running it over the same time window must not duplicate or corrupt aggregates.

### FR-4: Pricing and cost estimation

- The system SHALL maintain a **versioned pricing catalog** for each supported provider/model.
- For each call, the proxy SHALL:
  - compute a cost estimate using the configured catalog when possible,
  - mark calls with **unknown pricing** explicitly when model/provider/pricing information is missing or ambiguous.
- The system SHALL expose queries/reports to list:
  - total cost per provider/model over a period,
  - calls with unknown or uncosted pricing.

### FR-5: Coverage matrix and gap reporting

- The system SHALL maintain a **coverage matrix** that classifies:
  - traffic classes that are definitely observed,
  - traffic classes that are partially observed,
  - traffic classes that are unobservable with the current design.
- The matrix SHALL be backed by configuration and/or code-level rules, not ad-hoc claims.
- CLI/report tooling SHALL surface coverage gaps and blind spots (for example “local script X bypasses proxy via direct SDK calls”).

### FR-6: Security and privacy

- The system SHALL NEVER log raw secrets or API keys.
- Telemetry SHALL support **redaction rules** for sensitive fields, including:
  - full payload redaction,
  - partial redaction (for example replacing substrings or fields with opaque tokens),
  - structured field redaction for JSON bodies.
- Payload sampling SHALL be **configurable and off by default**; when enabled, sampling decisions SHALL be logged deterministically.

### FR-7: Reliability and failure behavior

- The system SHALL allow explicit configuration of **fail-open vs fail-closed** behavior per path or client class, including:
  - what happens if the proxy is down,
  - what happens if telemetry sinks are down,
  - what happens if pricing data is unavailable.
- No failure mode SHALL silently drop events without at least:
  - an error indication to the caller, or
  - a durable local indication that data was not captured.
- Backpressure and restart behavior SHALL be defined:
  - how the proxy behaves under high load,
  - how it resumes after restart without corrupting logs or rollups.

### FR-8: Performance

- The proxy SHALL introduce **bounded overhead**, and it SHALL be possible to measure:
  - p50/p95/p99 added latency across representative workloads,
  - per-call overhead attributed to telemetry, pricing, and storage.
- The system SHALL provide at least one **verification scenario** that measures this overhead and records evidence.

### FR-9: Operations and ergonomics

- The system SHALL provide **one-command start/stop/status** operations for local use.
- The system SHALL provide **runbooks** describing:
  - how to start and stop the proxy,
  - how to rotate logs and storage safely,
  - how to update pricing catalogs,
  - how to diagnose coverage gaps and common failure modes.

### FR-10: Local routing exhaust modeling

- The system SHALL define a versioned schema for local routing-exhaust snapshots (for example Cursor state/preferences/log activation metadata).
- The system SHALL provide a deterministic extractor that reads local artifacts and emits a snapshot conforming to that schema.
- The extractor SHALL explicitly classify routing visibility and per-turn attribution visibility using `known`, `partially_known`, or `unknown`.
- The extractor SHALL NOT claim authoritative per-turn model attribution when the source artifacts do not provide it.
- The extractor output SHALL be suitable for later enrichment joins with proxy telemetry (for example by timestamp/session/workspace).
- The extractor SHALL support optional deterministic sink projections for:
  - Prometheus-compatible metrics exposition,
  - Neo4j-compatible graph ingestion.

## Constraints and assumptions

- The environment provides:
  - a modern Node.js runtime and `npm`,
  - the `cc-sdd` tool for SDD-oriented workflows.
- The proxy is initially designed for **single-operator, local-host usage** on macOS but should not preclude future remote or multi-host deployments.
- Existing OBS/Hammerspoon workflows in this repository MUST remain non-breaking; proxy adoption will be **opt-in via configuration** and/or explicit client routing.

## Acceptance criteria (requirements-level)

1. All functional requirements FR-1 through FR-9 are addressed by the design and implementation.
2. For any given proxied call in a test run, it is possible to:
   - locate the raw event,
   - reconstruct token usage and cost from logs and pricing catalogs alone,
   - show which provider/model processed the call,
   - show whether the call is fully observed, partially observed, or unobservable and why.
3. The coverage matrix accurately describes what is and is not visible for the initial set of clients and providers integrated in this repository.
4. Operational commands and runbooks exist and can be executed by the repository owner without additional undocumented steps.
5. A local exhaust snapshot can be generated on demand, validated against its schema, and used to explain attribution gaps without speculative claims.

## Implemented baseline (2026-03-10 run)

This repository now includes a deterministic baseline implementation that satisfies the Functional Minimum for local validation runs:

- `scripts/token_proxy.py` provides:
  - local proxy endpoint (`/v1/chat/completions`),
  - append-only raw event capture (`events_raw` table + NDJSON),
  - normalized table + idempotent rollups,
  - one-command operations (`start`, `stop`, `status`),
  - report commands (`usage`, `top-clients`, `unknown-pricing`, `coverage`).
- `token_proxy/config/pricing.catalog.json` provides versioned pricing (`pricing_version`) and explicit unknown-pricing behavior.
- `token_proxy/config/coverage.matrix.json` defines definitely observed / partially observed / unobservable classes.
- `scripts/run_token_proxy_seed.py` executes a deterministic end-to-end verification harness and emits evidence under `evidence/token_proxy/<timestamp>/`.
- `scripts/extract_cursor_exhaust.py` emits:
  - canonical snapshot JSON,
  - Prometheus projection,
  - Neo4j projection.

This baseline is intentionally local-first and mock-provider-backed for deterministic repeatability; production provider integrations are a follow-up increment.

