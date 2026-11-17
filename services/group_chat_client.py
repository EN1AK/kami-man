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
from services.group_conversation import GroupConversation
from services.group_memes import MemeLibrary
from services.ygo_rag_agent_api import YgoRagAgentSettings

COMMAND = re.compile(r"^(?:[/!！]|ck\b|pl\b|查卡|卡图|查裁定|裁定|符文规则|符文裁定|绑定|订阅|我的战绩|随机聊天|群聊采集|群聊风格|群聊学习)", re.I)
PRIVATE = re.compile(r"https?://|www\.|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\d{7,}|(?:密码|口令|验证码|api[_ -]?key|token|住址|身份证|手机号)\s*[:：=]?", re.I)
SPECIALIST = re.compile(r"^/?(?:ck|pl|rbpl|rb|translate)(?=$|[\s:：\u3400-\u9fff])|^/?(?:裁定|翻译|查卡|查价|卡价|规则|符文规则|符文裁定|符文战场规则|卡图翻译)|^(?:用量|清空对话|重置对话|忘记上下文)$",re.I)


def context_text(event,bot_id):
    if getattr(event,"group_id",None) not in ALLOWED_GROUPS or str(event.user_id)==str(bot_id):return None
    if any(seg.type not in {"text","reply","at"} or (seg.type=="at" and str(seg.data.get("qq"))!=str(bot_id)) for seg in event.message):return None
    text=event.get_plaintext().strip()
    if not text or len(text)>3000 or PRIVATE.search(text) or re.search(r"[@＠]|\[CQ:",text) or COMMAND.search(text) or SPECIALIST.search(text):return None
    return text[:500]


def reply_message_id(event):
    reply=getattr(event,"reply",None)
    if reply is not None:
        value=getattr(reply,"message_id",getattr(reply,"id",None))
        if value is not None:return str(value)
    return next((str(seg.data["id"]) for seg in event.message if seg.type=="reply" and "id" in seg.data),"")


async def capture_group_context(bot,event,store):
    text=context_text(event,bot.self_id)
    now=time.time()
    if text is None or (getattr(event,"time",0) and abs(now-event.time)>120):return None
    conversation=GroupConversation(store)
    await asyncio.to_thread(conversation.seed_recent,event.group_id,now)
    parent=reply_message_id(event)
    quoted=getattr(event,"reply",None)
    if quoted and str(getattr(getattr(quoted,"sender",None),"user_id",""))==str(bot.self_id):
        quoted_text=quoted.message.extract_plain_text().strip()
        if quoted_text and not PRIVATE.search(quoted_text) and not re.search(r"[@＠]|\[CQ:",quoted_text):
            await asyncio.to_thread(conversation.remember_legacy_quote,event.group_id,parent,quoted_text)
    await asyncio.to_thread(conversation.record,event.group_id,event.message_id,event.user_id,text,reply_to=parent)
    return text


async def remember_bot_context(bot,event,text,result,store):
    if getattr(event,"group_id",None) not in ALLOWED_GROUPS:return
    if not text or PRIVATE.search(text) or re.search(r"[@＠]|\[CQ:",text):return
    message_id=result.get("message_id") if isinstance(result,dict) else None
    try:
        await asyncio.to_thread(GroupConversation(store).record,event.group_id,message_id,None,text,
            bot=True,reply_to=str(event.message_id))
    except Exception as exc:
        logger.warning("Sent group context not retained ({})",type(exc).__name__)


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
    def __new__(cls, text, meme_category=None, sources=None):
        value = super().__new__(cls,text)
        value.meme_category = meme_category
        value.sources = tuple(sources or ())
        return value


async def generate_reply(group, messages, samples, style_profile="", expressions=None, meme_categories=None, reply_target_id=""):
    settings = YgoRagAgentSettings.from_env()
    parts = urlsplit(settings.api_url)
    endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/",1)[0]+"/group-chat", "", ""))
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(endpoint, json={"group_id": group, "messages": messages, "style_samples": samples, "style_profile": style_profile, "expressions":expressions or [],"meme_categories":meme_categories or [],"reply_target_id":reply_target_id})
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

    async def capture_context(self,bot,event):
        try:return await capture_group_context(bot,event,self.store)
        except Exception as exc:logger.warning("Group context capture skipped ({})",type(exc).__name__)

    async def observe(self, bot, event):
        text = await self.capture_context(bot,event)
        if text is None:
            return
        now = time.time()
        event_time = getattr(event, "time", now)
        # Do not replay backlogged OneBot events after reconnecting.
        if event_time and abs(now-event_time) > 120:
            return
        try:
            learning_text=clean_text(event,bot.self_id)
            if learning_text is not None:
                await asyncio.to_thread(self.store.record,event.group_id,event.message_id,event.user_id,learning_text,now)
            addressed=getattr(event,"to_me",False) or any(seg.type=="at" for seg in event.message)
            if addressed:return
            conversation=GroupConversation(self.store)
            inserted=await asyncio.to_thread(conversation.claim_random,event.group_id,event.message_id)
            if not inserted or event.group_id in self.inflight or self.draw() >= PROBABILITY:
                return
            checkpoint = await asyncio.to_thread(self.store.reply_checkpoint,event.group_id)
            context_checkpoint=await asyncio.to_thread(conversation.checkpoint,event.group_id)
            messages,target_id=await asyncio.to_thread(conversation.context_with_target,event.group_id,event.message_id,now)
            _,samples=await asyncio.to_thread(self.store.context,event.group_id,now)
            if len(messages) < 4 or not target_id:
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
                reply = await generate_reply(event.group_id, messages, samples[:8-len(expressions)], profile["summary"], expressions, categories, target_id)
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
                if await asyncio.to_thread(self.store.reply_checkpoint,event.group_id)!=checkpoint or await asyncio.to_thread(conversation.checkpoint,event.group_id)!=context_checkpoint:
                    return
                state = await asyncio.to_thread(self.store.status,event.group_id)
                if not state["collect"] or not state["chat"] or time.time()-now>45:
                    return
                message = Message(MessageSegment.reply(event.message_id))
                if reply:
                    message += MessageSegment.text(reply)
                if image:
                    message += MessageSegment.image(image.image)
                result=await bot.send(event, message)
                await remember_bot_context(bot,event,str(reply) or "[机器人发送了表情，未读取图片内容]",result,self.store)
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
