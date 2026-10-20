## Context

See proposal.md. Random chat already uses original persona and a locally validated meme library. Mentions have a persistent per-user 30/day quota and a unified Agent session; quoted bot text is currently passed regardless of which branch produced it. Professional history can contain old ordinary chat.

## Goals / Non-Goals

Goals: neutral request selection, independent histories and provenance-aware quotes, direct professional delivery and original persona preservation. Non-goals: changing professional planner prompts/tools, learning from @ conversations, collecting group images or changing private-chat entry rules.

## Decisions

- Neutral routing endpoint accepts only current text and previous/quoted route metadata, never persona text, learned expressions or chat history. Explicit translation/rules/card/professional patterns bypass model classification; clear greetings may use a local casual shortcut. Other input uses a fresh non-thinking JSON classifier. Ambiguous, malformed or failed results resolve professional. Routing and persona calls share existing group-model budget; budget rejection cannot block professional service.
- Fresh professional session id is base + :professional; the previous mixed base session is not reused. A separate backend SessionStore database uses base + :persona, 30-minute TTL and eight turns. Neither branch reads the other's history. Persona context uses only same-user casual turns and optional learned style/expressions for the existing allowlisted group.
- New /api/mention-chat receives explicit @ text and a bounded catalog. It loads the unchanged original persona without importing professional history. Explicit specialist text escalates before persona loading; generated professional escalation is not saved as casual history. Professional escalation forwards only the original request and a verified professional quote, never persona intermediate output.
- Bot keeps a small persistent ledger of output-text SHA256 and route per scoped bot/group/user session, not copies of quote text. Only a known professional output quote is eligible for professional forwarding; unknown/legacy or casual quotes are omitted. The classifier receives only the route tag, not quote contents. Last route metadata aids short follow-ups without sharing history.
- Serialize requests per scoped mention session at the bot. Existing backend session locks protect generation/clear. Clear deletes casual, fresh professional and legacy histories without LLM calls, then removes local route/quote metadata. Concurrent clear cannot be followed by an older in-flight persona reply.
- Explicit @ requests remain one personal quota unit including classification; failures refund. They do not consume the random-chat 20-attempt cap. Local meme limits are shared per group with random chat (25 percent selection, five attempts/day, 30-minute cooldown, seven-day dedup). Meme library can explicitly allow other positive group ids for direct @ only; no group style/examples are read for those groups.
- Keep context/learned reference and catalog limits, no arbitrary model file paths. Ordinary @ answers can be short persona text/image; professional text/cards/evidence are sent directly as before with no persona rewrite.

## Risks / Trade-offs

- Semantic routing is imperfect -> explicit guard patterns, neutral classifier, conservative fallback and persona escalation.
- Old quoted answers have no provenance -> omit them instead of risking persona contamination; fresh professional history supports ordinary follow-ups.
- Two model calls for some casual mentions -> clear shortcuts and existing budget/quota controls; no classifier receives persona context.

## Migration Plan

Back up server sources and related SQLite databases. Add separate casual/state stores and compatible endpoints, deploy backend first then bot. Preserve old professional sessions without reading them in new requests; clear can remove them. Run isolation/quota/quote tests and full regressions, then synthetic local smoke without QQ sends. Roll back sources while retaining additive runtime stores.

## User-directed routing revision (2026-10-20)

This revision supersedes the semantic classifier, uncertainty fallback and persona escalation decisions above. Only explicit professional command prefixes select professional; other text always selects persona. Bare card numbers, URLs, subject matter, previous/quoted route tags and model confidence do not select professional. Images and control commands retain existing behavior. Persona generation has no escalation authority; transport/validation failures report an error and refund quota instead of switching branches. Professional follow-ups must repeat a professional command. The original persona asset, independent histories, quote provenance and output isolation remain unchanged. Routing has no model cost.
