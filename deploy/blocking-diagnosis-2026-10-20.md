# Mention delay: MyCard capacity scan contention (2026-10-20)

## Evidence

A mention handler ran from 12:13:41 to 12:17:45 CST. The persona model reservation began at 12:17:16 and the HTTP response completed at 12:17:17; model generation did not account for most of the delay. Independent client probes measured routing 0.038s, style lookup 0.005s, meme catalog 0.012s and persona generation 0.993s.

Live native/Python stack sampling found ArchiveStore.capture_available -> usage_bytes repeatedly traversing the archive tree. The 120-second reproduction capture contained 776 thread samples in capture_available. This is a sampled thread count, not a CPU percentage. Collector.collect and identity submitted a full scan per room to asyncio's default executor, which is also used by mention quota, route metadata and style lookup. Large discovery bursts can queue mention work behind archive scans. The original multi-minute incident was not sampled; contention is supported by current stacks, call sites and the isolated burst reproduction.

## Change

Collector now coalesces concurrent admission checks into a single task, caches successful results for five seconds, and runs scans in a dedicated one-worker executor. Shielding prevents a cancelled room from cancelling the shared scan. Errors are not cached as permission. Close cancels the shared task and shuts down the executor. ArchiveStore.require_capacity and the exact capacity check under the write lock are unchanged; cached admission never authorizes an unchecked write. Persona, professional services, quotas and API settings are unchanged.

## Validation

- Full bot regressions: 312 passed.
- A burst of 100 capacity checks performs one scan; unrelated work on a one-worker default executor completes while the scan is blocked.
- Cancelled waiters, five-second refresh, scan-error retry and false-capacity caching verified.
- Deployed production Collector; backup: /home/ubuntu/qqbot/mycard-capacity-fix-zyo1bc17/collector.py.
- Live stack confirms dedicated mycard-capacity_0 thread. A 20-second post-restart sample measured 17.7% bot CPU (not directly comparable to historical lifetime averages).
- Both services active; one established QQ connection; archive listener connected; no tracebacks or archive-processing errors during verification.
- Post-deployment natural mentions at 12:31:13-12:31:15 and 12:31:25-12:31:26 CST completed in about two and one seconds. No diagnostic QQ messages were sent by the agent.

Diagnostic stack files contain function names and source locations, no locals or message text, under /home/ubuntu/qqbot/.blocking-diagnostics/. The profiler is isolated there and was not added to production dependencies.
