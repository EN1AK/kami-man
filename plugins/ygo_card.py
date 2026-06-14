import re

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

RULINGS_PER_PAGE = 10
PAGE_PATTERN = re.compile(r"^(?:p|page)?(\d+)$|^第(\d+)页$", re.IGNORECASE)


def parse_ruling_args(text: str) -> tuple[str, int]:
    parts = text.rsplit(maxsplit=1)
    if len(parts) != 2:
        return text, 1

    cardname, page_text = parts
    match = PAGE_PATTERN.fullmatch(page_text)
    if not match:
        return text, 1

    page = int(match.group(1) or match.group(2))
    return cardname.strip(), max(page, 1)


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
    async def send_plain_messages():
        await bot.send(event, "合并转发发送失败，已切换为普通消息发送。")
        for msg in messages:
            await bot.send(event, msg)

    nodes = [
        make_forward_node(
            user_id=int(event.self_id),
            nickname=nickname,
            message=msg,
        )
        for msg in messages
    ]

    try:
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
            await send_plain_messages()
    except Exception:
        await send_plain_messages()


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
    query = args.extract_plain_text().strip()

    if not query:
        await ruling.finish("错误: 请输入卡片名称")

    cardname, page = parse_ruling_args(query)

    cards = await search_cards(cardname)

    if not cards:
        await ruling.finish(f"未找到卡片: {cardname}")

    card = cards[0]
    faqs = await fetch_card_faqs(card["id"])

    if not faqs:
        await ruling.finish(f"卡片「{card.get('cn_name', cardname)}」暂无裁定信息")

    total = len(faqs)
    max_page = (total + RULINGS_PER_PAGE - 1) // RULINGS_PER_PAGE
    if page > max_page:
        await ruling.finish(
            f"卡片「{card.get('cn_name', cardname)}」只有 {max_page} 页裁定，请输入 1-{max_page}。"
        )

    start = (page - 1) * RULINGS_PER_PAGE
    end = start + RULINGS_PER_PAGE
    page_faqs = faqs[start:end]

    messages: list[Message] = []

    header = Message(
        f"{card.get('cn_name', cardname)} 的裁定信息（第 {page}/{max_page} 页，共 {total} 条）："
    )
    messages.append(header)

    for faq in page_faqs:
        msg = Message()
        if faq.get("date"):
            msg += f"日期：{faq['date']}\n"
        msg += f"问题：{faq['question']}\n"
        msg += f"答案：{faq['answer']}"

        messages.append(msg)

    if not page_faqs:
        await ruling.finish(f"卡片「{card.get('cn_name', cardname)}」的裁定信息查询失败")

    page_tips = []
    if page > 1:
        page_tips.append(f"上一页：裁定 {cardname} {page - 1}")
    if page < max_page:
        page_tips.append(f"下一页：裁定 {cardname} {page + 1}")
    if page_tips:
        messages.append(Message("\n".join(page_tips)))

    await send_forward_msg(bot, event, messages)
