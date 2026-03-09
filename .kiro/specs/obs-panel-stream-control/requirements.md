# Requirements Document

## Introduction
This specification defines panel stream control for the OBS PiP layout managed from this machine.
The goal is to let the operator change the content channel for any panel, temporarily turn selected panels off,
and restart streaming on those panels without breaking the existing scene layout or projector setup.

## Requirements

### Requirement 1: Change channel on a panel
**Objective:** As an OBS operator, I want to change the channel shown in a specific panel without disrupting the overall PiP layout, so that I can quickly react to breaking news or switch feeds.

#### Acceptance Criteria
1. WHEN the operator selects a panel and a target channel THEN the system SHALL rebind that panel to the new stream source while preserving its position, scale, and alignment on the PiP scene.
2. IF the requested channel is already active in another panel THEN the system SHALL either warn the operator and request confirmation or provide a deterministic policy (e.g., swap, duplicate, or deny) documented in design.
3. WHEN the channel change completes THEN the system SHALL confirm success with a clear status message including which panel was updated and which channel is now active.
4. IF the channel change fails (e.g., invalid URL, OBS API error) THEN the system SHALL leave the existing panel binding unchanged and surface a diagnostic explaining what went wrong.

### Requirement 2: Turn off (stop streaming) selected panel(s)
**Objective:** As an OBS operator, I want to temporarily turn off one or more panels so that they stop streaming and/or disappear from the PiP view while keeping the rest of the layout intact.

#### Acceptance Criteria
1. WHEN the operator issues a "turn off" command for one or more panels THEN the system SHALL disable those panels’ scene items in OBS so they are no longer visible in the PiP output.
2. WHERE panel audio is routed through OBS THEN the system SHALL ensure that turning off a panel also mutes or removes its audio contribution so no sound leaks from an off panel.
3. WHILE a panel is turned off THE system SHALL preserve its configuration (panel identity, last channel, and geometry) so that it can be restarted without reconfiguration.
4. IF turning off a panel would violate a safety or policy constraint (for example, a minimum number of active panels) THEN the system SHALL reject the request and explain the reason.

### Requirement 3: Start streaming selected panel(s)
**Objective:** As an OBS operator, I want to start or resume streaming on one or more panels that are currently off so that I can bring feeds back into the PiP layout quickly and consistently.

#### Acceptance Criteria
1. WHEN the operator issues a "start streaming" command for one or more off panels THEN the system SHALL re-enable those panels’ scene items in OBS using their preserved geometry so they reappear in the same positions and sizes.
2. IF a restarted panel has a previously configured channel THEN the system SHALL attempt to restore that channel and report success or failure for each panel.
3. IF a restarted panel does not have a valid previous channel THEN the system SHALL prompt for a new channel selection before enabling the panel, or apply a documented default behavior.
4. WHILE a panel is in the process of starting THE system SHALL provide clear status so the operator can distinguish between pending, successful, and failed start operations.

