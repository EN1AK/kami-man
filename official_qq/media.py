"""Upload temporary QQ material for a single Markdown reply."""
import hashlib
from io import BytesIO
import re
from urllib.parse import urlsplit
from uuid import uuid4

from nonebot.adapters.qq.models import MessageMarkdown
from nonebot.drivers import Request
from PIL import Image


class VerifiedMarkdown(MessageMarkdown):
    force_verify_image_resource: bool = True


async def api(bot, method, *path, **kwargs):
    url = bot.adapter.get_api_base().joinpath("v2", "media-images", *path)
    return await bot._request(Request(method, url, timeout=10, **kwargs))


async def prepare(bot, raw):
    if not 0 < len(raw) <= 10_000_000:
        raise ValueError("bad material size")
    with Image.open(BytesIO(raw)) as image:
        fmt, (w, h) = image.format, image.size
        image.verify()
    if fmt not in {"PNG", "JPEG", "WEBP", "GIF"}:
        raise ValueError("bad material format")
    mime = "image/" + fmt.lower()
    name = f"kami-qq-{uuid4().hex}.{fmt.lower()}"
    digest = hashlib.md5(raw).hexdigest()
    info = await api(bot, "POST", "prepare", json={"file_name": name,
        "file_size": len(raw), "content_type": mime, "md5": digest,
        "sha1": hashlib.sha1(raw).hexdigest()})
    target = urlsplit(info["presigned_url"])
    if (target.scheme != "https" or not (target.hostname or "").endswith(".myqcloud.com")
            or target.username or target.password or target.port not in (None, 443)):
        raise ValueError("bad upload URL")
    response = await bot.adapter.request(Request("PUT", info["presigned_url"],
        content=raw, headers={"Content-Type": mime}, timeout=12))
    tag = next((v for k,v in response.headers.items() if k.lower()=="etag"), "").strip('"')
    if not 200 <= response.status_code < 300 or tag.lower()!=digest:
        raise ValueError("material upload failed")
    result = await api(bot, "POST", "complete", json={"upload_id": info["upload_id"], "md5": tag})
    ident = result["image_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", ident):
        raise ValueError("bad material ID")
    ref = result.get("url", "")
    if not re.fullmatch(r"qqbot-media://image/v1/[A-Za-z0-9_.~-]+", ref):
        await release(bot,ident,name)
        raise ValueError("bad material reference")
    return ident,name,f"![图片 #{w}px #{h}px]({ref})"


async def release(bot, ident, name):
    cursor=""; seen=set()
    for _ in range(5):
        page=await api(bot,"GET",**({"params":{"cursor":cursor}} if cursor else {}))
        for item in page.get("images",[]):
            if item.get("image_id")==ident:
                if item.get("file_name")==name:
                    await api(bot,"DELETE",ident,"delete")
                return
        cursor=page.get("next_cursor","")
        if not cursor or cursor in seen:return
        seen.add(cursor)
