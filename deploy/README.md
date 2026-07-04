# Deployment Helpers

## OneBot WebSocket Watchdog

`kami-onebot-watchdog.sh` checks whether the bot server still has an
established TCP connection on the OneBot reverse WebSocket port.

Default assumptions:

- Bot service: `kami-man.service`
- Bot port: `18080`
- OneBot container: `snowluma`

Install on the bot host:

```bash
sudo install -m 0755 deploy/kami-onebot-watchdog.sh /usr/local/bin/kami-onebot-watchdog
sudo install -m 0644 deploy/kami-onebot-watchdog.service /etc/systemd/system/kami-onebot-watchdog.service
sudo install -m 0644 deploy/kami-onebot-watchdog.timer /etc/systemd/system/kami-onebot-watchdog.timer
sudo systemctl daemon-reload
sudo systemctl enable --now kami-onebot-watchdog.timer
```

The watchdog only restarts the OneBot container when the bot service is active,
the container is running, and there is no established connection on the bot
WebSocket port.
