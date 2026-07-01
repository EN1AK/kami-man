from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.rule import Rule

from services.ygo_rag_api import (
    map_rag_error,
    query_ygo_rag,
)
from services.ygo_rag_messages import build_rag_message_texts, extract_mentioned_question


async def is_group_bot_mention(bot: Bot, event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    mentioned, _ = extract_mentioned_question(event.message, str(bot.self_id))
    return mentioned


rag_qa = on_message(rule=Rule(is_group_bot_mention), priority=20, block=False)

def make_forward_node(user_id: int, nickname: str, message: Message):
    return {
        "type": "node",
        "data": {
            "name": nickname,
            "uin": str(user_id),
            "content": message,
        },
    }


async def send_group_forward_msg(
    bot: Bot,
    event: GroupMessageEvent,
    texts: list[str],
    nickname: str = "游戏王 RAG",
):
    nodes = [
        make_forward_node(
            user_id=int(event.self_id),
            nickname=nickname,
            message=Message(text),
        )
        for text in texts
    ]

    try:
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=nodes,
        )
    except Exception:
        await bot.send(event, "合并转发发送失败，已切换为普通消息发送。")
        for text in texts:
            await bot.send(event, text)


@rag_qa.handle()
async def handle_rag_qa(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return

    mentioned, question = extract_mentioned_question(event.message, str(bot.self_id))
    if not mentioned:
        return

    if not question:
        await bot.send(event, "请在 @Bot 后输入要查询的游戏王问题。")
        return

    try:
        response = await query_ygo_rag(question)
    except Exception as exc:
        await bot.send(event, map_rag_error(exc))
        return

    texts = build_rag_message_texts(question, response)
    if not texts:
        await bot.send(event, "RAG 服务没有返回可发送的回答。")
        return

    await send_group_forward_msg(bot, event, texts)
