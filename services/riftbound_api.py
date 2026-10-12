"""Deterministic Riftbound lookup against the bilingual SQLite snapshot."""
import asyncio
import base64
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import logging
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

import httpx

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def cards_db_path() -> Path:
    return Path(os.getenv("RIFTBOUND_CARDS_DB") or ROOT.parent / "riftsim" / "cards_bilingual.db").resolve()


def image_cache_dir() -> Path:
    return Path(os.getenv("RIFTBOUND_IMAGE_CACHE") or ROOT / "data" / "riftbound_images").resolve()


@lru_cache(maxsize=2)
def _read_cards(path: str, mtime_ns: int, size: int) -> tuple[dict, ...]:
    with sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        cards = tuple(dict(row) for row in conn.execute("SELECT * FROM cards ORDER BY card_key"))
    if not cards:
        raise ValueError("卡库为空")
    return cards


def load_cards() -> tuple[dict, ...]:
    path = cards_db_path()
    stat = path.stat()
    return _read_cards(str(path), stat.st_mtime_ns, stat.st_size)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(c for c in text if c.isalnum())


def normalize_code(text: str) -> str | None:
    text = unicodedata.normalize("NFKC", text).strip()
    match = re.fullmatch(r"([a-z]{2,4})\s*[-·・]?\s*((?:\d{3}|[rt]\d+|sp\d+)[a-z]?\*?)(?:/\d+)?", text, re.I)
    return f"{match[1].upper()}-{match[2].upper()}" if match else None


def card_title(card: dict) -> str:
    title = card.get("name_cn") or card.get("name_en") or card["card_key"]
    if card.get("sub_title_cn"):
        title += "·" + card["sub_title_cn"]
    return title


def _aliases(card: dict) -> list[str]:
    return [normalize(value) for value in (
        card.get("name_cn"), card.get("name_en"), card.get("sub_title_cn"),
        card_title(card), card.get("card_key"),
    ) if value]


def _group_key(card: dict) -> tuple:
    # Same names alone do not prove identical effects. Preserve distinct mechanics.
    return (normalize(card.get("name_cn") or card.get("name_en")),
            normalize(card.get("sub_title_cn")), normalize(card.get("name_en")),
            card.get("type_en") or card.get("type_cn"),
            normalize(card.get("text_en") or card.get("text_cn")),
            card.get("energy"), card.get("rune_power"), card.get("might"), card.get("might_bonus"))


def _edition_order(card: dict) -> tuple:
    return ({"base": 0, "token": 1, "alt": 2, "star": 3, "sp": 4}.get(card.get("variant"), 5), card["card_key"])


def search_riftbound_cards(keyword: str, limit: int = 10) -> list[dict]:
    key = normalize(keyword)
    if not key or len(keyword) > 120 or limit <= 0:
        return []
    cards = load_cards()
    code = normalize_code(keyword)
    if code:
        return [dict(card, editions=[dict(card)], match_kind="exact", score=1.0)
                for card in cards if card["card_key"].upper() == code][:limit]
    tokens = [normalize(token) for token in re.split(r"[\s·,，]+", keyword) if normalize(token)]
    ranked = []
    for card in cards:
        aliases = _aliases(card)
        if key in aliases:
            ranked.append((3, 1.0, card))
        elif any(key in alias for alias in aliases) or any(all(token in alias for token in tokens) for alias in aliases):
            ranked.append((2, max(SequenceMatcher(None, key, alias).ratio() for alias in aliases), card))
    if not ranked and len(key) >= 2:
        for card in cards:
            aliases = [normalize(value) for value in (card.get("name_cn"), card.get("name_en"), card_title(card)) if value]
            score = max(SequenceMatcher(None, key, alias).ratio() for alias in aliases)
            if score >= (0.5 if len(key) == 2 else 0.6):
                ranked.append((1, score, card))
    if not ranked:
        return []
    best_rank = max(item[0] for item in ranked)
    ranked = [item for item in ranked if item[0] == best_rank]
    if best_rank == 1:
        best_score = max(item[1] for item in ranked)
        ranked = [item for item in ranked if item[1] >= best_score - 0.12]
    groups = {}
    for rank, score, card in ranked:
        group = groups.setdefault(_group_key(card), {"score": score, "editions": []})
        group["score"] = max(group["score"], score)
        group["editions"].append(card)
    results = []
    for group in groups.values():
        editions = sorted(group["editions"], key=_edition_order)
        results.append(dict(editions[0], editions=[dict(card) for card in editions],
                            score=group["score"], match_kind={3: "exact", 2: "partial", 1: "fuzzy"}[best_rank]))
    results.sort(key=lambda card: (-card["score"], _edition_order(card)))
    return results[:limit]


