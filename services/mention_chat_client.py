"""Separate explicit-mention persona calls from the professional Agent client."""
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
import re
import ipaddress
import asyncio

import httpx
from nonebot import logger
from services.group_chat_client import GroupReply,PRIVATE,capture_group_context,remember_bot_context
from services.group_conversation import GroupConversation
from services.group_chat_store import ALLOWED_GROUPS
from services.group_learning import GroupLearningStore
from services.group_memes import MemeLibrary
from services.ygo_rag_agent_api import YgoRagAgentSettings

ROOT = Path(__file__).resolve().parents[1]
learned_store = GroupLearningStore(ROOT/"data/group_chat.db")
mention_memes = MemeLibrary(ROOT/"data/group_memes/deepseek-girl-pack",ROOT/"data/group_chat.db",allowed_groups=None)
private_memes=MemeLibrary(ROOT/"data/group_memes/deepseek-girl-pack",ROOT/"data/private_memes.db",allowed_groups=None)



def endpoint(name):
    parts = urlsplit(YgoRagAgentSettings.from_env().api_url)
    return urlunsplit((parts.scheme,parts.netloc,parts.path.rsplit("/",1)[0]+"/"+name,"",""))


async def resolve_route(text,previous_route="",quoted_route=""):
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.post(endpoint("mention-route"),json=dict(text=text))
        response.raise_for_status()
        route = response.json().get("route")
    if route not in {"casual","professional"}:
        raise ValueError("Invalid mention route")
    return route


def style_context(group,text):
    if group not in ALLOWED_GROUPS:
        return "",[]
    state = learned_store.status(group)
    if not state["collect"]:
        return "",[]
    profile = learned_store.profile(group)
    return profile["summary"],learned_store.retrieve(group,[dict(text=text)])


async def conversation_context(bot,event):
    group=getattr(event,"group_id",None)
    if group not in ALLOWED_GROUPS:return [], ""
    try:
        await capture_group_context(bot,event,learned_store)
        return await asyncio.to_thread(GroupConversation(learned_store).context_with_target,group,event.message_id)
    except Exception as exc:
        logger.warning("Mention group context unavailable ({})",type(exc).__name__)
        return [], ""


async def record_casual_context(bot,event,text,result):
    await remember_bot_context(bot,event,text,result,learned_store)


async def request_casual(group,key,text,profile,expressions,categories,conversation=None,current_message_id=""):
    async with httpx.AsyncClient(timeout=165) as client:
        response = await client.post(endpoint("mention-chat"),json=dict(group_id=group,session_id=key,text=text,
            style_profile=profile,expressions=expressions,meme_categories=categories,group_conversation=conversation or [],
            current_message_id=current_message_id))
        response.raise_for_status()
        data = response.json()
    if data.get("route")=="professional":
        raise ValueError("Unexpected professional route for persona request")
    reply,category = data.get("reply"),data.get("meme_category")
    if data.get("route")!="casual" or not isinstance(reply,str) or len(reply)>2000:
        raise ValueError("Invalid mention persona response")
    reply = reply.strip()
    if not isinstance(category,str) or category not in {x["category"] for x in categories}:
        category = None
    sources=data.get("sources",[])
    body = validated_reply_body(reply,sources,separate=data.get("sources_separate") is True)
    if unsafe_persona_body(body):
        raise ValueError("Unsafe mention persona response")
    if not body and not category:
        raise ValueError("Empty mention persona response")
    return GroupReply(body,category,sources)


def unsafe_persona_body(body):
    # Public documentation can discuss API keys/tokens without revealing a value.
    credential = r'''(?:sk-[A-Za-z0-9_-]{10,}|Bearer\s+[A-Za-z0-9._~-]{10,}|(?:api[_ -]?key|token)["']?\s*[:：=]\s*["']?[A-Za-z0-9._~-]{8,})'''
    if re.search(credential,body,re.I):return True
    checked=re.sub(r'\b(?:api[_ -]?key|token)\b','凭证术语',body,flags=re.I)
    return bool(PRIVATE.search(checked) or re.search(r"[@＠]|\[CQ:",checked,re.I))


def validated_reply_body(reply,sources,*,separate=False):
    """Only the exact backend source footer is exempt from link filtering."""
    if not isinstance(sources,list) or len(sources)>6:
        raise ValueError("Invalid persona sources")
    urls=[]
    for source in sources:
        url=source.get("url") if isinstance(source,dict) else None
        if not isinstance(url,str) or not 1<=len(url)<=400 or any(c.isspace() for c in url) or "[CQ:" in url:
            raise ValueError("Invalid persona source URL")
        try:
            parts=urlsplit(url)
            host=(parts.hostname or "").rstrip('.').lower()
            if parts.scheme not in {'http','https'} or not host or parts.username is not None or parts.password is not None or parts.port not in {None,80,443}:
                raise ValueError("Invalid persona source URL")
            if host in {'localhost','metadata.google.internal'} or host.endswith(('.localhost','.local','.internal','.home','.lan')):
                raise ValueError("Private persona source URL")
            try:address=ipaddress.ip_address(host)
            except ValueError:address=None
            if address is not None and not address.is_global:
                raise ValueError("Private persona source URL")
        except ValueError as exc:
            raise ValueError("Invalid persona source URL") from exc
        if url in urls:raise ValueError("Duplicate persona source URL")
        urls.append(url)
    if not urls or separate:return reply
    footer="\n\n来源：\n"+"\n".join(urls)
    if not reply.endswith(footer):
        raise ValueError("Persona source footer mismatch")
    return reply[:-len(footer)]


async def clear_sessions(key):
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(endpoint("mention-clear"),json=dict(session_id=key))
        response.raise_for_status()
        if response.json().get("cleared") is not True:
            raise ValueError("Conversation clear failed")
