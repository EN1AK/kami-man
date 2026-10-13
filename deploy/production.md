# Production Deployment

This document records the production relationship between `kami-man` and
`ygo-rag`. Do not store API keys or other secrets here.

## Hosts And Paths

- Bot host: `ubuntu@150.109.237.67`
- Bot repository: `/home/ubuntu/qqbot/kami-man`
- RAG repository: `/home/ubuntu/qqbot/ygo-rag`
- RAG data backups: `/home/ubuntu/qqbot/ygo-rag-data-backups`
- Riftbound RAG repository: `/home/ubuntu/qqbot/riftsim`

## Services

- `kami-man.service`
  - Runs the NoneBot2 / OneBot V11 bot.
  - Entrypoint: `/home/ubuntu/qqbot/kami-man/bot.py`
  - Listens on `0.0.0.0:18080`
- `ygo-rag.service`
  - Runs the RAG HTTP service.
  - Entrypoint: `python -m rag_agent web --host 127.0.0.1 --port 7861`
  - Listens on `127.0.0.1:7861`
  - Also serves the Riftbound gateway route `POST /api/rift/query` (consume-path
    alias `/api/rift/api/query` for kami-man base-URL composition)
- `rift-rag.service`
  - Runs the Riftbound rules RAG backend.
  - Entrypoint: `./.venv/bin/python scripts/rag/rag_server.py --host 127.0.0.1 --port 7862 --preload`
  - Working directory: `/home/ubuntu/qqbot/riftsim`
  - Listens on `127.0.0.1:7862`
  - Data: `workspace/final/rules.db` + `cards_bilingual.db` tracked in git;
    `workspace/rag/rules_vectors.npy` + `rules_index.json` uploaded out of band;
    `BAAI/bge-m3` fetched server-side into the HF cache.
  - Secrets in `/home/ubuntu/qqbot/riftsim/.env` (`OPENAI_API_KEY` /
    `OPENAI_BASE_URL` / `RAG_LLM_MODEL`, tuning `RAG_AGENT_MAX_STEPS=3` /
    `RAG_REQUEST_TIMEOUT=240`). Same do-not-document-secrets rule applies.
  - Bot trigger: group-message aliases `符文规则` / `符文裁定` (plugin
    `plugins/rift_rag_qa.py`).
- `kami-onebot-watchdog.timer`
  - Runs every 2 minutes.
  - If the OneBot WebSocket on port `18080` is disconnected, recognizes QQ's
    saved-account login window and clicks its login button.
  - If QQ's main window is visible but the WebSocket remains disconnected,
    restarts `snowluma` with a 5-minute restart cooldown. An unrecognized
    login window is left untouched for manual attention.

## OneBot

- Container: `snowluma`
- Reverse WebSocket target:

```text
ws://host.docker.internal:18080/onebot/v11/ws
```

## Current RAG Agent Contract

The bot calls:

```text
POST http://127.0.0.1:7861/api/agent
```

The bot sends these request fields:

```json
{
  "text": "...",
  "semantic": true,
  "rerank": false,
  "llm_rerank": true,
  "max_steps": 6,
  "structured_max_block_chars": 1800
}
```

The bot consumes these response fields:

- `answer`
- `warnings`
- `exhausted`
- `structured.blocks[*].type`
- `structured.blocks[*].tool`
- `structured.blocks[*].ok`
- `structured.blocks[*].summary`
- `structured.blocks[*].result`

The agent block result may contain nested specialist structured blocks from
`search_cards` or `translate_text`, or `natural_answer` from `adjudicate`.
The bot should ignore fields it does not consume.

## Legacy RAG Query Contract

The old card-similarity endpoint remains available for direct service testing:

```text
POST http://127.0.0.1:7861/api/query
```

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
YGO_RAG_AGENT_API_URL=http://127.0.0.1:7861/api/agent
YGO_RAG_AGENT_TIMEOUT_SECONDS=240
YGO_RAG_AGENT_MAX_STEPS=6
YGO_RAG_AGENT_STRUCTURED_MAX_BLOCK_CHARS=1800
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

