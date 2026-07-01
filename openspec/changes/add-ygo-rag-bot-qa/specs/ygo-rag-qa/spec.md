## ADDED Requirements

### Requirement: Group mention triggers RAG QA

The system SHALL support natural-language Yu-Gi-Oh! RAG question answering in group chats when the bot is mentioned.

#### Scenario: Group user asks a question by mentioning the bot

- **WHEN** a group message contains an `at` mention targeting the bot and non-empty remaining text
- **THEN** the system treats the remaining text as the RAG question
- **AND** starts a RAG query workflow

#### Scenario: Mention contains no question text

- **WHEN** a group message mentions the bot but has no non-empty remaining text after bot mentions are removed
- **THEN** the system does not call the RAG service
- **AND** replies with a concise prompt asking the user to provide a question

#### Scenario: Group message does not mention the bot

- **WHEN** a group message does not contain an `at` mention targeting the bot
- **THEN** the system does not trigger RAG QA

### Requirement: Private chats do not trigger RAG QA

The system SHALL NOT trigger RAG QA from private messages.

#### Scenario: Private user sends a question

- **WHEN** a private message contains text that would otherwise be a RAG question
- **THEN** the system does not call the RAG service
- **AND** sends no RAG QA reply

### Requirement: RAG service HTTP request

The system SHALL call the deployed `ygo-rag` HTTP API for RAG answers.

#### Scenario: RAG query is submitted

- **WHEN** a valid group mention question is received
- **THEN** the system sends a `POST` request to the configured RAG API URL
- **AND** the request body includes the user question as `query`
- **AND** includes `semantic: true`
- **AND** includes `rerank: false`
- **AND** includes `llm_rerank: true`
- **AND** includes `llm: true`
- **AND** includes configured values for `top_k`, `rerank_candidates`, and `structured_max_block_chars`

#### Scenario: RAG API URL is not configured

- **WHEN** no RAG API URL is configured
- **THEN** the system uses `http://127.0.0.1:7860/api/query`

#### Scenario: RAG service returns warnings

- **WHEN** the RAG response includes non-empty `warnings`
- **THEN** the system includes those warnings in the bot response

### Requirement: Structured per-card response formatting

The system SHALL use the RAG API structured response to split replies by card.

#### Scenario: Structured card blocks are available

- **WHEN** the RAG response contains `structured.blocks`
- **THEN** each block with `type` equal to `card` becomes a separate bot message record
- **AND** the message text uses the block's `text` value

#### Scenario: Structured block is marked truncated

- **WHEN** a structured card block has `truncated: true`
- **THEN** the corresponding bot message record indicates that the card block was truncated

#### Scenario: Structured blocks are missing

- **WHEN** the RAG response does not contain usable `structured.blocks`
- **THEN** the system falls back to sending the response `answer` text split into safe message-sized chunks

### Requirement: Merged-forward delivery

The system SHALL send RAG answers as OneBot merged-forward messages in group chats.

#### Scenario: RAG answer is ready

- **WHEN** card blocks or fallback answer chunks are prepared
- **THEN** the system sends them as group merged-forward message nodes

#### Scenario: Merged-forward delivery fails

- **WHEN** sending group merged-forward messages fails
- **THEN** the system sends a fallback notice
- **AND** sends the prepared message texts as normal group messages in order

### Requirement: RAG service error handling

The system SHALL handle RAG service failures without crashing the bot.

#### Scenario: RAG request times out

- **WHEN** the RAG HTTP request exceeds the configured timeout
- **THEN** the system replies that the RAG query timed out

#### Scenario: RAG service returns an HTTP error

- **WHEN** the RAG service returns a non-success HTTP status
- **THEN** the system replies that the RAG service query failed

#### Scenario: RAG service response is malformed

- **WHEN** the RAG service returns JSON without a usable `answer` or structured blocks
- **THEN** the system replies that the RAG service returned an invalid response
