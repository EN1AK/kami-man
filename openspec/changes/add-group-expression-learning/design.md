## Context

See proposal.md. Server code already provides collection, SQLite storage, a 3% random gate, five-minute cooldown, 20 attempts/day and daily style summaries. Existing modifications are preserved. The user has approved implementation after cost exploration.

## Goals / Non-Goals

Goals: context-sensitive expression references, bounded runtime/API expense and inspectable learning progress. Non-goals: weight training, embeddings, another bot framework or a full jargon mining subsystem.

## Decisions

- Add a store subclass with expressions, evidence and persistent leased learning jobs. First learn after 100 eligible messages from three speakers; later after 50 new messages, at most two successes and three attempts per Beijing day. Retry no sooner than one hour. Every call receives at most eight anonymous source snippets; source ids must match supplied human evidence.
- Keep at most 300 expressions and expire after 30 days. Deduplicate source evidence, rank by local Chinese bigram/word overlap and recency, inject at most five relevant pairs. Unmatched contexts receive no forced expressions. Existing historical examples plus expression evidence share an eight-item historical reference budget.
- Use one non-thinking JSON call for abstention, expression selection and reply generation. Keep the existing random gate, cooldown and daily cap. Track recent successful bot replies for repetition suppression, never add them to learning sources. Discard replies after stop/clear or context changes while the model runs.
- Backend accounting reserves a conservative UTF-8-byte input upper estimate plus bounded output before calling, then settles using returned token usage at peak uncached Flash rates. Missing usage or failure retains the reservation. SQLite atomic reservations include in-flight/crash requests across restarts. Default monthly limit is CNY10, daily CNY1; both use Beijing dates and cover all three group routes. Status exposes only aggregate counts and estimated costs. Prices are configurable and estimates are not provider invoices.
- Staging copies are only editing aids; back up current server files, upload changes, run meaningful tests with synthetic fixtures, deploy backend before bot and check health/WebSocket without sending synthetic QQ messages.

## Risks / Trade-offs

- Sparse short samples lack context → conservative extraction, verified source ids, no inferred group events or identities.
- Keyword retrieval misses paraphrases → accept a smaller first version without added embedding memory.
- Budget estimates can differ from invoices → peak uncached pricing, retain uncertain reservations, show estimates explicitly and make rates configurable.
- Stale in-flight work → persistent generation tokens and source watermarks invalidated on administrative actions.

## Migration Plan

Additive SQLite schemas, existing summaries and samples preserved. Deploy compatible backend additions before bot. Roll back source files from the per-deployment backup and restart; leave additive runtime tables intact.
