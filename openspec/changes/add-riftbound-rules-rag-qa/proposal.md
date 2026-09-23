## Why

The current `rift-rag` design is a one-shot "retrieve-then-generate" pipeline: a single hybrid recall (BGE-M3 dense + keyword LIKE, RRF fusion) feeds one DeepSeek call. That structure has two gaps that make card-centric rules questions unreliable:

- **No card name recognition.** `extract_terms` only lifts rule numbers (`716.1`), card ids (`OGN-131`), latin tokens, and an 83-entry official keyword vocabulary — a Chinese card name like 海兽钓钩 never reaches the keyword channel, so card questions depend on dense-recall luck. The two strongest routing assets in the data stay unused: `rules.db.rule_cards` (7046 rule↔card links) and `cards_bilingual.db` (1267 cards with CN/EN/subtitle names).
- **No recovery loop and no citation validation.** Retrieval is single-shot top-k; empty recall bounces the question back to the user ("请补充章节号/卡号"); there is no query expansion, no retry, and the `[n] → rule_id` regex fallback rewrites whatever marker the model emitted without checking it against the retrieved pool.

The sister project `ygo-rag` (github.com/EN1AK/ygo-rag) already proves the fix on the same stack (BGE-M3 + DeepSeek): an explicit card-resolution loop (deterministic-first extraction, local-only candidate ids, bounded retry, visible unresolved/ambiguous coverage) and a bounded planner→tool agent loop whose final answer is accepted only through a citation-validated submit. This change adopts that architecture for Riftbound rules QA.

## What Changes

- **rift-rag service (riftsim repo) becomes an agent loop.** Deterministic card-name resolution runs first; the LLM planner then calls retrieval tools (`resolve_cards`, `get_card_rules` via `rule_cards`, `search_rules` hybrid with card-text expansion, `lookup_rule` by number/id) and must finish through `submit_answer`, which validates that every `[rule_id]` citation exists in the accumulated evidence pool. On planner failure or step exhaustion the service falls back to the existing one-shot generation over the gathered pool (`exhausted: true`).
- **Contract v2 (additive, backward compatible).** Request gains optional `mode` (`agent` default / `oneshot` escape hatch) and `trace`. Response gains `resolved_cards`, `coverage` (unresolved/ambiguous mentions), `exhausted`, `mode`, and optional `trace`; `answer`/`warnings`/`sources` and all error semantics are unchanged, so old clients keep working.
- **Bot side consumes v2 fields tolerantly.** The client parses the new optional fields, surfaces recognized cards and unresolved/ambiguous mentions as short lines in the merged-forward nodes, and treats `exhausted` as a warning rather than an error. New envs: `RIFT_RAG_MODE`, `RIFT_RAG_TRACE`.
- **Deployment data grows.** `rift-rag` now also needs `cards_bilingual.db` next to `rules.db` + vector index; service env gains card-resolution and agent-loop tunables (all with code defaults).
- **Unchanged:** bot → HTTP-only boundary, group-only text-alias triggering, merged-forward delivery with plain fallback, no private-chat replies, failure-message mapping.

## Capabilities

### New Capabilities

- `riftbound-rules-rag-qa`: Group-only natural-language Riftbound rules question answering through a deployed `rift-rag` HTTP service, including text-alias triggering, agent-loop cited answers with validated `[rule_id]` citations, recognized-card and mention-coverage surfacing, cited-answer merged-forward formatting, and failure-message mapping.

### Modified Capabilities

- None.

## Impact

- Affected code (riftsim repo, tracked here as prerequisite tasks):
  - New `scripts/rag/card_resolver.py` (card alias index + deterministic resolver + optional constrained LLM assist).
  - New `scripts/rag/agent_loop.py` (planner protocol, tool execution, evidence pool, submit validation, fallback).
  - Refactor `scripts/rag/rag_query.py` into retrieval tools; keep one-shot pipeline as fallback/`oneshot` mode.
  - `scripts/rag/rag_server.py` contract v2.
- Affected code (this repo):
  - Update `services/rift_rag_api.py` (v2 payload/response fields, `RIFT_RAG_MODE`/`RIFT_RAG_TRACE`).
  - Update `services/rift_rag_messages.py` (recognized-card and coverage lines).
  - Update tests under `tests/test_rift_rag_*.py`.
- Affected runtime systems:
  - `rift-rag.service` data directory gains `cards_bilingual.db` (≈1 MB) next to `rules.db`, `rules_vectors.npy`, `rules_index.json`.
  - Optional service envs: `RAG_AGENT_MAX_STEPS` (default 4), `RAG_LLM_CARD_EXTRACTION` / `RAG_LLM_CARD_SELECTION` (default off), `RAG_CARD_RESOLUTION_TOP_K` / retry limit.
- User-visible behavior:
  - Card questions ("海兽钓钩的放逐怎么处理") resolve the card by name and cite the card's own rules; answers may show recognized cards and unresolved mentions.
  - `mode=oneshot` keeps the previous behavior for A/B and troubleshooting.
- Out of scope:
  - The Yu-Gi-Oh! `@bot` RAG flows; the disabled `/rb` card-lookup plugin.
  - LangGraph/LangChain adoption; the loop is hand-rolled to keep riftsim dependency-free.
  - Bot-side caching, databases, or conversation memory.
