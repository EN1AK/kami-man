## Why

`ygo-rag` now exposes an LLM translation feature, and Kami Man Bot should let group users access it without adding LLM or RAG runtime dependencies to the bot process. The desired chat UX is explicit: translation should only run when a group message both mentions the bot and uses a translation command.

## What Changes

- Add a group-only translation capability triggered by mentioning the bot and using a translation command.
- Call the deployed `ygo-rag` agent HTTP translation endpoint instead of importing agent code into the bot process.
- Send the LLM translation result back to the group, splitting long results into safe message records before delivery.
- Do not trigger or reply to this feature in private chats.
- Keep the existing RAG QA behavior separate from translation command handling.
- Add configurable translation API endpoint and timeout settings if they are not already covered by existing RAG settings.
- Handle translation timeout, HTTP errors, network errors, and malformed responses with user-visible failure messages.

## Capabilities

### New Capabilities

- `ygo-rag-translation`: Group-only LLM translation through the deployed `ygo-rag` agent, including command parsing, HTTP request handling, long-response splitting, and private-chat suppression.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - New or extended plugin under `plugins/` for group `@bot` translation command handling.
  - New or extended service module under `services/` for calling the `ygo-rag` translation API and validating responses.
  - Tests for command extraction, private-chat suppression, API payload/response parsing, error mapping, and long-response splitting.
  - Help documentation entry for the new translation command.
- Affected runtime systems:
  - Requires the deployed `ygo-rag` agent service to expose the LLM translation API on the bot server.
  - Requires LLM credentials to remain configured in the `ygo-rag` service environment, not in the bot repository.
- Affected dependencies:
  - Bot side should continue using existing HTTP client dependencies; no RAG model or LLM SDK dependencies should be added to the bot process.
- User-visible behavior:
  - Group users can request translation by mentioning the bot and using the translation command.
  - Private users cannot trigger this feature.
