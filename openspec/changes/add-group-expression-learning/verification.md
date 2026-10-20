## Server verification (2026-10-17)

- Authoritative workspaces: /home/ubuntu/qqbot/kami-man and /home/ubuntu/qqbot/ygo-rag.
- Before deployment, saved changed source and an online SQLite backup under /home/ubuntu/qqbot/group-learning-backup-20261017-231623 (server-only, private mode).
- Bot complete suite: 280 passed. Backend complete suite after final fix: 449 passed, five existing adjudication deprecation warnings. Total 729 passed.
- OpenSpec strict validation passed. Existing modified files were preserved; no reset, pull or commit was performed.
- Synthetic API smoke: three source-verified expressions; chat reply generated in 1.06s. No synthetic QQ messages sent.
- First automatic real-sample learning returned HTTP500 because the provider produced eight candidates instead of five. Added a regression and bounded validated output locally to five. An operator retry after repair released only the failed expired lease timer, retaining the daily attempt count and shared cost ledger; normal automatic retries still wait an hour.
- First real learning batch then completed successfully: five expressions with human source evidence; two scheduled/operator attempts, one success. Diagnostic provider call is recorded separately in the shared model usage ledger.
- Final health: both services active; one established OneBot connection; HTTP health true. Available RAM 1697MiB; bot cgroup 108535808 bytes, backend 286486528 bytes. This is a single-group startup observation, not a load benchmark.
- Shared ledger: five calls (including smoke/diagnostics), 1851 input tokens, 571 output tokens, 256 cache tokens, zero reasoning tokens, no uncertain reservations, CNY0.008270 conservative estimated cost.
- Limits confirmed: daily CNY1/monthly CNY10, 20 chat attempts/day, existing collection switches preserved. Existing sample/profile data retained; new tables are additive and runtime databases remain Git-ignored.
