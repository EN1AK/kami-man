# Official QQ query service

`kami-qq-official.service` is independent of `kami-man.service` and listens only on
127.0.0.1:18081. It connects to QQ via WebSocket; it does not load OneBot plugins,
collect replays, send notifications, or write legacy identity/usage/chat state.
Use a separate venv with `official_qq/requirements.txt`. Both JSON config files
under `~/.config/kami-qq-official/` must be private (0600): `credentials.json`
contains `app_id` and `app_secret`, and `backends.json` contains the allowlisted
query backend environment settings. Update the latter after rotating the bridge
secret. Neither file belongs in Git.

Enable group/DM scenarios for the app in QQ developer settings and send `帮助`
(or `@机器人 帮助` in a test group). The initial command set includes cards,
prices, rulings, history, win rate, first win, decks, and cached report images.
Official MyCard queries require an explicit player name. Bulk card queries list
candidates; price selection can be narrowed by a more exact command. No old QQ
bindings, subscriptions, group learning, or admin/Agent commands are migrated.
Markdown is native. The bot tries official material upload for combined replies,
then uses separate images when the material endpoint is unavailable.

To stop this entry only: `sudo systemctl disable --now kami-qq-official.service`.
