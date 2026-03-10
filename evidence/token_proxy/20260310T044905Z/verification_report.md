# Token Proxy End-to-End Verification Report

- Timestamp: `20260310T044905Z`
- Overall result: `FAIL`

## Residual risks

- Proxy coverage is limited to traffic routed through configured local endpoint.
- Real upstream provider failure semantics are only partially represented by local mocks.
- Advisory routing exhaust still leaves per-turn attribution unknown in this environment.
