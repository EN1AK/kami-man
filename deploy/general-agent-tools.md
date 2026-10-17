# General chat tools

The unified RAG Agent now provides web_search, read_webpage, current_time and calculate.
See the server-side contract in the ygo-rag repository at docs/general-tools.md.

Examples:
- @神人 搜一下今天 DeepSeek 的官方公告，并给出来源
- @神人 帮我读一下这个公开链接：https://example.com/article
- @神人 现在北京时间几点？纽约呢？
- @神人 1250 打八五折再加 18 元运费是多少？

The Agent selects tools semantically. Basic-tool-only responses are rendered as ordinary QQ
text, including available web sources, instead of a forwarded debug trace. Mixed card requests
retain their existing detailed results and card images. Failures and incomplete-tool warnings
are shown, and verified source links are not repeated when already present in the answer.

The existing 30-per-day per-user @ quota is unchanged. Search/fetch calls use the existing
official DeepSeek account and are bounded to three attempts per request by the backend.
No bot-side API key, browser session or additional public listener is introduced.
