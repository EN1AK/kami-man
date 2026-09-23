## Context

The previous design shipped a minimal one-shot pipeline: QQ alias → bot HTTP client → `rift-rag` single-request QA (`POST /api/query` with hybrid retrieval → one DeepSeek call → `[rule_id]` citations). That baseline works for pure rule questions ("什么是迅捷 keyword") but is structurally weak for card questions, because nothing maps a Chinese card name to a card or to its rules.

Verified data facts (riftsim repo):

- `workspace/final/rules.db`: `rules` (2984 rows; R-CARD canonical rules carry effect text, card names only appear in `topic` like `card:OGN-242 (Baited Hook / 海兽钓钩)`), `rule_cards` (7046 rule_id↔card_id links with `origin`), `rule_keywords` (885 keyword links), `rules_fts` (FTS5, unusable for Chinese with the default tokenizer).
- `cards_bilingual.db`: `cards` (1267 rows) with `card_key`, `name_cn`, `sub_title_cn`, `name_en`, `text_cn`, `text_en`. Full CN display names compose subtitle + name (e.g. `斥候标兵` + `艾娃` → "斥候标兵 艾娃"); same names recur across sets/variants, so a name can map to multiple `card_key`s.
- Existing service (baseline, stays as fallback): `scripts/rag/rag_query.py` one-shot hybrid retrieval (dense BGE-M3 top-30 + keyword/rule-id LIKE top-30 → RRF k=60 → top-k) + `generate()` with bracket-citation extraction; `scripts/rag/rag_server.py` serving `{answer, warnings, sources}`.

Reference (read-only, external): ygo-rag `rag_agent/adjudication_agent.py` (agentic card resolution loop: deterministic mention extraction → local-only candidate ids → bounded retry → visible coverage) and `rag_agent/assistant_agent.py` (bounded planner→tool loop with strict JSON actions, duplicate-signature suppression, deterministic end). We adopt the architecture, not the dependencies.

Truth rule, unchanged: the bot is not the rules manual; `rift-rag` is the QA source of truth, the bot only routes input and formats returned results.

## Goals / Non-Goals

**Goals:**

- Card-name recognition that is deterministic-first, local-only for ids, and explicit about unresolved/ambiguous mentions.
- A bounded, citation-validated agent loop: the LLM chooses retrieval tools but can only answer through `submit_answer` with citations drawn from the evidence pool.
- Contract v2 that adds fields without breaking the existing `{answer, warnings, sources}` consumers.
- Deterministic fallback: any planner failure degrades to today's one-shot pipeline, never to a user-visible crash.

**Non-Goals:**

- LangGraph/LangChain or any agent framework dependency.
- Multi-turn conversation memory, clarification round-trips back to the user, or reranking.
- Card-image lookup, battle mechanics, or changes to Yu-Gi-Oh! flows.

## Decisions

### D1. Bot → rift-rag HTTP boundary stays; contract goes v2 additively

Request `POST /api/query`:

- `query` (string, required), `top_k` (int 1-20, default 6) — unchanged.
- `mode` (`"agent"` default | `"oneshot"`), `trace` (bool, default false) — new, optional. Invalid `mode`/`top_k` → same 400 body `{"error": "<短句说明>"}`.

Response 200 (all fields after `sources` are new):

```json
{
  "answer": "... [R-CR-716.1.1] ...",
  "warnings": ["检索结果为空"],
  "sources": [{"rule_id": "R-CR-716.1.1", "topic": "..."}],
  "mode": "agent",
  "exhausted": false,
  "resolved_cards": [
    {"card_id": "OGN-242", "mention": "海兽钓钩", "name_cn": "海兽钓钩",
     "name_en": "Baited Hook", "confidence": "exact", "source": "deterministic"}
  ],
  "coverage": {
    "unresolved_mentions": ["某卡名"],
    "ambiguous_mentions": [{"mention": "蔚", "candidates": [{"card_id": "OGN-066a", "name_cn": "蔚·铲除者"}]}]
  },
  "trace": [{"step": 1, "tool": "search_rules", "arguments": {"query": "..."}, "ok": true, "summary": "12 rules"}]
}
```

- `resolved_cards`/`coverage`/`exhausted` are emitted in agent mode; `oneshot` mode omits them (or sends empty values). `trace` only when requested.
- Errors: 400 invalid body (`{"error": ...}`), 500 `{"error": "服务内部错误"}` (+1 internal warning entry), 404/405, plain bodies, `Connection: close`, keep-alive — all unchanged.
- Rationale: additive fields keep the already-deployed bot parsing code working; `oneshot` is both escape hatch and rollback path. Alternative considered: silently upgrading the old response — rejected because card QA then has no coverage diagnostics and exhausted loops cannot be told apart from confident answers.

