# Implementation Plan

## Panel Stream Control Tasks

- [ ] 1. Establish panel and channel configuration foundations
  - Define a logical panel model (e.g., `main`, `aux_left`, `aux_right`, `aux_center`) and map each to the corresponding OBS input name and scene item ID.
  - Create a lightweight configuration file for channels (e.g., `dw_live`, `bbc_live`, custom URLs) that can be referenced by scripts.
  - Implement a small helper module to load and validate panel and channel configuration at startup.
  - _Requirements: 1, 2, 3_

- [ ] 2. Implement "change channel on panel" command
- [ ] 2.1 Implement core channel change logic
  - Add a function that accepts `panel_id` and `channel_id` (or URL) and resolves them using the configuration and OBS WebSocket API.
  - Update the target panel’s OBS input settings to bind to the new stream while preserving position, scale, and alignment.
  - Return structured status (per panel) indicating success or failure and any diagnostics.
  - _Requirements: 1_

- [ ] 2.2 Expose a CLI entry point for channel changes
  - Add a CLI wrapper (e.g., `obs_panel_control.py --change-channel`) to call the core channel change logic with arguments.
  - Ensure CLI usage is scriptable from Hammerspoon or other automation (clear exit codes and JSON/text summaries).
  - Document example invocations for common scenarios (e.g., switching main panel to a specific news channel).
  - _Requirements: 1_

- [ ] 3. Implement "turn off selected panels" command
- [ ] 3.1 Implement panel off behavior in OBS
  - Add a function that accepts a list of `panel_id` values and resolves them to scene item IDs via the panel registry.
  - For each resolved panel, disable the corresponding scene item and ensure associated audio sources are muted.
  - Preserve each panel’s last-known channel in configuration so it can be restored later.
  - _Requirements: 2_

- [ ] 3.2 Expose a CLI entry point for turning panels off
  - Add CLI support (e.g., `--turn-off`) that takes one or more panel identifiers.
  - Ensure errors for individual panels do not abort the entire operation; report per-panel outcomes instead.
  - Provide clear terminal output summarizing which panels were successfully turned off and which failed.
  - _Requirements: 2_

- [ ] 4. Implement "start streaming selected panels" command
- [ ] 4.1 Implement panel start behavior in OBS
  - Add a function that accepts a list of `panel_id` values and re-enables their scene items if they are currently disabled.
  - If a panel has a preserved channel configuration, attempt to restore that channel and report any failures.
  - When no preserved channel exists, apply a default or prompt-driven behavior as defined in configuration, and report which branch was taken.
  - _Requirements: 3_

- [ ] 4.2 Expose a CLI entry point for starting panels
  - Add CLI support (e.g., `--start`) that starts streaming on one or more panels by logical ID.
  - Ensure the command returns clear, per-panel status codes and messages suitable for integration into scripts or keybindings.
  - Verify that repeated calls with the same arguments are idempotent and safe.
  - _Requirements: 3_

- [ ] 5. Verification and hardening
- [ ] 5.1 Add basic automated tests (where feasible)
  - Add unit tests for panel and channel resolution logic, including error cases (unknown panel, unknown channel).
  - Add integration tests or a manual test script to verify channel change, turn off, and start flows against a running OBS instance.
  - _Requirements: 1, 2, 3_

- [ ] 5.2 Operationalize scripts for everyday use
  - Wire the new commands into Hammerspoon or other automation entry points preferred on this machine.
  - Capture a short operator runbook describing how to invoke each command and interpret status output.
  - _Requirements: 1, 2, 3_

