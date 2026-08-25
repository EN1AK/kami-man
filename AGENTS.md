# AGENTS.md

Kami Man Bot —— 基于 NoneBot2 + OneBot V11 的 QQ 机器人（游戏王查卡/裁定、MyCard 对战平台、Riftbound 查卡）。

## 从本机 Windows 沙箱推送代码

本机是 Windows DSH 沙箱。Git for Windows 的 MSYS2 子进程（`sh.exe` / `ssh.exe`）在沙箱下无法创建信号命名管道，直接 `git push` 会报：

```text
couldn't create signal pipe, Win32 error 5
```

推送前先切换到 Windows 原生 OpenSSH（直接 exec，不经 MSYS2 shell）：

```powershell
$env:GIT_SSH = 'C:\Windows\System32\OpenSSH\ssh.exe'
git push origin main
```

- 只有 `GIT_SSH` 环境变量可用；`GIT_SSH_COMMAND` 和 `core.sshCommand` 都会走 MSYS2 shell，同样报错。
- 直接 `ssh` / `scp` 到服务器时，用 Windows 原生 OpenSSH（`Get-Command ssh` → `C:\Program Files\OpenSSH\ssh.exe`）即可。

## 部署到服务器

- 服务器：`ubuntu@150.109.237.67`
- 仓库：`/home/ubuntu/qqbot/kami-man`
- Bot 服务：`kami-man.service`（入口 `bot.py`，监听 `0.0.0.0:18080`）

只改 bot 代码时：

```bash
ssh ubuntu@150.109.237.67
cd /home/ubuntu/qqbot/kami-man
git pull --ff-only
python3 -m py_compile <改动的 .py 文件>
sudo systemctl restart kami-man.service
systemctl status kami-man.service --no-pager -l
```

详细部署/RAG 契约见 `deploy/production.md`。

## 文件操作注意

- `write`/`edit` 工具（filesystem 后端）创建的文件，pwsh 侧无法删除（`Remove-Item`、`.NET File.Delete`、`git clean` 都报错），即便属主与当前用户一致。
- 写 `.ps1` 脚本时注释保持纯 ASCII：含全角标点（如 `（）` `：`）或反引号的中文注释会导致脚本解析异常（表现为脚本内 `$env:` 赋值未生效）。
