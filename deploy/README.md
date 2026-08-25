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

## Windows sandbox git push

When pushing from the local Windows sandbox, Git for Windows' MSYS2 helpers
(`sh.exe` / `ssh.exe`) cannot create a signal named pipe and `git push` fails
with `couldn't create signal pipe, Win32 error 5`. Use the Windows-native
OpenSSH client instead via the `GIT_SSH` environment variable:

```powershell
$env:GIT_SSH = 'C:\Windows\System32\OpenSSH\ssh.exe'
git push origin main
```

`deploy/git-push.ps1` wraps this and forwards arguments to `git push`:

```powershell
pwsh -File deploy/git-push.ps1                 # git push origin main
pwsh -File deploy/git-push.ps1 origin dev      # custom remote/branch
```

Note: `GIT_SSH_COMMAND` and `core.sshCommand` do NOT work here because git
runs them through the MSYS2 shell, which hits the same signal-pipe error.
`GIT_SSH` execs the client directly, so only it works in the sandbox.
