# Token Proxy Verification Plan

This document defines how the token proxy and observability layer will be verified, which evidence must be produced, and how verification ties back to the **requirements** and **design**.

Verification is organized around:

- correctness of telemetry and cost accounting,
- coverage truthfulness,
- reliability and failure behavior,
- performance overhead,
- operational readiness.

All significant verification runs MUST emit evidence bundles under `evidence/token_proxy/<timestamp>/`.

## Executed verification harness (current)

Use this one-command deterministic run to execute the full verification contract:

- `.venv_obsws/bin/python scripts/run_token_proxy_seed.py`

The harness performs:

- Zero-Step bootstrap capture (`node`, `npm`, `cc-sdd`),
- dual-provider end-to-end proxy traffic,
- raw/normalized/rollup validation,
- unknown-pricing validation,
- coverage-gap validation including direct bypass proof,
- p50/p95/p99 overhead measurement,
- Cursor exhaust extraction + schema validation + sink projections,
- residual risk and explicit pass/fail report generation.

Expected outputs are written to a new bundle at:

- `evidence/token_proxy/<timestamp>/`

## Evidence bundles

Each verification run produces a **timestamped evidence directory**, for example:

- `evidence/token_proxy/20260309T193000Z/`

Each bundle MUST include:

- **V-E1**: Redacted config snapshot
  - Contents:
    - current proxy configuration (with secrets removed),
    - pricing catalog snapshot,
    - coverage matrix snapshot.
  - Purpose:
    - anchor verification claims to a concrete configuration state.
- **V-E2**: Health/status output
  - Contents:
    - output from `token-proxy status`,
    - health endpoints checks (if applicable).
  - Purpose:
    - confirm the system state during the run.
- **V-E3**: Sample raw events
  - Contents:
    - subset of entries from `events_raw` and/or NDJSON exports.
  - Purpose:
    - demonstrate actual telemetry contents and schema adherence.
- **V-E4**: Normalized and rollup output
  - Contents:
    - example rows from `events_normalized`,
    - example rows from `daily_rollups`.
  - Purpose:
    - show that ETL and rollups are functioning and idempotent.
- **V-E5**: Validation checks with pass/fail
  - Contents:
    - machine-readable validation results (for example JSON or text),
    - human-readable summary.
  - Purpose:
    - document what was tested, with explicit outcomes.
- **V-E6**: Known limitations and blind spots
  - Contents:
    - list of uncovered traffic classes,
    - partial observations and their rationale,
    - risks related to current coverage.
  - Purpose:
    - communicate residual risk and avoid over-claiming observability.
- **V-E7**: Local exhaust snapshot + schema validation
  - Contents:
    - `cursor_exhaust_snapshot.json`,
    - schema validation result against `docs/sdd/token-proxy/cursor-exhaust.schema.json`.
  - Purpose:
    - provide deterministic evidence for attribution-gap analysis and later enrichment joins.
- **V-E8**: Local exhaust sink projections
  - Contents:
    - `cursor_exhaust.prom` (Prometheus textfile),
    - `cursor_exhaust.cypher` (Neo4j import projection).
  - Purpose:
    - prove sink portability without changing canonical snapshot semantics.

## Verification scenarios

### Scenario S1 — Minimal correctness smoke test

**Goal**

Verify that a single proxied request:

- succeeds end-to-end,
- produces a valid telemetry event,
- is visible in normalized storage and a basic report.

**Setup**

- Proxy service running with:
  - at least one provider/model configured,
  - pricing catalog entry for that provider/model,
  - storage initialized.

**Steps**

1. Start the proxy via CLI: `token-proxy start`.
2. Send a single, small request through the proxy (for example a short chat completion).
3. Stop the proxy (if needed) to flush events.
4. Run the normalization and rollup jobs for the appropriate time window.
5. Generate a usage report for that window.
6. Collect evidence bundle `S1`:
   - config snapshot,
   - status output,
   - sample raw events,
   - sample normalized and rollup rows,
   - validation results.

**Checks**

- C1.1: A raw event with the expected correlation id exists in `events_raw`.
- C1.2: A normalized row exists mapping to the same request with:
  - correct provider/model,
  - non-null token counts,
  - non-null latency.
- C1.3: The usage report includes this call in the correct provider/model group.
- C1.4: The evidence bundle contains all required artifacts V-E1–V-E6.

### Scenario S2 — Dual-provider accounting

**Goal**

Verify correct accounting when using at least two distinct provider/model combinations, as required by the Functional Minimum.

**Setup**

- Proxy configured with at least two providers/models with valid pricing entries.

**Steps**

1. Start the proxy.
2. Send at least one request per provider/model through the proxy.
3. Run normalization and rollups.
4. Generate:
   - a usage report by provider/model,
   - a report of unknown/uncosted calls.
5. Collect evidence bundle `S2`.

**Checks**

- C2.1: Each provider/model combination has:
  - correct total token counts,
  - correct total estimated cost (per pricing catalog).
- C2.2: No call with a matching pricing entry appears in the unknown/uncosted report.
- C2.3: Evidence includes clear proof of per-provider/model accounting.

### Scenario S3 — Coverage matrix validation

**Goal**

Validate that the coverage matrix accurately describes observable, partial, and unobservable traffic for the current environment.

