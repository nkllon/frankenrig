# Token Proxy Design

## Design goals

This design realizes the **requirements** for a deterministic, auditable token proxy and usage observability layer while honoring the cross-cutting concerns specified in the session seed prompt:

- determinism and auditability,
- coverage truthfulness,
- security and privacy,
- reliability behavior,
- performance,
- cost correctness,
- operations ergonomics.

The design is intentionally modular so that future extensions (additional providers, richer analytics, remote deployment) do not force breaking changes to the core telemetry and storage model.

## High-level architecture

At a high level, the system comprises five major subsystems:

1. **Proxy Service**
   - A local network service that accepts LLM requests from clients and forwards them to external providers.
   - Responsibilities:
     - request validation and normalization,
     - provider/model routing,
     - timing and retry orchestration,
     - telemetry event emission.

2. **Telemetry Pipeline**
   - A deterministic, append-only event pipeline that:
     - accepts structured events from the proxy,
     - enforces schema and redaction rules,
     - writes raw events to durable storage,
     - feeds normalization and rollup jobs.

3. **Storage and Analytics**
   - A local storage layer that supports:
     - **raw event log** (append-only),
     - **normalized analytics tables**,
     - **daily rollups**.
   - Backed by a file-based database (for example SQLite) and/or newline-delimited JSON files, with explicit schema versioning.

4. **Control and Reporting CLI**
   - A CLI surface for:
     - starting/stopping/status of the proxy service,
     - generating reports (totals, top consumers, unknown pricing, coverage gaps),
     - running verification scenarios and emitting evidence artifacts.

5. **Local Exhaust Collector**
   - A deterministic collector for local IDE/runtime artifacts that provide model-routing hints but not authoritative per-turn attribution.
   - Responsibilities:
     - query known local state artifacts (for example Cursor state DB),
     - summarize extension runtime logs and pairing metadata,
     - emit a versioned snapshot with explicit visibility classification (`known`/`partially_known`/`unknown`).

All components run locally on the operator’s machine and are configured via a central configuration file and/or directory.

## Component details

### Proxy Service

**Responsibilities**

- Expose a local HTTP API compatible with common LLM client expectations (for example `POST /v1/chat/completions` for OpenAI-style calls).
- Accept requests from:
  - local scripts and tools,
  - Hammerspoon/OBS automation (via HTTP or shell commands).
- Normalize incoming requests into an internal representation:
  - provider,
  - model,
  - endpoint type (chat/completions, embeddings, etc.),
  - input payload.
- Apply routing rules from configuration to select:
  - upstream provider endpoint,
  - authentication method (for example API key),
  - model mapping (for example alias `default` → `gpt-4.1`).
- Execute the upstream call with:
  - timing measurement (start/end timestamps),
  - retry policy (configurable per provider/path),
  - clear classification of success vs error and terminal outcome.
- Emit a **telemetry event** capturing all required dimensions once the call completes or fails.

**Interfaces**

- **Inbound HTTP API**:
  - Primary: `POST /v1/chat/completions` (OpenAI-like; initial focus).
  - Future: other endpoints (for example `POST /v1/completions`, embeddings) keyed behind explicit feature flags.
- **Outbound provider APIs**:
  - Provider-specific HTTP endpoints with appropriate auth headers and payload shapes.
- **Telemetry sink interface**:
  - A local interface (for example function call or message queue) for sending structured events to the Telemetry Pipeline.

### Telemetry Pipeline

**Responsibilities**

- Define and enforce a **versioned event schema**, including:
  - `schema_version`,
  - timestamp (UTC),
  - request/correlation id,
  - client identity (if known),
  - provider/model/endpoint,
  - token counts,
  - latency,
  - retry metadata,
  - dedupe fingerprint,
  - pricing version and cost fields (possibly initially `null` until enrichment).
- Apply **redaction rules** and **sampling decisions**:
  - Redaction configured per field or payload section.
  - Sampling configurable and off by default; when on, sampling must be deterministic and logged.
- Validate events against the schema; reject or quarantine malformed events without crashing the proxy.
- Persist events to the **raw event log** in an append-only fashion.
- Trigger or enqueue **normalization and rollup jobs**.

**Event schema**

The event schema will be represented as:

- a clear, versioned TypeScript/Python type (depending on implementation language),
- a JSON Schema definition checked at runtime before persistence.

Key fields include:

- `schema_version`: semantic version of the telemetry schema.
- `event_id`: unique identifier for the event.
- `correlation_id`: id tying together related events, if clients provide one.
- `timestamp_utc`: ISO 8601.
- `client_id`: string or structured object describing the calling app/script when available.
- `provider`, `model`, `endpoint`: strings referencing configured entities.
- `prompt_tokens`, `completion_tokens`, `total_tokens`: integers.
- `pricing_version`: identifier referencing the pricing catalog snapshot.
- `estimated_cost`: numeric, currency-agnostic base unit (for example USD).
- `latency_ms`: integer.
- `status`: success/error classification.
- `error_code`, `error_type`: when applicable.
- `retry_count`, `terminal_outcome`.
- `dedupe_fingerprint`: non-sensitive hash computed from non-secret fields.

