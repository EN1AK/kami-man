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

    await send_group_forward_nodes(bot, event, nodes, fallback_notice)


async def send_group_forward_nodes(
    bot: Bot,
    event: GroupMessageEvent,
    nodes: list[dict],
    fallback_notice: str,
):
    """发送合并转发节点；仅当合并转发 API 失败时退回普通消息逐条发送。"""
    try:
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=nodes,
        )
    except Exception:
        await bot.send(event, fallback_notice)
        for node in nodes:
            if not isinstance(node, dict):
                continue
            content = (node.get("data") or {}).get("content")
            if content is None:
                continue
            await bot.send(event, content)
