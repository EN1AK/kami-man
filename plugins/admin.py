import base64
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from nonebot.exception import FinishedException
from nonebot import on_command
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.params import CommandArg



PROJECT_ROOT = Path(__file__).resolve().parent.parent
HELP_MD = PROJECT_ROOT / "assets" / "help.md"
HELP_IMAGE = PROJECT_ROOT / "assets" / "help.png"
RENDER_SCRIPT = PROJECT_ROOT / "assets" / "render_help.py"
# Linux 服务器上的 systemd 服务名
SERVICE_NAME = "kami-man"


help_cmd = on_command("帮助", aliases={"help", "菜单"}, priority=5)


@help_cmd.handle()
async def handle_help():
    try:
        if not HELP_IMAGE.exists() or HELP_MD.stat().st_mtime > HELP_IMAGE.stat().st_mtime:
            subprocess.run(
                [sys.executable, str(RENDER_SCRIPT)],
                cwd=PROJECT_ROOT,
                timeout=20,
                check=True,
            )

        image = base64.b64encode(HELP_IMAGE.read_bytes()).decode("utf-8")
        await help_cmd.finish(MessageSegment.image(f"base64://{image}"))

    except FinishedException:
        raise

    except Exception as e:
        await help_cmd.finish(f"帮助图生成失败：{e}")

reload_cmd = on_command("重载插件", aliases={"更新代码", "更新插件", "reload"}, permission=SUPERUSER, priority=1)


@reload_cmd.handle()
async def handle_reload(args: Message = CommandArg()):
    mode = args.extract_plain_text().strip()

    await reload_cmd.send("开始从 Git 拉取最新代码...")

    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="ignore",
        )

        output = (result.stdout or "") + (result.stderr or "")

        if result.returncode != 0:
            await reload_cmd.finish(f"Git 拉取失败：\n{output}")

        await reload_cmd.send(f"Git 拉取完成：\n{output[-1000:]}")

        if mode == "不重启":
            await reload_cmd.finish("已更新代码，但未重启。")

        await reload_cmd.send("准备重启 Bot 服务...")

        subprocess.Popen(
            ["sudo", "systemctl", "restart", SERVICE_NAME],
            cwd=PROJECT_ROOT,
        )

        await reload_cmd.finish("已发送重启命令，Bot 即将重启。")

    except subprocess.TimeoutExpired:
        await reload_cmd.finish("Git 拉取超时。")
    except Exception as e:
        await reload_cmd.finish(f"重载失败：{e}")
