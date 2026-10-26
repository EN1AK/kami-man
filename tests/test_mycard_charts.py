import asyncio
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from PIL import Image
import pytest
from services.mycard_archive import charts,reports
from services.mycard_archive.store import ArchiveStore

def usage(rows=2):
    return dict(total=100,covered=80,missing=20,stale=1,extra_rows=[],
        rows=[dict(card=i+1,players=40,copies=80,main=40,extra=0,rate=.5) for i in range(rows)])

def matchup():
    return dict(days=30,eligible=30,used=25,missing_result=3,missing_deck=1,unclassified=1,
        rows=[dict(a="测试卡组甲",b="测试卡组乙",matches=20,a_wins=12,b_wins=8),
              dict(a="测试卡组甲",b="测试卡组甲",matches=5,a_wins=0,b_wins=0)])

@pytest.mark.parametrize("kind",["usage","matchups","empty"])
def test_render_png_with_chinese_and_empty_samples(kind):
    if kind=="usage":raw=charts.render_usage(usage(),{1:"测试卡片甲",2:"测试卡片乙"},"2026-10-26 10:00 北京时间")
    elif kind=="matchups":raw=charts.render_matchups(matchup(),"2026-10-26 10:00 北京时间")
    else:raw=charts.render_usage(usage(0),{},"2026-10-26 10:00 北京时间")
    image=Image.open(BytesIO(raw))
    assert image.format=="PNG" and image.width>=1000 and image.height>=700
    assert len(raw)<4*1024**2

def stub(monkeypatch,calls):
    async def players(session):calls.append("ranking");await asyncio.sleep(0);return ["fixture"]
    monkeypatch.setattr(reports,"top_players",players)
    monkeypatch.setattr(reports,"card_usage",lambda *args:usage(22))
    monkeypatch.setattr(reports,"card_names",lambda *args:{1:"测试卡"})
    monkeypatch.setattr(reports,"render_usage",lambda data,names,stamp,page: b"\x89PNG\r\n\x1a\n"+str(page).encode())

def test_same_day_pages_share_snapshot_next_day_refreshes(tmp_path,monkeypatch):
    calls=[];stub(monkeypatch,calls)
    now=[datetime(2026,10,26,12,tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()]
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts",clock=lambda:now[0])
    async def run():
        first=await service.image("usage")
        assert first==await service.image("usage")
        await service.image("usage",2)
        assert calls==["ranking"]
        now[0]+=86400
        await service.image("usage")
        assert calls==["ranking","ranking"]
    asyncio.run(run())

def test_concurrent_requests_do_not_duplicate_daily_build(tmp_path,monkeypatch):
    calls=[];stub(monkeypatch,calls)
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts")
    async def run():
        result=await asyncio.gather(*(service.image("usage") for _ in range(6)))
        assert len(set(result))==1
    asyncio.run(run())
    assert calls==["ranking"]

def test_refresh_only_builds_two_default_images(tmp_path,monkeypatch):
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts")
    called=[]
    async def image(kind,page=1,days=30):called.append((kind,days));return b""
    monkeypatch.setattr(service,"image",image)
    asyncio.run(service.refresh())
    assert called==[("usage",30),("extra",30),("matchups",30)]

def test_pruning_retention_and_size_does_not_delete_other_files(tmp_path,monkeypatch):
    store=ArchiveStore(tmp_path/"archive");root=tmp_path/"charts";root.mkdir()
    service=reports.ChartReports(store,root)
    (root/"2026-10-20-usage-p1.png").write_bytes(b"x"*20)
    (root/"2026-10-26-usage.json").write_bytes(b"x"*10)
    (root/"2026-10-26-usage-p1.png").write_bytes(b"x"*20)
    (root/"2026-10-26-usage-p2.png").write_bytes(b"x"*20)
    (root/"unrelated.txt").write_text("keep",encoding="utf-8")
    monkeypatch.setattr(reports,"CACHE_LIMIT",30)
    service.prune("2026-10-26")
    assert not (root/"2026-10-20-usage-p1.png").exists()
    assert (root/"unrelated.txt").exists() and (root/"2026-10-26-usage.json").exists()
    assert sum(p.stat().st_size for p in root.glob("*.png"))<=20

def test_chart_parameters_rejected_before_network(tmp_path):
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts")
    async def run():
        for args in (("unknown",1,30),("usage",0,30),("matchups",1,91)):
            with pytest.raises(ValueError):await service.image(*args)
    asyncio.run(run())


def test_query_commands_send_images_only_when_triggered(tmp_path,monkeypatch):
    from services.mycard_archive import commands
    from nonebot.adapters.onebot.v11 import Message
    registered={}
    class Matcher:
        def handle(self):
            def attach(fn):self.handler=fn;return fn
            return attach
    def command(name,**kwargs):
        registered[name]=Matcher();return registered[name]
    monkeypatch.setattr(commands,"on_command",command)
    store=ArchiveStore(tmp_path/"archive")
    factory=commands.register_commands(lambda:store,lambda:None)
    calls=[];sent=[]
    async def image(kind,page=1,days=30):calls.append((kind,page,days));return b"fixture-png"
    monkeypatch.setattr(factory(),"image",image)
    class Bot:
        async def send(self,event,message):sent.append(message)
    assert not sent and not calls
    async def run():
        await registered["前百卡片使用率"].handler(Bot(),SimpleNamespace(),Message(""))
        await registered["卡组对阵胜率"].handler(Bot(),SimpleNamespace(),Message("7 2"))
        await registered["额外卡组使用率"].handler(Bot(),SimpleNamespace(),Message(""))
    asyncio.run(run())
    assert calls==[("usage",1,30),("matchups",2,7),("extra",1,30)]
    assert len(sent)==3 and all(m.type=="image" for m in sent)


def test_extra_chart_uses_separate_rows():
    data=usage(0)
    data["extra_rows"]=[dict(card=9,players=40,copies=40,rate=.5)]
    raw=charts.render_extra(data,{9:"额外测试卡"},"2026-10-26 北京时间")
    assert Image.open(BytesIO(raw)).format=="PNG"
