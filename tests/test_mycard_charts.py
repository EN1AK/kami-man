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
    async def players(session,store):calls.append("ranking");await asyncio.sleep(0);return ["fixture"]
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
    async def image(kind,page=1,days=30,rank_cutoff=100):called.append((kind,days,rank_cutoff));return b""
    monkeypatch.setattr(service,"image",image)
    asyncio.run(service.refresh())
    assert called==[("usage",30,100),("extra",30,100),("matchups",30,100),("matchups",30,500),("impact",30,100),("impact",30,500)]

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
        for args in (("unknown",1,30),("usage",0,30),("matchups",1,91),("matchups",2,30)):
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
    async def image(kind,page=1,days=30,rank_cutoff=100):calls.append((kind,page,days,rank_cutoff));return b"fixture-png"
    monkeypatch.setattr(factory(),"image",image)
    class Bot:
        async def send(self,event,message):sent.append(message)
    assert not sent and not calls
    async def run():
        await registered["卡片使用率"].handler(Bot(),SimpleNamespace(),Message(""))
        await registered["卡组对阵胜率"].handler(Bot(),SimpleNamespace(),Message("7"))
        await registered["额外卡组使用率"].handler(Bot(),SimpleNamespace(),Message(""))
        await registered["卡组对阵胜率"].handler(Bot(),SimpleNamespace(),Message("前500 7"))
        await registered["卡片影响度"].handler(Bot(),SimpleNamespace(),Message("30 1"))
        await registered["卡片影响度"].handler(Bot(),SimpleNamespace(),Message("前500 7 2 额外"))
    asyncio.run(run())
    assert calls==[("usage",1,30,100),("matchups",1,7,100),("extra",1,30,100),("matchups",1,7,500),("impact",1,30,100),("impact-extra",2,7,500)]
    assert len(sent)==6 and all(m.type=="image" for m in sent)


def test_extra_chart_uses_separate_rows():
    data=usage(0)
    data["extra_rows"]=[dict(card=9,players=40,copies=40,rate=.5)]
    raw=charts.render_extra(data,{9:"额外测试卡"},"2026-10-26 北京时间")
    assert Image.open(BytesIO(raw)).format=="PNG"


@pytest.mark.parametrize("distribution",[{1:1,2:1,3:2},{"1":1,"2":1,"3":2}])
def test_copy_distribution_uses_carriers_and_survives_json(distribution):
    value=charts.copy_text({"players":4,"distribution":distribution})
    assert "1张 25.0%" in value and "2张 25.0%" in value and "3张 50.0%" in value
    assert "4+" not in value


def test_copy_distribution_keeps_large_observed_bucket():
    assert "4+张 50.0%" in charts.copy_text({"players":2,"distribution":{1:1,"4+":1}})



def test_matchup_matrix_direction_mirror_and_missing_samples():
    from services.mycard_archive.statistics import matchup_matrix
    data=dict(rows=[dict(a="A",b="B",matches=10,a_wins=3,b_wins=7),
                    dict(a="A",b="A",matches=5,a_wins=0,b_wins=0),
                    dict(a="C",b="C",matches=1,a_wins=0,b_wins=0)])
    m=matchup_matrix(data)
    assert m["names"]==["A","B","C"] and m["appearances"]==[20,10,2]
    assert m["rates"][0][1]==.3 and m["rates"][1][0]==.7
    assert m["rates"][0][0] is None and m["samples"][0][0]==5
    assert m["rates"][0][2] is None and m["samples"][0][2]==0
    assert m["shown_matches"]==16


def test_matchup_matrix_only_top20_and_counts_unique_included_matches():
    from services.mycard_archive.statistics import matchup_matrix
    rows=[dict(a=f"P{i:02}",b=f"P{i:02}",matches=i+1,a_wins=0,b_wins=0) for i in range(21)]
    m=matchup_matrix(dict(rows=rows))
    assert len(m["names"])==20 and m["names"][0]=="P20" and "P00" not in m["names"]
    assert m["shown_matches"]==sum(range(2,22))
    assert len(m["rates"])==20 and all(len(r)==20 for r in m["rates"])


def test_matchup_heatmap_empty_and_invalid_page():
    data=matchup();data["rows"]=[]
    assert Image.open(BytesIO(charts.render_matchups(data,"北京时间"))).format=="PNG"
    with pytest.raises(ValueError):charts.render_matchups(matchup(),"北京时间",2)



def test_matchup_scope_snapshots_and_images_are_independent(tmp_path,monkeypatch):
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts")
    calls=[]
    def build(store,days,now,rank_cutoff=100):
        calls.append(rank_cutoff);data=matchup();data["rank_cutoff"]=rank_cutoff;return data
    monkeypatch.setattr(reports,"matchup_stats",build)
    monkeypatch.setattr(reports,"render_matchups",lambda data,*args:b"\x89PNG\r\n\x1a\n"+str(data["rank_cutoff"]).encode())
    async def run():
        a=await service.image("matchups")
        b=await service.image("matchups",rank_cutoff=500)
        assert a!=b and a.endswith(b"100") and b.endswith(b"500")
        assert await service.image("matchups")==a
        assert await service.image("matchups",rank_cutoff=500)==b
        with pytest.raises(ValueError):await service.image("matchups",rank_cutoff=200)
    asyncio.run(run())
    assert calls==[100,500]
    assert len(list((tmp_path/"charts").glob("*matchups-top*-30.json")))==2
