# Production Deployment

This document records the production relationship between `kami-man` and
`ygo-rag`. Do not store API keys or other secrets here.

## Hosts And Paths

- Bot host: `ubuntu@150.109.237.67`
- Bot repository: `/home/ubuntu/qqbot/kami-man`
- RAG repository: `/home/ubuntu/qqbot/ygo-rag`
- RAG data backups: `/home/ubuntu/qqbot/ygo-rag-data-backups`

## Services

- `kami-man.service`
  - Runs the NoneBot2 / OneBot V11 bot.
  - Entrypoint: `/home/ubuntu/qqbot/kami-man/bot.py`
  - Listens on `0.0.0.0:18080`
- `ygo-rag.service`
  - Runs the RAG HTTP service.
  - Entrypoint: `python -m rag_agent web --host 127.0.0.1 --port 7861`
  - Listens on `127.0.0.1:7861`
- `kami-onebot-watchdog.timer`
  - Runs every 2 minutes.
  - Restarts the `snowluma` OneBot container if `kami-man.service` is active
    but no established WebSocket connection exists on port `18080`.

## OneBot

- Container: `snowluma`
- Reverse WebSocket target:

```text
ws://host.docker.internal:18080/onebot/v11/ws
```

## Current RAG Contract

The bot calls:

```text
POST http://127.0.0.1:7861/api/query
```

The bot sends these request fields:

```json
{
  "query": "...",
  "top_k": 10,
  "rerank_candidates": 10,
  "semantic": true,
  "rerank": false,
  "llm_rerank": true,
  "llm": true,
  "structured_max_block_chars": 1800
}
```

The bot consumes these response fields:

- `answer`
- `warnings`
- `structured.blocks[*].type`
- `structured.blocks[*].text`
- `structured.blocks[*].truncated`

The RAG service may return additional fields such as `structured_query` and
`filter_diagnostics`; the bot should ignore fields it does not consume.

## Current Translation Contract

The bot calls:

```text
POST http://127.0.0.1:7861/api/translate
```

The bot sends these request fields:

```json
{
  "text": "...",
  "source_lang": "auto",
  "target_lang": "zh-CN",
  "structured_max_block_chars": 1800
}
```

The bot consumes these response fields:

- `translation`
- `warnings`
- `structured.blocks[*].type`
- `structured.blocks[*].text`
- `structured.blocks[*].truncated`

Only blocks with `type` equal to `translation` are sent as structured
translation message records. If no usable structured blocks are returned, the
bot falls back to splitting the top-level `translation` text.

## Production Environment

Bot-side drop-in:

```text
/etc/systemd/system/kami-man.service.d/ygo-rag.conf
```

Current bot-side values:

```text
YGO_RAG_API_URL=http://127.0.0.1:7861/api/query
YGO_RAG_TIMEOUT_SECONDS=240
YGO_RAG_TOP_K=10
YGO_RAG_RERANK_CANDIDATES=10
YGO_RAG_STRUCTURED_MAX_BLOCK_CHARS=1800
YGO_RAG_TRANSLATE_API_URL=http://127.0.0.1:7861/api/translate
YGO_RAG_TRANSLATE_TIMEOUT_SECONDS=240
YGO_RAG_TRANSLATE_SOURCE_LANG=auto
YGO_RAG_TRANSLATE_TARGET_LANG=zh-CN
YGO_RAG_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS=1800
YGO_RAG_TRANSLATE_COMMAND_ALIASES=翻译,translate
```

RAG service unit and drop-ins:

```text
/etc/systemd/system/ygo-rag.service
/etc/systemd/system/ygo-rag.service.d/llm-rerank.conf
```

Current RAG-side values:

```text
RAG_DEVICE=cpu
RAG_EMBEDDING_DEVICE=cpu
RAG_RERANKER_DEVICE=cpu
CHROMA_PERSIST_DIR=data/chroma
RAG_CARDS_DB=data/cards.cdb
RAG_LLM_RERANK_MAX_CANDIDATES=100
```

Secret values live in:

```text
/home/ubuntu/qqbot/ygo-rag/.env
```

Do not print, commit, or copy the DeepSeek API key into documentation.

## Current Production Versions

Update this section after coordinated deployments.

- `ygo-rag`: `d17d360 Improve structured filtered recall`
- `ygo-rag` data: uploaded from local `D:\workspace\rag\data` on 2026-07-02
- RAG smoke-test candidate count: `total_candidates=14819`
- `kami-man`: local workspace contains the RAG bot integration and OneBot
  watchdog deployment files

