# Token Proxy SDD Session Seed Prompt

```text
You are my implementation agent for building a production-grade token proxy and usage observability layer in this repository.
Treat this as SPECIFICATION-DRIVEN DEVELOPMENT (SDD), not ad-hoc coding.

## Mission
Design and implement a deterministic, auditable token proxy system so we can answer with evidence:
- Which API/provider/model handled each request
- Prompt/completion/total tokens per call
- Cost and latency per call
- Coverage gaps (what traffic is and is not visible)

## Zero-Step Bootstrap (Required Before SDD)
Run and report these checks first:
1) `node -v`
2) `npm -v`
3) `cc-sdd --version`

If `cc-sdd` is missing, install globally and verify:
- `npm install -g cc-sdd`
- `cc-sdd --version`

Do not continue until this bootstrap is complete and reported.

## Agent Identity Report (Required At Start)
Before requirements work, print a short "Agent Identity Report" with:
- active assistant/runtime identity as visible in-session
- model/routing visibility status (`known`, `partially known`, or `unknown`)
- whether exact per-turn auto-routing is inspectable from available artifacts
- execution mode and tool capabilities available for this session

If any identity/routing detail is not observable, say so explicitly and continue without guessing.

## Mandatory SDD Process (Do Not Skip)
Work in this order:
1) Requirements
2) Design
3) Task Breakdown
4) Execution
5) Verification + Evidence

Before implementation, create and align on:
- `docs/sdd/token-proxy/requirements.md`
- `docs/sdd/token-proxy/design.md`
- `docs/sdd/token-proxy/tasks.md`
- `docs/sdd/token-proxy/verification.md`
- `docs/sdd/token-proxy/operations.md`

If implementation reveals design gaps, STOP, patch SDD docs first, then continue.

## Non-Negotiable Cross-Cutting Concerns
1. Determinism and auditability
   - Every metric must be reproducible from logs.
   - Telemetry schema must be versioned.
   - Ingestion and rollups must be idempotent.
2. Coverage truthfulness
   - Build an explicit coverage matrix:
     - definitely observed traffic
     - partially observed traffic
     - unobservable traffic
   - Never claim full visibility without proof.
3. Security and privacy
   - Never log raw secrets/API keys.
   - Enforce redaction policy for sensitive fields.
   - Payload sampling configurable and off by default.
4. Reliability behavior
   - Define fail-open vs fail-closed by path.
   - Define outage/restart/backpressure behavior.
   - No silent data loss.
5. Performance
   - Measure p50/p95/p99 overhead introduced by proxy.
6. Cost correctness
   - Versioned pricing model.
   - Unknown pricing flagged, never guessed silently.
7. Operations
   - One-command start/stop/status.
   - Runbook for incident response and upgrades.

## Functional Minimum
Capture and persist:
- timestamp (UTC), request/correlation id
- client identity (app/script/source path when available)
- provider, model, endpoint
- prompt_tokens, completion_tokens, total_tokens
- estimated cost + pricing source/version
- latency and success/error status
- retries and terminal outcome
- dedupe fingerprint (non-sensitive hash)

Additionally capture local routing exhaust snapshot(s):
- Cursor routing preference artifacts (ensemble/single-model preferences)
- extension runtime activation summaries (Codex/Claude logs)
- session pairing metadata
- explicit attribution-gap status (`known` / `partially known` / `unknown`)
- emit at least one sink projection (`Prometheus` or `Neo4j`; both preferred)

Provide:
- append-only raw event log
- normalized analytics store/table
- daily rollups
- CLI/report commands for:
  - totals by provider/model
  - top token consumers by client
  - unknown/uncosted calls
  - coverage gaps

## Verification and Evidence (Required)
For each milestone, write artifacts under:
- `evidence/token_proxy/<timestamp>/`

Each bundle must include:
- redacted config snapshot
- health/status output
- sample raw events
- normalized rollup output
- validation checks with pass/fail
- known limitations and blind spots

Final verification must include:
- end-to-end test with at least two distinct model/provider calls
- proof of token and cost accounting
- proof supporting all coverage matrix claims
- proof that local routing-exhaust snapshots are schema-valid and do not over-claim per-turn attribution
- explicit residual risk list

## Delivery Rules
- No speculative success claims.
- Every claim maps to command output or artifact.
- Prefer deterministic/rule-based logic over heuristics.
- Keep existing OBS/Hammerspoon workflows non-breaking.

## Immediate First Step
Run Zero-Step Bootstrap, then emit the Agent Identity Report, then draft the five SDD docs.
Do not begin coding until those docs are internally consistent.
```
