import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from services import card_translation as card


def test_signed_image_url_and_proxy_prefix_are_preserved(monkeypatch):
    monkeypatch.setenv("YGO_RAG_AGENT_API_URL", "http://rag.example/prefix/api/agent")
    real_client = httpx.AsyncClient
    def handler(request):
        import json
        if request.method == "GET":
            assert str(request.url) == "https://gchat.qpic.cn/a?rkey=a%2Bb&x=1"
            return httpx.Response(200, content=b"\xff\xd8\xfftest")
        assert str(request.url) == "http://rag.example/prefix/api/card-translate"
        assert json.loads(request.content) == {"images": ["data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xfftest").decode("ascii")]}
        return httpx.Response(200, json={"translation": "中文卡名：测试\n效果：测试"})
    monkeypatch.setattr(card.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    image = SimpleNamespace(data={"url": "https://gchat.qpic.cn/a?rkey=a%2Bb&x=1"})
    result = asyncio.run(card.translate_card_image(SimpleNamespace(), image))
    assert "中文卡名" in result.translation
    assert result.original_image == "base64://" + base64.b64encode(b"\xff\xd8\xfftest").decode("ascii")


def test_get_image_fallback_and_unreadable_error(monkeypatch):
    monkeypatch.setattr(card, "download_qq_image", AsyncMock(return_value="data:image/jpeg;base64,/9j/"))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(card.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(422, json={"error": "unreadable"})), **kwargs))
    bot = SimpleNamespace(call_api=AsyncMock(return_value={"url": "https://example.com/card.jpg"}))
    with pytest.raises(card.CardImageError, match="清晰"):
        asyncio.run(card.translate_card_image(bot, SimpleNamespace(data={"file": "opaque-image-id"})))
    bot.call_api.assert_awaited_once_with("get_image", file="opaque-image-id")


def test_missing_image_url_is_actionable():
    with pytest.raises(card.CardImageError, match="重新发送"):
        asyncio.run(card.translate_card_image(SimpleNamespace(), SimpleNamespace(data={})))


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "file:///a", "https://qpic.cn.attacker.example/a", "https://user:pass@gchat.qpic.cn/a"])
def test_image_download_rejects_non_qq_hosts(url):
    with pytest.raises(card.CardImageError, match="上传卡图"):
        asyncio.run(card.download_qq_image(url))


@pytest.mark.parametrize("status,content,expected", [(302, b"", "下载失败"), (200, b"<html>expired</html>", "格式"), (200, b"\xff\xd8\xff" + b"x" * 30, "过大")])
def test_download_rejects_redirects_non_images_and_oversize(monkeypatch, status, content, expected):
    monkeypatch.setattr(card, "MAX_IMAGE_BYTES", 20)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(card.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content)), **kwargs))
    with pytest.raises(card.CardImageError, match=expected):
        asyncio.run(card.download_qq_image("https://gchat.qpic.cn/a"))
