# riftbound-card-lookup Specification

## Purpose

Define the implemented Riftbound local card database, search, single-card lookup, batch lookup, and sync-script behavior.

## Requirements

### Requirement: Riftbound local card database

The system SHALL use `data/riftbound_cards.json` as the local Riftbound card database.

#### Scenario: Card database exists

- **GIVEN** `data/riftbound_cards.json` exists
- **THEN** Riftbound lookup loads cards from that JSON file using UTF-8

#### Scenario: Card database is missing

- **GIVEN** `data/riftbound_cards.json` does not exist
- **THEN** Riftbound lookup behaves as if there are no cards

### Requirement: Riftbound card search

The system SHALL search Riftbound cards by normalized card fields.

#### Scenario: User searches cards

- **GIVEN** a search keyword
- **THEN** the system normalizes the keyword by lowercasing, removing normal spaces and full-width spaces, and trimming
- **AND** compares against normalized `zh_name`, `en_name`, `code`, `id`, and `set`
- **AND** returns exact normalized-field matches before partial matches

### Requirement: Single Riftbound lookup

The system SHALL support single-card Riftbound lookup.

#### Scenario: User searches one Riftbound card

- **GIVEN** a user sends `rb <keyword>`, `符文查卡 <keyword>`, or `符文 <keyword>`
- **WHEN** matching cards exist
- **THEN** the bot sends the first matching card
- **AND** includes the card image when `image_url` download succeeds
- **AND** includes formatted card text

#### Scenario: User omits keyword

- **GIVEN** a user sends `rb`, `符文查卡`, or `符文` without a keyword
- **THEN** the bot replies with an error asking for a card name

### Requirement: Batch Riftbound lookup

The system SHALL support batch Riftbound lookup.

#### Scenario: User searches Riftbound cards in batch

- **GIVEN** a user sends `rbpl <keyword>`, `符文批量 <keyword>`, or `符文批量查卡 <keyword>`
- **WHEN** matching cards exist
- **THEN** the bot builds messages for at most 8 cards
- **AND** sends them using OneBot merged-forward messages

#### Scenario: Batch lookup in unsupported message type

- **GIVEN** a batch response is requested from a message type that is not group or private
- **THEN** the bot sends `当前消息类型暂不支持合并转发。`

### Requirement: Riftbound data synchronization script

The system SHALL include a manual script to regenerate the local Riftbound card database.

#### Scenario: Sync script runs

- **GIVEN** `python assets/sync_riftbound_db.py` is executed
- **THEN** the script downloads `card_detail.json` and `cardDB.json`
- **AND** normalizes and merges cards
- **AND** writes UTF-8 JSON to `data/riftbound_cards.json`

## External Dependencies

- Sync data source: `https://raw.githubusercontent.com/choowx2002/project_k_image/main/card_detail.json`
- Sync data source: `https://raw.githubusercontent.com/choowx2002/project_k_image/main/cardDB.json`
- Runtime card images are downloaded from each card's `image_url`.

## Open Questions

- The repository does not define how often `data/riftbound_cards.json` should be regenerated.
- Batch Riftbound merged-forward sending has no implemented exception fallback; desired failure behavior is not specified.