### D2. Card resolution is deterministic-first, local-only for ids

New `scripts/rag/card_resolver.py`, adapted from ygo-rag's card-resolution loop:

- **Alias index** (built at startup from `cards_bilingual.db.cards` + R-CARD `topic` strings; ~1267 cards, trivial in-memory): aliases per `card_key` = `card_key`, `name_cn`, `name_en` (when not null), composite full names `{sub_title_cn} {name_cn}` and `{name_cn} {sub_title_cn}`, and punctuation/whitespace/case-normalized forms of all of the above (normalize `·`/`・`/spaces, strip `《》「」"“”`, case-fold latin).
- **Mention extraction (deterministic, default):** card-id regex (`[A-Z]{2,4}-\d{3}[a-z]?`) + longest-match scan of the alias dictionary over the query + quoted spans (`《》「」"`) checked against the dictionary first.
- **Candidate selection:** exact id/name hit → `confidence=exact`, resolved. Normalized-form hit → `normalized`, resolved. Otherwise fuzzy character-overlap candidates (top `RAG_CARD_RESOLUTION_TOP_K`, default 5): unique match → `fuzzy`, resolved; multiple card_keys → ambiguous (kept visible, never guessed). Same-name variants (different sets) are ambiguous unless one alias form is strictly stronger (full-name match beats bare-name match).
- **Bounded retry (default 1, `RAG_CARD_RESOLUTION_RETRY`):** unresolved mentions get one retry with a wider context window around the mention; ambiguous mentions stay ambiguous.
- **LLM assists are constrained and off by default:** `RAG_LLM_CARD_EXTRACTION=1` lets the model propose extra *name strings* when deterministic extraction found nothing (strings still must resolve through the local index); `RAG_LLM_CARD_SELECTION=1` lets the model pick *among local candidate card_keys only* — unknown ids are rejected. Both follow ygo-rag's rule: the local database is the sole source of ids.
- Output: `{resolved: [...], ambiguous: [...], unresolved: [...]}` — always surfaced in contract v2 `coverage`/`resolved_cards`.

### D3. Retrieval is refactored into tools over an evidence pool

`rag_query.py` keeps its dense/keyword/RRF retrieval core but is exposed as planner-callable tools; a module-level `EvidencePool` accumulates every rule row any tool returns (keyed by `rule_id`):

| Tool | Behavior |
| --- | --- |
| `resolve_cards(mentions: [str])` | Runs D2 (incl. optional LLM extraction round). The service also pre-runs deterministic resolution on the raw query before the loop and injects the result into the planner prompt. |
| `get_card_rules(card_key, top_k?)` | Direct `rules ⋈ rule_cards WHERE card_id = ?` join (R-CARD canonical + CR rules mentioning the card); observation includes card display name and canonical text snippet. |
| `search_rules(query, top_k?)` | Current hybrid retrieve; if cards are resolved, the query is expanded with up to 2 resolved cards' canonical text (ygo-rag's referenced-card expansion pattern). |
| `lookup_rule(rule_id_or_number)` | Exact `R-CR-716.1` / `R-CARD-OGN-242` hit, or `716.1` → `rule_id LIKE '%716.1%'`. |
| `submit_answer(answer, citations)` | Terminal. Validated (D4); on failure returns an error observation instead of ending. |

All tool calls add rows to the pool and entries to the trace (`tool`, `arguments`, `ok`, row counts).

### D4. Bounded planner loop with citation-validated submit

New `scripts/rag/agent_loop.py`, hand-rolled (no framework):

Loop: `planner → validate action → execute tool → append observation → planner → … → submit_answer → end`.

- **Planner protocol:** each DeepSeek call must return one JSON `{tool, arguments, rationale}` (reasoning stays out of the final answer); the system prompt lists the tool schemas, the pre-resolved cards, and the rules: cite only pool rule_ids, finish via `submit_answer`, never guess (卡号/规则号 must come from observations).
- **Bounds:** `RAG_AGENT_MAX_STEPS` default 4, clamped 1-8. Duplicate `(tool, canonical arguments)` signatures are rejected as useless. Two consecutive unparseable/invalid planner outputs, or any LLM call failure → break to fallback.
- **Citation validation (adapted ygo-rag `submit_ruling`):** on `submit_answer`, code regex-scans `answer` for `[…]` markers; every marker must be a `rule_id` present in the evidence pool, and every element of `citations` must be in the pool. Invalid → error observation (`"citation R-CR-999 not in evidence pool"`), the planner may fix and resubmit while steps remain.
- **Deterministic fallback:** when steps exhaust before a valid submit, or the planner breaks, the service runs today's one-shot `generate(query, pool_rows)` over whatever the pool holds; empty pool → the existing fixed "暂时无法可靠回答…" answer + `检索结果为空` warning; response sets `exhausted: true`. Latency cost of the loop is 1 small prompt per step + final generation; with max 4 steps this stays well under the bot's 240 s timeout, and `mode=oneshot` restores old single-call latency.

