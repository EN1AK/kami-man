## Context

Kami Man Bot is a NoneBot2/OneBot V11 QQ bot. It currently handles card lookup, rulings, MyCard statistics, subscriptions, help images, and admin commands through local plugins.

`ygo-rag` is a separate project that runs heavier retrieval and LLM workloads. Its updated HTTP API exposes `POST /api/query` and returns both the original `answer/results/warnings` fields and a `structured` object whose `blocks` are already split per card for bot delivery.

The target deployment is a bot server running both services:

```text
QQ group message
  -> Kami Man Bot plugin
  -> http://127.0.0.1:7860/api/query
  -> ygo-rag retrieval + LLM rerank + LLM answer
  -> structured per-card blocks
  -> OneBot merged-forward message records
```

## Goals / Non-Goals

**Goals:**

- Add a group-only natural-language Yu-Gi-Oh! RAG QA entry point.
- Trigger only when a group message mentions the bot and contains a non-empty question.
- Call the deployed `ygo-rag` HTTP API with LLM answer generation and LLM judge rerank enabled by default.
- Use `structured.blocks[*].text` as the primary unit for merged-forward response nodes, so each card is a separate message record.
- Surface API warnings and errors clearly.
- Keep heavy RAG dependencies and model loading outside the bot process.

**Non-Goals:**

- Do not embed `rag_agent` directly into Kami Man Bot.
- Do not implement or modify the `ygo-rag` service in this change.
- Do not enable this feature in private chat.
- Do not redesign existing `ck`, `pl`, `裁定`, or MyCard commands.
- Do not add a database or persistent bot-side cache for RAG results.

## Decisions

### Use HTTP service boundary

The bot will call a configured HTTP endpoint, defaulting to `http://127.0.0.1:7860/api/query`.

Rationale: `ygo-rag` depends on Chroma, embedding/rerank models, and LLM integrations. Keeping it in a separate process avoids slowing bot startup, avoids dependency conflicts, and lets the bot server supervise/restart the RAG service independently.

Alternative considered: import `rag_agent.query_service.execute_query` directly. This was rejected because model loading and CPU/GPU work would share the NoneBot event loop process.

### Trigger on group mention only

The plugin will handle `GroupMessageEvent` only. It will inspect message segments for an `at` segment matching the bot self id, remove all bot mentions from the question text, and ignore empty questions.

Rationale: The user explicitly required `@bot` question behavior and private chat must not trigger the feature. Mention-only triggering also avoids collisions with existing empty-prefix commands.

Alternative considered: register a command such as `rag`. This is simpler but does not match the desired chat UX.

### Default request payload

The bot will send defaults equivalent to:

```json
{
  "semantic": true,
  "rerank": false,
  "llm_rerank": true,
  "llm": true,
  "top_k": 5,
  "rerank_candidates": 5,
  "structured_max_block_chars": 1800
}
```

Rationale: The confirmed product behavior is LLM answer plus LLM judge rerank. Keeping `rerank` false avoids local BGE reranker usage by default. Initial `top_k` and `rerank_candidates` should be modest because each group question can trigger DeepSeek calls.

Alternative considered: use `top_k: 10` and `rerank_candidates: 20`. This follows `ygo-rag` CLI defaults but may be too slow and costly for chat use.

### Prefer structured blocks over parsing free-form LLM text

Merged-forward nodes will be built from `structured.blocks[*].text` when available. The bot may add a leading summary/warnings node and can fall back to answer text if structured blocks are absent.

Rationale: The updated API provides per-card blocks specifically for bot delivery. This avoids fragile regex parsing of `answer`.

Alternative considered: split `answer` by card numbering. This is unreliable because LLM output is free-form.

### Response delivery and fallback

The bot will send the RAG result as merged-forward messages for group chats. If merged-forward sending fails, it will fall back to normal group messages using the same node text order.

Rationale: RAG answers can be long, and existing Yu-Gi-Oh! batch/ruling behavior already uses merged-forward with fallback.

### Configuration

Configuration will be read from environment variables with code defaults:

- `YGO_RAG_API_URL`
- `YGO_RAG_TIMEOUT_SECONDS`
- `YGO_RAG_TOP_K`
- `YGO_RAG_RERANK_CANDIDATES`
- `YGO_RAG_STRUCTURED_MAX_BLOCK_CHARS`

Rationale: The project does not currently have a config file system, and environment variables are consistent with deployment-sensitive values.

## Risks / Trade-offs

- RAG service unavailable or slow -> Use HTTP timeout and return a concise failure message to the group.
- DeepSeek timeout or malformed LLM rerank response -> Rely on `ygo-rag` warnings and include them in the response when present.
- Empty-prefix NoneBot command configuration could create accidental matches -> Use a message matcher or regex/checker that explicitly requires group mention.
- Merged-forward can be rejected by QQ/NapCat risk controls -> Fall back to normal group messages.
- Per-card blocks can still be too long -> Pass `structured_max_block_chars` and respect the returned `truncated` flag.
- LLM answer text may contain useful summary not present in card blocks -> Add a summary node from `answer` when it is present and not redundant, or include it after card blocks if the implementation can keep message count reasonable.

## Migration Plan

1. Deploy `ygo-rag` on the bot server and verify `POST /api/query` locally.
2. Configure DeepSeek credentials in the `ygo-rag` service environment.
3. Deploy the bot plugin with the default local RAG API endpoint.
4. Test in a non-production QQ group by mentioning the bot with a short question.
5. Roll back by disabling/removing the new plugin or unsetting the RAG endpoint configuration; existing bot features are otherwise independent.

## Open Questions

- Should the summary/free-form `answer` be sent before card blocks, after card blocks, or omitted when structured blocks are available?
- Should this feature be restricted to selected groups or superusers initially?
- What is the production timeout target after observing real DeepSeek latency?
