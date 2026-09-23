# Riftbound Rules RAG QA Specification

## Purpose

让 QQ 群成员可以用自然语言询问 Riftbound 规则问题。机器人只负责群消息触发和结果格式化，不内置规则内容；自然语言问答事实源是部署完成的 `rift-rag` HTTP 服务。该服务通过卡名识别和有界的检索-回答 agent loop 生成带 `[rule_id]` 引用标记的回答，并显式暴露卡牌识别结果与未解析提及。本规格覆盖机器人侧所需的配置、触发、请求格式化、响应解析与合并转发展示。

## ADDED Requirements

### Requirement: Text alias triggers Riftbound RAG rules QA
The system SHALL trigger the Riftbound rules QA flow only in group messages when a plain text message starts with one of `问规则`, `规则`, or `问下规则`, and the remaining stripped text is non-empty.

#### Scenario: Alias with question enters the QA flow
- **WHEN** a group text message is `问规则 麦田圈在对方回合能发动吗`
- **THEN** the bot extracts `麦田圈在对方回合能发动吗` and enters the Riftbound RAG QA flow

#### Scenario: All aliases supported
- **WHEN** a group text message starts with `问规则`, `规则`, or `问下规则`
- **THEN** the bot enters the same Riftbound RAG QA flow

#### Scenario: No usable question text returns a short write error
- **WHEN** a group text message has only an alias or only whitespace after the alias
- **THEN** the bot replies with the short text `请在命令后写下问题内容` and does not call the QA service

#### Scenario: Non-matching or non-group message is ignored
- **WHEN** a message is private, is not a plain text message, or does not start with a supported alias
- **THEN** the bot does not enter the Riftbound RAG QA flow

### Requirement: Private chats never reply through the Riftbound RAG flow
The system SHALL return no reply in private messages for this feature.

#### Scenario: Private text with alias gets no response
- **WHEN** a private text message starts with `问规则`
- **THEN** the bot sends no reply from this feature

### Requirement: Bot sends the question through the configured RAG HTTP API
When a valid group question is found, the system SHALL send a `POST` request to `{RIFT_RAG_BASE_URL}/api/query` with JSON body `{ "query": <question text> }` plus the configured `mode` (default `agent`) and `trace` flag, waiting up to the configured timeout for the service to finish its agent loop. The default base URL SHALL be `http://127.0.0.1:7862`; it MAY be overridden with `RIFT_RAG_BASE_URL` / `RIFT_QA_BASE_URL`. The timeout value SHALL come from `RIFT_RAG_TIMEOUT_SECONDS` / `RIFT_QA_TIMEOUT_SECONDS` with a default matching the deployed service's worst-case agent-loop latency.

#### Scenario: Question is posted to the query API
- **WHEN** a group enters the QA flow with question `海兽钓钩的放逐怎么处理`
- **THEN** the bot sends one `POST` request with `query` set to `海兽钓钩的放逐怎么处理` and the configured `mode` to the configured query API
- **AND** waits up to the configured timeout for the response

#### Scenario: Base URL, mode, and timeout are configurable through environment variables
- **WHEN** the bot process starts with explicit `RIFT_RAG_*` or `RIFT_QA_*` environment variables
- **THEN** the QA client uses those settings for the HTTP request

### Requirement: Bot consumes additive contract-v2 fields tolerantly
The system SHALL accept success JSON containing `answer` (string), `warnings` (string list), and `sources` (object list), and SHALL tolerate missing, extra, or empty values for the agent-mode fields `mode`, `exhausted`, `resolved_cards`, `coverage` (`unresolved_mentions` / `ambiguous_mentions`), and `trace`. A response produced by an older one-shot service without these fields SHALL still be accepted.

#### Scenario: Full v2 response parses
- **WHEN** the service returns `answer`, `warnings`, `sources`, plus `exhausted`, `resolved_cards`, and `coverage`
- **THEN** the bot parses all available fields for display

#### Scenario: Legacy response without v2 fields parses
- **WHEN** the service returns only `answer`, `warnings`, and `sources`
- **THEN** the bot treats the missing agent fields as empty/absent and still delivers the answer and sources

### Requirement: Bot surfaces recognized cards and mention coverage
When present, the system SHALL surface recognized cards as a short `识别卡牌：…` line and unresolved or ambiguous mentions as warning lines in the forwarded content. `exhausted=true` SHALL be surfaced as a warning line and SHALL NOT be treated as an error or an invalid result. These lines use only service-provided card ids and mentions; the bot SHALL NOT render cards, infer card names, or search missing mentions by itself.

#### Scenario: Recognized cards are shown
- **WHEN** the response contains `resolved_cards` with card `OGN-242` / `海兽钓钩`
- **THEN** the merged-forward content includes a line like `识别卡牌：海兽钓钩（OGN-242）`

