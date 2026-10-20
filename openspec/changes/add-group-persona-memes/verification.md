## Server acceptance (2026-10-20)

- Source and online group SQLite backup: /home/ubuntu/qqbot/persona-memes-backup-m47w8zzh. No reset, pull, API credential change or package installation.
- Persona from pinned upstream revision: 1388 characters, all original paragraph text retained, including placeholders. Checked source DOCX extraction equality and recorded SHA256. Source document and provenance remain beside persona.txt.
- Meme pack: 140 verified upstream files, 109.05MiB. Current local media inventory: 27 categories, 131 images eligible under 4MiB limit; larger source files retained but not sent.
- Bot complete synthetic suite: 296 passed. Backend complete synthetic suite: 461 passed, five existing adjudication deprecation warnings. Total 757 passed. OpenSpec strict validation and Git diff checks passed.
- Actual local API smoke used synthetic anonymous messages and the original persona. Valid 10-character reply returned in 4.99 seconds with optional category null. A real local image was Base64 encoded and its 2223 bytes/hash verified using an isolated temporary history DB. No QQ send API was invoked for testing.
- Backend deployed before bot. Final services active, health true, one established OneBot connection, no tracebacks in the three-minute acceptance window.
- Group collection/chat switches remain enabled. Human sample count 688, learned expressions 19, latest learning watermark 688; two successful batches on 2026-10-20. No data clear/backfill or image learning introduced.
- Production meme history at acceptance: zero image attempts. Status command exposes 131 eligible images, 27 categories, five-attempt daily limit.
- Available server memory 1629MiB; bot cgroup 162824192 bytes, backend 280379392 bytes. This is a startup observation, not a load benchmark.
- Scope remains proactive group chat only. Ordinary @ agent and specialist/translation code paths are unchanged. Real QQ image delivery will first occur through normal authorized group activity; no synthetic group notification or test message was sent.
