## Purpose

Allow explicitly mentioned casual conversations to use an original persona and optional memes while ensuring professional Agent prompts, histories, evidence and delivered results remain isolated from persona context.

## ADDED Requirements

### Requirement: Fixed command routing
The system SHALL route text only by explicit command prefixes: ck, pl, rb, rbpl, translate, 查卡, 裁定, 翻译, 规则, 查价, 卡价 and existing Rift rule aliases. All other text MUST use the persona path regardless of subject matter, previous route, quoted route or model opinion. Routing MUST NOT call an LLM. Images retain the existing translation path. Routing failures MUST report an error and refund quota instead of silently selecting professional. Persona output MUST NOT escalate requests automatically.

#### Scenario: Specialist request
- **WHEN** a user starts a request with a configured professional command
- **THEN** the original request reaches the professional path without persona or learned-style fields

### Requirement: Independent histories and quotes
The system SHALL store casual history separately by bot/group/user and use a fresh professional session namespace that does not read old mixed history. Persona output and unknown-provenance quotes MUST NOT be forwarded to the professional Agent.

#### Scenario: Casual followed by rules question
- **WHEN** a user chats in character then asks a card-ruling question prefixed with 裁定, optionally quoting that persona reply
- **THEN** the professional request receives neither the casual history nor the quoted persona text

#### Scenario: Professional follow-up
- **WHEN** a user follows up on a verified professional answer using a professional command
- **THEN** professional session context and the verified professional quote can be used without persona rewriting

### Requirement: Casual persona and direct professional results
The system SHALL use the unchanged original persona and optional local memes for casual @ conversations. Learned style MUST only be read for the existing allowed group. Professional answers, card text, rules conditions and references MUST be sent directly without persona postprocessing.

#### Scenario: Casual request in another group
- **WHEN** another group mentions the bot for ordinary chat
- **THEN** the bot can use the fixed persona but cannot receive the allowed group's learned style or expressions

### Requirement: Shared quota and complete clearing
The system SHALL charge one existing personal quota unit per @ request, refund failed requests, keep images on their existing path and clear both isolated and legacy histories without model calls or quota charges. In-flight requests and clear MUST be serialized per scoped session.

#### Scenario: Clear after casual and professional turns
- **WHEN** the user sends 清空对话
- **THEN** casual, professional and legacy histories and local quote metadata are cleared without LLM calls

#### Scenario: Quota exhausted
- **WHEN** the personal daily quota has no capacity
- **THEN** neither routing nor persona generation is invoked
