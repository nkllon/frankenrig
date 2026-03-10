# Token Proxy Task Breakdown

This document decomposes the token proxy work into concrete, traceable tasks aligned with the **requirements** and **design** documents. Tasks are organized into phases but may be executed iteratively as long as SDD invariants are maintained (requirements/design updated before code changes when gaps are discovered).

## Current execution status (2026-03-10)

- Completed in this milestone:
  - T0.1, T0.2
  - T1.1, T1.4, T1.5, T1.6, T1.7, T1.8
  - T2.1, T2.2, T2.3, T2.4, T2.5
  - T3.1, T3.2, T3.4, T3.5, T3.6, T3.7
  - T5.1, T5.2, T5.3, T5.4, T5.5, T5.6
  - T6.1, T6.2, T6.3, T6.4, T6.5, T6.6
- Partially complete / deferred:
  - T3.3 (real upstream providers; current harness uses deterministic local mocks)
  - T4.1-T4.4 (redaction and sampling controls implemented at baseline level, but not full policy engine depth)
  - T7.1-T7.4 (integration of all existing repo workflows behind proxy remains follow-on)
  - T8.3 (README integration still pending full production hardening milestone)

## Phase 0 — Environment and SDD scaffolding

- **T0.1**: Confirm Node.js, npm, and `cc-sdd` availability (Zero-Step Bootstrap).
- **T0.2**: Maintain SDD documents:
  - `requirements.md`,
  - `design.md`,
  - `tasks.md`,
  - `verification.md`,
  - `operations.md`.
- **T0.3**: Establish a canonical working directory structure for:
  - configuration (`token-proxy.config.*`, pricing, coverage matrix),
  - storage (database, raw logs),
  - evidence (`evidence/token_proxy/<timestamp>/`).

## Phase 1 — Configuration and schema foundations

- **T1.1**: Define configuration schema and default config file:
  - `token-proxy.config.json` (or similar),
  - sections for proxy, providers, security, storage, operations.
- **T1.2**: Define telemetry event schema:
  - language-native type definition,
  - JSON Schema with `schema_version`.
- **T1.3**: Implement schema validation helper(s) for events.
- **T1.4**: Define pricing catalog format:
  - `pricing.catalog.json` with providers/models/pricing/version.
- **T1.5**: Define coverage matrix format:
  - `coverage.matrix.json` representing observable/partial/unobservable classes.
- **T1.6**: Define local exhaust snapshot schema:
  - `docs/sdd/token-proxy/cursor-exhaust.schema.json`,
  - explicit visibility status fields (`known`/`partially_known`/`unknown`).
- **T1.7**: Implement deterministic local exhaust extractor:
  - `scripts/extract_cursor_exhaust.py`,
  - collect state DB preferences, extension log summaries, pairing metadata.
- **T1.8**: Implement sink projections for local exhaust:
  - Prometheus textfile metrics output,
  - Neo4j Cypher projection output.

## Phase 2 — Storage and analytics layer

- **T2.1**: Choose storage backend (initially SQLite + optional NDJSON export).
- **T2.2**: Implement storage initialization/migration:
  - create `events_raw`, `events_normalized`, `daily_rollups` tables.
- **T2.3**: Implement append-only raw event writer:
  - insert events into `events_raw`,
  - ensure durability and ordering guarantees.
- **T2.4**: Implement normalization job:
  - read from `events_raw`,
  - validate and normalize events into `events_normalized`,
  - compute pricing using `pricing.catalog.json`,
  - uphold idempotency for repeated runs.
- **T2.5**: Implement daily rollup job:
  - aggregate `events_normalized` into `daily_rollups`,
  - design and document idempotent recomputation per date range.
- **T2.6**: Implement optional raw NDJSON export/import (for external analysis).

## Phase 3 — Proxy service implementation

- **T3.1**: Implement basic HTTP server exposing OpenAI-style `POST /v1/chat/completions`.
- **T3.2**: Implement configuration-driven provider/model routing:
  - map incoming requests to provider endpoints and models.
- **T3.3**: Implement upstream provider client(s) for at least two providers/models:
  - for example:
    - Provider A: OpenAI-compatible,
    - Provider B: Anthropic/Gemini-compatible.
