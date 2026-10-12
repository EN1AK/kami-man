from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.rule import Rule

from services.onebot_forward import send_group_forward_msg
from services.ygo_rag_translation_api import (
    map_translation_error,
    translate_with_ygo_rag,
)
from services.ygo_rag_translation_messages import (
    build_translation_message_texts,
    extract_translation_request,
)


async def is_group_translation_command(bot: Bot, event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    mentioned, is_command, _ = extract_translation_request(
        event.message,
        str(bot.self_id),
        plain_text=event.get_plaintext(),
        to_me=event.to_me,
    )
    return mentioned and is_command


ygo_rag_translate = on_message(
    rule=Rule(is_group_translation_command),
    priority=19,
    block=True,
)


@ygo_rag_translate.handle()
async def handle_ygo_rag_translate(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return

    mentioned, is_command, text = extract_translation_request(
        event.message,
        str(bot.self_id),
        plain_text=event.get_plaintext(),
        to_me=event.to_me,
    )
    if not mentioned or not is_command:
        return

    from services.unified_agent import handle_question
    await handle_question(bot,event,"翻译成中文："+text if text else "")
