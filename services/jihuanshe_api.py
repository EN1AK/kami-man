"""集换社查价；游戏和语种分区贯穿搜索、选择及价格查询。"""
import asyncio
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from services.ygo_api import search_cards
from services.riftbound_api import card_title, normalize as normalize_rift_name, normalize_code, search_riftbound_cards

RARITIES = {'N', 'NR', 'NPR', 'R', 'SR', 'UR', 'UTR', 'SER', 'PSER', 'QCSER', 'CR', 'HR', 'GR', 'GSR', 'GUR', 'ESR', 'P', 'PR', 'PAR', 'KC', 'MR', 'QCSE', 'STARLIGHT', 'PROMO', 'TOKEN', '普通', '罕见', '稀有', '史诗', '传奇', '异画', '异画(超编)', '异画(签名)'}
LANGUAGES = {'jp': '日文', 'sc': '简中', 'tc': '繁中', 'en': '英文', 'kr': '韩文'}
GAME_LANGUAGES = {'ygo': ('jp', 'sc', 'en'), 'riftbound': ('sc', 'tc', 'en', 'kr')}
GAME_NAMES = {'ygo': '游戏王', 'riftbound': '符文战场'}
LANGUAGE_ALIASES = {
    '日文': 'jp', '日版': 'jp', '日语': 'jp', 'jp': 'jp',
    '简中': 'sc', '简体': 'sc', '简体中文': 'sc', '中文': 'sc', 'sc': 'sc',
    '繁中': 'tc', '繁体': 'tc', '繁体中文': 'tc', 'tc': 'tc',
    '英文': 'en', '英语': 'en', 'en': 'en',
    '韩文': 'kr', '韩语': 'kr', 'kr': 'kr',
}
GAME_ALIASES = {'游戏王': 'ygo', 'ygo': 'ygo', '符文': 'riftbound', '符文战场': 'riftbound', 'riftbound': 'riftbound', 'rb': 'riftbound'}


class PriceError(Exception):
    """可直接展示的固定失败提示。"""


CARD_CHOICE_LIMIT = 25  # Same visible result limit as pl.


@dataclass(frozen=True)
class CardCandidate:
    name: str
    password: str | None = None
    card: dict | None = None
    entries: list[dict] | None = None


class CardChoices(PriceError):
    def __init__(self, candidates: list[CardCandidate]):
        super().__init__('匹配到多张游戏王卡片，请先选卡。')
        self.candidates = candidates[:CARD_CHOICE_LIMIT]
        self.more = len(candidates) > CARD_CHOICE_LIMIT


@dataclass(frozen=True)
class PriceQuery:
    name: str
    rarity: str | None
    game: str
    language: str


def normalize_name(value: str) -> str:
    return unicodedata.normalize('NFKC', value).strip().casefold()


def scope_label(game: str, language: str) -> str:
    if game not in GAME_LANGUAGES or language not in GAME_LANGUAGES[game]:
        available = '、'.join(LANGUAGES[x] for x in GAME_LANGUAGES.get(game, ()))
        raise PriceError(f'{GAME_NAMES.get(game, "该游戏")}查价支持的语种：{available or "暂无"}。')
    return f'{GAME_NAMES[game]}·{LANGUAGES[language]}'


def parse_query(text: str, default_game: str = 'ygo') -> PriceQuery:
    tokens = text.strip().split()
    game = default_game
    if tokens and tokens[0].casefold() in GAME_ALIASES:
        game = GAME_ALIASES[tokens.pop(0).casefold()]
    languages = {LANGUAGE_ALIASES[token.casefold()] for token in tokens if token.casefold() in LANGUAGE_ALIASES}
    if len(languages) > 1:
        raise PriceError('一次请选择一种语种，例如「简中」或「日文」。')
    tokens = [token for token in tokens if token.casefold() not in LANGUAGE_ALIASES]
    language = next(iter(languages), 'sc' if game == 'riftbound' else 'jp')
    scope_label(game, language)
    rarity = None
    if tokens and unicodedata.normalize('NFKC', tokens[-1]).upper() in RARITIES:
        rarity = unicodedata.normalize('NFKC', tokens.pop()).upper()
    return PriceQuery(' '.join(tokens), rarity, game, language)


