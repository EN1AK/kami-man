# runtime-data Specification

## Purpose

Define the implemented local runtime JSON storage behavior and ignored generated/runtime files.

## Requirements

### Requirement: Runtime JSON directory

The system SHALL use the `data/` directory for local runtime JSON state.

#### Scenario: MyCard service module is imported

- **GIVEN** `services/mycard_api.py` is imported
- **THEN** the `data/` directory is created if it does not exist

### Requirement: MyCard user binding storage

The system SHALL store MyCard user bindings in `data/mycard_user.json`.

#### Scenario: Binding is saved

- **GIVEN** a QQ user id and MyCard username
- **THEN** the file stores a JSON object mapping QQ user id strings to MyCard username strings

#### Scenario: Binding file cannot be read

- **GIVEN** `data/mycard_user.json` is missing or unreadable
- **THEN** binding reads return an empty object

### Requirement: MyCard subscription storage

The system SHALL store MyCard subscriptions in `data/subscribe.json`.

#### Scenario: Subscription is saved

- **GIVEN** a MyCard username has subscriptions
- **THEN** the file stores a JSON object mapping that username to a list of two-item arrays
- **AND** each array contains target type and target id as strings

#### Scenario: Subscription file cannot be read

- **GIVEN** `data/subscribe.json` is missing or unreadable
- **THEN** subscription reads return an empty object

### Requirement: MyCard latest-match cache

The system SHALL store latest-match cache values in `data/last_match.json`.

#### Scenario: Match cache is saved

- **GIVEN** a MyCard username has a cached latest match
- **THEN** the file stores a JSON object mapping that username to a match key string

#### Scenario: Match cache file cannot be read

- **GIVEN** `data/last_match.json` is missing or unreadable
- **THEN** cache reads return an empty object

### Requirement: JSON write format

The system SHALL write MyCard runtime JSON using UTF-8.

#### Scenario: Runtime JSON is written

- **GIVEN** MyCard runtime data is saved
- **THEN** JSON is written with indentation of 4
- **AND** non-ASCII characters are preserved

### Requirement: Runtime data is not source-controlled by default

The project SHALL ignore runtime JSON and generated help images.

#### Scenario: Git ignore rules are evaluated

- **THEN** `data/*.json` is ignored
- **AND** `assets/help.png` is ignored

## Open Questions

- The repository does not define migration behavior if JSON schemas change.
- The repository does not define locking or concurrency handling for simultaneous JSON writes.
- The repository currently contains local runtime JSON files in the working tree even though `.gitignore` excludes them; their lifecycle is not documented.
