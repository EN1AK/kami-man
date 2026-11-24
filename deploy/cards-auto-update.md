# Chinese card catalog auto-update

The shared catalog is `/home/ubuntu/qqbot/shared-ygo/cards.cdb`.
The old `/home/ubuntu/qqbot/ygo-rag/data/cards.cdb` is a compatibility symlink.
`kami-cards-update.timer` checks hourly, with up to five minutes of jitter.
Upstream: <https://github.com/mycard/ygopro-database/blob/master/locales/zh-CN/cards.cdb>.

The updater uses an HTTP ETag conditional request. A changed download is staged
in the destination directory, checked with SQLite `quick_check`, and validated
for required columns and matching named card records. It rejects fewer than
10,000 cards or a decrease greater than 5 percent. SHA-256 comparison avoids
replacing identical contents. Only a validated file is atomically installed.
Failures leave the current catalog and successful update state intact.

One previous catalog is retained at
`/home/ubuntu/qqbot/ygo-rag-data-backups/cards-auto-update/previous.cdb`.
Update state is `/home/ubuntu/qqbot/ygo-rag/data/cards-update/state.json`.
A file lock prevents overlapping runs. The service runs as ubuntu, at low CPU
and I/O priority, capped at 25 percent of one CPU and 128 MiB memory.

`/home/ubuntu/qqbot/shared-ygo/strings.conf` is updated by the same job from
<https://github.com/Fluorohydride/ygopro/blob/master/strings.conf>. It is validated
separately (at least 400 valid set-name records), backed up, and atomically
replaced. Invalid labels retain the previous file; an update failure is logged
by systemd. The catalog and label table are independently versioned upstream.

The bot's naming catalog and RAG card cache reload on file changes. No service
restart is required for data updates. This updates card records and setcodes;
it does not rebuild card/ruling vector indexes. New cards therefore
become available to direct catalog matching, while semantic vector coverage
still depends on a separate index build.

Consumers:

- `kami-man.service`: `MYCARD_CARD_DB` and `MYCARD_SETNAMES` are set in
  `/etc/systemd/system/kami-man.service.d/shared-cards.conf`.
- `ygo-rag.service`: `RAG_CARDS_DB` is set in the corresponding
  `shared-cards.conf` drop-in. The legacy path resolves to the shared file too.
- `yugioh-ccb`: Docker Compose mounts the shared directory read-only at
  `/app/shared-cards`. `CARD_DB_PATH` reads the shared base records;
  `CARD_STRINGS_PATH` reads the labels; `CARD_METADATA_DB` reads its existing
  private heat/release/pack/alias data. The legacy website database is retained
  for this supplemental data only. A request checks file stamps at most once
  every ten seconds and swaps in a fully loaded catalog on changes. Existing
  catalog data remains active if loading fails. The website source files are
  mounted read-only from its checkout, avoiding an image rebuild.

Riftbound uses a different game's schema and retains its own databases. Backup
and diagnostic copies are historical snapshots and must not be redirected.

The website changes are preserved in `deploy/ccb-shared-cards.patch` (apply from
`/home/ubuntu/yugioh-ccb-main` with `patch -p1`). Original website and bot source
files and the previous updater unit were backed up under
`/home/ubuntu/qqbot/shared-cards-backup-20261020-195001` before deployment.

Deployment verification on 2026-10-20: all 368 bot tests passed, all 100 preview
deck names matched, an added card was returned by the live RAG query endpoint,
and the website returned HTTP 200 with a healthy Docker status. Its loader
retained 444 hot cards and 14,022 cards with release dates (14,498 unique names;
the shared base contains 15,071 records including alternate identities).

Install from the server checkout:

```bash
sudo install -m 644 deploy/kami-cards-update.service deploy/kami-cards-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start kami-cards-update.service
sudo systemctl enable --now kami-cards-update.timer
systemctl list-timers kami-cards-update.timer --no-pager
journalctl -u kami-cards-update.service -n 30 --no-pager
```

To stop future updates: `sudo systemctl disable --now kami-cards-update.timer`.
Before a rollback, stop the timer and updater, copy `previous.cdb` to a temporary
file beside `cards.cdb`, validate it with this updater's `validate` function,
and atomically rename it over `cards.cdb`. Delete the update state so the next
check does not send a stale ETag.
