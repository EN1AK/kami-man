"""Forward public Bilibili updates and summarize linked videos on request."""

import asyncio
from contextlib import AsyncExitStack, closing
from datetime import datetime, timezone
from functools import lru_cache
import os
from pathlib import Path
import re
import sqlite3
from subprocess import TimeoutExpired
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot_plugin_apscheduler import scheduler
from scripts.bilibili_link_preview import VIDEO_ID, summarize_video, video_id


GROUP_ID = 819151070
LUKE = 3706939584285247
MINAZUKI = 1958342
LIVE_CREATORS = (LUKE, MINAZUKI)
# UID -> (display name, follow dynamics)
CREATORS = {
    LUKE: ("卢克TCG", True),
    23344361: ("Nron2093", True),
    6267249: ("水桥卡牌", True),
    599193: ("Luminous_J", False),
    MINAZUKI: ("水无月菌", True),
    1955897084: ("鸣潮", True),
    3546795158276766: ("符文战场", True),
    519200091: ("游戏王卡片游戏", True),
}
STATE = Path(__file__).resolve().parents[1] / "data" / "bilibili_subscriptions.sqlite3"
API = "https://api.bilibili.com"
LIVE_API = "https://api.live.bilibili.com"
ERRORS = (httpx.HTTPError, KeyError, TypeError, ValueError)
DYNAMIC_TYPES = {"DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_DRAW", "DYNAMIC_TYPE_ARTICLE", "DYNAMIC_TYPE_FORWARD"}
REPLAY_TITLE = re.compile(r"直播[\s·:：/／_-]*(?:回放|录播|录像|实录|存档|记录)|录播|^[\s【〖\[（(]*回放")
delivery_lock = asyncio.Lock()
summary_lock = asyncio.Lock()
VIDEO_LINK = re.compile(rf"https?://(?:www\.)?bilibili\.com/video/(?:{VIDEO_ID.pattern})/?(?:\?p=[0-9]+)?")
verified_sources = set()
group_verified = False


