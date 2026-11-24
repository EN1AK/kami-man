"""Deliver recorded group chat reasoning independently from normal bot replies."""
import asyncio
from contextlib import closing, suppress
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import time

from nonebot import get_bots, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from services.onebot_forward import make_forward_node


CHINA = timezone(timedelta(hours=8))
ROUTE_LABELS = {"chat": "随机接话", "mention_chat": "群内 @", "mention_repair": "群内 @ 格式重试"}
_worker = None


def read_pending(path):
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        return db.execute(
            "SELECT id,created,route,content FROM chat_reasoning "
            "WHERE sent IS NULL AND created >= ? ORDER BY id LIMIT 4",
            (time.time() - 7 * 86400,),
        ).fetchall()


def mark_sent(path, row_id):
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1)) as db, db:
        db.execute("UPDATE chat_reasoning SET sent=? WHERE id=?", (time.time(), row_id))


async def relay_once(bot, path, group):
    for row_id, created, route, content in await asyncio.to_thread(read_pending, path):
        when = datetime.fromtimestamp(created, CHINA).strftime("%m-%d %H:%M:%S")
        label = ROUTE_LABELS.get(route, "群聊")
        parts = [f"DeepSeek 思考记录 #{row_id} · {label} · {when}"]
        parts.extend(content[i:i + 600] for i in range(0, len(content), 600))
        nodes = [make_forward_node(int(bot.self_id), "思考记录", Message(MessageSegment.text(part)))
                 for part in parts]
        await bot.call_api("send_group_forward_msg", group_id=group, messages=nodes)
        await asyncio.to_thread(mark_sent, path, row_id)


async def relay_loop(path, group):
    while True:
        try:
            bot = next((bot for bot in get_bots().values() if isinstance(bot, Bot)), None)
            if bot is not None:
                await relay_once(bot, path, group)
        except Exception as exc:
            logger.warning("Chat reasoning relay failed ({})", type(exc).__name__)
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(10)


@get_driver().on_startup
async def start_relay():
    global _worker
    path = os.getenv("CHAT_REASONING_DB")
    group = os.getenv("CHAT_REASONING_GROUP", "")
    if path and group.isascii() and group.isdecimal() and int(group) > 0:
        _worker = asyncio.create_task(relay_loop(Path(path), int(group)))


@get_driver().on_shutdown
async def stop_relay():
    if _worker is not None:
        _worker.cancel()
        with suppress(asyncio.CancelledError):
            await _worker
