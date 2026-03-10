# Agent Identity Report

- Active assistant/runtime identity: `gpt-5.3-codex-high` in Cursor coding-agent runtime.
- Model/routing visibility status: `partially known`.
- Exact per-turn auto-routing inspectability from available artifacts: `not directly inspectable`; only advisory routing preferences/log exhaust are available.
- Execution mode and capabilities used in this run:
  - tool-assisted local development with filesystem read/write, shell command execution, JSON/SQLite inspection,
  - deterministic Python execution harness with local mock providers,
  - schema validation via `jsonschema` in `.venv_obsws`.