def open_state():
    STATE.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(STATE)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS activation (group_id INTEGER PRIMARY KEY, started INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS creator_activation (
            group_id INTEGER NOT NULL, uid INTEGER NOT NULL, started INTEGER NOT NULL,
            PRIMARY KEY (group_id, uid)
        );
        CREATE TABLE IF NOT EXISTS checkpoint (
            group_id INTEGER NOT NULL, uid INTEGER NOT NULL, source TEXT NOT NULL, checked INTEGER NOT NULL,
            PRIMARY KEY (group_id, uid, source)
        );
        CREATE TABLE IF NOT EXISTS delivery (
            group_id INTEGER NOT NULL, event_id TEXT NOT NULL, published INTEGER NOT NULL,
            url TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
            image TEXT NOT NULL DEFAULT '', preview TEXT NOT NULL DEFAULT '', PRIMARY KEY (group_id, event_id)
        );
    """)
    with db:
        db.execute("BEGIN IMMEDIATE")
        columns = {column[1] for column in db.execute("PRAGMA table_info(delivery)")}
        if "image" not in columns:
            db.execute("ALTER TABLE delivery ADD COLUMN image TEXT NOT NULL DEFAULT ''")
        if "preview" not in columns:
            db.execute("ALTER TABLE delivery ADD COLUMN preview TEXT NOT NULL DEFAULT ''")
        now = int(time.time())
        db.execute("INSERT OR IGNORE INTO activation VALUES (?, ?)", (GROUP_ID, now))
        db.execute(
            "INSERT OR IGNORE INTO creator_activation SELECT DISTINCT checkpoint.group_id, checkpoint.uid,"
            " activation.started FROM checkpoint JOIN activation USING (group_id) WHERE checkpoint.group_id = ?",
            (GROUP_ID,),
        )
        db.executemany(
            "INSERT OR IGNORE INTO creator_activation VALUES (?, ?, ?)",
            ((GROUP_ID, uid, now) for uid in CREATORS),
        )
    return db


async def get_data(client, host, path, params, referer):
    headers = {"Referer": referer}
    if referer.startswith("https://space.bilibili.com/"):
        headers["Origin"] = "https://space.bilibili.com"
    response = await client.get(host + path, params=params, headers=headers)
    response.raise_for_status()
    result = response.json()
    if result["code"] != 0:
        raise ValueError(f"{path} 返回 {result['code']}")
    return result["data"]


def cover_url(value):
    if not isinstance(value, str) or not value:
        return ""
    try:
        url = urlsplit("https:" + value if value.startswith("//") else value)
        if (url.scheme in {"http", "https"} and (url.hostname or "").endswith(".hdslb.com")
                and url.username is None and url.password is None and url.port in {None, 443}):
            return urlunsplit(url._replace(scheme="https"))
    except ValueError:
        pass
    return ""


def dynamic_preview(uid, modules):
    dynamic = modules.get("module_dynamic") or {}
    major = dynamic.get("major") or {}
    opus = major.get("opus") or {}
    draw = dynamic.get("dyn_draw") or major.get("draw") or {}
    description = modules.get("module_desc") or dynamic.get("desc") or {}
    text = description.get("text") or (opus.get("summary") or {}).get("text") or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    excerpt = "\n".join(lines[:2])
    if len(excerpt) > 150 or len(lines) > 2:
        excerpt = excerpt[:150].rstrip() + "…"
    parts = [f"{CREATORS[uid][0]}的动态", opus.get("title"), excerpt]
    images = draw.get("items") or opus.get("pics") or []
    image = cover_url(images[0].get("src") or images[0].get("url")) if images else ""
    return "\n".join(part for part in parts if part), image


async def videos(client, uid, cutoff):
    events = []
    for page in range(1, 6):
        data = await get_data(client, API, "/x/series/recArchivesByKeywords",
                              {"mid": uid, "pn": page, "ps": 30, "keywords": "", "orderby": "senddate"},
                              f"https://space.bilibili.com/{uid}/dynamic")
        rows = data["archives"]
        for row in rows:
            bvid = row["bvid"]
            title = row.get("title")
            if title and not REPLAY_TITLE.search(title) and re.fullmatch(r"BV[A-Za-z0-9]{10}", bvid):
                aid = int(row["aid"])
                events.append((f"video:{aid}", int(row["pubdate"]), f"https://www.bilibili.com/video/{bvid}/",
                               cover_url(row.get("pic")), ""))
        if len(rows) < 30 or int(rows[-1]["pubdate"]) < cutoff:
            break
    else:
        raise ValueError("投稿过多，本轮未推进检查进度")
    return events


async def dynamics(client, uid, cutoff):
    events = []
    cursor = ""
    for _ in range(5):
        params = {"host_mid": uid, "offset": cursor} if cursor else {"host_mid": uid}
        data = await get_data(client, API, "/x/polymer/web-dynamic/desktop/v1/feed/space",
                              params, f"https://space.bilibili.com/{uid}/dynamic")
        if data.get("err_msg"):
            raise ValueError(data["err_msg"])
        if not cursor and not data["items"]:
            raise ValueError("已知有历史动态的账号返回了空列表")
        timestamps = []
        for row in data["items"] or []:
            modules = row["modules"]
            if isinstance(modules, list):
                modules = {key: value for module in modules for key, value in module.items() if key != "module_type"}
            author = modules.get("module_author") or {}
            published = int(author.get("pub_ts") or 0)
            if published:
                timestamps.append(published)
            if not published or int(author.get("mid") or uid) != uid:
                continue
            if row["type"] == "DYNAMIC_TYPE_AV":
                aid = int((row.get("basic") or {}).get("rid_str") or 0)
                dynamic = modules.get("module_dynamic") or {}
                archive = dynamic.get("dyn_archive") or (dynamic.get("major") or {}).get("archive") or {}
                title = archive.get("title")
                if aid and title and not REPLAY_TITLE.search(title):
                    bvid = archive.get("bvid") or ""
                    video_id = bvid if re.fullmatch(r"BV[A-Za-z0-9]{10}", bvid) else f"av{aid}"
                    events.append((f"video:{aid}", published, f"https://www.bilibili.com/video/{video_id}/",
                                   cover_url(archive.get("cover")), ""))
                continue
            if not CREATORS[uid][1] or row["type"] not in DYNAMIC_TYPES:
                continue
            dynamic_id = row["id_str"]
            if re.fullmatch(r"[0-9]+", dynamic_id):
                preview, image = dynamic_preview(uid, modules)
                events.append((f"dynamic:{dynamic_id}", published, f"https://t.bilibili.com/{dynamic_id}", image, preview))
        next_cursor = data.get("offset")
        if not data.get("has_more") or not next_cursor or next_cursor == cursor:
            break
        if timestamps and timestamps[-1] < cutoff:
            break
        cursor = next_cursor
    else:
        raise ValueError("动态过多，本轮未推进检查进度")
    return events


async def livestream(client, uid, cutoff):
    data = await get_data(client, LIVE_API, "/room/v1/Room/get_status_info_by_uids",
                          {"uids[]": uid}, "https://live.bilibili.com/")
    room = data[str(uid)]
    if int(room["live_status"]) != 1:
        return []
    room_id = int(room["room_id"])
    started = int(room.get("live_time") or 0)
    if room_id <= 0 or started <= 0:
        raise ValueError("直播中，但接口缺少房间号或开播时间")
    return [(f"live:{room_id}:{started}", started, f"https://live.bilibili.com/{room_id}", "", "")]


async def collect(sources):
    failed = []
    async with AsyncExitStack() as resources:
        db = resources.enter_context(closing(open_state()))
        client = await resources.enter_async_context(httpx.AsyncClient(
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        ))
        starts = dict(db.execute("SELECT uid, started FROM creator_activation WHERE group_id = ?", (GROUP_ID,)))
        for uid, fetch in sources:
            try:
                checked = int(time.time())
                started = starts[uid]
                key = (uid, fetch.__name__)
                previous = db.execute(
                    "SELECT checked FROM checkpoint WHERE group_id = ? AND uid = ? AND source = ?",
                    (GROUP_ID, *key),
                ).fetchone()
                cutoff = max(started, previous[0] - 3600) if previous else started
                events = await fetch(client, uid, cutoff)
                with db:
                    db.executemany(
                        "INSERT INTO delivery (group_id, event_id, published, url, image, preview) VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(group_id, event_id) DO UPDATE SET "
                        "image = COALESCE(NULLIF(delivery.image, ''), excluded.image), "
                        "preview = COALESCE(NULLIF(delivery.preview, ''), excluded.preview) "
                        "WHERE delivery.sent = 0 AND ((delivery.image = '' AND excluded.image != '') "
                        "OR (delivery.preview = '' AND excluded.preview != ''))",
                        ((GROUP_ID, event_id, published, url, image, preview)
                         for event_id, published, url, image, preview in events
                         if published >= started),
                    )
                    db.execute("INSERT OR REPLACE INTO checkpoint VALUES (?, ?, ?, ?)", (GROUP_ID, *key, checked))
                if key not in verified_sources:
                    logger.info("B站订阅读取成功 {} {} （{} 条）", CREATORS[uid][0], fetch.__name__, len(events))
                    verified_sources.add(key)
            except ERRORS as exc:
                logger.warning("B站订阅读取失败 {} {}: {}", CREATORS[uid][0], fetch.__name__, exc)
                failed.append((uid, fetch))
            if len(sources) > 1:
                await asyncio.sleep(1)
    return failed


async def send_link(bot, event_id, url, image, preview):
    text = f"{preview}\n{url}" if preview else url
    image = cover_url(image)
    if event_id.startswith(("video:", "dynamic:")) and image:
        try:
            await bot.call_api("send_group_msg", group_id=GROUP_ID, message=[
                {"type": "image", "data": {"file": image}},
                {"type": "text", "data": {"text": "\n" + text}},
            ])
            return
        except ActionFailed:
            logger.warning("B站订阅图片发送被拒绝，改发文字 {}", event_id)
    await bot.call_api("send_group_msg", group_id=GROUP_ID, message=[{"type": "text", "data": {"text": text}}])


async def deliver():
    global group_verified
    async with delivery_lock:
        try:
            bot = get_bot()
        except ValueError:
            return
        if not group_verified:
            try:
                group = await bot.call_api("get_group_info", group_id=GROUP_ID, no_cache=True)
                if int(group["group_id"]) != GROUP_ID:
                    raise ValueError("群号与配置不一致")
            except Exception as exc:
                logger.warning("B站订阅无法确认目标群 {}: {}", GROUP_ID, type(exc).__name__)
                return
            logger.info("B站订阅目标群 {} 已确认", GROUP_ID)
            group_verified = True
        with closing(open_state()) as db:
            pending = db.execute(
                "SELECT event_id, url, image, preview FROM delivery "
                "WHERE group_id = ? AND sent = 0 ORDER BY published LIMIT 10",
                (GROUP_ID,),
            ).fetchall()
            for event_id, url, image, preview in pending:
                try:
                    await send_link(bot, event_id, url, image, preview)
                except Exception as exc:
                    logger.warning("B站订阅发送失败 {}: {}", event_id, type(exc).__name__)
                    return
                with db:
                    db.execute("UPDATE delivery SET sent = 1 WHERE group_id = ? AND event_id = ?", (GROUP_ID, event_id))
                await asyncio.sleep(1)


def is_summary_request(event: GroupMessageEvent) -> bool:
    return (event.group_id == GROUP_ID and event.reply is not None
            and event.get_plaintext().strip() == "总结一下")


video_summary = on_message(rule=is_summary_request, priority=4, block=True)


@lru_cache(maxsize=64)
def get_video_summary(ident, page):
    with httpx.Client(timeout=25) as client:
        return summarize_video(client, ident, page)


@video_summary.handle()
async def handle_video_summary(event: GroupMessageEvent):
    quoted = event.reply.message.extract_plain_text()
    link = VIDEO_LINK.search(quoted)
    if not link:
        await video_summary.finish("请回复一条带 B 站视频链接的消息，再发「总结一下」。")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        await video_summary.finish("视频总结还未配置 DeepSeek 凭证。")
    if summary_lock.locked():
        await video_summary.finish("正在总结另一条视频，稍后再试。")
    async with summary_lock:
        try:
            ident, page = video_id(link.group())
            if page < 1:
                raise ValueError("分 P 无效")
            summary = await asyncio.to_thread(get_video_summary, ident, page)
        except (*ERRORS, OSError, IndexError, TimeoutExpired) as exc:
            logger.warning("B站视频总结失败 {}", type(exc).__name__)
            await video_summary.finish("暂时没能读取或总结这条视频，稍后可以再试。")
    await video_summary.finish(MessageSegment.reply(event.message_id) + MessageSegment.text(summary))


@scheduler.scheduled_job("interval", minutes=15, id="bilibili_posts", max_instances=1, coalesce=True,
                         next_run_time=datetime.now(timezone.utc))
async def poll_posts():
    # The dynamic feed also surfaces video posts when the archive list is temporarily unavailable.
    failed = await collect([(uid, fetch) for uid in CREATORS for fetch in (videos, dynamics)])
    await deliver()
    if failed:
        await asyncio.sleep(15)
        await collect(failed)
        await deliver()


@scheduler.scheduled_job("interval", minutes=2, id="bilibili_live", max_instances=1, coalesce=True,
                         next_run_time=datetime.now(timezone.utc))
async def poll_live():
    await collect([(uid, livestream) for uid in LIVE_CREATORS])
    await deliver()