async def bridge_request(path: str, payload: dict) -> dict:
    url = os.getenv('JIHUANSHE_BRIDGE_URL', '').strip().rstrip('/')
    token = os.getenv('JIHUANSHE_BRIDGE_TOKEN', '').strip()
    if not url or not token:
        raise PriceError('查价服务尚未配置。')
    try:
        timeout = float(os.getenv('JIHUANSHE_BRIDGE_TIMEOUT', '90'))
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url + path, json=payload, headers={'Authorization': 'Bearer ' + token})
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError('invalid response')
        if response.status_code != 200:
            messages = {
                'busy': '查价服务正在处理其他查询，请稍后重试。',
                'needs_login': '查价电脑上的集换社需要重新登录，请联系管理员。',
                'needs_miniapp': '集换社小程序暂时无法恢复，请联系管理员。',
                'wechat_unavailable': '查价电脑上的微信暂时不可用，请稍后重试。',
                'upstream_error': '集换社暂时没有返回价格，请稍后重试。',
            }
            raise PriceError(messages.get(body.get('error'), '查价连接正在恢复，请稍后重试。'))
        return body
    except PriceError:
        raise
    except httpx.TimeoutException:
        raise PriceError('查价超时，请稍后重试。') from None
    except httpx.HTTPError:
        raise PriceError('查价电脑暂时离线或连接正在恢复，请稍后重试。') from None
    except (ValueError, TypeError):
        raise PriceError('查价服务返回异常，请稍后重试。') from None



async def _versions(keyword: str, game: str, language: str) -> list[dict]:
    body = await bridge_request('/v1/versions', {'keyword': keyword, 'game': game, 'language': language})
    entries = body.get('entries')
    if not isinstance(entries, list):
        raise PriceError('查价服务返回异常，请稍后重试。')
    return entries


def _valid_versions(entries: list[dict], game: str, language: str) -> list[dict]:
    valid = []
    seen = set()
    for row in entries:
        if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0:
            continue
        if row.get('game') != game or row.get('language') != language:
            raise PriceError('查价服务返回的游戏或语种不符，请稍后重试。')
        if row.get('object_type') not in {None, 'unknown', 'card'}:
            continue
        if row['id'] not in seen:
            valid.append(row)
            seen.add(row['id'])
    return valid


def _row_names(row: dict) -> list[str]:
    return [str(value) for value in [row.get('name_cn'), row.get('name_jp'), row.get('name_en'), *(row.get('aliases') or [])] if value]


def _rift_code(number: str) -> str | None:
    number = re.sub(r'[·\s-](?:SC|TC|EN|KR)$', '', number, flags=re.I)
    return normalize_code(number)


def ygo_card_password(card: dict) -> str | None:
    value = card.get('id')
    if type(value) is int and value > 0:
        return str(value).zfill(8)
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return value.zfill(8)
    return None


def ygo_card_names(card: dict) -> set[str]:
    return {normalize_name(str(value)) for key, value in card.items()
            if key in {'cn_name', 'sc_name', 'md_name', 'jp_name', 'en_name'} and value}


async def resolve_ygo_card(query: str) -> dict | None:
    # Reuse the same YGOCDB search as ck/pl; only the text-only choice flow differs.
    cards = await search_cards(query)
    unique = []
    seen = set()
    for card in cards or []:
        if not isinstance(card, dict) or not ygo_card_names(card):
            continue
        key = ygo_card_password(card) or tuple(sorted(ygo_card_names(card)))
        if key not in seen:
            seen.add(key)
            unique.append(card)
    normalized = normalize_name(query)
    password = normalized.zfill(8) if normalized.isascii() and normalized.isdecimal() else None
    exact = [card for card in unique if normalized in ygo_card_names(card)
             or (password is not None and password == ygo_card_password(card))]
    matches = exact or unique
    if len(matches) > 1:
        raise CardChoices([CardCandidate(
            name=card.get('cn_name') or card.get('sc_name') or card.get('jp_name') or card.get('en_name') or query,
            password=ygo_card_password(card), card=card,
        ) for card in matches])
    return matches[0] if matches else None


