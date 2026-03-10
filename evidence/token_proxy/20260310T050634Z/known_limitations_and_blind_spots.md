# Known Limitations and Blind Spots

- Verification uses deterministic local mock providers; real provider auth/rate limits are not exercised.
- Only OpenAI-style chat endpoint is implemented in this milestone.
- Fail-open path returns synthetic response for degraded upstream state and should be revisited for production fallback strategy.
- Traffic that bypasses proxy remains unobservable by design and is tracked via coverage matrix, not telemetry events.
- Cursor routing exhaust is advisory and cannot attribute exact per-turn model/provider routing.
