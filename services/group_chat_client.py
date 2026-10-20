"""Ordinary-message capture and bounded, opt-in group chatter."""
import asyncio
from pathlib import Path
import random
import re
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from services.group_chat_store import ALLOWED_GROUPS, PROBABILITY
from services.group_learning import GroupLearningStore
from services.group_memes import MemeLibrary
from services.ygo_rag_agent_api import YgoRagAgentSettings

COMMAND = re.compile(r"^(?:[/!！]|ck\b|pl\b|查卡|卡图|查裁定|裁定|符文规则|符文裁定|绑定|订阅|我的战绩|随机聊天|群聊采集|群聊风格|群聊学习)", re.I)
PRIVATE = re.compile(r"https?://|www\.|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\d{7,}|(?:密码|口令|验证码|api[_ -]?key|token|住址|身份证|手机号)\s*[:：=]?", re.I)


def clean_text(event, bot_id):
    if event.group_id not in ALLOWED_GROUPS or str(event.user_id) == str(bot_id):
        return None
    if getattr(event, "to_me", False) or any(seg.type != "text" for seg in event.message):
        return None
    text = event.get_plaintext().strip()
    if not 2 <= len(text) <= 500 or text.startswith(("@", "＠")) or "[CQ:" in text or COMMAND.search(text) or PRIVATE.search(text):
        return None
    return text


class GroupReply(str):
    def __new__(cls, text, meme_category=None):
        value = super().__new__(cls,text)
        value.meme_category = meme_category
        return value


async def generate_reply(group, messages, samples, style_profile="", expressions=None, meme_categories=None):
    settings = YgoRagAgentSettings.from_env()
    parts = urlsplit(settings.api_url)
    endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/",1)[0]+"/group-chat", "", ""))
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(endpoint, json={"group_id": group, "messages": messages, "style_samples": samples, "style_profile": style_profile, "expressions":expressions or [],"meme_categories":meme_categories or []})
        response.raise_for_status()
        data = response.json()
    reply = data.get("reply")
    if not isinstance(reply, str) or len(reply) > 100:
        raise ValueError("Invalid group reply")
    reply = reply.strip()
    if PRIVATE.search(reply) or re.search(r"[@＠]|\[CQ:",reply,re.I):
        return GroupReply("")
    category = data.get("meme_category")
    allowed = {item["category"] for item in (meme_categories or [])}
    if not isinstance(category,str) or category not in allowed:
        category = None
    return GroupReply(reply,category)


class GroupChatService:
    def __init__(self, store, *, draw=random.random, meme_library=None):
        self.store = store
        self.draw = draw
        self.inflight = set()
        self.meme_library = meme_library

    async def observe(self, bot, event):
        text = clean_text(event, bot.self_id)
        if text is None:
            return
        now = time.time()
        event_time = getattr(event, "time", now)
        # Do not replay backlogged OneBot events after reconnecting.
        if event_time and abs(now-event_time) > 120:
            return
        try:
            inserted = await asyncio.to_thread(self.store.record, event.group_id, event.message_id, event.user_id, text, now)
            if not inserted or event.group_id in self.inflight or self.draw() >= PROBABILITY:
                return
            checkpoint = await asyncio.to_thread(self.store.reply_checkpoint,event.group_id)
            messages, samples = await asyncio.to_thread(self.store.context, event.group_id, now)
            if len(messages) < 4:
                return
            day = await asyncio.to_thread(self.store.reserve, event.group_id, now)
            if day is None:
                return
            self.inflight.add(event.group_id)
            try:
                profile = await asyncio.to_thread(self.store.profile, event.group_id)
                expressions = await asyncio.to_thread(self.store.retrieve,event.group_id,messages,now)
                categories = []
                if self.meme_library:
                    try:
                        categories = await asyncio.to_thread(self.meme_library.categories,event.group_id)
                    except Exception as exc:
                        logger.warning("Group meme catalog unavailable ({})",type(exc).__name__)
                reply = await generate_reply(event.group_id, messages, samples[:8-len(expressions)], profile["summary"], expressions, categories)
                category = getattr(reply,"meme_category",None)
                state = await asyncio.to_thread(self.store.status, event.group_id)
                # Recheck admin switches after the model returns, before sending anything.
                if not (reply or category) or not state["collect"] or not state["chat"] or time.time()-now > 45:
                    return
                if reply and not await asyncio.to_thread(self.store.reply_allowed,event.group_id,checkpoint,reply):
                    return
                image = None
                if category and self.meme_library:
                    try:
                        image = await asyncio.to_thread(self.meme_library.reserve,event.group_id,category)
                    except Exception as exc:
                        logger.warning("Group meme selection skipped ({})",type(exc).__name__)
                if not reply and image is None:
                    return
                # Selection can involve file IO: recheck the source epoch/context afterwards.
                if await asyncio.to_thread(self.store.reply_checkpoint,event.group_id)!=checkpoint:
                    return
                state = await asyncio.to_thread(self.store.status,event.group_id)
                if not state["collect"] or not state["chat"] or time.time()-now>45:
                    return
                message = Message(MessageSegment.text(reply)) if reply else Message()
                if image:
                    message += MessageSegment.image(image.image)
                await bot.send(event, message)
                await asyncio.to_thread(self.store.sent, event.group_id, day)
                if reply:
                    await asyncio.to_thread(self.store.record_reply,event.group_id,str(reply))
            finally:
                self.inflight.discard(event.group_id)
        except Exception as exc:
            # Never log raw group messages, model prompts, or identifiers.
            logger.warning("Group chat skipped ({})", type(exc).__name__)


store = GroupLearningStore(Path(__file__).resolve().parents[1] / "data/group_chat.db")
meme_library = MemeLibrary(Path(__file__).resolve().parents[1]/"data/group_memes/deepseek-girl-pack",store.path)
service = GroupChatService(store,meme_library=meme_library)
