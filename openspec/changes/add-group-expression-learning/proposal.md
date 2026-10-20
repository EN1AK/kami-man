## Why

Group replies currently use a broad summary and unrelated historical snippets. Contextual expression retrieval can improve relevance within the existing single-group resource and privacy limits.

## What Changes

- Persist evidence-backed situation/expression pairs from bounded anonymous samples.
- Retrieve relevant expressions locally and combine reply selection and generation in one model call.
- Bound background learning, exclude bot output from learning, and invalidate work on collection stop/clear.
- Record model usage and enforce a conservative shared monthly CNY budget for group chat, learning and summaries.

## Capabilities

### New Capabilities
- group-expression-learning: bounded contextual expression learning, retrieval and inspection.
- group-model-budget: persistent usage accounting and budget admission for group features.

### Modified Capabilities

None.

## Impact

Authoritative implementation and deployment: server kami-man and ygo-rag. Extend existing local HTTP contracts without changing card translation or user quotas; no additional models or infrastructure.
