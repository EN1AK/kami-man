## Why

Kami Man Bot currently supports deterministic Yu-Gi-Oh! card lookup and ruling lookup, but it cannot answer natural-language similarity questions such as “有没有效果类似某张卡的卡”. The separate `ygo-rag` project now exposes an HTTP API with structured per-card response blocks, making it practical to add group-chat RAG question answering without embedding the heavy RAG runtime into the bot process.

## What Changes

- Add a new group-only RAG QA capability triggered by mentioning the bot and providing a question.
- Call a same-server `ygo-rag` HTTP service instead of importing the RAG package into the bot process.
- Use LLM answer generation and LLM judge reranking by default.
- Send answers as OneBot merged-forward message records, split primarily by `structured.blocks[*].text` so each retrieved card becomes its own node.
- Do not trigger or reply to this feature in private chats.
- Add configurable RAG API endpoint, timeout, top-k, rerank candidate count, and per-card block length limits.
- Handle RAG warnings, timeout, HTTP errors, and malformed responses with user-visible failure messages.

## Capabilities

### New Capabilities

- `ygo-rag-qa`: Group-only natural-language Yu-Gi-Oh! RAG question answering through a deployed `ygo-rag` HTTP service, including default LLM rerank/answer settings and merged-forward per-card response formatting.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - New plugin under `plugins/` for group `@bot` RAG QA handling.
  - New service module under `services/` for `ygo-rag` HTTP API calls and response validation.
  - Possible small shared helper for merged-forward sending if duplication with existing card lookup handlers is reduced.
- Affected runtime systems:
  - Requires `ygo-rag` to be deployed as a long-running HTTP service on the bot server, expected to listen on a local endpoint such as `http://127.0.0.1:7860/api/query`.
  - Requires the `ygo-rag` service environment to provide `DEEPSEEK_API_KEY` for both LLM judge rerank and final LLM answer generation.
- Affected dependencies:
  - Bot side can use existing `httpx`; no RAG model dependencies should be added to the bot process.
- User-visible behavior:
  - Group users can ask questions by mentioning the bot.
  - Private users cannot trigger this feature.
