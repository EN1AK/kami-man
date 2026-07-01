# bot-runtime Specification

## Purpose

Define the implemented NoneBot startup, adapter registration, and plugin-loading behavior for Kami Man Bot.

## Requirements

### Requirement: NoneBot runtime initialization

The system SHALL initialize a NoneBot application from `bot.py`.

#### Scenario: Bot process starts

- **GIVEN** `python bot.py` is executed
- **THEN** NoneBot is initialized with host `0.0.0.0`
- **AND** port `18080`
- **AND** command starts `/` and empty string
- **AND** superuser `2954452539`

### Requirement: OneBot V11 adapter registration

The system SHALL register the OneBot V11 adapter with the NoneBot driver.

#### Scenario: Adapter is available

- **GIVEN** the bot process starts
- **THEN** the OneBot V11 adapter is registered on the active NoneBot driver

### Requirement: Plugin loading

The system SHALL load scheduler support and all local plugins.

#### Scenario: Plugins are loaded

- **GIVEN** the bot process starts
- **THEN** `nonebot_plugin_apscheduler` is loaded
- **AND** all plugin modules under `plugins/` are loaded

## Open Questions

- The repository does not define whether runtime configuration should remain hard-coded or move to environment variables.
- The repository does not define a health-check endpoint or process supervisor contract.
