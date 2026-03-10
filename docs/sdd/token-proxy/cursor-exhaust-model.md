# Cursor Exhaust Model (Attribution-Gap Lane)

## Purpose

This model captures deterministic local artifacts that hint at model routing behavior when exact per-turn attribution is not available from IDE/runtime logs.

It is an explicit **advisory lane**, not an authoritative source for per-request provider/model truth.

## Sources

- Cursor global state DB:
  - `cursor/bestOfNEnsemblePreferences`
  - `cursor/lastSingleModelPreference`
  - `cursor/planExecUseChatModel`
  - `cursor/newChatModelAutoSwitchApplied`
- Cursor extension logs:
  - `openai.chatgpt/Codex.log`
  - `Anthropic.claude-code/Claude VSCode.log`
- App pairing metadata:
  - `~/Library/Application Support/com.openai.chat/app_pairing_extensions/Cursor-*`

## Output contract

- Snapshot schema:
  - `docs/sdd/token-proxy/cursor-exhaust.schema.json`
- Extractor:
  - `scripts/extract_cursor_exhaust.py`
- Default pairing retention in snapshot:
  - most recent 25 records (configurable via `--max-pairings`)
- Optional sink outputs:
  - Prometheus textfile (`--prometheus-textfile`)
  - Neo4j import script (`--neo4j-cypher`)
- Status semantics:
  - `known`: direct authoritative attribution signal exists.
  - `partially_known`: only hints/preferences are visible.
  - `unknown`: no reliable attribution signal exists.

## Enrichment strategy

Use this lane to enrich, not replace, proxy telemetry:

- **Authoritative lane**:
  - proxy raw events and normalized events (request-level provider/model/token/cost).
- **Advisory lane**:
  - local exhaust snapshot fields and derived candidate model pools.

Join signals by:
- timestamp windows,
- workspace/session identifiers where available,
- client/tool identity hints.

## Sink guidance

- **Prometheus**: best for low-cardinality operational visibility and alerting (`unknown` attribution ratio, candidate pool size, runtime-log presence).
- **Neo4j**: best for relationship analysis across sessions/workspaces/models and later correlation with proxy event graph entities.
- Keep JSON snapshot as canonical source; sink outputs are deterministic projections.

## Guardrails

- Never claim exact per-turn model attribution from local exhaust alone.
- Keep schema versioned and validate every snapshot.
- Keep allowlisted extraction to avoid leaking prompt history or secrets.
- Treat conflicts between advisory and authoritative lanes as evidence of coverage gaps.
