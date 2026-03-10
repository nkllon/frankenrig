# Token Proxy Operations

This document describes how to operate the token proxy and observability layer in day-to-day use, including:

- starting/stopping and monitoring the service,
- managing configuration, pricing, and coverage,
- handling storage and log rotation,
- responding to incidents,
- performing upgrades.

It is intended for the repository owner/operator running the system locally.

## Operational model overview

- The token proxy runs as a **local service** on the operator's machine.
- Control and reporting are performed via a **CLI tool** (for example `token-proxy`), which:
  - starts/stops the service,
  - reports status and health,
  - runs analytics and verification commands.
- Configuration and data are stored under predictable paths relative to the repository root (exact locations to be finalized during implementation), such as:
  - `config/token-proxy.config.json`,
  - `config/pricing.catalog.json`,
  - `config/coverage.matrix.json`,
  - `data/token_proxy.db`,
  - `data/events_raw.ndjson`,
  - `evidence/token_proxy/<timestamp>/`.

## Lifecycle commands

### Start

- Command:
  - `.venv_obsws/bin/python scripts/token_proxy.py --config token_proxy/config/token-proxy.config.json start`
- Behavior:
  - loads configuration and validates it,
  - initializes storage and migrations,
  - starts the proxy service listening on the configured address/port,
  - logs startup information (version, config paths, schema versions).

### Stop

- Command:
  - `.venv_obsws/bin/python scripts/token_proxy.py --config token_proxy/config/token-proxy.config.json stop`
- Behavior:
  - initiates graceful shutdown of the service,
  - flushes in-memory telemetry buffers to storage,
  - reports exit status.

### Status

- Command:
  - `.venv_obsws/bin/python scripts/token_proxy.py --config token_proxy/config/token-proxy.config.json status`
- Behavior:
  - reports:
    - whether the service is running,
    - process id (if applicable),
    - config file in use,
    - storage location(s),
    - recent error conditions (if any),
    - schema and pricing catalog versions.

### Reload (optional)

- Command:
  - not implemented in this milestone (restart is the supported deterministic path)
- Behavior:
  - reloads configuration (proxy, providers, security, pricing, coverage) without a full restart where feasible.

## Configuration management

### Primary configuration file

- File:
  - `token-proxy.config.json` (exact path TBD).
- Contents:
  - proxy listen address and port,
  - provider definitions and model mappings,
  - fail-open/fail-closed policies,
  - security and redaction rules,
  - sampling configuration,
  - storage locations,
  - logging levels and file paths.

### Pricing catalog

- File:
  - `pricing.catalog.json`.
- Management:
  - modify pricing entries when provider pricing changes,
  - bump `pricing_version` and/or effective dates,
  - verify changes by running a small verification scenario and storing evidence.

### Coverage matrix

- File:
  - `coverage.matrix.json`.
- Management:
  - update entries when:
    - new clients or workflows are added,
    - existing clients move behind the proxy,
    - routing changes create new blind spots.
  - re-run coverage verification scenario (`S3` in `verification.md`) after significant coverage changes.

### Local exhaust snapshot schema

- File:
  - `docs/sdd/token-proxy/cursor-exhaust.schema.json`.
- Management:
  - bump schema version when fields are added/removed/renamed,
  - keep extractor and schema in lockstep,
  - validate extracted snapshots before using them for analysis or joins.

### Secrets management

- API keys and secrets are **not** stored in configuration files.
- Recommended approaches:
  - environment variables (for example `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`),
  - secure OS keychain integrations where feasible.
- The proxy reads secrets at startup or on demand and never writes them to logs or evidence artifacts.

## Storage and log rotation

### Database

- Location:
  - `data/token_proxy.db` (or similar).
- Maintenance:
  - periodic backups (for example simple file copies when the service is stopped),
  - optional vacuum/compaction according to SQLite best practices.

### Raw events and exports

- Location:
  - `data/events_raw.ndjson` (if enabled),
  - or `events_raw` table in the database.
- Rotation:
  - configure max file size or age for NDJSON exports,
  - archive older files with timestamps,
  - ensure rotation scripts do not break ETL idempotency (for example, ETL should work from database, not exclusively from rotated files).

### Logs

- Service logs include:
  - startup/shutdown events,
  - warnings and errors,
  - summary counters.
- Rotation:
  - use OS-level log rotation (for example `logrotate`) or built-in rolling log functionality if provided by the implementation.

## Local exhaust capture workflow

