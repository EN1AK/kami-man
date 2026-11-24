# Persona web tools and quoted proactive replies

Explicit group mentions and bot-admin private conversations reuse the existing
`rag_agent.general_tools` implementations for `web_search`, `read_webpage`,
`current_time`, and `calculate`. The professional Agent, its fixed-prefix router,
prompts and history remain independent. The original group and private persona
files are unchanged. Proactive random replies do not perform web queries.

## Deciding whether to search

The same model turn that normally generates the persona reply chooses either
an answer or a JSON tool action. There is no extra classifier call for ordinary
chat and no keyword-based switch into the professional Agent.

The runtime policy instructs the model to search for explicit search/latest/
verification requests, facts that change with time (weather, prices, scores,
recent events, current officeholders and product versions), or uncertainty that
requires factual verification. It uses the current request, isolated casual
history and a supplied Beijing timestamp to resolve references such as
"today". Link-reading requests use the page reader; time and arithmetic have
their own tools. Requests not to browse must be respected; jokes, fiction and
stable historical facts should not trigger searches mechanically.

This is a model decision guided by policy, not a guarantee that every ambiguous
question is classified perfectly. The API reports `tools_used` for inspection.

## Limits and sources

- Up to three total tool calls and two external web calls per turn.
- A 75-second backend deadline; bot client timeout is 90 seconds.
- Existing group-model budget accounting covers every model round. Web API
  supplier charges, if any, are not added to those token-only counters.
- Existing public-URL restrictions, HTTP response bounds, short cache and
  request rate limiting are reused. Search arguments contain only the required
  public query, not the full persona/group history. Tool observations are
  explicitly untrusted data and page windows are bounded.
- Source URLs come from successful tool results, not invented model links.
  Up to three URLs are appended in a deterministic source footer. The bot
  exempts only that exact footer from its existing privacy/link filter.
- The complete reply including sources remains within 2,000 characters and
  uses the existing segmented sending mechanism and meme handling.
- Failed tools are shown as failed observations; the model must acknowledge
  missing evidence. Deadline, model or budget failures after tool use return
  an honest bounded fallback, retaining verified sources when available.

## Random reply target

The observer sends the triggering message text as bounded `reply_target` data
to the random-chat model and instructs it to respond to that message in context.
OneBot `MessageSegment.reply(event.message_id)` is prepended to the outgoing
text/image message. Text-only and image-only replies both quote the source.
The trigger probability, cooldown, daily limits, collection policy, message
epoch checks and stale-result suppression are unchanged.

## Deployment

Backend changes: `rag_agent/persona_tools.py`, `rag_agent/mention_chat.py`,
`rag_agent/group_chat.py`, and `tests/test_persona_tools.py` in `ygo-rag`.
Bot changes: the mention and group-chat clients and existing related tests.
Original files were backed up in
`/home/ubuntu/qqbot/persona-web-backup-20261022-123053`.

Validation: 530 backend tests and 373 bot tests passed. Tests cover direct
single-call chat, search/read observations, source provenance, tool quotas,
failures, deadlines, private persona isolation, and quoted text/image replies.
Live tool connectivity was confirmed with a public API-documentation query;
test calls never send QQ messages.