**Setup**

- Coverage matrix file populated with:
  - at least one definitely observed traffic class,
  - at least one partially observed class,
  - at least one unobservable class (for example direct SDK usage bypassing proxy).

**Steps**

1. Identify (or create) representative clients for each traffic class.
2. For observable and partially observed classes:
   - route requests through the proxy,
   - verify that events are generated.
3. For unobservable classes:
   - execute client actions that bypass the proxy (if safe),
   - confirm that no corresponding events appear in storage.
4. Run coverage report via CLI.
5. Collect evidence bundle `S3`.

**Checks**

- C3.1: Coverage report matches the matrix definitions.
- C3.2: For each “definitely observed” class tested, events appear with full required dimensions.
- C3.3: For each “partially observed” class, evidence clearly shows which dimensions are missing.
- C3.4: For “unobservable” classes, no events are seen and the matrix explicitly calls out the blind spot.

### Scenario S4 — Reliability and failure behavior

**Goal**

Verify that fail-open/fail-closed behavior is correctly applied and that telemetry degradation is detectable, not silent.

**Setup**

- Configuration defining:
  - at least one path/client as fail-open,
  - at least one path/client as fail-closed.

**Steps**

1. Start the proxy in normal mode; run a baseline request for each path.
2. Simulate a provider outage (for example by pointing to an invalid upstream endpoint).
3. Exercise both paths/clients during the outage.
4. Restore provider configuration.
5. Simulate a storage outage (for example by making the database temporarily unavailable) while proxy stays up.
6. Exercise both paths/clients again.
7. Collect evidence bundle `S4`.

**Checks**

- C4.1: Fail-closed paths return clear errors to the caller during provider outage.
- C4.2: Fail-open paths continue (or fall back) according to configuration, and resulting traffic is correctly classified in the coverage matrix (for example unobservable when bypassing proxy).
- C4.3: During storage outage, proxy behavior matches configured policy (reject vs accept-with-warning).
- C4.4: Evidence includes explicit records of degraded telemetry states; no silent data loss.

### Scenario S5 — Performance overhead

**Goal**

Measure p50/p95/p99 latency overhead introduced by the proxy.

**Setup**

- Baseline access to at least one provider/model without the proxy (direct client).
- Proxy configured with equivalent provider/model.

**Steps**

1. Run a baseline performance script that:
   - sends N requests directly to the provider,
   - records latency distribution.
2. Run the same workload through the proxy.
3. Compute per-percentile overhead:
   - Δp50, Δp95, Δp99.
4. Store results in an evidence bundle `S5`.

**Checks**

- C5.1: Overhead is within acceptable bounds defined in requirements (or explicitly documented if higher).
- C5.2: Evidence includes raw measurements, summary statistics, and configuration snapshot.

### Scenario S6 — End-to-end final verification

**Goal**

Demonstrate final, end-to-end behavior with:

- at least two providers/models,
- correct token and cost accounting,
- validated coverage claims,
- explicit residual risks.

**Setup**

- System configured close to intended normal operation:
  - multiple providers/models,
  - realistic pricing catalog,
  - populated coverage matrix,
  - representative clients.

**Steps**

1. Start the proxy and confirm status is healthy.
2. Execute a mixed workload:
   - multiple clients,
   - multiple providers/models,
   - both short and longer prompts.
3. Run normalization and rollups.
4. Generate reports:
   - totals by provider/model,
   - top clients,
   - unknown pricing,
   - coverage.
5. Collect a comprehensive evidence bundle `S6`.
6. Document residual risks and blind spots explicitly.

**Checks**

- C6.1: Usage and cost reports match expectations derived from the workload.
- C6.2: Coverage report and evidence support all coverage matrix claims.
- C6.3: Any limitations are clearly listed in the evidence bundle and `verification.md`.

### Scenario S7 — Local routing exhaust verification

**Goal**

Verify that local Cursor routing exhaust is captured deterministically, schema-valid, and explicit about attribution limits.

**Setup**

- Local artifacts available:
  - Cursor state DB,
  - Cursor logs directory,
  - pairing metadata directory.
- Schema file present:
  - `docs/sdd/token-proxy/cursor-exhaust.schema.json`.

**Steps**

1. Run:
   - `python3 scripts/extract_cursor_exhaust.py --output evidence/token_proxy/<timestamp>/cursor_exhaust_snapshot.json`
2. Validate snapshot against schema.
3. Store validation result in the same evidence bundle.

**Checks**

- C7.1: Snapshot file exists and conforms to schema.
- C7.2: `derived_signals.per_turn_model_attribution.status` is not overstated (for current known artifacts, expected `unknown`).
- C7.3: Snapshot contains routing preference hints (`bestOfNEnsemblePreferences` and/or `lastSingleModelPreference`) when present in local state DB.
- C7.4: Evidence bundle includes V-E7 artifacts.
- C7.5: Prometheus projection and Neo4j projection are generated and stored as V-E8 artifacts.

## Residual risk tracking

- Maintain a section in each evidence bundle summarizing **residual risks**:
  - unmonitored traffic,
  - approximated pricing,
  - performance concerns,
  - operational gaps.
- Update this document when:
  - risks are retired (by design/implementation changes),
  - new risks are discovered.


