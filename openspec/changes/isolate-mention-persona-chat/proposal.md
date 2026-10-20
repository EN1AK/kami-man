## Why

The user wants the original persona and memes on casual @ mentions while keeping professional services free of persona influence. The existing unified mention client currently forwards all text into one Agent session.

## What Changes

- Route explicit professional command prefixes directly; send all other text to persona without classification or automatic escalation.
- Add an isolated persona conversation endpoint using the unchanged original persona, optional allowed-group learned style and local memes.
- Start professional mentions in a fresh session namespace; store casual turns separately and prevent quoted persona output from entering professional requests.
- Preserve shared per-user quota, image translation, raw specialist result delivery and proactive learning. Clear conversation clears both histories and legacy history.

## Capabilities

### New Capabilities
- mention-persona-isolation: neutral routing, persona-only casual history, clean professional contexts and shared quota.

### Modified Capabilities

None.

## Impact

Server kami-man mention dispatcher and client/state helpers; compatible ygo-rag local endpoints. Existing Agent planner/tools, original persona asset, API credentials and specialist prompts remain unchanged. No new framework or model dependency.
