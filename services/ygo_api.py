import base64
from typing import Optional

import httpx
from bs4 import BeautifulSoup


YGOCDB_API = "https://ygocdb.com/api/v0/"
PRIMARY_IMG = "https://cdn.233.momobako.com/ygoimg/ygopro/{id}.webp"
FALLBACK_IMG = "https://cdncf.moecube.com/ygopro-super-pre/data/pics/{id}.jpg"


async def search_cards(name: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(YGOCDB_API, params={"search": name})
        r.raise_for_status()
        data = r.json()
        return data.get("result", [])


async def fetch_card_faqs(card_id: int) -> list[dict]:
    url = f"{YGOCDB_API}card/{card_id}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"show": "all"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    card_id_key = str(card_id)
    faqs: list[dict] = []

    for faq in data.get("faqs") or []:

        question = html_to_text(faq.get("question", ""))
        answer = html_to_text(faq.get("answer", ""))

        if not question or not answer:
            continue

        faqs.append(
            {
                "fid": faq.get("fid", ""),
                "date": faq.get("date", ""),
                "question": question,
                "answer": answer,
            }
        )

    return faqs


def html_to_text(html: str) -> str:
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True)


def format_card_text(card: dict) -> str:
    text = card.get("text", {})

    lines = [
        f"常用名: {card.get('cn_name', '')}",
        f"MD卡名: {card.get('md_name', '')}",
        text.get("types", ""),
        text.get("desc", ""),
    ]

    if text.get("pdesc"):
        lines.append(f"灵摆效果：[{text['pdesc']}]")

    return "\n".join(line for line in lines if line)


async def download_image_base64(card_id: int) -> Optional[str]:
    urls = [
        PRIMARY_IMG.format(id=card_id),
        FALLBACK_IMG.format(id=card_id),
    ]

    async with httpx.AsyncClient(timeout=10) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code == 200 and r.content:
                    b64 = base64.b64encode(r.content).decode("utf-8")
                    return f"base64://{b64}"
            except Exception:
                continue

    return None
