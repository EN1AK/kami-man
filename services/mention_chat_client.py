"""Separate explicit-mention persona calls from the professional Agent client."""
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
import re

import httpx
from services.group_chat_client import GroupReply,PRIVATE
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


async def request_casual(group,key,text,profile,expressions,categories):
    async with httpx.AsyncClient(timeout=55) as client:
        response = await client.post(endpoint("mention-chat"),json=dict(group_id=group,session_id=key,text=text,
            style_profile=profile,expressions=expressions,meme_categories=categories))
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
    if PRIVATE.search(reply) or re.search(r"[@＠]|\[CQ:",reply,re.I):
        raise ValueError("Unsafe mention persona response")
    if not reply and not category:
        raise ValueError("Empty mention persona response")
    return GroupReply(reply,category)


async def clear_sessions(key):
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(endpoint("mention-clear"),json=dict(session_id=key))
        response.raise_for_status()
        if response.json().get("cleared") is not True:
            raise ValueError("Conversation clear failed")