## Update Workflows

### Bot-only update

Use this when only bot code changes.

```bash
cd /home/ubuntu/qqbot/kami-man
python -m py_compile \
  services/ygo_rag_messages.py \
  services/ygo_rag_translation_api.py \
  services/ygo_rag_translation_messages.py \
  services/onebot_forward.py \
  plugins/ygo_rag_qa.py \
  plugins/ygo_rag_translate.py
sudo systemctl restart kami-man.service
systemctl status kami-man.service --no-pager -l
```

Verify:

```bash
journalctl -u kami-man.service -n 80 --no-pager
ss -Htn | grep 18080
```

### RAG code-only update

Use this when `ygo-rag` code changes but `data/cards.cdb` and `data/chroma`
do not change.

```bash
cd /home/ubuntu/qqbot/ygo-rag
git pull --ff-only
./.venv/bin/python -m py_compile rag_agent/*.py
./.venv/bin/python -m pytest tests -q
sudo systemctl restart ygo-rag.service
systemctl status ygo-rag.service --no-pager -l
```

Run a local API smoke test before considering the update complete.

### RAG code and data update

Use this when the vector store or card database changes.

1. Package local code as a git bundle from `D:\workspace\rag`.
2. Package local data from `D:\workspace\rag\data`:
   - `cards.cdb`
   - `chroma/`
3. Upload both packages to `/tmp` on the bot host.
4. On the bot host:

```bash
cd /home/ubuntu/qqbot/ygo-rag
git bundle verify /tmp/ygo-rag-local.bundle
git fetch /tmp/ygo-rag-local.bundle HEAD:refs/remotes/local/upload
git checkout -B main refs/remotes/local/upload
sudo systemctl stop ygo-rag.service
backup="data.backup.$(date +%Y%m%d%H%M%S)"
mv data "$backup"
mkdir -p /tmp/ygo-rag-data-new
tar -xzf /tmp/ygo-rag-data.tgz -C /tmp/ygo-rag-data-new
mv /tmp/ygo-rag-data-new data
chmod -R u+rwX,go+rX data
./.venv/bin/python -m py_compile rag_agent/*.py
./.venv/bin/python -m pytest tests -q
sudo systemctl start ygo-rag.service
mkdir -p /home/ubuntu/qqbot/ygo-rag-data-backups
mv "$backup" /home/ubuntu/qqbot/ygo-rag-data-backups/
```

Verify:

```bash
systemctl status ygo-rag.service --no-pager -l
curl -sS -H 'Content-Type: application/json' \
  --data-binary @/tmp/ygo-rag-smoke.json \
  http://127.0.0.1:7861/api/query
```

Clean temporary upload files after verification.

## Rollback

### Roll back RAG data

```bash
cd /home/ubuntu/qqbot/ygo-rag
sudo systemctl stop ygo-rag.service
mv data data.failed.$(date +%Y%m%d%H%M%S)
cp -a /home/ubuntu/qqbot/ygo-rag-data-backups/<backup-dir> data
sudo systemctl start ygo-rag.service
```

### Roll back RAG code

Use a known-good commit:

```bash
cd /home/ubuntu/qqbot/ygo-rag
git checkout -B main <known-good-commit>
./.venv/bin/python -m pytest tests -q
sudo systemctl restart ygo-rag.service
```

### Roll back bot code

Use the repository's normal git rollback process, then:

```bash
cd /home/ubuntu/qqbot/kami-man
sudo systemctl restart kami-man.service
```

## Health Checks

```bash
systemctl is-active kami-man.service
systemctl is-active ygo-rag.service
systemctl list-timers --all | grep kami-onebot-watchdog
ss -Htn | grep 18080
journalctl -u kami-man.service -n 80 --no-pager
journalctl -u ygo-rag.service -n 80 --no-pager
docker logs --tail 120 snowluma
```

Expected:

- `kami-man.service` is active.
- `ygo-rag.service` is active.
- OneBot has an established WebSocket connection on port `18080`.
- RAG API returns HTTP 200 for a non-LLM smoke test.

## Coordination Rules

- Keep `kami-man` and `ygo-rag` as separate repositories.
- `kami-man` must only call `ygo-rag` through HTTP; it must not import
  `rag_agent`.
- Adding response fields is compatible.
- Removing or renaming response fields requires a bot compatibility update
  before deploying the RAG change.
- Data updates should be treated as production releases and must keep a backup.
