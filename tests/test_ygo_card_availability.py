import asyncio
import base64
from collections import OrderedDict
import importlib
import httpx
import pytest
from services import ygo_api


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(ygo_api,"_IMAGE_CACHE",OrderedDict())
    monkeypatch.setattr(ygo_api,"_IMAGE_INFLIGHT",{})
    monkeypatch.setattr(ygo_api,"_IMAGE_COOLDOWN",{})
    monkeypatch.setattr(ygo_api,"_IMAGE_LOOP",None)



@pytest.fixture
def plugin(monkeypatch):
    import nonebot
    import importlib.util
    class Matcher:
        def handle(self):return lambda fn:fn
    monkeypatch.setattr(nonebot,"on_command",lambda *args,**kwargs:Matcher())
    spec=importlib.util.spec_from_file_location("isolated_ygo_card", "plugins/ygo_card.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def client_factory(monkeypatch,handler):
    real=httpx.AsyncClient
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(ygo_api.httpx,"AsyncClient",lambda **kwargs:real(transport=transport))


def test_image_cache_and_inflight_requests_are_deduplicated(monkeypatch):
    calls=[]
    async def handler(request):
        calls.append(str(request.url));await asyncio.sleep(.01)
        return httpx.Response(200,content=b"\xff\xd8\xfffixture")
    client_factory(monkeypatch,handler)
    async def run():
        values=await asyncio.gather(*(ygo_api.download_image_base64(1) for _ in range(8)))
        assert len(set(values))==1 and values[0].startswith("base64://")
        assert await ygo_api.download_image_base64(1)==values[0]
    asyncio.run(run())
    assert len(calls)==1


def test_timeout_fallback_and_source_cooldown(monkeypatch):
    calls=[]
    async def handler(request):
        calls.append(request.url.host)
        if request.url.host=="cdncf.moecube.com":raise httpx.ConnectTimeout("unavailable",request=request)
        return httpx.Response(200,content=b"\xff\xd8\xfffixture")
    client_factory(monkeypatch,handler)
    async def run():
        assert await ygo_api.download_image_base64(1)
        assert await ygo_api.download_image_base64(2)
    asyncio.run(run())
    assert calls==["cdncf.moecube.com","cdn02.moecube.com","cdn02.moecube.com"]


def test_html_not_sent_as_image_and_negative_results_cached(monkeypatch):
    calls=[]
    async def handler(request):calls.append(request);return httpx.Response(200,content=b"<html>unavailable</html>")
    client_factory(monkeypatch,handler)
    async def run():
        assert await ygo_api.download_image_base64(1) is None
        assert await ygo_api.download_image_base64(1) is None
    asyncio.run(run())
    assert len(calls)==3


def test_batch_image_fetch_concurrency_and_original_order(monkeypatch,plugin):
    ygo_card=plugin
    active=peak=0
    async def image(code):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.005*(6-code%5));active-=1
        return None
    monkeypatch.setattr(ygo_card,"download_image_base64",image)
    cards=[dict(id=i,cn_name=f"Card{i}") for i in range(15)]
    messages=asyncio.run(ygo_card.build_card_messages(cards))
    assert peak==5 and len(messages)==15
    assert all(f"Card{i}" in str(m) and "卡图暂不可用" in str(m) for i,m in enumerate(messages))


def test_slow_batch_returns_text_within_deadline(monkeypatch,plugin):
    ygo_card=plugin
    real_wait=asyncio.wait
    async def short_wait(tasks,timeout):return await real_wait(tasks,timeout=.01)
    async def slow(code):await asyncio.sleep(20)
    monkeypatch.setattr(ygo_card.asyncio,"wait",short_wait)
    monkeypatch.setattr(ygo_card,"download_image_base64",slow)
    cards=[dict(id=i,cn_name=f"Card{i}") for i in range(25)]
    messages=asyncio.run(ygo_card.build_card_messages(cards))
    assert len(messages)==25 and all("卡图暂不可用" in str(m) for m in messages)
