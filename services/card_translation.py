"""Translate a QQ card image through the RAG service's vision endpoint."""
import base64
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.ygo_rag_agent_api import YgoRagAgentSettings
from services.ygo_rag_translation_api import parse_translation_response


@dataclass(frozen=True)
class CardImageTranslation:
    translation: str
    original_image: str


class CardImageError(ValueError):
    pass


MAX_IMAGE_BYTES = 10 * 1024 * 1024
QQ_IMAGE_DOMAINS = ("qq.com", "qq.com.cn", "qpic.cn", "gtimg.cn", "qlogo.cn")


async def download_qq_image(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (parts.scheme not in {"https", "http"} or parts.username or parts.password
            or parts.port not in {None, 80, 443}
            or not any(host == domain or host.endswith("." + domain) for domain in QQ_IMAGE_DOMAINS)):
        raise CardImageError("无法读取此卡图链接，请直接上传卡图到群聊。")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise CardImageError("卡图过大，请发送不超过 10 MB 的图片。")
    except httpx.HTTPError as exc:
        raise CardImageError("卡图下载失败或链接已过期，请重新发送原图。") from exc
    data = bytes(content)
    if data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise CardImageError("请发送 JPG、PNG、GIF 或 WebP 格式的卡图。")
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def card_images(event):
    """Only use images attached to this message, never unrelated chat history."""
    return [seg for seg in event.message if seg.type == "image"]


async def translate_card_image(bot, image):
    url = image.data.get("url")
    if not url:
        file = image.data.get("file", "")
        if str(file).startswith(("https://", "http://")):
            url = file
        elif file:
            info = await bot.call_api("get_image", file=file)
            url = info.get("url")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise CardImageError("无法获取卡图，请重新发送原图后再试。")

    image_data = await download_qq_image(url)

    settings = YgoRagAgentSettings.from_env()
    parts = urlsplit(settings.api_url)
    # Derive the endpoint from the same service, including any proxy prefix.
    path = parts.path.rsplit("/", 1)[0] + "/card-translate"
    endpoint = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
        response = await client.post(endpoint, json={"images": [image_data]})
        if response.status_code == 422:
            raise CardImageError("无法完整识别卡名或效果，请发送清晰、完整的单张卡图。")
        response.raise_for_status()
    translated = parse_translation_response(response.json())
    return CardImageTranslation(translated.translation, "base64://" + image_data.partition(",")[2])
