"""游戏王集换社查价，按聊天及发起用户保存三分钟的罕贵选择。"""
import re
import time
from dataclasses import dataclass

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.rule import Rule

from services.jihuanshe_api import PriceError, find_versions, parse_query, price_message, rarity_groups, select_rarity

card_price = on_command('卡价', aliases={'卡价查询', '查价格'}, priority=5, block=True)
TTL = 180


@dataclass
class Selection:
    name: str
    groups: list[tuple[str, list[dict]]]
    expires: float


pending: dict[tuple[str, str], Selection] = {}


def session_key(event: MessageEvent) -> tuple[str, str]:
    return str(event.self_id), event.get_session_id()


def prune_selections() -> None:
    now = time.monotonic()
    for key in [key for key, value in pending.items() if value.expires <= now]:
        pending.pop(key, None)


async def awaiting_selection(event: MessageEvent) -> bool:
    prune_selections()
    return session_key(event) in pending and bool(re.fullmatch(r'取消|\d{1,2}|[A-Za-z]{1,8}', event.get_plaintext().strip()))


price_selection = on_message(rule=Rule(awaiting_selection), priority=6, block=True)


@card_price.handle()
async def handle_price(event: MessageEvent, args: Message = CommandArg()):
    prune_selections()
    pending.pop(session_key(event), None)
    query, rarity = parse_query(args.extract_plain_text())
    if not query:
        await card_price.finish('用法：卡价 卡名或卡密\n例如：卡价 原石之皇脉\n也可以：卡价 原石之皇脉 UTR')
    try:
        name, entries = await find_versions(query)
        groups = rarity_groups(entries)
        if rarity or len(groups) == 1:
            selected = select_rarity(groups, rarity or '1')
            if not selected:
                raise PriceError('该卡没有这个罕贵，可选：' + '、'.join(r for r, _ in groups))
            result = await price_message(name, selected)
        else:
            pending[session_key(event)] = Selection(name, groups, time.monotonic() + TTL)
            lines = [f'{name}：请选择罕贵']
            for index, (label, rows) in enumerate(groups, 1):
                packs = '、'.join(dict.fromkeys(str(row.get('number') or '未知卡号') for row in rows))
                lines.append(f'{index}. {label}（{packs}）')
            lines.append('回复编号或罕贵；3分钟内有效，回复「取消」结束。')
            result = '\n'.join(lines)
    except PriceError as error:
        result = str(error)
    await card_price.finish(MessageSegment.text(result))


@price_selection.handle()
async def handle_selection(event: MessageEvent):
    key = session_key(event)
    selection = pending.get(key)
    if not selection or selection.expires <= time.monotonic():
        pending.pop(key, None)
        await price_selection.finish('选择已过期，请重新发送「卡价 卡名」。')
    answer = event.get_plaintext().strip()
    if answer == '取消':
        pending.pop(key, None)
        await price_selection.finish('已取消查价。')
    selected = select_rarity(selection.groups, answer)
    if not selected:
        await price_selection.finish('请选择列表中的编号或罕贵，或回复「取消」。')
    pending.pop(key, None)
    try:
        result = await price_message(selection.name, selected)
    except PriceError as error:
        result = str(error)
    await price_selection.finish(MessageSegment.text(result))