Current bot-side Riftbound rules env names (see [.env.example](file:///c:/Users/Mortis/Desktop/Workspace/kami-man/.env.example)):

- Deployed on the live host: `RIFT_RAG_BASE_URL=http://127.0.0.1:7861/api/rift` (routes through the ygo-rag gateway; switch to `http://127.0.0.1:7862` to bypass the gateway) and `RIFT_RAG_TIMEOUT_SECONDS=290`, appended to the existing drop-in `/etc/systemd/system/kami-man.service.d/ygo-rag.conf`. Timeout chain: bot 290 > gateway `RIFTBOUND_RAG_TIMEOUT_SECONDS=270` (drop-in `/etc/systemd/system/ygo-rag.service.d/rift.conf`) > upstream `RAG_REQUEST_TIMEOUT=240`.

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

- `ygo-rag`: `dd80b64 Add Riftbound rules gateway (contract-v2 pass-through), design doc, pytest guidance cleanup`
- `kami-man`: `6933251 rift-rag trigger aliases -> 符文规则/符文裁定; drop misplaced openspec change; fix whitespace-topic / fullwidth-comma / adapter-compat issues`
- `riftsim`: `0fbe382 rift-rag agent 模式与契约 v2：planner→工具循环 + 引用校验 + 确定性回退`

## Update Workflows

### Bot-only update

Use this when only bot code changes.

```bash
cd /home/ubuntu/qqbot/kami-man
python -m py_compile \
  services/ygo_rag_agent_api.py \
  services/ygo_rag_agent_messages.py \
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

## Riftbound Card Lookup

Commands `rb` / `符文查卡` and `rbpl` / `符文批量` / `符文批量查卡`
query the bilingual SQLite database directly. Lookup supports subtitles, exact
codes, substring matching and typo candidates. Same-effect editions are grouped;
the broad `符文` alias is not registered, preserving rules Q&A triggers.

- `RIFTBOUND_CARDS_DB`: defaults to the sibling `riftsim/cards_bilingual.db`.
  For production use `/home/ubuntu/qqbot/kami-man/data/riftbound/cards_bilingual.db`,
  a validated runtime snapshot of the repaired local riftsim DB.
- `RIFTBOUND_IMAGE_CACHE`: defaults to `data/riftbound_images/` in the bot repo.
  For production use `/home/ubuntu/qqbot/kami-man/data/riftbound_images`.
- Put these environment variables in a dedicated systemd drop-in,
  `/etc/systemd/system/kami-man.service.d/riftbound-cards.conf`, preserving the
  existing RAG configuration.
- Download images **on the Linux server only**, using the bot virtualenv:

  ```bash
  cd /home/ubuntu/qqbot/kami-man
  RIFTBOUND_CARDS_DB=/home/ubuntu/qqbot/kami-man/data/riftbound/cards_bilingual.db \
    RIFTBOUND_IMAGE_CACHE=/home/ubuntu/qqbot/kami-man/data/riftbound_images \
    venv/bin/python assets/cache_riftbound_images.py --concurrency 4
  ```

  The downloader resumes valid cached images, retries failures and falls back
  from CN to EN. Cache filenames hash the source URL. Downloads are size-limited
  and written atomically. `download_report.json` records coverage, English
  fallbacks and failures. The script refuses Windows execution.
- Validate updated snapshots before atomically replacing the configured file.
  Preserve `text_cn_filled` / `cn_fill_note`: rebuilding from the raw scrape
  alone loses reviewed supplements. The index refreshes on file timestamp or
  size changes. Supplementary translations and errata are labeled separately.
- Verify with `DRIVER=~none venv/bin/python -m pytest tests -q`, then restart the
  bot and check its service logs. QQ delivery requires a real user command.


## Unified Agent migration (2026-10-12)

`ygo-rag.service` on 7861 now owns chat, both game domains and translation.
Mentions and explicit Rift/translation aliases share `POST /api/agent`, scoped
by bot/group/user; chat is a plain reply, professional responses preserve
evidence and card images. `rift-rag.service` on 7862 is disabled after verification.
The earlier two-backend topology in this file is historical. Current settings,
module paths, request budgets and rollback: `../ygo-rag/docs/unified-agent.md`.
The server is the authoritative workspace for this migration.


## Agent daily quota

Unified QQ Agent requests share a persistent per-QQ daily limit of 30 across groups and aliases.
The date boundary is Asia/Shanghai midnight. NoneBot superusers are exempt, but usage is recorded.
SQLite `data/agent_usage.db` is runtime-only and excluded from Git; keep it across restarts/deploys.
Atomic reservations include in-flight requests, and failed upstream calls are refunded to the reservation day.
Blank/oversized requests, usage commands and exact `清空对话` are free. Standalone card commands are unchanged.
`@神人 用量` shows personal use; `@神人 用量统计` is restricted to superusers (today totals and top 20).


## Jihuanshe price lookup on Windows

The QQ commands `卡价 卡名 [语种] [罕贵]` and
`符文卡价 卡名或编号 [语种] [罕贵]` use the logged-in Windows
WeChat Jihuanshe mini-program, without a rooted Android phone. Version selection
expires after 180 seconds and is scoped to bot/chat/user. Results keep pack
numbers separate and distinguish current minimum listing price from the latest
Jihuanshe market-history point. All prices are CNY. Search, selection, detail
and history requests carry the same game/language scope; details must match the
requested platform partition before any price is returned. Results and selection
prompts show the language. Missing market history stays unavailable; it is not
replaced by another language's price. Cardrush and PTCG remain outside this integration.

Verified partition mapping from the mini-program game configuration:

| Game | Language | `game_key` | `game_sub_key` |
|---|---|---|---|
| Yu-Gi-Oh | Japanese (default) | `ygo` | `ocg` |
| Yu-Gi-Oh | Simplified Chinese | `ygo` | `sc` |
| Yu-Gi-Oh | English | `ygo` | `tcg` |
| Riftbound | Simplified Chinese (default) | `lol` | `default` |
| Riftbound | Traditional Chinese | `lol` | `tc` |
| Riftbound | English | `lol` | `en` |
| Riftbound | Korean | `lol` | `kr` |

The old `ocg` scope was the platform's Japanese partition; it was not a mixed
language scope. Explicit partition labels now avoid that ambiguity. For example:
`卡价 原石之皇脉 简中 SR`, `卡价 原石之皇脉 日文 SR`,
`符文卡价 OGN-119 英文` or `卡价 符文 OGN-119 简中`.
The bridge accepts only this allowlist. Unsupported or conflicting languages
are rejected. The legacy `name_jp` request key remains supported for old clients;
new clients send `keyword`, `game` and `language` on both endpoints.

Riftbound resolves full titles and subtitles through the existing card snapshot
when available, with direct market search as a fallback. Accessories are excluded;
ambiguous character names return complete-title candidates. Card numbers select
an exact edition, preserving base/alternate/signed variants. A space-separated
subtitle may need a character search followed by full-title matching.

The local bridge uses [WMPFDebugger](https://github.com/evi0s/WMPFDebugger).
Verified on WeChat 4.1.15.13 / WMPF 25715, Node 22+ and PowerShell 7. The debugger
needs offsets for the installed WMPF version; recheck compatibility after WeChat
updates. Keep upstream `yarn.lock`. `setup.ps1` installs the locked dependencies,
binds both debugger sockets to loopback, exits on Frida session detachment,
uses IPv4 for the hook and enables the
observed desktop-shortcut launch scene 1023. Scene 1000 remains excluded.

On the Windows account that runs WeChat, log into Jihuanshe and use its menu to
create a desktop shortcut. From this repository:

```powershell
./scripts/jihuanshe_windows/setup.ps1
./scripts/jihuanshe_windows/start.ps1 -AutoStart
./scripts/jihuanshe_windows/start.ps1
./scripts/jihuanshe_windows/start.ps1 -Status
```

Runtime dependencies, private `config.json` and logs stay under
`.venv/jhs-windows-poc/`, excluded from Git. Setup preserves the existing bridge
token and accepts `-DebuggerDir`, `-ShortcutPath`, `-SshHost` and `-AppId`; `-EnableAutoOpen` is an explicit opt-in.
The default target app ID is `wx64479c83c7630409`, verified in the logged-in
Jihuanshe session. The bridge only offers version/price queries, never arbitrary
JavaScript execution or WeChat login tokens.

The Windows task `KamiMan-Jihuanshe-Bridge` starts a hidden supervisor at the
current user's logon, with normal user privileges. A repeating one-minute
trigger also restores the supervisor if it exits; overlapping runs are ignored.
The supervisor adopts an existing bridge only after checking its saved process
ID, creation time and script/config paths, preserving the active mini-program
connection. `start.ps1 -Status` reports both supervision and mini-program
auto-open mode. An explicit `start.ps1 -Stop` remains stopped across watchdog
checks until `start.ps1` clears the stop request. The supervisor restarts a
failed bridge with a 5–60 second backoff and removes only its own debugger/tunnel
children. The bridge serializes queries, checks the session every 30 seconds and restarts
failed debugger/tunnel processes. The local configuration now uses
`autoOpen: false`, as requested, so tests and recovery never launch or activate
the mini-program on the user's working desktop. The user opened it on a dedicated
Windows virtual desktop; background requests do not switch desktops.

When `autoOpen` is false, a missing mini-program session requires manually
reopening Jihuanshe on that dedicated desktop. The supervisor and SSH recovery
continue to work. A debugger restart may also need this manual step. A virtual
desktop alone is not treated as authorization to launch a window on the current
desktop. For a separate machine where foreground windows are acceptable,
`setup.ps1 -EnableAutoOpen` explicitly opts into shortcut recovery. That mode
closes only the Jihuanshe mini-program window and may bring its replacement to
the foreground. New private configurations default to manual opening.

Windows must remain online and awake with the user signed in and WeChat logged
in. A lost WeChat/Jihuanshe login still needs manual login; the bridge does not
enter passwords, bypass login or unlock Windows. Sleep/lock and overnight
behavior have not been verified. A request during recovery may need retrying.

Only `127.0.0.1` listens on Windows ports 8791 (authenticated HTTP), 9421 and
62000 (debugger). Native Windows OpenSSH forwards the server's loopback port:

```text
-R 127.0.0.1:8791:127.0.0.1:8791 ubuntu@150.109.237.67
```

The tunnel uses batch authentication, connection timeout, SSH keepalives and
`ExitOnForwardFailure`; Windows SSH key access must already work. No public
firewall port is needed. The production bot receives these settings from the
root-owned, mode-600 systemd drop-in
`/etc/systemd/system/kami-man.service.d/jihuanshe.conf`:

```ini
[Service]
Environment="JIHUANSHE_BRIDGE_URL=http://127.0.0.1:8791"
Environment="JIHUANSHE_BRIDGE_TOKEN=<same token as Windows private config>"
Environment="JIHUANSHE_BRIDGE_TIMEOUT=90"
```

Transfer the shared bridge token privately; do not commit it, print it in logs
or place it in a public URL. After changing the drop-in, run
`sudo systemctl daemon-reload` and `sudo systemctl restart kami-man.service`.
Check service status, the reverse listener on `127.0.0.1:8791`, and a real QQ
query. Logs under `.venv/jhs-windows-poc/service.*.log` record lifecycle events
without request bodies or session tokens. They are replaced on bridge restart.

Verified on 2026-10-12: QQ delivered real prices; killing the owned SSH tunnel
recreated the reverse connection; killing the debugger restored the shortcut
session and price requests. The supervisor also recovers a killed bridge and
cleans up its orphaned helper processes. Closing the Jihuanshe window also
reopened the mini-program and restored real prices. Login-triggered startup was registered
and run through Task Scheduler; a full Windows reboot was not tested. On
2026-10-13 the local configuration disabled automatic mini-program launching
to avoid interrupting the working desktop.

To stop or disable logon startup:

```powershell
./scripts/jihuanshe_windows/start.ps1 -Stop
./scripts/jihuanshe_windows/start.ps1 -RemoveAutoStart
```

`-Stop` requests graceful shutdown, preserving unrelated WeChat/SSH processes.
Start again with `start.ps1`. To remove production price configuration, remove
only the `jihuanshe.conf` drop-in, reload systemd and restart the bot; preserve
other drop-ins. Commands then report that price lookup is not configured.


Language/Riftbound verification (2026-10-13): real background requests returned
separate ROTA-JP058 SR and ROTA-SC058 SR prices, and OGN-119 Simplified Chinese,
English and Traditional Chinese results. Korean Riftbound and English Yu-Gi-Oh
version searches also returned their respective partitions. A foreign Japanese
version ID requested under Simplified Chinese is rejected rather than relabeled.
No-history/no-listing results remain unavailable. Python command/client tests and
Node bridge tests cover scope isolation, two-step selection, numbered editions,
accessory exclusion and manual desktop mode. Local automatic launching remains
disabled; the user reopened Jihuanshe on a dedicated virtual desktop.


Yu-Gi-Oh fuzzy price selection (2026-10-13): `卡价` reuses the same
`services.ygo_api.search_cards` YGOCDB search as `ck` and `pl`, without calling
image download or card-message builders. Unique exact standard-name/alias or
password matches take priority over API order. Otherwise multiple matches show
up to 25 text candidates, the same visible limit as `pl`, including card names
and passwords. Reply with a list number, listed password or unique full name.
Duplicates are removed by password; a truncated list asks for a narrower query.

The next stage selects rarity; an explicitly supplied rarity skips that stage.
Both stages keep the original game/language, are scoped to bot/chat/user, expire
after 180 seconds each and support cancellation. The chosen canonical card
metadata is reused directly, so selecting a candidate does not rerun the fuzzy
search and accidentally pick a different card. If YGOCDB is unavailable and the
market search finds several cards, the same text chooser keeps each card's
market versions together; market card IDs are never presented as YGO passwords.
`ck`, `pl` and their image responses retain their existing behavior. Riftbound's
ambiguous-title handling is unchanged. Examples: `卡价 原石 简中` then choose
`56506740`, then `SR`; or `卡价 原石 简中 SR` then choose the card to get prices.
This update changes only the bot; no local mini-program restart is needed.
