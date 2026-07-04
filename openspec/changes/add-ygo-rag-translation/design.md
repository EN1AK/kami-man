## Context

Kami Man Bot already talks to the separately deployed `ygo-rag` service over HTTP for group RAG QA. That separation is still the right boundary for translation: the bot should parse chat commands and deliver messages, while `ygo-rag` owns LLM credentials, prompt logic, and model/provider integration.

The new `ygo-rag` agent translation feature is available on the same bot server as a local HTTP API at `POST /api/translate`.

## Goals / Non-Goals

**Goals:**

- Add a group-only `@bot` translation command path.
- Route translation requests to the deployed `ygo-rag` agent LLM translation API.
- Split long translation results into message-sized records before sending.
- Keep private messages from triggering translation.
- Keep translation command handling from accidentally falling through to the existing RAG QA workflow.
- Keep LLM credentials and provider SDKs out of the bot process.

**Non-Goals:**

- Do not implement translation inside Kami Man Bot.
- Do not add embedding, reranker, LLM SDK, or `rag_agent` imports to the bot process.
- Do not change existing RAG QA request defaults or retrieval behavior.
- Do not support private-chat translation in this change.
- Do not persist translation history or add bot-side caching.

## Decisions

### Use a separate translation command route

The bot will recognize translation only when a group message mentions the bot and the remaining text begins with a translation command alias, such as `翻译` or `translate`.

Rationale: RAG QA currently treats `@bot <question>` as a natural-language question. Translation needs an explicit command to avoid stealing normal RAG questions and to match the requested trigger behavior.

Alternative considered: infer translation intent from natural language. This was rejected because it would create ambiguous routing between RAG QA and translation.

### Call `ygo-rag` over HTTP

The bot will call a configured translation API URL on the deployed `ygo-rag` service. The default endpoint is `http://127.0.0.1:7860/api/translate`.

Rationale: `ygo-rag` owns the LLM translation implementation and credentials. HTTP keeps deployment and dependency boundaries consistent with the existing RAG QA integration.

Alternative considered: import `rag_agent` directly. This was rejected because it would move LLM/runtime dependencies and failure modes into the NoneBot process.

### Treat command argument as the translation request

The parser will strip the bot mention and translation command, then send the remaining text to the agent as the translation input. The bot also sends configured `source_lang`, `target_lang`, and `structured_max_block_chars` fields.

Rationale: The user request only specifies a translation command and agent LLM translation. Passing the command argument through avoids inventing bot-side language parsing, while environment-configured language defaults map directly to the agent API.

Alternative considered: add bot-side syntax such as `翻译到日文 <text>`. This may be useful later but is not required for the first integration.

### Reuse long-message splitting and forward delivery patterns

Translation responses may be long. The bot will split text into safe chunks and send them as message records. If merged-forward delivery is reused and fails, the bot should fall back to normal group messages in order.

Rationale: Existing RAG QA already has a long-answer delivery pattern. Translation should not risk OneBot message length failures.

Alternative considered: send a single plain message. This was rejected because long translations can exceed practical message limits.

## Risks / Trade-offs

- Unknown agent API contract -> Confirm endpoint, request body, and response fields before implementation; keep bot settings configurable.
- Command collision with RAG QA -> Give the translation handler higher priority or explicitly make RAG QA ignore translation commands.
- Long translation responses still too many messages -> Use chunk size limits and preserve order.
- LLM translation latency -> Use a configurable timeout and user-facing timeout error.
- Agent unavailable -> Map HTTP/network errors to concise group replies without crashing the bot.

## Migration Plan

1. Confirm the `ygo-rag` translation API endpoint, request body, and response fields.
2. Add bot-side translation API settings and parser/formatter helpers.
3. Add a group-only plugin route for `@bot 翻译 ...` / `@bot translate ...`.
4. Ensure the existing RAG QA route does not process translation commands.
5. Add unit tests for parsing, API payload/response validation, routing, private-chat suppression, and long-response splitting.
6. Update help and deployment documentation with the new environment settings.
7. Deploy bot code after the `ygo-rag` agent translation endpoint is available on the server.

Rollback: disable or remove the translation plugin/configuration and restart `kami-man.service`. Existing RAG QA and card lookup behavior should remain independent.

## Open Questions

- None. The agent contract is `POST /api/translate` with request fields `text`, `source_lang`, `target_lang`, and `structured_max_block_chars`; response fields include `translation`, `warnings`, and `structured.blocks`.
