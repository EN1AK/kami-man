from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.params import CommandArg

from services.riftbound_api import (
    download_image_base64,
    format_riftbound_card,
    search_riftbound_cards,
)


rb = on_command("rb", aliases={"符文查卡", "符文"}, priority=5)
rb_pl = on_command("rbpl", aliases={"符文批量", "符文批量查卡"}, priority=5)


def make_forward_node(user_id: int, nickname: str, message: Message):
    return {
        "type": "node",
        "data": {
            "name": nickname,
            "uin": str(user_id),
            "content": message,
        },
    }


async def send_forward_msg(
    bot: Bot,
    event: MessageEvent,
    messages: list[Message],
    nickname: str = "符文战场查卡",
):
    nodes = [
        make_forward_node(
            user_id=int(event.self_id),
            nickname=nickname,
            message=msg,
        )
        for msg in messages
    ]

    if isinstance(event, GroupMessageEvent):
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=nodes,
        )
    elif isinstance(event, PrivateMessageEvent):
        await bot.call_api(
            "send_private_forward_msg",
            user_id=event.user_id,
            messages=nodes,
        )
    else:
        await bot.send(event, "当前消息类型暂不支持合并转发。")


async def build_card_message(card: dict) -> Message:
    msg = Message()

    img = await download_image_base64(card.get("image_url", ""))
    if img:
        msg += MessageSegment.image(img)

    msg += format_riftbound_card(card)
    return msg


@rb.handle()
async def handle_rb(args: Message = CommandArg()):
    keyword = args.extract_plain_text().strip()

    if not keyword:
        await rb.finish("错误: 请输入卡片名称，例如：rb 金克丝")

    cards = search_riftbound_cards(keyword, limit=10)

    if not cards:
        await rb.finish(f"未找到符文战场卡片: {keyword}")

    msg = await build_card_message(cards[0])
    await rb.finish(msg)



@rb_pl.handle()
async def handle_rb_pl(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    keyword = args.extract_plain_text().strip()

    if not keyword:
        await rb_pl.finish("错误: 请输入卡片名称，例如：rbpl 金克丝")

    cards = search_riftbound_cards(keyword, limit=8)

    if not cards:
        await rb_pl.finish(f"未找到符文战场卡片: {keyword}")

    messages = []

    for card in cards:
        msg = await build_card_message(card)
        messages.append(msg)

    await send_forward_msg(bot, event, messages)