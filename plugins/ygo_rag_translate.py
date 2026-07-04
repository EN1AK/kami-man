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

    if not text:
        await bot.send(event, "\u8bf7\u5728 @Bot \u540e\u4f7f\u7528\u201c\u7ffb\u8bd1\u201d\u547d\u4ee4\u5e76\u8f93\u5165\u8981\u7ffb\u8bd1\u7684\u6587\u672c\u3002")
        return

    try:
        response = await translate_with_ygo_rag(text)
    except Exception as exc:
        await bot.send(event, map_translation_error(exc))
        return

    texts = build_translation_message_texts(text, response)
    if not texts:
        await bot.send(event, "\u7ffb\u8bd1\u670d\u52a1\u6ca1\u6709\u8fd4\u56de\u53ef\u53d1\u9001\u7684\u7ed3\u679c\u3002")
        return

    await send_group_forward_msg(
        bot,
        event,
        texts,
        nickname="\u795e\u4eba",
        fallback_notice="\u5408\u5e76\u8f6c\u53d1\u53d1\u9001\u5931\u8d25\uff0c\u5df2\u5207\u6362\u4e3a\u666e\u901a\u6d88\u606f\u53d1\u9001\u3002",
    )
