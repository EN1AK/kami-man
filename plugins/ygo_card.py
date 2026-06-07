from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.params import CommandArg

from services.ygo_api import (
    search_cards,
    format_card_text,
    download_image_base64,
    fetch_card_faqs,
)


ck = on_command("ck", aliases={"查卡"}, priority=5)
card_pic = on_command("查卡图", aliases={"卡图"}, priority=5)
pl = on_command("pl", aliases={"批量查卡"}, priority=5)
ruling = on_command("裁定", aliases={"ruling", "查裁定"}, priority=5)


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
    nickname: str = "kami-man",
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

    img = await download_image_base64(card["id"])
    if img:
        msg += MessageSegment.image(img)

    msg += format_card_text(card)
    return msg


@ck.handle()
async def handle_ck(args: Message = CommandArg()):
    cardname = args.extract_plain_text().strip()

    if not cardname:
        await ck.finish("错误: 请输入卡片名称")

    cards = await search_cards(cardname)

    if not cards:
        await ck.finish(f"未找到卡片: {cardname}")

    msg = await build_card_message(cards[0])
    await ck.finish(msg)


@card_pic.handle()
async def handle_card_pic(args: Message = CommandArg()):
    cardname = args.extract_plain_text().strip()

    if not cardname:
        await card_pic.finish("错误: 请输入卡片名称")

    cards = await search_cards(cardname)

    if not cards:
        await card_pic.finish(f"未找到卡片: {cardname}")

    card = cards[0]
    img = await download_image_base64(card["id"])

    if not img:
        await card_pic.finish(f"找到卡片「{card.get('cn_name', cardname)}」，但图片下载失败。")

    await card_pic.finish(MessageSegment.image(img))


@pl.handle()
async def handle_pl(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    cardname = args.extract_plain_text().strip()

    if not cardname:
        await pl.finish("错误: 请输入卡片名称")

    cards = await search_cards(cardname)

    if not cards:
        await pl.finish(f"未找到卡片: {cardname}")

    cards = cards[:25]

    messages: list[Message] = []

    for card in cards:
        msg = await build_card_message(card)
        messages.append(msg)

    await send_forward_msg(bot, event, messages)


@ruling.handle()
async def handle_ruling(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    cardname = args.extract_plain_text().strip()

    if not cardname:
        await ruling.finish("错误: 请输入卡片名称")

    cards = await search_cards(cardname)

    if not cards:
        await ruling.finish(f"未找到卡片: {cardname}")

    card = cards[0]
    faqs = await fetch_card_faqs(card["id"])

    if not faqs:
        await ruling.finish(f"卡片「{card.get('cn_name', cardname)}」暂无裁定信息")

    messages: list[Message] = []

    header = Message()
    img = await download_image_base64(card["id"])
    if img:
        header += MessageSegment.image(img)
    header += f"{card.get('cn_name', cardname)} 的裁定信息："
    messages.append(header)

    count = 0
    for faq in faqs:
        if count >= 10:
            break

        msg = Message()
        if faq.get("date"):
            msg += f"日期：{faq['date']}\n"
        msg += f"问题：{faq['question']}\n"
        msg += f"答案：{faq['answer']}"

        messages.append(msg)
        count += 1

    if count == 0:
        await ruling.finish(f"卡片「{card.get('cn_name', cardname)}」的裁定信息查询失败")

    if len(faqs) > count:
        messages.append(
            Message(f"该卡片还有 {len(faqs) - count} 条裁定未显示。")
        )

    await send_forward_msg(bot, event, messages)
