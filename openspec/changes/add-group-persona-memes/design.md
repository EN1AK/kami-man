## Context

See proposal.md. Current random group chat returns a string, receives up to 15 recent human messages and eight combined historical references, and learns independently via background jobs. OneBot runs in a container, so host filesystem image paths cannot be assumed accessible.

## Goals / Non-Goals

Goals: direct original persona and classified meme assets with no additional inference calls. Non-goals: installing AstrBot, rewriting upstream persona text, image learning, embeddings, or changing specialist and ordinary @ agent replies.

## Decisions

- Pin prompt repository revision 869d6793b93a756a410f00da44852f8b774e48f1 and meme revision 7b9d61b09ce068cac621ff2c520ecab11d35d967. Save original DOCX, extracted paragraph text and provenance/checksums. Do not replace placeholders or edit upstream wording. Keep runtime JSON/privacy/tool limits in separate integration instructions.
- Backend reads GROUP_CHAT_PERSONA_FILE (default personas/deepseek-group/persona.txt). The original text is included intact; learned summaries and expressions remain user data. A missing default file preserves legacy behavior; an explicitly configured invalid file reports an error.
- Add bounded meme_categories [{category,description}] to /api/group-chat. Only advertised categories can be returned as meme_category, otherwise null. Existing callers without categories retain the original {reply} response. Empty text with an allowed category can represent image-only output. Filtered unsafe text cannot cause an image to be sent.
- Store runtime pack under data/group_memes/deepseek-girl-pack. Only local supported raster files under validated category directories, no symlinks or model-controlled paths. Normalize format characters in category names; keep downloaded assets unchanged. Limit a delivered image to 4MiB, transmit as Base64 to OneBot. Missing/corrupt assets fall back to text.
- Bot compatibility uses a string-like reply carrying optional category metadata. A library is injected into the production service; existing text-only tests/services work without it. The same model call handles abstention, text and category choice.
- Draw at 25% probability for requested images, at most five image attempts per Beijing day and one per 30 minutes. Persist atomic reservations and image hashes in the existing group SQLite; avoid identical images for seven days. Keep uncertain delivery reservations counted; no extra outbound tests in QQ. Sending/admin/context checks apply equally to image-only and text+image replies.
- Export aggregate meme status through the existing learning-status command. All bot output remains excluded from human learning sources. No historical image fetching or group image collection is introduced.

## Risks / Trade-offs

- Original persona contains examples and capabilities beyond the random-chat route -> retain it verbatim while fixed transport/privacy/tool instructions remain authoritative.
- Random images within a category may mismatch a phrase -> optional low-frequency selection, no forced images; later captions can be a separate change.
- Asset download may be partial -> download to a private staging directory, validate Git object hashes, atomically publish only a complete pack.

## Migration Plan

Back up current server sources and existing SQLite via online backup. Install pinned assets, deploy compatible backend additions before bot. Run relevant and full synthetic regressions, then bounded local API smoke without sending QQ messages. Roll back source from backup; preserve additive history tables and learned data.
