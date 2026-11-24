# Public group conversation continuity

The enabled learning group now has a separate short-lived dialogue window.
Random chat and explicit mentions (including replies to bot messages) receive
the same public group conversation. Private sessions and professional Agents
do not receive it.

## Storage and scope

`group_conversation` is an additive table in `data/group_chat.db`. It stores
sanitized member text, successfully sent casual bot messages, message IDs and
same-group parent IDs. Entries have a 30-minute logical lifetime; each group
keeps at most 200 rows and each model request selects at most 30. Individual
text entries are bounded to 500 characters. Expiry is enforced on reads/writes
and through the existing periodic cleanup.

The current quote chain (up to five messages) is pinned when selecting the
window, so a busy group cannot immediately evict the referenced bot statement.
Raw message IDs and hashed member identities stay in SQLite; model payloads use
local `m1` IDs, `reply_to` relationships, anonymized member labels, and an
explicit `assistant`/`user` role. A bot's earlier statement is marked as the
bot's own statement, not attributed to another member.

Learning still reads only the existing filtered `group_samples`. Bot outputs,
mentions and quote replies are not added to expression/style learning. The
existing learning/collection whitelist, model budgets and random-chat limits
are unchanged. Context capture excludes specialist commands, sensitive text
and unsupported media; a bot meme may be represented only as a nonvisual
placeholder. Closing collection or clearing the group's data deletes this
short-lived conversation too.

## Entry points

- A priority-0, nonblocking group observer captures safe context before other
  matchers stop propagation. It never sends messages or calls a model.
- Random chat deduplicates attempts separately from learning samples. It checks
  both the old collection epoch and the new context checkpoint before sending,
  dropping stale replies when another message arrives while generating.
- Casual replies record successfully sent text using the returned OneBot message
  ID. Random and explicit-mention sends use the same context representation.
- Explicit mentions send `group_conversation` as bounded reference data to
  `/api/mention-chat`. Private/other-group requests with this data are rejected.
  The professional branch does not pass or read it.
- Existing recent human samples initialize an empty context window. Recently
  archived random bot replies can be recovered on a verified quote by exact
  match. No broad QQ-history fetching or private-history migration is performed.

Context read/write errors are best-effort and do not turn an already delivered
casual reply into a generic request failure.

## Validation and rollback

Server backup:
`/home/ubuntu/qqbot/group-conversation-backup-20261026-185049` contains original
source and a SQLite backup of the pre-change group database. The new table can
remain unused if source changes are rolled back; existing learning tables were
not rewritten.

449 bot tests and 561 backend tests passed. Tests include quote chains, another
member's follow-up, long/busy windows, role/scope validation, collection switches,
learning isolation, stale-result suppression and failed context writes. Shared
bot context and model accounting are isolated to temporary test databases.

In a synthetic live-model check, a member mentioned noodles while the bot said
it wanted curry. Both random chat and explicit quote-followup correctly recalled
the bot's curry statement (10.82s and 1.17s). Tests did not send QQ messages or
load real group dialogue into the test prompts.
