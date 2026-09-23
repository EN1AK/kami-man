from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.rule import Rule

from services.onebot_forward import send_group_forward_msg
from services.rift_rag_api import map_rift_rag_error, query_rift_rag
from services.rift_rag_messages import (
    build_rift_rag_message_texts,
    extract_text_mention_question,
    is_rift_alias_message,
)


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
        await bot.send(
            event,
            "请在别名后输入要查询的符文规则问题，例如：符文规则 伤害结算时守卫什么时候生效",
        )
        return

    try:
        response = await query_rift_rag(question)
    except Exception as exc:
        await bot.send(event, map_rift_rag_error(exc))
        return

    texts = build_rift_rag_message_texts(question, response)
    if not texts:
        await bot.send(event, "符文规则服务没有返回可发送的回答。")
        return

    await send_group_forward_msg(
        bot,
        event,
        texts,
        nickname="符文规则 RAG",
        fallback_notice="合并转发发送失败，已切换为普通消息发送。",
    )
