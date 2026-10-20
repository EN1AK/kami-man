## Purpose

Keep single-group proactive chat, expression learning and style summaries within a persistent configurable API budget while providing aggregate token and estimated expense visibility.

## ADDED Requirements

### Requirement: Persistent shared budget admission
The system SHALL atomically reserve estimated maximum call cost before group model invocation, default to CNY10 per month and CNY1 per day using Beijing dates, and include in-flight and uncertain failed calls in budget totals. Chat, learning and summaries MUST share this budget and explicitly disable thinking.

#### Scenario: Concurrent calls near the limit
- **WHEN** reservations would exceed a daily or monthly limit
- **THEN** excess calls are rejected before invoking the provider, including after a restart

### Requirement: Aggregate usage accounting
The system SHALL record route, input/output/cache/reasoning token counts when available, and estimated CNY cost without storing prompts or responses in the accounting ledger. Unknown usage MUST retain its reserved estimate.

#### Scenario: Successful metered response
- **WHEN** the provider returns valid token usage
- **THEN** the reservation is settled at configured conservative rates and appears in aggregate status

#### Scenario: Missing usage or provider failure
- **WHEN** actual token usage cannot be determined
- **THEN** the reservation remains counted rather than being treated as free
