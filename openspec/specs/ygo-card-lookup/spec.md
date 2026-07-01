# ygo-card-lookup Specification

## Purpose

Define the implemented Yu-Gi-Oh! card search, image lookup, batch lookup, and ruling lookup behavior.

## Requirements

### Requirement: Yu-Gi-Oh! card search

The system SHALL support single-card Yu-Gi-Oh! lookup by command.

#### Scenario: User searches for one card

- **GIVEN** a user sends `ck <card name>` or `查卡 <card name>`
- **WHEN** YGOCDB returns one or more cards
- **THEN** the bot sends the first matching card
- **AND** includes the card image when image download succeeds
- **AND** includes formatted text containing common name, Master Duel name, type text, description, and pendulum description when present

#### Scenario: User omits card name

- **GIVEN** a user sends `ck` or `查卡` without a card name
- **THEN** the bot replies `错误: 请输入卡片名称`

#### Scenario: No card is found

- **GIVEN** a user searches for a card name
- **WHEN** YGOCDB returns no results
- **THEN** the bot replies `未找到卡片: <card name>`

### Requirement: Yu-Gi-Oh! card-image lookup

The system SHALL support image-only Yu-Gi-Oh! lookup.

#### Scenario: User searches for a card image

- **GIVEN** a user sends `查卡图 <card name>` or `卡图 <card name>`
- **WHEN** YGOCDB returns at least one card
- **AND** image download succeeds
- **THEN** the bot sends only the image

#### Scenario: Card image cannot be downloaded

- **GIVEN** a card is found
- **WHEN** both configured image URLs fail
- **THEN** the bot replies that the card was found but image download failed

### Requirement: Yu-Gi-Oh! batch lookup

The system SHALL support batch Yu-Gi-Oh! lookup.

#### Scenario: User searches in batch

- **GIVEN** a user sends `pl <card name>` or `批量查卡 <card name>`
- **WHEN** YGOCDB returns matching cards
- **THEN** the bot builds messages for at most 25 cards
- **AND** sends them using OneBot merged-forward messages

#### Scenario: Merged-forward send fails

- **GIVEN** a batch lookup or ruling response is sent
- **WHEN** merged-forward sending fails
- **THEN** the bot sends a fallback notice
- **AND** sends the messages one by one as normal messages

### Requirement: Yu-Gi-Oh! ruling lookup

The system SHALL support ruling lookup from YGOCDB card FAQ data.

#### Scenario: User searches rulings

- **GIVEN** a user sends `裁定 <card name>`, `ruling <card name>`, or `查裁定 <card name>`
- **WHEN** the card is found
- **AND** FAQ entries are available
- **THEN** the bot sends a merged-forward response
- **AND** includes a header with page number and total FAQ count
- **AND** includes up to 10 FAQ entries for the requested page

#### Scenario: User requests a ruling page

- **GIVEN** a user sends a ruling query ending with `2`, `p2`, `page2`, or `第2页`
- **THEN** the bot treats the suffix as the requested page number
- **AND** clamps page numbers below 1 to page 1

#### Scenario: Requested ruling page exceeds maximum

- **GIVEN** a user requests a page greater than the maximum available page
- **THEN** the bot replies that only the available page range exists

## External Dependencies

- Card search and FAQ data come from `https://ygocdb.com/api/v0/`.
- Card images are downloaded first from `https://cdn.233.momobako.com/ygoimg/ygopro/{id}.webp`, then from `https://cdncf.moecube.com/ygopro-super-pre/data/pics/{id}.jpg`.

## Open Questions

- YGOCDB response schemas are not committed in the repository.
- The repository does not define retry behavior beyond current per-request exception handling.