### Storage and Analytics

**Storage choices**

- Use a **local SQLite database file** (for example `token_proxy.db`) as the primary normalized storage.
- Optionally maintain a **newline-delimited JSON file** (for example `events_raw.ndjson`) as an export-friendly raw log.

**Tables**

- `events_raw`:
  - columns: `event_id`, `timestamp_utc`, `raw_json`, minimal indexing.
  - append-only; used as the canonical source of truth.
- `events_normalized`:
  - columns reflecting the normalized event schema (provider, model, tokens, cost, etc.).
  - populated by an idempotent ETL step from `events_raw`.
- `daily_rollups`:
  - dimensions: date, provider, model, client_id (nullable), other configured grouping keys.
  - measures: total requests, total tokens, total cost, error counts, latency summaries.

**Idempotency**

- ETL/rollup jobs must be **idempotent**:
  - Each job runs for a specific date range and uses a deterministic key (for example `(date, provider, model, client_id)`).
  - Existing rollup rows for that key are either:
    - overwritten atomically, or
    - computed incrementally in a way that avoids double counting (for example by using a high-water mark on `event_id`).

### Pricing Catalog

**Representation**

- A versioned configuration file (for example `pricing.catalog.json`) that defines:
  - providers,
  - models,
  - per-token pricing for prompt and completion,
  - currency,
  - effective date ranges.

**Usage**

- When normalizing an event, the ETL step:
  - looks up pricing based on provider/model and timestamp,
  - computes cost deterministically,
  - records `pricing_version` and `estimated_cost`.
- Events without a matching pricing entry are:
  - marked with `estimated_cost = null`,
  - flagged as **unknown pricing** for reporting.

### Coverage Matrix

**Concept**

- The coverage matrix describes which traffic is:
  - **definitely observed**: all required metrics available,
  - **partially observed**: some metrics missing or approximated,
  - **unobservable**: cannot be seen without architectural changes.

**Realization**

- Represented as a configuration artifact (for example `coverage.matrix.json`) with entries such as:
  - `source` (for example script name, integration type),
  - `path` (for example HTTP, SDK, shell),
  - `provider/model` (or wildcard),
  - `coverage_level` (definite/partial/none),
  - `notes` and `limitations`.
- The reporting CLI reads this artifact and cross-checks it against:
  - observed events in storage,
  - known configured clients/providers.

### Control and Reporting CLI

**Capabilities**

- **Service control**:
  - `token-proxy start`: start the proxy service.
  - `token-proxy stop`: stop the proxy service.
  - `token-proxy status`: show health and configuration summary.
- **Reports**:
  - `token-proxy report usage --by provider,model --since <date>`:
    - totals by provider/model (requests, tokens, cost).
  - `token-proxy report top-clients --limit N`:
    - top token consumers by client.
  - `token-proxy report unknown-pricing`:
    - events with missing/unknown pricing.
  - `token-proxy report coverage`:
    - summary of coverage matrix and observed gaps.
- **Verification**:
  - `token-proxy verify basic`:
    - runs a basic end-to-end scenario and writes evidence under `evidence/token_proxy/<timestamp>/`.

### Local Exhaust Collector

**Responsibilities**

- Produce deterministic snapshots from local artifacts that are useful for attribution-gap analysis.
- Preserve strict truthfulness boundaries:
  - include what is directly observable,
  - do not infer unobserved per-turn model routing.
- Emit outputs that are easy to enrich with proxy telemetry later.

**Interfaces**

- **Input artifacts**:
  - Cursor local state database (`state.vscdb`),
  - Cursor extension logs (Codex/Claude activation/runtime logs),
  - app pairing metadata files.
- **Output artifact**:
  - versioned JSON snapshot conforming to `docs/sdd/token-proxy/cursor-exhaust.schema.json`.
  - optional Prometheus textfile projection for metrics pipelines.
  - optional Neo4j Cypher projection for graph ingest.

**Output schema highlights**

- `cursor_state`:
  - best-of-N ensemble preferences,
  - single-model preferences,
  - selected allowlisted state values.
- `extension_runtime`:
  - latest log session and per-window activation summaries.
- `pairing_sessions`:
  - app/workspace/session metadata for correlation.
- `derived_signals`:
  - candidate model pool (hints),
  - explicit per-turn attribution status and reason.

**Sink projections**

- **Prometheus projection**:
  - one-hot gauges for routing/per-turn visibility status,
  - counts for pairing sessions, candidate models, windows/log presence.
- **Neo4j projection**:
  - `CursorExhaustSnapshot` node,
  - related `CandidateModel`, `CursorPairingSession`, `Workspace`, and `CursorWindow` nodes,
  - deterministic `MERGE` relationships enabling enrichment joins.

