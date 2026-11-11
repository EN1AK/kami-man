import base64
import asyncio
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup


YGOCDB_API = "https://ygocdb.com/api/v0/"
PRIMARY_IMG = "https://cdncf.moecube.com/images/ygopro-images-zh-CN/{id}.jpg"
FALLBACK_IMG = "https://cdn02.moecube.com/images/ygopro-images-zh-CN/{id}.jpg"
LEGACY_IMG = "https://cdn.233.momobako.com/ygoimg/ygopro/{id}.webp"
IMAGE_DIR = Path(__file__).resolve().parents[1] / "data" / "ygo_images"
MAX_IMAGE_BYTES = 2 * 1024**2
_IMAGE_CACHE = OrderedDict()
_IMAGE_INFLIGHT = {}
_IMAGE_COOLDOWN = {}
_IMAGE_LOOP = None
_IMAGE_SLOTS = None
_IMAGE_CACHE_LIMIT = 16 * 1024 * 1024


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


def _cache_image(card_id,value):
    now=time.monotonic()
    _IMAGE_CACHE[card_id]=(now+(21600 if value else 30),value)
    _IMAGE_CACHE.move_to_end(card_id)
    for key,(expires,_) in list(_IMAGE_CACHE.items()):
        if expires<=now:_IMAGE_CACHE.pop(key,None)
    while len(_IMAGE_CACHE)>128 or sum(len(value or "") for _,value in _IMAGE_CACHE.values())>_IMAGE_CACHE_LIMIT:
        _IMAGE_CACHE.popitem(last=False)


def valid_card_image(data):
    return 0 < len(data) <= MAX_IMAGE_BYTES and (
        data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n") or
        data.startswith(b"RIFF") and data[8:12] == b"WEBP")


def _read_card_image(card_id):
    try:
        with (IMAGE_DIR / f"{int(card_id)}.img").open("rb") as file:
            data = file.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        return None
    if valid_card_image(data):
        return "base64://" + base64.b64encode(data).decode("ascii")
    return None


async def _fetch_card_image(card_id):
    async with _IMAGE_SLOTS:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4,connect=2),follow_redirects=True) as client:
            for template in (PRIMARY_IMG,FALLBACK_IMG,LEGACY_IMG):
                if _IMAGE_COOLDOWN.get(template,0)>time.monotonic():continue
                try:
                    r=await client.get(template.format(id=card_id))
                    if r.status_code>=500:
                        _IMAGE_COOLDOWN[template]=time.monotonic()+60
                        continue
                    content=r.content
                    image=(content.startswith(b"\xff\xd8\xff") or content.startswith(b"\x89PNG\r\n\x1a\n") or
                           content.startswith(b"RIFF") and content[8:12]==b"WEBP")
                    if r.status_code==200 and image and len(content)<=2*1024**2:
                        return "base64://"+base64.b64encode(content).decode("ascii")
                except httpx.HTTPError:
                    _IMAGE_COOLDOWN[template]=time.monotonic()+60
    return None


async def _load_card_image(card_id):
    value = await asyncio.to_thread(_read_card_image, card_id)
    if value:
        _cache_image(card_id, value)
        return value
    try:
        value=await asyncio.wait_for(_fetch_card_image(card_id),timeout=7)
    except asyncio.TimeoutError:value=None
    _cache_image(card_id,value)
    return value


async def download_image_base64(card_id: int) -> Optional[str]:
    global _IMAGE_LOOP,_IMAGE_SLOTS
    loop=asyncio.get_running_loop()
    if _IMAGE_LOOP is not loop:
        _IMAGE_LOOP=loop;_IMAGE_SLOTS=asyncio.Semaphore(6);_IMAGE_INFLIGHT.clear()
    cached=_IMAGE_CACHE.get(card_id)
    if cached and cached[0]>time.monotonic():
        _IMAGE_CACHE.move_to_end(card_id)
        return cached[1]
    task=_IMAGE_INFLIGHT.get(card_id)
    if task is None:
        task=asyncio.create_task(_load_card_image(card_id))
        _IMAGE_INFLIGHT[card_id]=task
        def clear(done):
            if _IMAGE_INFLIGHT.get(card_id) is done:_IMAGE_INFLIGHT.pop(card_id,None)
        task.add_done_callback(clear)
    return await asyncio.shield(task)