### D5. Bot consumes v2 fields tolerantly; display stays compact

- `RiftRagSettings`: envs `RIFT_RAG_BASE_URL` (default `http://127.0.0.1:7862`), `RIFT_RAG_TIMEOUT_SECONDS` (default 240.0), new `RIFT_RAG_MODE` (default `agent`, passed through), `RIFT_RAG_TRACE` (default off, debug-only).
- `query_rift_rag()` sends `mode`/`trace`; `RiftRagResponse` gains optional `resolved_cards: list[dict]`, `unresolved_mentions: list[str]`, `ambiguous_mentions: list[dict]`, `exhausted: bool` — all parsed with missing-key tolerance (old service responses still parse).
- `build_rift_rag_nodes()`: question node appends `识别卡牌：海兽钓钩（OGN-242）` when `resolved_cards` non-empty; `识别失败：某卡名` / `卡名歧义：蔚（OGN-066a 等）` when coverage non-empty, and `已达检索步数上限，答案基于部分证据` when `exhausted`. Answer node appended as the final node when non-empty. Sources node unchanged. Empty/whitespace question kept, answer-text question dropped. No card rendering, no name/URL guessing.
- Triggering, group-only scope, private-chat silence, merged-forward with plain fallback, and error mapping (`连接失败…` / `请求超时…` / `RAG 服务返回异常 …` / `RAG 服务内部错误 …` / `RAG 服务返回了空结果 …`) are unchanged. `exhausted` is **not** an error.

### D6. Runtime/deployment (riftsim server)

- Data directory gains `cards_bilingual.db` (`RAG_CARDS_DB_PATH` env, default alongside `RAG_RULES_DB_PATH`); the resolver degrades to id/dictionary-only matching if the cards DB is missing (warns, does not crash).
- New optional envs all have code defaults: `RAG_AGENT_MAX_STEPS` (4), `RAG_LLM_CARD_EXTRACTION` (0), `RAG_LLM_CARD_SELECTION` (0), `RAG_CARD_RESOLUTION_TOP_K` (5), `RAG_CARD_RESOLUTION_RETRY` (1). Secret-bearing envs (`OPENAI_API_KEY`, `RAG_LLM_MODEL`, proxy) unchanged.
- Memory/CPU unchanged: no new model; BGE-M3 worker pattern unchanged.

## Risks / Trade-offs

- **Risk:** planner JSON drift wastes steps on invalid actions → Mitigation: strict schema prompt, 2-strike break to fallback, duplicate-signature rejection.
- **Risk:** 2-4 DeepSeek calls per question raise latency/cost in group chats → Mitigation: small planner prompts, max_steps=4 default, `mode=oneshot` escape hatch, adjustable via env.
- **Risk:** hallucinated citations → Mitigation: D4 validation against the pool; unvalidated submit never reaches the user (fallback carries the extraction-based rewriting too).
- **Risk:** fuzzy card matching misfires on short names → Mitigation: full-name beats bare-name, ambiguity stays visible, LLM selection off by default.
- **Trade-off:** in-pool answer generation depends on `get_card_rules` join quality (`rule_cards.origin` covers evidence/rule_id sources only) → Accepted: `search_rules` expansion covers gaps; coverage fields expose misses.

## Migration Plan

1. riftsim: build alias index + `card_resolver.py` resolver with unit tests.
2. riftsim: refactor `rag_query.py` into tools + evidence pool; keep existing one-shot pipeline intact as fallback/`oneshot`.
3. riftsim: `agent_loop.py` + citation validation + fallback; fixture-LLM unit tests.
4. riftsim: `rag_server.py` contract v2 wiring; curl smoke for both modes.
5. bot: client + message-building updates with tests.
6. Verification: `pytest` both repos, `py_compile`, `openspec validate --strict`.
7. Deployment: upload `cards_bilingual.db` with existing data files, update env/systemd, start service, validate in a real group (card-interaction question, pure-rules question, garbage input), update `docs/production.md`.
8. Rollback: set `RIFT_RAG_MODE=oneshot` (bot) or redeploy previous rift-rag code; previous bot files redeploy cleanly since v2 fields are additive.

## Open Questions

- After production intake, if deterministic resolution miss-rate is high (e.g. heavy abbreviation/slang usage), flip `RAG_LLM_CARD_EXTRACTION=1` and measure; initial default stays off to keep hot path latency/cost low.
- Tune `RAG_AGENT_MAX_STEPS` (3 vs 4) against answer quality once trace data accumulates.
