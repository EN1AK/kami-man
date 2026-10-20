## Purpose

Enable an existing group-chat bot to learn contextual expressions from bounded anonymous human evidence and retrieve them for relevant short replies without additional local model infrastructure.

## ADDED Requirements

### Requirement: Evidence-backed bounded learning
The system SHALL learn only for group 819151070 from at most eight anonymous historical samples per call, verify each expression's cited source, persist progress and daily limits, and exclude bot output from learning. Initial learning MUST require 100 messages and three speakers, later learning 50 new messages, with at most two successes and three attempts per Beijing day.

#### Scenario: Sufficient human evidence
- **WHEN** sufficient new samples exist and daily capacity remains
- **THEN** a leased learning batch is attempted and only valid cited expressions are persisted

#### Scenario: Collection stopped during learning
- **WHEN** collection is stopped or cleared while learning is in flight
- **THEN** that job cannot write back even after collection is resumed

### Requirement: Relevant retrieval and compatible replies
The system SHALL retrieve at most five relevant expressions locally, keep combined historical references within eight items, and decide abstention and reply content in a single generation call. Existing 20 daily attempts, five-minute cooldown and privacy filtering MUST remain. Clear MUST remove learned expressions; stored expressions MUST be bounded to 300 and 30 days.

#### Scenario: Unrelated conversation
- **WHEN** no expressions match the current topic
- **THEN** the bot is not forced to use an unrelated learned expression

#### Scenario: Inspect learning
- **WHEN** a member requests group learning status
- **THEN** the bot shows expression count, new-message progress and aggregate budget status without raw sample logs

#### Scenario: Bot output repeats or context advances
- **WHEN** a generated reply repeats recent bot output or the source conversation changed during generation
- **THEN** it is not sent and does not become learning evidence