- Extract local Cursor routing exhaust:
  - `.venv_obsws/bin/python scripts/extract_cursor_exhaust.py --output evidence/token_proxy/<timestamp>/cursor_exhaust_snapshot.json`
- Validate snapshot against schema (example command shape):
  - `.venv_obsws/bin/python -m jsonschema -i evidence/token_proxy/<timestamp>/cursor_exhaust_snapshot.json docs/sdd/token-proxy/cursor-exhaust.schema.json`
- Emit Prometheus + Neo4j projections (optional):
  - `.venv_obsws/bin/python scripts/extract_cursor_exhaust.py --output evidence/token_proxy/<timestamp>/cursor_exhaust_snapshot.json --prometheus-textfile evidence/token_proxy/<timestamp>/cursor_exhaust.prom --neo4j-cypher evidence/token_proxy/<timestamp>/cursor_exhaust.cypher`
- Operational guidance:
  - run snapshot capture at the start and end of high-stakes debugging sessions,
  - treat this snapshot as advisory routing telemetry, not authoritative per-turn attribution,
  - join with proxy telemetry for stronger evidence (timestamp, workspace/session metadata).

## Health checks and monitoring

- Health endpoints (for example `/health`, `/ready`) provide:
  - basic liveness (process running),
  - readiness (able to serve traffic),
  - storage connectivity status.
- `token-proxy status` aggregates:
  - health endpoint results,
  - internal error counters,
  - last successful storage and rollup operations.

For local-only operation, external monitoring systems are not strictly required, but the design leaves room for integration with systemd, launchd, or other supervisors in the future.

## Incident response runbooks

### Proxy not starting

1. Run `token-proxy status` to gather last-known state.
2. Check service logs for configuration or binding errors.
3. Validate configuration:
   - run a config validation command if available (for example `token-proxy config validate`),
   - fix syntax or semantic issues.
4. Verify secrets:
   - ensure required environment variables are set.
5. Retry `token-proxy start`.
6. If still failing, capture logs and configuration snapshot and store in an evidence bundle for debugging.

### No events being recorded

1. Confirm service is running and healthy.
2. Confirm clients are correctly configured to send traffic to the proxy endpoint.
3. Use a simple manual test call (for example `curl` or a small script) to generate a known request.
4. Check:
   - `events_raw` table or NDJSON file,
   - service logs for telemetry errors.
5. If events are missing:
   - inspect redaction/sampling configuration (ensure sampling is not discarding all events),
   - verify storage connectivity.
6. Record findings and remediation steps in an evidence bundle if the issue is non-trivial.

### Storage errors or database corruption

1. Stop the proxy (`token-proxy stop`).
2. Create a backup copy of the existing database and raw logs.
3. Attempt database integrity checks and repairs per backend recommendations (for example SQLite `PRAGMA integrity_check`).
4. If repair fails:
   - restore from a recent backup if available,
   - consider re-importing from NDJSON exports if they exist.
5. Document:
   - root cause (if known),
   - data loss (if any),
   - mitigation steps.

### Unexpected costs or token usage

1. Run reports:
   - totals by provider/model,
   - top clients.
2. Identify outlier providers/models or clients.
3. Inspect raw and normalized events for those outliers.
4. Check pricing catalog entries for correctness and effective dates.
5. Adjust pricing catalog if incorrect; re-run rollups as needed.
6. Update coverage matrix if unexpected traffic sources are discovered.

## Upgrades

- When upgrading the token proxy implementation:
  - review release notes and migration steps,
  - apply any required database migrations,
  - bump schema and pricing versions as needed.
- Before and after upgrade:
  - run at least Scenario S1 (minimal correctness),
  - ideally run a subset of S2–S6 from `verification.md`.
- Record upgrade evidence:
  - before/after status,
  - relevant migration logs,
  - verification outcomes.

## Alignment with SDD artifacts

- `operations.md` is kept in sync with:
  - configuration formats defined in `design.md`,
  - verification scenarios in `verification.md`,
  - tasks in `tasks.md`.
- When operational behavior changes (for example new commands, different policies), update:
  - this document,
  - any affected configuration schemas,
  - verification scenarios that assert operational behavior.

## Full one-command verification execution

For deterministic end-to-end operation and evidence generation:

- `.venv_obsws/bin/python scripts/run_token_proxy_seed.py`

This command creates a complete evidence bundle (config snapshot, status, events, rollups, validation checks, limitations, and residual risks) under `evidence/token_proxy/<timestamp>/`.

