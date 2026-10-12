"""集换社查价客户端；登录会话只存在于 Windows 微信内。"""
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation

import httpx

from services.ygo_api import search_cards

RARITIES = {'N', 'NR', 'R', 'SR', 'UR', 'UTR', 'SER', 'PSER', 'QCSER', 'CR', 'HR', 'GR', 'GSR', 'GUR', 'ESR', 'P', 'PR', 'PAR', 'KC', 'MR', 'QCSE'}


class PriceError(Exception):
    """可直接展示的固定失败提示。"""


def normalize_name(value: str) -> str:
    return unicodedata.normalize('NFKC', value).strip().casefold()


def parse_query(text: str) -> tuple[str, str | None]:
    parts = text.strip().rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].upper() in RARITIES:
        return parts[0].strip(), parts[1].upper()
    return text.strip(), None


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


async def find_versions(query: str) -> tuple[str, list[dict]]:
    card = None
    try:
        cards = await search_cards(query)
        if cards:
            card = cards[0]
    except (httpx.HTTPError, ValueError):
        pass
    keyword = (card or {}).get('jp_name') or query
    names = {normalize_name(str(value)) for key, value in (card or {}).items()
             if key in {'cn_name', 'sc_name', 'md_name', 'jp_name'} and value}
    body = await bridge_request('/v1/versions', {'name_jp': keyword})
    entries = body.get('entries')
    if not isinstance(entries, list):
        raise PriceError('查价服务返回异常，请稍后重试。')
    if not entries and normalize_name(keyword) != keyword.casefold():
        body = await bridge_request('/v1/versions', {'name_jp': unicodedata.normalize('NFKC', keyword)})
        entries = body.get('entries', [])
    valid = []
    seen = set()
    for row in entries:
        if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0:
            continue
        row_names = {normalize_name(str(value)) for value in [row.get('name_cn'), row.get('name_jp'), *(row.get('aliases') or [])] if value}
        if card and not (names & row_names):
            continue
        if row.get('object_type') not in {None, 'unknown', 'card'}:
            continue
        if row['id'] not in seen:
            valid.append(row)
            seen.add(row['id'])
    if not valid:
        raise PriceError(f'未找到「{query}」的集换社卡片版本。')
    card_ids = {row.get('card_id') for row in valid}
    if not card and len(card_ids) > 1:
        candidates = list(dict.fromkeys(row.get('name_cn') or row.get('name_jp') or '' for row in valid))
        raise PriceError('找到多张卡片，请输入完整卡名或卡密：\n' + '\n'.join(candidates[:8]))
    name = (card or {}).get('cn_name') or valid[0].get('name_cn') or query
    return name, valid


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


async def price_message(name: str, entries: list[dict]) -> str:
    prices = []
    if len(entries) > 60:
        raise PriceError('该罕贵的版本过多，请换一个更精确的卡名查询。')
    for start in range(0, len(entries), 20):
        body = await bridge_request('/v1/prices', {'version_ids': [row['id'] for row in entries[start:start + 20]]})
        batch = body.get('prices')
        if not isinstance(batch, list):
            raise PriceError('查价服务返回异常，请稍后重试。')
        prices.extend(batch)
    by_id = {row.get('id'): row for row in prices if isinstance(row, dict)}
    lines = [f'{name} · 集换社价格']
    for entry in entries:
        row = by_id.get(entry['id'])
        lines.append(f"\n{entry.get('number') or '未知卡号'} · {entry.get('rarity') or '未知罕贵'}")
        if not row or row.get('error'):
            lines.append('价格暂不可用')
            continue
        lines.extend([f"最低价：{money(row.get('min_price'))}", f"集换价：{money(row.get('market_price'))}"])
        if row.get('market_date'):
            lines.append(f"集换价日期：{row['market_date']}")
    lines.append('\n最低价包含该版本全部在售出品；币种为人民币。')
    return '\n'.join(lines)