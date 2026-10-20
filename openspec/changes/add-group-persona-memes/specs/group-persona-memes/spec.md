## Purpose

Allow the existing lightweight group chatbot to use an unchanged upstream persona and optional classified meme images while continuing its independent learning from bounded human text samples.

## ADDED Requirements

### Requirement: Original persona with independent learning
The system SHALL preserve the upstream Big Fish persona text without edits and keep provenance. Group style descriptions and human expression samples MUST continue to be supplied independently and MUST NOT rewrite that persona. Bot output MUST remain excluded from human learning.

#### Scenario: Persona installed
- **WHEN** the configured original persona is available
- **THEN** generation includes its complete original text alongside existing runtime constraints and learned style data

#### Scenario: Legacy operation
- **WHEN** no default persona asset or meme catalog is installed
- **THEN** text-only group chat remains usable

### Requirement: Single-call optional category selection
The system SHALL select optional meme categories in the existing generation call, accept only bounded advertised categories and preserve old clients' reply contract. Unavailable images MUST fall back to text. Image-only replies MUST be supported when a valid category is selected.

#### Scenario: Combined reply
- **WHEN** a valid category is selected and delivery capacity remains
- **THEN** the bot sends at most one image with optional text without another model call

#### Scenario: Unsafe or unknown selection
- **WHEN** the reply is filtered or the category is not advertised
- **THEN** no image is sent for that selection

### Requirement: Bounded local media delivery
The system SHALL send only validated local raster files of at most 4MiB, protect against traversal and symlinks, persist a five-attempt daily image limit and 30-minute cooldown, avoid identical images for seven days, and apply existing collection/chat/context checks to every delivery. Requested memes MUST be probabilistically limited to 25 percent by default.

#### Scenario: Restart near image limit
- **WHEN** an image request arrives after restart while the daily cap or cooldown is active
- **THEN** no additional image reservation is admitted

#### Scenario: Admin stops an in-flight reply
- **WHEN** collection or chat is stopped, cleared, or the source context changes during generation
- **THEN** neither text nor image from the stale generation is sent

#### Scenario: Learning status requested
- **WHEN** a user requests existing group learning status
- **THEN** aggregate installed image and daily image-attempt counts are available without raw member messages
