## 1. Agent API Contract

- [x] 1.1 Confirm the deployed `ygo-rag` translation endpoint path, request body, response fields, and warning/error shape.
- [x] 1.2 Record the confirmed bot-side environment variables and defaults for translation API URL, timeout, and chunk size.

## 2. Translation API Client

- [x] 2.1 Add or extend a `services` module that reads translation settings from environment variables.
- [x] 2.2 Implement an async HTTP client function that posts translation requests to the configured `ygo-rag` agent endpoint.
- [x] 2.3 Validate successful translation responses into translated text and optional warnings.
- [x] 2.4 Map timeout, HTTP status, network, and malformed-response failures to concise user-facing messages.

## 3. Command Parsing And Routing

- [x] 3.1 Add helper logic that extracts translation requests from group messages that mention the bot and start with a supported translation command.
- [x] 3.2 Ensure translation parsing supports text mentions already accepted by the bot mention fallback where applicable.
- [x] 3.3 Ensure private messages do not trigger translation and do not receive translation replies.
- [x] 3.4 Ensure translation commands do not fall through to the existing RAG QA workflow.

## 4. Bot Response Delivery

- [x] 4.1 Split long translation results into safe message-sized records while preserving order.
- [x] 4.2 Include translation service warnings in the bot response when warnings are present.
- [x] 4.3 Send prepared translation records to the group, reusing the existing merged-forward/fallback pattern where practical.
- [x] 4.4 Reply with a concise prompt when the command is present but no translation input is provided.

## 5. Tests

- [x] 5.1 Add unit tests for translation command extraction, including bot mention, text mention fallback, empty input, and non-command mentions.
- [x] 5.2 Add unit tests for private-chat suppression and RAG QA fallthrough prevention.
- [x] 5.3 Add unit tests for translation API payload construction, response validation, and error mapping.
- [x] 5.4 Add unit tests for warning inclusion and long-result splitting.
- [x] 5.5 Run the focused RAG/translation test set.

## 6. Documentation And Validation

- [x] 6.1 Update `assets/help.md` with the translation command once the command syntax is final.
- [x] 6.2 Update deployment documentation with the translation service endpoint and bot-side environment variables.
- [x] 6.3 Run `openspec validate add-ygo-rag-translation --strict` and fix any proposal/spec/task issues.