async def find_versions(query: str, game: str = 'ygo', language: str = 'jp', *, selected_card: dict | None = None) -> tuple[str, list[dict]]:
    label = scope_label(game, language)
    keyword = query
    names: set[str] = set()
    display_name = None
    code = _rift_code(query) if game == 'riftbound' else None
    if game == 'ygo':
        try:
            card = selected_card if selected_card is not None else await resolve_ygo_card(query)
            if card:
                keyword = card.get('jp_name') or card.get('cn_name') or query
                names = ygo_card_names(card)
                display_name = card.get('cn_name') or card.get('sc_name')
        except (httpx.HTTPError, ValueError):
            pass
    elif not code:
        try:
            cards = await asyncio.to_thread(search_riftbound_cards, query, 2)
            if len(cards) == 1 and cards[0]['match_kind'] != 'fuzzy':
                card = cards[0]
                keyword = card.get('name_cn') or query
                names = {normalize_rift_name(value) for value in (card_title(card), card.get('name_en')) if value}
        except (OSError, ValueError, sqlite3.Error):
            pass
    entries = _valid_versions(await _versions(keyword, game, language), game, language)
    if not entries and unicodedata.normalize('NFKC', keyword) != keyword:
        entries = _valid_versions(await _versions(unicodedata.normalize('NFKC', keyword), game, language), game, language)
    if game == 'riftbound' and not entries and not names and not code:
        # The market stores comma-separated subtitles; a space-separated query
        # may only match a playmat. Search the character, then match the full title.
        first = re.split(r'[\s·,，]+', query.strip())[0]
        if first != query:
            entries = _valid_versions(await _versions(first, game, language), game, language)
            full_name = normalize_rift_name(query)
            entries = [row for row in entries if any(full_name in normalize_rift_name(value) for value in _row_names(row))]
    if names:
        normalizer = normalize_rift_name if game == 'riftbound' else normalize_name
        entries = [row for row in entries if names & {normalizer(value) for value in _row_names(row)}]
    if code:
        entries = [row for row in entries if _rift_code(str(row.get('number') or '')) == code]
    if not entries:
        raise PriceError(f'未找到「{query}」的{label}卡片版本。')
    card_ids = {row.get('card_id') for row in entries}
    if len(card_ids) > 1:
        if game == 'ygo':
            by_card: dict[object, list[dict]] = {}
            for row in entries:
                by_card.setdefault(row.get('card_id'), []).append(row)
            raise CardChoices([CardCandidate(
                name=rows[0].get('name_cn') or rows[0].get('name_jp') or query,
                entries=rows,
            ) for rows in by_card.values()])
        candidates = list(dict.fromkeys(row.get('name_cn') or row.get('name_jp') or '' for row in entries))
        raise PriceError(f'{label}找到多张卡片，请输入完整卡名或卡号：\n' + '\n'.join(candidates[:8]))
    name = display_name or entries[0].get('name_cn') or query
    return name, entries


def rarity_groups(entries: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for row in entries:
        rarity = str(row.get('rarity') or '未知').upper()
        groups.setdefault(rarity, []).append(row)
    return list(groups.items())


def select_rarity(groups: list[tuple[str, list[dict]]], selection: str) -> list[dict] | None:
    if selection.isdecimal() and 1 <= int(selection) <= len(groups):
        return groups[int(selection) - 1][1]
    return next((rows for rarity, rows in groups if rarity == selection.upper()), None)


def money(value) -> str:
    if value is None:
        return '暂无'
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return '暂无'
        return f'¥{amount:.2f}'
    except (InvalidOperation, TypeError):
        return '暂无'


async def price_message(name: str, entries: list[dict], game: str = 'ygo', language: str = 'jp') -> str:
    label = scope_label(game, language)
    if any(row.get('game') != game or row.get('language') != language for row in entries):
        raise PriceError('选择的版本语种不符，请重新发送查价命令。')
    prices = []
    if len(entries) > 60:
        raise PriceError('该罕贵的版本过多，请换一个更精确的卡名查询。')
    for start in range(0, len(entries), 20):
        body = await bridge_request('/v1/prices', {'version_ids': [row['id'] for row in entries[start:start + 20]], 'game': game, 'language': language})
        batch = body.get('prices')
        if not isinstance(batch, list):
            raise PriceError('查价服务返回异常，请稍后重试。')
        prices.extend(batch)
    by_id = {row.get('id'): row for row in prices if isinstance(row, dict)}
    lines = [f'{name} · 集换社价格（{label}）']
    for entry in entries:
        row = by_id.get(entry['id'])
        lines.append(f"\n{entry.get('number') or '未知卡号'} · {entry.get('rarity') or '未知罕贵'}")
        if not row or row.get('error') or row.get('game') != game or row.get('language') != language:
            lines.append('价格暂不可用')
            continue
        lines.extend([f"最低价：{money(row.get('min_price'))}", f"集换价：{money(row.get('market_price'))}"])
        if row.get('market_date'):
            lines.append(f"集换价日期：{row['market_date']}")
    lines.append(f'\n语种：{LANGUAGES[language]}；币种：人民币。最低价为该版本当前在售出品价格。')
    return '\n'.join(lines)
