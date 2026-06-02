import base64
import json
from pathlib import Path
from typing import Optional

import httpx


ROOT = Path(__file__).resolve().parent.parent
CARD_FILE = ROOT / "data" / "riftbound_cards.json"


def load_cards() -> list[dict]:
    if not CARD_FILE.exists():
        return []
    return json.loads(CARD_FILE.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return str(text).lower().replace(" ", "").replace("　", "").strip()


def search_riftbound_cards(keyword: str, limit: int = 10) -> list[dict]:
    cards = load_cards()
    key = normalize(keyword)

    exact = []
    partial = []

    for card in cards:
        fields = [
            card.get("zh_name", ""),
            card.get("en_name", ""),
            card.get("code", ""),
            card.get("id", ""),
            card.get("set", ""),
        ]

        names = [normalize(x) for x in fields if x]

        if key in names:
            exact.append(card)
        elif any(key in x for x in names):
            partial.append(card)

    return (exact + partial)[:limit]




def format_riftbound_card(card: dict) -> str:
    lines = []

    if card.get("zh_name"):
        lines.append(f"卡名: {card['zh_name']}")
    if card.get("subtitle"):
        lines.append(f"副标题: {card['subtitle']}")
    if card.get("code"):
        lines.append(f"编号: {card['code']}")

    basic = []

    for key, label in [
        ("type", "类型"),
        ("color", "颜色"),
        ("region", "地区"),
        ("cost", "费用"),
        ("return_cost", "回费"),
        ("power", "力量"),
        ("rarity", "稀有度"),
        ("set_code", "系列"),
    ]:
        value = card.get(key)
        if value:
            basic.append(f"{label}: {value}")

    if basic:
        lines.append(" / ".join(basic))

    if card.get("zh_text"):
        lines.append("")
        lines.append(card["zh_text"])

    if card.get("artist"):
        lines.append("")
        lines.append(f"画师: {card['artist']}")

    return "\n".join(lines)

async def download_image_base64(url: str) -> Optional[str]:
    if not url:
        return None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url)

        if r.status_code != 200 or not r.content:
            return None

        b64 = base64.b64encode(r.content).decode("utf-8")
        return f"base64://{b64}"
    except Exception:
        return None