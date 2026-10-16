# MyCard replay and deck archive

This feature independently follows the public room discovery and ordinary-account spectator flow
used in [hikari-bot](https://github.com/ParseeX/hikari-bot/tree/main/hikari_bot/services/mycard_archive).
Protocol fields were checked against the official MyCard YGOPro replay headers and decoder.
It does not copy the upstream implementation or reuse its deployment credentials.

## Scope and behavior

The bot listens to `wss://tiramisu.moecube.com:8923/?filter=started` and confirms each player's
current `arena_rank` using `https://sapi.moecube.com:444/ygopro/arena/user`.
A match is eligible if either player is ranked 1-500. Unknown ranks never grant eligibility.
Rank queries have concurrency 4 and a 5-minute cache; failures are retried while rooms remain live.
Only public two-player rooms allowing normal spectating are joined, with a configurable four-socket
limit and a minimum two seconds between admissions. The observer account's own games are skipped.
Three consecutive failed joins trigger global backoff. Fewer than 256 MiB free pauses capture.
The archive directory has a configurable 10 GiB limit by default. Collection pauses at the limit
without deleting any saved replay. The limit counts SQLite, replay files, deck files and export ZIPs.
The collector leaves 64 MiB within the limit for active-match metadata and finalization.

The TCP observer sends player-info and join-room frames only, confirms observer seat 7, and saves
STOC_REPLAY after that confirmation. It sends no gameplay responses and does not bypass room access.
Active games have no total watch timeout; room deletion allows 30 seconds for delayed replay delivery.
STOC_DUEL_END records a normal end, not independent proof that every possible round was received.
Connection failures and missed admission are recorded, and partial archives remain usable.
Without credentials, public room/rank discovery still runs, but no spectator connection or fake replay
is created. Pending rooms resume within about 30 seconds after credentials are added.

## Persistent evidence and deck versions

Runtime directory: `/home/ubuntu/qqbot/kami-man/data/mycard_archive`.
The SQLite index uses WAL, replay evidence is content-addressed and atomically replaced, and duplicate
frames do not increase observations. Restart recovery indexes orphan replay files, resumes live rooms,
and labels vanished active rooms as partial/unavailable. Original unsupported replays remain exported.
Each round yields observed Main/Extra. The first chronological observed deck is the match baseline;
maximum positive card-count differences in later rounds are **observed Side**, not the complete Side.
Same consecutive Main/Extra cores merge observations and Side evidence; a changed core or a union
exceeding 15 Side cards starts a new consecutive version. Raw per-match evidence is never overwritten.
Export ZIPs include raw YRP files, per-round and merged YDKs, and JSON metadata with completeness issues.
Raw Side over 15 is preserved, rather than truncated to make a share link.

## Configure an ordinary account

No credentials are included in Git. Do not paste passwords or login tokens into QQ commands or logs.
On the server, after obtaining a normal MyCard login token from your own logged-in client:

```bash
cd /home/ubuntu/qqbot/kami-man
venv/bin/python scripts/mycard_credentials.py
```

The tool reads the token without echo, verifies `accounts/authUser`, and atomically writes a mode-0600
`data/mycard_archive/credentials.json` containing the token only. It never stores the account password.
Alternatively create a mode-0600 JSON with the ordinary account's official `username` and `u16_secret`.
The runtime reloads changed credential files and refreshes token authentication periodically.
No account registration or authentication bypass is performed.

Production settings are in `/etc/systemd/system/kami-man.service.d/mycard-archive.conf`:

```ini
[Service]
Environment=MYCARD_CAPTURE_ENABLED=true
Environment=MYCARD_ARCHIVE_DIR=/home/ubuntu/qqbot/kami-man/data/mycard_archive
Environment=MYCARD_ARCHIVE_MAX_GB=10
Environment=MYCARD_CREDENTIALS_FILE=/home/ubuntu/qqbot/kami-man/data/mycard_archive/credentials.json
Environment=MYCARD_CAPTURE_CONCURRENCY=4
Environment=MYCARD_RANK_CUTOFF=500
Environment=MYCARD_JOIN_INTERVAL=2
```

Preserve this runtime directory across code deployments. If the archive reaches its limit,
new rooms and replay frames pause until space is freed or the configured limit is raised;
existing archives remain available, and an export is rejected if its ZIP would exceed the limit. Setting capture enabled false stops new
monitoring after a service restart; archived queries remain available. There is no automatic deletion
or unsolicited QQ notification. Archive, per-player and file commands use existing SUPERUSER access.
`前排卡组信息` is public, and uses the actual official front-100 endpoint `arena/users?o=pt`; it does not
claim that endpoint contains the top 500. Help lists the complete command set.

## Optional classification

`data/mycard_archive/deck-rules.json` is read on each query. Example:

```json
{"version":1,"rules":[{"name":"Example archetype","requires":{"89631139":2}}]}
```

Each rule requires all card IDs with at least the indicated copy count in Main+Extra. Matching labels
combine; without rules the archive says unclassified. Invalid rules produce an explicit query failure,
while raw replays and deck files remain saved.

## Validation

Parser, archive recovery, deduplication, Side multiplicity, consecutive version transitions, room event
reconciliation, spectator framing/access confirmation, rank boundaries, missing credentials, queue
cancellation, safe ZIP paths and the archive quota are tested with synthetic data.

Current validation: 208 bot tests pass, including quota boundary checks for saved replays, concurrent
writes and ZIP exports. The running archive has saved real spectator captures.


## Automatic transfer to the home host

The home Windows machine stores cold replay evidence in
`D:\file\mycard_archive\batches\<batch-id>.tar`.
The `KamiMan-MyCard-Offload` scheduled task runs as SYSTEM at startup and every five minutes.
It uses Git Bash and a dedicated SSH key under `C:\ProgramData\KamiMan\MyCardOffload`.
The corresponding server authorized key is restricted to
`scripts/mycard_offload_ssh.py`: prepare, fetch, commit and status only; it cannot open a shell.

When local usage approaches the existing 10 GiB cap (one MiB before the capture ceiling),
the server packages up to 512 MiB of finished matches per batch. Active matches are excluded.
Each tar contains original YRP files, YDKs and match manifests; account credentials are excluded.
Home verifies the expected byte count and SHA-256, atomically renames the downloaded file and
writes a checksum sidecar before acknowledging the transfer. Only then does the server remove
the transferred YRP files and cached ZIPs. The SQLite index, deck observations, manifests and
YDKs stay on the server, so deck queries and history remain available.

Old replay downloads in QQ report the home archive path. They are no longer reconstructed
or served by QQ. Open or extract the tar on home to view the original evidence.
A failed copy, offline home, full D drive or checksum mismatch leaves the server evidence intact.
Capture still pauses at its local cap until verified transfer frees space.

Runtime files:
- Home script: `D:\file\mycard_archive\offload.sh`
- Home log: `D:\file\mycard_archive\offload.log`
- Home checksum: `<batch-id>.tar.sha256`
- Server pending batch: `data/mycard_offload_stage/pending.json`
- Server transfer spool: `data/mycard_offload_stage/<batch-id>.tar`

The pending batch is reused after interruption, including after home has downloaded it but
before the server has acknowledged cleanup. Server confirmation and cleanup are idempotent.
Staging space is outside the live archive quota and holds at most one batch; packaging requires
an additional 256 MiB of free disk space. The local index and retained metadata still count
toward the 10 GiB limit.

To reinstall the home schedule after provisioning its key and trusted server host key, copy the
versioned shell script to the home script path and run
`scripts/install_mycard_home_task.ps1` on home. The task never wakes or unlocks the machine.
