import asyncio
import os
import sqlite3
from dataclasses import replace

import httpx
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.rule import Rule

from services.onebot_forward import send_group_forward_nodes
from services.agent_usage import is_exempt, usage_store
from services.rift_rag_api import RiftRagSettings, map_rift_rag_error, query_rift_rag
from services.ygo_rag_messages import chunk_text, extract_rag_question
from services.rift_rag_messages import (
    build_rift_rag_nodes,
    extract_text_mention_question,
    get_text_mention_aliases,
    is_rift_alias_message,
)

EMPTY_QUESTION_TEXT = "请在命令后写下问题内容"
FORWARD_FALLBACK_NOTICE = "合并转发发送失败，已切换为普通消息发送。"


def dedicated_question(bot, event):
    mentioned, text = extract_rag_question(event.message, str(bot.self_id),
                                          plain_text=event.get_plaintext(), to_me=event.to_me)
    aliases = sorted({*get_text_mention_aliases(), "符文裁定查询", "符文战场规则"}, key=len, reverse=True)
    return extract_text_mention_question(text if mentioned else event.get_plaintext(), aliases)


async def is_group_rift_alias(bot: Bot, event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if os.getenv("RIFT_RULING_BASE_URL"):
        return dedicated_question(bot, event)[0]
    return is_rift_alias_message(
        event.get_plaintext(),
        event.message,
        str(bot.self_id),
        to_me=event.to_me,
    )


# 优先级低于命令匹配器（on_command 默认 priority=1），/rb 等命令优先处理
rift_rag_qa = on_message(rule=Rule(is_group_rift_alias), priority=4, block=True)


@rift_rag_qa.handle()
async def handle_rift_rag_qa(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return

    base = os.getenv("RIFT_RULING_BASE_URL")
    matched, question = (dedicated_question(bot, event) if base
                         else extract_text_mention_question(event.get_plaintext()))
    if not matched:
        return

    if not base:
        from services.unified_agent import handle_question
        return await handle_question(bot, event, "符文战场规则：" + question if question else "")
    if not question or len(question) > 8000:
        await rift_rag_qa.finish("请发送 符文裁定 问题，最多 8000 字。")
    try:
        ticket = await asyncio.to_thread(usage_store.reserve, event.user_id, exempt=is_exempt(event.user_id))
    except (sqlite3.Error, OSError):
        await rift_rag_qa.finish("用量记录暂时不可用，请稍后再试。")
    if ticket is None:
        await rift_rag_qa.finish("今天的问答额度已用完。发送 @神人 用量 可查看记录。")
    try:
        settings = replace(RiftRagSettings.from_env(), base_url=base)
        result = await query_rift_rag(question, settings)
        nodes = []
        for node in build_rift_rag_nodes(question, result, sender_name="符文裁定", sender_user_id=bot.self_id):
            for text in chunk_text(node["data"]["content"]):
                nodes.append({**node, "data": {**node["data"], "content": Message(MessageSegment.text(text))}})
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Rift ruling failed ({})", type(exc).__name__)
        await asyncio.to_thread(usage_store.refund, ticket)
        await rift_rag_qa.finish(map_rift_rag_error(exc))
    await send_group_forward_nodes(bot, event, nodes, FORWARD_FALLBACK_NOTICE)
