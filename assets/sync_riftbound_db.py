import json
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "riftbound_cards.json"

REPO = "https://raw.githubusercontent.com/choowx2002/project_k_image/main"
DETAIL_URL = f"{REPO}/card_detail.json"
DB_URL = f"{REPO}/cardDB.json"


def pick(obj: dict, *keys, default=""):
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return default


def normalize_items(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["data", "cards", "cardList", "list", "result"]:
            if isinstance(data.get(key), list):
                return data[key]
        return list(data.values())
    return []


def get_first_craft(card: dict) -> dict:
    crafts = card.get("craftList") or []
    return crafts[0] if crafts else {}


def get_first_product(card: dict) -> dict:
    products = card.get("productList") or []
    return products[0] if products else {}


def convert_card(card: dict) -> dict:
    craft = get_first_craft(card)
    product = get_first_product(card)

    colors = card.get("cardColorNameList") or []
    color_text = " / ".join(colors)

    zh_text_parts = []

    if card.get("cardEffect"):
        zh_text_parts.append(card["cardEffect"])

    if card.get("attachEffect"):
        zh_text_parts.append(f"装配效果：{card['attachEffect']}")

    if card.get("flavorText"):
        zh_text_parts.append(f"Flavor：{card['flavorText']}")

    return {
        "id": str(card.get("id", "")),
        "code": str(card.get("cardNoShort") or card.get("cardNo") or ""),
        "card_no": str(card.get("cardNo") or ""),
        "zh_name": str(card.get("cardName") or ""),
        "en_name": "",
        "subtitle": str(card.get("subTitle") or ""),

        "type": str(card.get("cardCategoryName") or card.get("cardCategory") or ""),
        "category": str(card.get("cardCategory") or ""),

        "color": color_text,
        "color_raw": card.get("cardColorList") or [],

        "region": str(card.get("region") or ""),
        "tag": str(card.get("tag") or ""),

        "cost": "" if card.get("energy") is None else str(card.get("energy")),
        "return_cost": "" if card.get("returnEnergy") is None else str(card.get("returnEnergy")),
        "power": "" if card.get("power") is None else str(card.get("power")),

        "rarity": str(craft.get("rarityName") or ""),
        "rarity_raw": str(craft.get("rarity") or ""),
        "foil": str(craft.get("extendRarityName") or ""),
        "artist": str(craft.get("artist") or ""),

        "set": str(product.get("productName") or ""),
        "set_code": str(card.get("cardSeries") or ""),
        "product_code": str(product.get("productCode") or ""),

        "zh_text": "\n".join(zh_text_parts),
        "en_text": "",

        "image_url": str(craft.get("frontImage") or ""),
        "back_image_url": str(craft.get("backImage") or ""),

        "qa": card.get("cardQaList") or [],
        "errata": str(card.get("errata") or ""),
        "raw": card,
    }

def merge_cards(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged = {}

    for source in [secondary, primary]:
        for raw in source:
            card = convert_card(raw)
            key = card["code"] or card["id"] or card["zh_name"] or card["en_name"]
            if not key:
                continue

            if key not in merged:
                merged[key] = card
            else:
                old = merged[key]
                for k, v in card.items():
                    if k == "raw":
                        continue
                    if v and not old.get(k):
                        old[k] = v

    return list(merged.values())


def main():
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        detail = client.get(DETAIL_URL).json()
        carddb = client.get(DB_URL).json()

    detail_items = normalize_items(detail)
    db_items = normalize_items(carddb)

    cards = merge_cards(detail_items, db_items)

    cards.sort(key=lambda x: (x.get("set", ""), x.get("code", ""), x.get("zh_name", "")))

    OUT_FILE.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"生成完成：{OUT_FILE}")
    print(f"卡片数量：{len(cards)}")


if __name__ == "__main__":
    main()