# Collapsed source records and stronger persona research

This supersedes the inline-source-footer and two-web-call behavior described
in `persona-web-and-reply-quotes-2026-10-22.md`.

## Delivery

The persona endpoint returns the answer in `reply`, verified URLs in `sources`,
and `sources_separate: true`. The answer remains limited to 2,000 characters;
sources no longer consume that allowance. Isolated casual history retains the
sources for follow-up questions, but visible reply segments do not contain the
source footer.

`GroupReply.sources` carries validated metadata to `unified_agent`. After the
ordinary answer and optional meme, the bot sends one merged-forward card:
`send_group_forward_msg` for groups, `send_private_forward_msg` for private
conversations. The card contains a header and up to six source nodes. URLs are
generated from successful tools; unverified model links remain disallowed.
The bot also accepts the previous backend footer format and separates it before
sending, permitting a compatible rollout.

Source-card failure is logged without dumping links into ordinary messages or
repeating an already delivered answer. The existing professional reply and
random-chat sending paths remain independent.

## Query policy

- At most six web calls and eight total general-tool calls per turn, used only
  as needed. Simple chat still requires one model round and no web calls.
- Request budget: 150 seconds server-side, 165 seconds in the bot client.
  Complex research can take longer than an ordinary reply.
- Refine vague or irrelevant searches with the subject, date, region or site.
  Prefer current official/primary sources and cross-check disputed claims.
- At least one successful page read is required before treating search evidence
  as verified. If the model attempts to finish after only search snippets, the
  loop explicitly requests a page read. If a page cannot be read, the reply
  acknowledges that the snippets have not been adequately verified.
- Once direct, current evidence is sufficient, stop rather than filling the
  quota. Tool/time/budget failures retain an honest bounded fallback.
- Avoid duplicate answer/content fields in tool observations. Correct page
  continuation offsets when windows are shortened; compact old observations
  while retaining the latest two full windows to bound growing context.

Every model round continues to use existing budget accounting. No professional
prompts, personas, group-learning settings or random-reply probabilities change.

## Deployment

Pre-change backup:
`/home/ubuntu/qqbot/persona-sources-backup-20261022-124749`.

Live isolated-model check: a current model/context-size question used
`web_search` and `read_webpage`, returned two official documentation URLs as
separate metadata, and produced an answer without URL text in 11.89 seconds.
No QQ test messages were sent. Source-card payloads and failure behavior are
tested with a mock OneBot adapter.
