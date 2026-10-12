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
Environment=MYCARD_CREDENTIALS_FILE=/home/ubuntu/qqbot/kami-man/data/mycard_archive/credentials.json
Environment=MYCARD_CAPTURE_CONCURRENCY=4
Environment=MYCARD_RANK_CUTOFF=500
Environment=MYCARD_JOIN_INTERVAL=2
```

Preserve this runtime directory across code deployments. Setting capture enabled false stops new
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
cancellation, and safe ZIP paths are tested with synthetic data. Production can verify public discovery
and official ranks without credentials. A real end-to-end spectator replay awaits the owner's account
configuration; do not report that live capture was verified before it was.

Initial validation: 172 bot tests passed (44 archive cases). Live public WS and both official rank
endpoints were verified on the deployment server. No real spectator capture was attempted without credentials.