## Configuration model

Configuration is centralized in a file or directory, for example:

- `token-proxy.config.json`:
  - `proxy`:
    - listen address/port,
    - default provider/model,
    - fail-open vs fail-closed behavior per path.
  - `providers`:
    - mapping of provider ids to:
      - base URLs,
      - auth methods (API keys env var names),
      - supported models.
  - `security`:
    - redaction rules,
    - sampling settings (off by default).
  - `storage`:
    - database file paths,
    - raw log file location.
  - `operations`:
    - log rotation policies,
    - health check configuration.
- `cursor-exhaust.config.json` (optional):
  - source paths for local artifacts,
  - field allowlists/redaction policy,
  - output location conventions for snapshots.

Configuration changes are applied via:

- reload-on-signal (for example SIGHUP) or
- explicit `token-proxy reload` command.

## Reliability and failure modes

- **Proxy unreachable**:
  - Behavior determined by `fail_open`/`fail_closed` settings per client/path.
  - Fail-open: client falls back to direct provider calls or cached endpoint; this traffic is explicitly classified as **unobservable** in the coverage matrix.
  - Fail-closed: client receives a clear error; events about the failure are logged locally if possible.
- **Telemetry/storage failure**:
  - The proxy attempts to write to a durable local buffer.
  - If storage remains unavailable, the proxy either:
    - rejects new requests (fail-closed), or
    - serves requests but logs explicit “telemetry degraded” events (fail-open), depending on configuration.
- **Pricing data unavailable**:
  - Requests continue (if configured).
  - Events are marked with unknown pricing and surfaced by reports; no silent cost assumptions are made.

## Performance considerations

- Telemetry writes are batched where possible (for example using a small in-memory buffer with flush-on-interval and flush-on-shutdown).
- Token and cost computation is lightweight and deterministic, based on provider responses and pricing catalog lookups.
- For verification, the system includes a scenario that:
  - sends representative traffic through the proxy,
  - measures overhead (p50/p95/p99),
  - writes a short performance report into `evidence/token_proxy/<timestamp>/`.

## Security and privacy

- API keys and secrets are never written to disk; they are:
  - read from environment variables or secure local stores,
  - only used in outbound requests.
- Redaction is applied *before* events leave the process boundary into persistent storage.
- When payload sampling is enabled:
  - the sampling policy is explicit (for example “1% of requests per client”),
  - sampling decisions are logged deterministically so experiments are reproducible.

## Alignment with requirements

This design:

- Satisfies the **Functional Minimum** by capturing and persisting all required fields.
- Provides an append-only raw event log, normalized analytics store, and daily rollups.
- Defines deterministic pricing and coverage models with explicit versioning and gap reporting.
- Enforces strong boundaries for secrets and payload redaction.
- Supports one-command operations via the CLI interface.
- Treats local routing exhaust as a first-class, versioned data source for attribution-gap analysis and future enrichment.
- Leaves room for incremental integration into existing OBS/Hammerspoon workflows without breaking them, by allowing clients to adopt the proxy via configuration and local routing rather than global side effects.

## Implemented reference architecture (current)

The current code-level implementation in this repository is:

- `scripts/token_proxy.py`
  - `serve`: foreground HTTP proxy service with `/health`, `/ready`, and `/v1/chat/completions`.
  - `start` / `stop` / `status`: background lifecycle control with pid/state and health probing.
  - `init`: deterministic SQLite schema initialization.
  - `normalize` / `rollup`: idempotent analytics transformation path.
  - `report usage|top-clients|unknown-pricing|coverage`: operator-facing evidence queries.
- `token_proxy/config/token-proxy.config.json`
  - runtime settings (host/port, retry policy, fail-open/fail-closed defaults),
  - provider routing map,
  - storage paths,
  - catalog/matrix references.
- `token_proxy/config/pricing.catalog.json`
  - versioned rates per provider/model.
- `token_proxy/config/coverage.matrix.json`
  - explicit traffic class declarations and validation expectations.
- `scripts/run_token_proxy_seed.py`
  - deterministic end-to-end harness:
    - boots local mock providers,
    - drives dual-provider proxy traffic,
    - proves bypass visibility gap behavior,
    - computes p50/p95/p99 overhead,
    - validates Cursor exhaust snapshot schema,
    - emits complete evidence bundle.

### Current storage realization

- `events_raw`: append-only canonical source of truth.
- `events_normalized`: idempotent upsert by `event_id`.
- `daily_rollups`: idempotent upsert keyed by `(day_utc, provider, model, client_id)`.

### Current reliability realization

- Provider failure path supports:
  - `fail_closed`: explicit upstream failure response and recorded error event.
  - `fail_open`: synthetic response with recorded degraded outcome.
- No silent event loss by design in handled request paths.

