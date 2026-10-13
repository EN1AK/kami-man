"""游戏王及符文战场文字查价，按聊天及用户保存选卡/罕贵状态。"""
import re
import time
import unicodedata
from dataclasses import dataclass

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.rule import Rule

from services.jihuanshe_api import (
    CardCandidate, CardChoices, PriceError, PriceQuery, find_versions, normalize_name,
    parse_query, price_message, rarity_groups, select_rarity, scope_label, ygo_card_names,
)

card_price = on_command('卡价', aliases={'卡价查询', '查价格'}, priority=5, block=True)
rift_price = on_command('符文卡价', aliases={'符文查价', 'rb价', 'rbprice'}, priority=5, block=True)
TTL = 180


@dataclass
class Selection:
    name: str
    groups: list[tuple[str, list[dict]]]
    expires: float
    game: str = 'ygo'
    language: str = 'jp'


@dataclass
class CardSelection:
    query: PriceQuery
    candidates: list[CardCandidate]
    expires: float


pending: dict[tuple[str, str], Selection | CardSelection] = {}


def session_key(event: MessageEvent) -> tuple[str, str]:
    return str(event.self_id), event.get_session_id()


def prune_selections() -> None:
    now = time.monotonic()
    for key in [key for key, value in pending.items() if value.expires <= now]:
        pending.pop(key, None)


def normalized_answer(text: str) -> str:
    return unicodedata.normalize('NFKC', text).strip()


def select_card(candidates: list[CardCandidate], answer: str) -> CardCandidate | None:
    if re.fullmatch(r'\d{1,2}', answer) and 1 <= int(answer) <= len(candidates):
        return candidates[int(answer) - 1]
    name = normalize_name(answer)
    password = name.zfill(8) if name.isascii() and name.isdecimal() else None
    matches = [candidate for candidate in candidates
               if name in ({normalize_name(candidate.name)} | ygo_card_names(candidate.card or {}))
               or (password is not None and password == candidate.password)]
    return matches[0] if len(matches) == 1 else None


async def awaiting_selection(event: MessageEvent) -> bool:
    prune_selections()
    selection = pending.get(session_key(event))
    if not selection:
        return False
    text = normalized_answer(event.get_plaintext())
    if text == '取消':
        return True
    if isinstance(selection, CardSelection):
        return bool(re.fullmatch(r'\d{1,8}', text)) or select_card(selection.candidates, text) is not None
    return bool(re.fullmatch(r'\d{1,2}', text)) or any(label == text.upper() for label, _ in selection.groups)


price_selection = on_message(rule=Rule(awaiting_selection), priority=6, block=True)


def card_prompt(event: MessageEvent, query: PriceQuery, choices: CardChoices) -> str:
    pending[session_key(event)] = CardSelection(query, choices.candidates, time.monotonic() + TTL)
    lines = [f'匹配到多张卡片（{scope_label(query.game, query.language)}），请先选卡：']
    for index, candidate in enumerate(choices.candidates, 1):
        detail = f'卡密：{candidate.password}' if candidate.password else ''
        if not detail and candidate.entries:
            numbers = list(dict.fromkeys(str(row.get('number') or '未知卡号') for row in candidate.entries))
            detail = '卡号：' + '、'.join(numbers[:3])
        lines.append(f'{index}. {candidate.name}' + (f'（{detail}）' if detail else ''))
    if choices.more:
        lines.append('候选较多，仅显示前25张；可重新发送更完整的卡名缩小范围。')
    lines.append('回复编号、列表中的卡密或完整卡名；3分钟内有效，回复「取消」结束。')
    return '\n'.join(lines)


async def version_result(event: MessageEvent, query: PriceQuery, name: str, entries: list[dict]) -> str:
    groups = rarity_groups(entries)
    if query.rarity or len(groups) == 1:
        selected = select_rarity(groups, query.rarity or '1')
        if not selected:
            raise PriceError('该卡没有这个罕贵，可选：' + '、'.join(r for r, _ in groups))
        return await price_message(name, selected, query.game, query.language)
    pending[session_key(event)] = Selection(name, groups, time.monotonic() + TTL, query.game, query.language)
    lines = [f'{name}（{scope_label(query.game, query.language)}）：请选择罕贵']
    for index, (label, rows) in enumerate(groups, 1):
        packs = '、'.join(dict.fromkeys(str(row.get('number') or '未知卡号') for row in rows))
        lines.append(f'{index}. {label}（{packs}）')
    lines.append('回复编号或罕贵；3分钟内有效，回复「取消」结束。')
    return '\n'.join(lines)


async def lookup_result(event: MessageEvent, query: PriceQuery, candidate: CardCandidate | None = None) -> str:
    try:
        if candidate is not None and candidate.entries is not None:
            name, entries = candidate.name, candidate.entries
        elif candidate is not None:
            name, entries = await find_versions(query.name, query.game, query.language, selected_card=candidate.card)
        else:
            name, entries = await find_versions(query.name, query.game, query.language)
        return await version_result(event, query, name, entries)
    except CardChoices as choices:
        return card_prompt(event, query, choices)
    except PriceError as error:
        return str(error)


async def respond_price(matcher, event: MessageEvent, text: str, default_game: str):
    prune_selections()
    pending.pop(session_key(event), None)
    try:
        query = parse_query(text, default_game)
        if not query.name:
            await matcher.finish('用法：卡价 卡名 [语种] [罕贵]\n例如：卡价 原石 简中 SR\n模糊命中多张时先回复编号选卡，再选罕贵；只返回文字。\n符文：符文卡价 OGN-119 简中\n默认：游戏王日文，符文战场简中。')
        result = await lookup_result(event, query)
    except PriceError as error:
        result = str(error)
    await matcher.finish(MessageSegment.text(result))


@card_price.handle()
async def handle_price(event: MessageEvent, args: Message = CommandArg()):
    await respond_price(card_price, event, args.extract_plain_text(), 'ygo')


@rift_price.handle()
async def handle_rift_price(event: MessageEvent, args: Message = CommandArg()):
    await respond_price(rift_price, event, args.extract_plain_text(), 'riftbound')


@price_selection.handle()
async def handle_selection(event: MessageEvent):
    key = session_key(event)
    selection = pending.get(key)
    if not selection or selection.expires <= time.monotonic():
        pending.pop(key, None)
        await price_selection.finish('选择已过期，请重新发送查价命令。')
    answer = normalized_answer(event.get_plaintext())
    if answer == '取消':
        pending.pop(key, None)
        await price_selection.finish('已取消查价。')
    if isinstance(selection, CardSelection):
        candidate = select_card(selection.candidates, answer)
        if candidate is None:
            await price_selection.finish('请选择列表中的编号、卡密或完整卡名，或回复「取消」。')
        pending.pop(key, None)
        result = await lookup_result(event, selection.query, candidate)
        await price_selection.finish(MessageSegment.text(result))
    selected = select_rarity(selection.groups, answer)
    if not selected:
        await price_selection.finish('请选择列表中的编号或罕贵，或回复「取消」。')
    pending.pop(key, None)
    try:
        result = await price_message(selection.name, selected, selection.game, selection.language)
    except PriceError as error:
        result = str(error)
    await price_selection.finish(MessageSegment.text(result))