- **T3.4**: Implement timing, retry logic, and terminal outcome classification.
- **T3.5**: Integrate telemetry emission:
  - construct event objects with all required fields,
  - send to Telemetry Pipeline.
- **T3.6**: Implement fail-open/fail-closed behavior based on configuration:
  - behavior when proxy cannot reach provider,
  - behavior when telemetry/storage is degraded.
- **T3.7**: Add health and readiness endpoints (for example `/health`, `/ready`).

## Phase 4 — Security, privacy, and redaction

- **T4.1**: Implement redaction policy engine:
  - field-level and payload-level rules,
  - configuration-driven behavior.
- **T4.2**: Integrate redaction into telemetry emission path:
  - secrets and sensitive content never written to persistent storage.
- **T4.3**: Implement configurable payload sampling:
  - default off,
  - deterministic and logged when enabled.
- **T4.4**: Verify that API keys/secrets are only sourced from secure configuration (for example environment variables) and never logged.

## Phase 5 — Control and reporting CLI

- **T5.1**: Implement CLI skeleton:
  - `token-proxy <command> [options]`.
- **T5.2**: Implement service control commands:
  - `start`, `stop`, `status`, optionally `reload`.
- **T5.3**: Implement usage reports:
  - totals by provider/model over a time range.
- **T5.4**: Implement top consumer reports:
  - top token consumers by client.
- **T5.5**: Implement unknown/uncosted calls report:
  - list events with missing or null pricing.
- **T5.6**: Implement coverage report:
  - summarize coverage matrix,
  - cross-check against observed events to highlight gaps.

## Phase 6 — Verification and evidence tooling

- **T6.1**: Implement verification harness(es) described in `verification.md`:
  - scripts or CLI subcommands that:
    - send representative traffic through the proxy,
    - query storage and generate assertions.
- **T6.2**: Implement evidence bundle generator:
  - create `evidence/token_proxy/<timestamp>/` directories,
  - capture:
    - redacted config snapshot,
    - health/status output,
    - sample raw events,
    - normalized rollup output,
    - validation checks with pass/fail,
    - known limitations and blind spots.
- **T6.3**: Implement performance measurement scenario:
  - measure p50/p95/p99 overhead introduced by the proxy,
  - record results in an evidence bundle.
- **T6.4**: Implement end-to-end test scenario using at least two providers/models:
  - verify token and cost accounting across both,
  - validate coverage matrix claims.
- **T6.5**: Implement local exhaust validation scenario:
  - run extractor,
  - validate output against `cursor-exhaust.schema.json`,
  - store artifact in evidence bundle.
- **T6.6**: Validate sink projections:
  - verify Prometheus textfile generation,
  - verify Neo4j Cypher generation and basic syntax sanity.

## Phase 7 — Integration with existing workflows

- **T7.1**: Identify existing scripts/automation in this repo that call LLM providers (if any).
- **T7.2**: Design safe, opt-in routing for these clients through the proxy:
  - environment variable overrides,
  - local HTTP endpoint configuration,
  - or explicit wrapper commands.
- **T7.3**: Implement non-breaking integration adaptations where appropriate:
  - wrappers or small shims that point to the proxy instead of direct providers.
- **T7.4**: Update coverage matrix to reflect:
  - which workflows are now fully observed,
  - which remain partial/unobserved and why.

## Phase 8 — Documentation and operations

- **T8.1**: Populate `operations.md` with:
  - start/stop/status procedures,
  - configuration management,
  - backup/restore and rotation guidance,
  - incident response runbooks.
- **T8.2**: Update `verification.md` with:
  - concrete test cases,
  - commands to run them,
  - expected outputs and evidence references.
- **T8.3**: Ensure `README.md` or sub-section points to token proxy SDD docs and basic usage.
- **T8.4**: Document local exhaust cadence and enrichment join guidance in `operations.md`.

## Task tracking and SDD discipline

- Any time a task reveals a design or requirement gap:
  - **STOP** implementation on that path,
  - update `requirements.md` and/or `design.md`,
  - only then continue coding.
- Each major task or phase completion should:
  - produce evidence artifacts as defined in `verification.md`,
  - update the coverage matrix and operational docs as needed.

