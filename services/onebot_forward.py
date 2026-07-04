from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message


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
    nickname: str,
    fallback_notice: str,
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
        await bot.send(event, fallback_notice)
        for text in texts:
            await bot.send(event, text)