ICONS = {"S": "战力", "s": "战力", "A": "任意符能", ">>": "", ">": ""}
EN_ICONS = {"might": "战力", "exhaust": "横置", "rune_fury": "红色符能", "rune_calm": "绿色符能",
            "rune_mind": "蓝色符能", "rune_body": "橙色符能", "rune_chaos": "紫色符能",
            "rune_order": "黄色符能", "rune_rainbow": "任意符能"}


def readable_text(text: str | None) -> str:
    def cn_icon(match):
        value = match[1]
        if value.isdigit():
            return f"[{value}能量]"
        value = ICONS.get(value, value).replace(">", "")
        return f"[{value}]" if value else ""

    def en_icon(match):
        value = match[1]
        if value.startswith("energy_"):
            value = value[7:] + "能量"
        else:
            value = EN_ICONS.get(value, value)
        return f"[{value}]"

    return re.sub(r":rb_([a-z0-9_]+):", en_icon,
                  re.sub(r"\{\{([^{}]+)\}\}", cn_icon, text or ""))


def format_riftbound_card(card: dict) -> str:
    lines = [card_title(card), "编号：" + card["card_key"]]
    if card.get("name_en") and card.get("name_cn"):
        lines.append("英文名：" + card["name_en"])
    fields = [("type_cn", "类型"), ("color_cn", "颜色"), ("energy", "能量费用"),
              ("rune_power", "符能费用"), ("might", "战力"), ("might_bonus", "战力加成"),
              ("rarity_cn", "稀有度"), ("region_cn", "地区")]
    basic = [f"{label}：{card[key]}" for key, label in fields if card.get(key) not in (None, "")]
    if not card.get("type_cn") and card.get("type_en"):
        basic.insert(0, "类型：" + card["type_en"])
    if not card.get("color_cn") and card.get("domain_en"):
        basic.append("特性：" + card["domain_en"])
    lines.append(" / ".join(basic))
    text = card.get("text_cn_filled") or card.get("text_cn") or card.get("text_en")
    if text:
        lines.extend(["", readable_text(text)])
    if card.get("text_cn_filled"):
        lines.append("补译说明：" + (card.get("cn_fill_note") or "对照英文补译，非官方中文文本"))
    elif not card.get("text_cn") and card.get("text_en"):
        lines.append("（暂无中文效果，以上为英文原文）")
    if card.get("errata_cn"):
        lines.extend(["", "勘误：" + readable_text(card["errata_cn"])])
    editions = card.get("editions", [])
    if len(editions) > 1:
        lines.append("其他版本：" + "、".join(c["card_key"] for c in editions if c["card_key"] != card["card_key"]))
        lines.append("查询指定版本：rb 编号")
    return "\n".join(line for line in lines if line is not None)


def format_candidates(cards: list[dict], *, more: bool = False) -> str:
    fuzzy = any(card["match_kind"] == "fuzzy" for card in cards)
    lines = ["未找到完全匹配，以下是相近卡片：" if fuzzy else "找到多张卡片，请用编号查询："]
    for card in cards:
        suffix = f"（共{len(card['editions'])}个版本）" if len(card["editions"]) > 1 else ""
        lines.append(f"rb {card['card_key']}  {card_title(card)}{suffix}")
    if more:
        lines.append("还有更多结果，请补充卡名或副标题。")
    return "\n".join(lines)


def image_cache_path(url: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or image_cache_dir()) / (hashlib.sha256(url.encode()).hexdigest() + ".img")


def valid_image(data: bytes) -> bool:
    return bool(data) and len(data) <= MAX_IMAGE_BYTES and (
        data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or
        data.startswith((b"GIF87a", b"GIF89a")) or
        (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


async def fetch_image(url: str, client: httpx.AsyncClient, cache_dir: Path | None = None) -> bytes | None:
    path = image_cache_path(url, cache_dir)
    try:
        data = await asyncio.to_thread(path.read_bytes)
        if valid_image(data):
            return data
    except OSError:
        pass
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            if not response.headers.get("content-type", "").lower().startswith("image/"):
                return None
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    return None
                chunks.append(chunk)
            data = b"".join(chunks)
        if not valid_image(data):
            return None
        def save():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(data)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        try:
            await asyncio.to_thread(save)
        except OSError:
            logger.warning("Riftbound image cache write failed: %s", path)
        return data
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Riftbound image download failed: %s: %s", url, exc)
        return None


async def card_image(card: dict, client: httpx.AsyncClient | None = None,
                     cache_dir: Path | None = None) -> tuple[str | None, str | None]:
    if client is None:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as owned_client:
            return await card_image(card, owned_client, cache_dir)
    for field, language in (("image_url_cn", "cn"), ("image_url_en", "en")):
        if card.get(field):
            data = await fetch_image(card[field], client, cache_dir)
            if data:
                return "base64://" + base64.b64encode(data).decode("ascii"), language
    return None, None
