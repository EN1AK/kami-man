import base64
from typing import Optional

import httpx
from bs4 import BeautifulSoup


YGOCDB_API = "https://ygocdb.com/api/v0/"
PRIMARY_IMG = "https://cdn.233.momobako.com/ygopro/pics/{id}.jpg"
FALLBACK_IMG = "https://cdncf.moecube.com/ygopro-super-pre/data/pics/{id}.jpg"


async def search_cards(name: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(YGOCDB_API, params={"search": name})
        r.raise_for_status()
        data = r.json()
        return data.get("result", [])


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


async def fetch_faq(faq_id: int) -> Optional[dict]:
    url = "https://www.db.yugioh-card.com/yugiohdb/faq_search.action"

    params = {
        "ope": 5,
        "fid": faq_id,
        "keyword": "",
        "tag": -1,
        "request_locale": "ja",
    }

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        question = soup.find(id="question_text")
        answer = soup.find(id="answer_text")

        if not question or not answer:
            return None

        return {
            "question": question.get_text(" ", strip=True),
            "answer": answer.get_text(" ", strip=True),
        }
    except Exception:
        return None