#### Scenario: Unresolved or ambiguous mentions become warnings
- **WHEN** the response `coverage` contains unresolved or ambiguous mentions
- **THEN** the bot shows them as warning lines so users can see which names were not resolved

#### Scenario: Exhausted loop remains a deliverable answer
- **WHEN** the service returns `exhausted=true` with a fallback `answer`
- **THEN** the bot still forwards the answer and sources, adding a warning line such as `已达检索步数上限，答案基于部分证据`

### Requirement: Bot keeps and displays the cited QA answer
The system SHALL treat a populated `answer` string as the QA result, keep `[rule_id]` citation markers unchanged, and send the answer plus the configured base URL as one merged-forward node.

#### Scenario: Answer with citation markers is forwarded intact
- **WHEN** the service returns answer text containing markers like `[R-CR-716.1.1]`
- **THEN** the final bot answer keeps those markers unchanged
- **AND** the merged-forward output includes the answer text
- **AND** the same node includes a line `回答生成自 {RIFT_RAG_BASE_URL}` with the actual configured base URL

### Requirement: Bot formats cited rules as merged-forward output
The system SHALL format successful QA output as OneBot V11 merged-forward message nodes with the question (including recognized-card and coverage lines when present), cited rules, and answer nodes, with plain message text fallback only for merged-forward API failures. Merged-forward node sender SHALL use the active command message sender self name and self ID. A rule source SHALL contribute one node whose content adds topic text only when `topic` is a populated string.

#### Scenario: Question, rules, and answer nodes are built in order
- **WHEN** the service returns a cited answer and one or more sources
- **THEN** the first node carries the original question text plus any recognized-card or coverage lines
- **AND** each source creates one merged-forward node with content headed by `规则 {rule_id}`
- **AND** a populated `topic` value adds a separate line `主题 {topic}`
- **AND** an empty, whitespace-only, missing, or non-string `topic` adds no topic line
- **AND** the sourced answer is appended as the final merged-forward node
- **AND** the original command message sender name appears as each node sender name
- **AND** the original command message sender user ID appears as each node sender user ID

#### Scenario: Sender falls back when only one identity part is present
- **WHEN** a source/answer/question node is built and only sender name or sender user ID is available
- **THEN** the bot still sends the merged-forward message with the available identity metadata

### Requirement: Neither usable answer nor cited rules is an invalid result
The system SHALL treat a success response whose `answer` is empty or whitespace and whose `sources` is empty or missing as an invalid result and SHALL reply with the service-data write error text.

#### Scenario: Empty answer and no sources returns a write error
- **WHEN** the service response has an empty or whitespace-only `answer` and no usable sources
- **THEN** the bot replies with a short text that matches `RAG 服务返回了空结果，请检查 7862 端口服务日志`

### Requirement: RAG failures map to fixed QQ failure messages
The system SHALL map connection failures, timeouts, pending unavailability, and upstream/API 5xx data failures to the documented fixed short texts in `plugins/rift_rag_qa.py`, and SHALL reuse this mapping across RAG call sites. Timed-out or explicitly busy backend requests SHALL remain distinguishable from other upstream failures.

#### Scenario: Connection failure is reported as a connection problem
- **WHEN** the call to the RAG service raises a connection error
- **THEN** the bot replies with the short text `连接失败：请确认 7862 端口服务已启动`

#### Scenario: Timeout is reported as a timeout
- **WHEN** the call to the RAG service times out
- **THEN** the bot replies with the short text `请求超时，请稍后重试`

#### Scenario: Upstream data failure is reported with a service-specific message
- **WHEN** the RAG service returns a non-success or malformed response
- **THEN** the bot replies with a short text that matches `RAG 服务返回异常 ...` or the documented internal-error text

#### Scenario: Internal service failure is reported as internal
- **WHEN** the RAG service returns an explicit internal-failure result
- **THEN** the bot replies with a short text that matches `RAG 服务内部错误，请稍后重试或检查 7862 端口日志`

### Requirement: Dedicated runtime configuration for QA client
The system SHALL expose one runtime settings block for QA features with the RAG base URL override key `RIFT_RAG_BASE_URL` / `RIFT_QA_BASE_URL`, timeout key `RIFT_RAG_TIMEOUT_SECONDS` / `RIFT_QA_TIMEOUT_SECONDS`, mode key `RIFT_RAG_MODE` (default `agent`), and trace key `RIFT_RAG_TRACE` (default off). QA plugins SHALL obtain settings through that QA configuration instead of unrelated blocks.

#### Scenario: Settings expose base URL, timeout, and mode for the RAG QA client
- **WHEN** the QA settings block is loaded
- **THEN** it provides an HTTP base URL, a numeric timeout, the request `mode`, and the trace flag used by the QA flow
