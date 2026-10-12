"""Riftbound card commands; keep the broad 符文 alias free for rules Q&A."""
import asyncio
import logging

import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from services.onebot_forward import make_forward_node, send_group_forward_nodes
from services.riftbound_api import (
    card_image, format_candidates, format_riftbound_card, search_riftbound_cards,
)

logger = logging.getLogger(__name__)
rb = on_command("rb", aliases={"符文查卡"}, priority=5, block=True)
rb_pl = on_command("rbpl", aliases={"符文批量", "符文批量查卡"}, priority=5, block=True)
BATCH_LIMIT = 10


async def lookup(keyword: str) -> list[dict] | None:
    try:
        return await asyncio.to_thread(search_riftbound_cards, keyword, BATCH_LIMIT + 1)
    except Exception as exc:
        logger.exception("Riftbound card database unavailable: %s", exc)
        return None


async def build_card_message(card: dict, client: httpx.AsyncClient | None = None) -> Message:
    image, language = await card_image(card, client)
    message = Message()
    if image:
        message += MessageSegment.image(image)
    if language == "en":
        message += MessageSegment.text("（使用英文卡图）\n")
    elif not image:
        message += MessageSegment.text("（卡图暂不可用）\n")
    message += MessageSegment.text(format_riftbound_card(card))
    return message


async def send_forward_msg(bot: Bot, event: MessageEvent, messages: list[Message], nickname: str):
    nodes = [make_forward_node(int(event.self_id), nickname, message) for message in messages]
    notice = "合并转发发送失败，已切换为普通消息发送。"
    if isinstance(event, GroupMessageEvent):
        await send_group_forward_nodes(bot, event, nodes, notice)
        return
    if isinstance(event, PrivateMessageEvent):
        try:
            await bot.call_api("send_private_forward_msg", user_id=event.user_id, messages=nodes)
            return
        except Exception:
            await bot.send(event, notice)
    for message in messages:
        await bot.send(event, message)

@rb.handle()
async def handle_rb(args: Message = CommandArg()):
    keyword = args.extract_plain_text().strip()
    if not keyword:
        await rb.finish("请输入卡名或编号，例如：rb 阿狸、rb OGN-066。支持副标题和模糊搜索。")
    if len(keyword) > 120:
        await rb.finish("查询内容过长，请输入卡名或编号。")
    cards = await lookup(keyword)
    if cards is None:
        await rb.finish("符文卡库暂不可用，请稍后重试。")
    if not cards:
        await rb.finish(f"未找到卡片：{keyword}")
    if len(cards) > 1 or cards[0]["match_kind"] == "fuzzy":
        await rb.finish(MessageSegment.text(format_candidates(cards[:BATCH_LIMIT], more=len(cards) > BATCH_LIMIT)))
    await rb.finish(await build_card_message(cards[0]))


@rb_pl.handle()
async def handle_rb_pl(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    keyword = args.extract_plain_text().strip()
    if not keyword:
        await rb_pl.finish("请输入卡名或编号，例如：rbpl 阿狸。每次最多展示10种卡片。")
    if len(keyword) > 120:
        await rb_pl.finish("查询内容过长，请输入卡名或编号。")
    cards = await lookup(keyword)
    if cards is None:
        await rb_pl.finish("符文卡库暂不可用，请稍后重试。")
    if not cards:
        await rb_pl.finish(f"未找到卡片：{keyword}")
    if cards[0]["match_kind"] == "fuzzy":
        await rb_pl.finish(MessageSegment.text(format_candidates(cards[:BATCH_LIMIT], more=len(cards) > BATCH_LIMIT)))
    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        async def build(card):
            async with semaphore:
                return await build_card_message(card, client)
        messages = list(await asyncio.gather(*(build(card) for card in cards[:BATCH_LIMIT])))
    if len(cards) > BATCH_LIMIT:
        messages.insert(0, Message("结果较多，仅展示前10种卡片，请补充卡名或副标题缩小范围。"))
    await send_forward_msg(bot, event, messages, nickname="符文查卡")
