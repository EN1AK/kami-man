## ADDED Requirements

### Requirement: Group mention translation command

The system SHALL support LLM translation in group chats when the bot is mentioned and the message uses a translation command.

#### Scenario: Group user requests translation

- **WHEN** a group message contains an `at` mention targeting the bot and the remaining text begins with a supported translation command
- **AND** the text after the translation command is non-empty
- **THEN** the system treats the text after the command as the translation request
- **AND** starts a translation workflow

#### Scenario: Translation command has no input

- **WHEN** a group message mentions the bot and uses a supported translation command
- **AND** there is no non-empty text after the translation command
- **THEN** the system does not call the translation service
- **AND** replies with a concise prompt asking the user to provide text to translate

#### Scenario: Group message mentions the bot without translation command

- **WHEN** a group message mentions the bot but does not use a supported translation command
- **THEN** the system does not trigger the translation workflow

### Requirement: Private chats do not trigger translation

The system SHALL NOT trigger LLM translation from private messages.

#### Scenario: Private user sends translation command

- **WHEN** a private message contains text that would otherwise be a valid translation command
- **THEN** the system does not call the translation service
- **AND** sends no translation reply

### Requirement: Translation service HTTP request

The system SHALL call the deployed `ygo-rag` agent HTTP API for LLM translation.

#### Scenario: Translation request is submitted

- **WHEN** a valid group mention translation command is received
- **THEN** the system sends a `POST` request to the configured translation API URL
- **AND** the request body includes the user's translation request text

#### Scenario: Translation API URL is not configured

- **WHEN** no translation API URL is configured
- **THEN** the system uses the default local `ygo-rag` agent translation endpoint

#### Scenario: Translation service returns warnings

- **WHEN** the translation response includes non-empty warnings
- **THEN** the system includes those warnings in the bot response

### Requirement: Translation response formatting

The system SHALL send the LLM translation result back to the group in safe message-sized records.

#### Scenario: Translation result is ready

- **WHEN** the translation service returns non-empty translated text
- **THEN** the system prepares one or more outbound message records containing the translated text
- **AND** preserves the order of the translated text

#### Scenario: Translation result is long

- **WHEN** the translated text exceeds the configured message chunk size
- **THEN** the system splits the translated text into multiple message records
- **AND** sends the records in order

#### Scenario: Translation response is empty

- **WHEN** the translation service returns no usable translated text
- **THEN** the system replies that the translation service returned no sendable result

### Requirement: Translation service error handling

The system SHALL handle translation service failures without crashing the bot.

#### Scenario: Translation request times out

- **WHEN** the translation HTTP request exceeds the configured timeout
- **THEN** the system replies that the translation request timed out

#### Scenario: Translation service returns an HTTP error

- **WHEN** the translation service returns a non-success HTTP status
- **THEN** the system replies that the translation service request failed

#### Scenario: Translation service response is malformed

- **WHEN** the translation service returns JSON without usable translated text
- **THEN** the system replies that the translation service returned an invalid response
