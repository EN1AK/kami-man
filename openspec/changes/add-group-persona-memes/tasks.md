## 1. Persona and generation

- [x] 1.1 Install pinned original persona and pack with provenance and hash validation; verify extracted text equals source DOCX paragraphs and media inventory.
- [x] 1.2 Extend group API with original persona and optional category selection; verify old-client compatibility, prompt inclusion and unsafe selection tests.

## 2. Bot integration

- [x] 2.1 Implement bounded local library, atomic reservations, repeat protection and Base64 delivery; verify traversal, size, image validation, caps and restart tests.
- [x] 2.2 Wire text/image/image-only replies and aggregate status while preserving learning; verify generation count, stale/admin checks and existing learning regressions.

## 3. Deployment

- [x] 3.1 Document configuration and contracts, validate change and run bot/backend full regressions.
- [x] 3.2 Back up and deploy on server; verify health, QQ connection, original-text integrity, model smoke and learning state without sending synthetic QQ messages.
