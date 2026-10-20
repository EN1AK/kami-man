# Verification

Deployed to ubuntu@150.109.237.67 on 2026-10-20 from the isolated, tested server copy.

- Complete regressions: bot 310 passed; backend 482 passed (792 total).
- Original professional Agent, session implementation, LLM implementation and persona file hashes match the pre-deployment backup.
- Live synthetic localhost checks: health succeeds; explicit specialist request routes professional; greeting routes casual; persona API returns a casual reply; professional Agent returns an answer.
- Synthetic casual and professional turns were stored separately, one each. Clear removed both and the legacy key; final synthetic turn counts are zero.
- Bot and backend services active; one established QQ connection; no service tracebacks during deployment verification. No synthetic messages were sent to QQ.
- New metadata database is ignored by Git. It stores scoped hashes and route tags rather than raw reply text.
- Server snapshot: 2 CPUs; 1642 MiB available memory. Classification and casual generation use remote APIs and existing shared budget controls; this snapshot is not a sustained load benchmark.
- Source and SQLite backup: /home/ubuntu/qqbot/mention-isolation-backup-cn200zsn. Existing unrelated working changes preserved; no commit or push performed.

Professional mentions start a fresh suffixed session instead of reading legacy mixed history. Ambiguous or failed classification falls back to professional handling. Persona prompts remain unchanged; learned style remains restricted to the existing allowed group.
## Routing correction (2026-10-20)

User-reported subjective game banter was reproduced as professional twice. Updated only the neutral router and separate runtime protocol to distinguish subjective game preferences/banter from objective performance, pricing and factual comparisons; the original persona asset and professional Agent are unchanged. Isolation regressions: 21 passed. Live user-provided example routes casual with either empty or professional previous-route metadata; objective comparison and card-chain request remain professional. Persona API returns a casual reply. Synthetic history cleared; both services active and QQ connection established. No QQ test messages sent. Rollback source: /home/ubuntu/qqbot/mention-routing-fix-jkkg1tqy/mention_chat.py.

## Fixed command routing deployment (2026-10-20)

Per explicit user direction, replaced semantic classification with deterministic professional command prefixes and default persona routing. Removed classifier model calls, confidence/previous-route decisions, error fallback to professional and persona-generated escalation. Full isolated regressions: bot 310 passed, backend 495 passed (805 total). Live HTTP checks: 11 fixed-route cases pass even with prior/quoted professional tags; no classification budget calls added; real persona API returns casual reply. Synthetic history cleared. Original persona, professional Agent/session/LLM hashes unchanged; health succeeds, both services active and one QQ connection established. No QQ test messages sent. Source backup: /home/ubuntu/qqbot/fixed-mention-routing-i9e9ivrf.
