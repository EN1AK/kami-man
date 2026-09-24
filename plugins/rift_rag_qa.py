from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.rule import Rule

from services.onebot_forward import send_group_forward_nodes
from services.rift_rag_api import map_rift_rag_error, query_rift_rag
from services.rift_rag_messages import (
    build_rift_rag_nodes,
    extract_text_mention_question,
    is_rift_alias_message,
)

EMPTY_QUESTION_TEXT = "请在命令后写下问题内容"
FORWARD_FALLBACK_NOTICE = "合并转发发送失败，已切换为普通消息发送。"


async def is_group_rift_alias(bot: Bot, event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    return is_rift_alias_message(
        event.get_plaintext(),
        event.message,
        str(bot.self_id),
        to_me=event.to_me,
    )


# 优先级低于命令匹配器（on_command 默认 priority=1），/rb 等命令优先处理
rift_rag_qa = on_message(rule=Rule(is_group_rift_alias), priority=20, block=False)


@rift_rag_qa.handle()
async def handle_rift_rag_qa(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return

    matched, question = extract_text_mention_question(event.get_plaintext())
    if not matched:
        return

    if not question:
        await bot.send(event, EMPTY_QUESTION_TEXT)
        return

    try:
        response = await query_rift_rag(question)
    except Exception as exc:
        await bot.send(event, map_rift_rag_error(exc))
        return

    sender_name = None
    if event.sender is not None:
        sender_name = event.sender.card or event.sender.nickname

    nodes = build_rift_rag_nodes(
        question,
        response,
        sender_name=sender_name,
        sender_user_id=event.user_id,
    )

    await send_group_forward_nodes(bot, event, nodes, FORWARD_FALLBACK_NOTICE)
