# Independent group learning (2026-10-29)

Enabled groups: 819151070 and 875615212. Bot and backend allowlists agree.
The existing group_id keys isolate collection settings, samples, anonymous speakers,
style summaries, expression evidence, recent conversation and quote relationships,
random reply cooldowns and limits, and meme history. A new group starts empty;
no old group profile or examples are copied. Professional Agent routing is unchanged.
The hourly worker visits both groups. Summary thresholds and learning cadence stay unchanged.
Random replies: 3 percent eligible-message probability, 300-second cooldown,
20 generation attempts per group per day. Context: 30 minutes, at most 30 messages.
Global model budget remains CNY 1/day and CNY 10/month, shared across groups.

Changes: bot services/group_chat_store.py; backend rag_agent/group_chat.py,
group_style.py, group_learning.py, mention_chat.py. The single ALLOWED_GROUP
constant remains as the default validation scope for legacy mention callers;
feature authorization uses ALLOWED_GROUPS/is_enabled_group.

Validation: 122 bot tests and 112 backend tests passed. New regression checks
exercise independent summary/learning jobs, the same user and message IDs in
both groups, conversation quote chains, per-group reply reservation, clearing
one group without touching the other, allowed-group validation and session mismatch.
Tests use temporary stores and isolated budget files; no QQ test messages were sent.
Both systemd services restarted successfully. Live status endpoint returned 200;
new group learning request passed group authorization and failed only the intended
invalid sample check. Unknown group 123 still returned Group is not enabled.

Backup: /home/ubuntu/qqbot/multi-group-backup-20261029-204533
Includes original changed source and group-chat-before.sqlite3.
Backend patch: deploy/multi-group-learning-backend.patch (apply in ygo-rag).
New backend regression: ygo-rag/tests/test_multi_group_isolation.py.

Group controls (mention bot): 群聊学习 状态 / 群聊风格 / 随机聊天 关闭 /
群聊采集 关闭. Controls operate on the current group only.
