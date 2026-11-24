# Group-chat budget false exhaustion

At 14:30 on 2026-10-22, `/api/mention-chat` returned HTTP 429 with
`Group model budget exhausted`. Both services were healthy. The bot mapped
every HTTP error to its generic RAG request-failed message.

The production budget contained 38 fake-model test reservations totaling
CNY 0.640304. The tests in `test_group_chat.py` and `test_group_style.py` mocked
provider calls, returned no token usage, and unintentionally used the default
production budget path. Thus their conservative reservations remained charged
despite no corresponding provider requests. Exact fixture counts and timestamp
clusters matched the four test executions at 12:31:52, 12:34:02, 12:38:37 and
12:52:57. Production metered usage was approximately CNY 0.32; the phantom
reservations pushed the budget near its CNY 1 daily cap.

Before correcting the ledger, SQLite backup captured the complete original
database at:
`/home/ubuntu/qqbot/ygo-rag-data-backups/budget-test-reservations-20261022/before.sqlite3`.
The same directory contains `excluded-test-reservations.json`, including the
reason, matching timestamps and all 38 original rows. Only rows matching the
confirmed test windows, routes, reserved state and missing usage fields were
removed. Both the expected count and total amount were checked before commit.
Real metered calls and unconfirmed older reservations were left intact.

Backend `tests/conftest.py` now sets a temporary `GROUP_CHAT_BUDGET_DB` for every
test. Running all 532 backend tests again created zero production reservations.
The 50 relevant bot tests passed. The bot now distinguishes its local budget
429 from generic provider throttling and other HTTP failures.

After restarting only the bot to load the improved messages, a real HTTP chat
request succeeded and the synthetic session was cleared. Daily estimated usage
was CNY 0.333888 at verification; limits remain CNY 1/day and CNY 10/month.
No QQ test messages were sent and no provider balance or API credentials changed.
