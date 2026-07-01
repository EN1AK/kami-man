## 1. RAG API Client

- [x] 1.1 Add a `services` module that reads RAG endpoint settings from environment variables with defaults for URL, timeout, top-k, rerank candidates, and structured block max length.
- [x] 1.2 Implement an async HTTP client function that posts group questions to the configured `ygo-rag` API with `semantic: true`, `rerank: false`, `llm_rerank: true`, and `llm: true`.
- [x] 1.3 Validate successful RAG responses into answer text, warning text, and structured card blocks.
- [x] 1.4 Map timeout, HTTP status, network, and malformed-response failures to concise user-facing error messages.

## 2. Group Mention Plugin

- [x] 2.1 Add a NoneBot plugin that only handles `GroupMessageEvent`.
- [x] 2.2 Detect `at` segments targeting the bot self id and ignore messages without a bot mention.
- [x] 2.3 Extract the question by removing bot mention segments and trimming remaining plain text.
- [x] 2.4 Reply with a prompt for question text when a group message mentions the bot without a non-empty question.
- [x] 2.5 Ensure private messages do not trigger RAG QA and do not receive RAG QA replies.

## 3. Response Formatting

- [x] 3.1 Build merged-forward nodes from `structured.blocks[*].text`, one card block per node.
- [x] 3.2 Include warnings from the RAG API in a leading or trailing message node when warnings are present.
- [x] 3.3 Mark card nodes whose structured block has `truncated: true`.
- [x] 3.4 Fall back to safe chunking of `answer` text when structured card blocks are missing.
- [x] 3.5 Fall back to normal group messages if merged-forward sending fails.

## 4. Verification

- [x] 4.1 Add focused unit tests for question extraction from group messages containing bot mentions.
- [x] 4.2 Add focused unit tests for RAG response validation and error mapping.
- [x] 4.3 Add focused unit tests for structured block formatting, truncation markers, and answer fallback chunking.
- [x] 4.4 Run the available Python test command or document why tests cannot run in the local environment.
- [x] 4.5 Run `openspec validate add-ygo-rag-bot-qa --strict` and fix any proposal/spec/task issues.

## 5. Deployment Notes

- [x] 5.1 Document the expected `ygo-rag` service endpoint and required `DEEPSEEK_API_KEY` in README or deployment notes.
- [x] 5.2 Document the bot-side environment variables for RAG URL, timeout, top-k, rerank candidates, and structured block max length.
