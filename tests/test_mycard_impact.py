import asyncio
import json
from io import BytesIO
import time
from PIL import Image
import pytest
from services.mycard_archive.impact import summarize,impact_stats
from services.mycard_archive.store import ArchiveStore
from services.mycard_archive.outcomes import MatchResults
from services.mycard_archive import charts,reports


def sample(group,carry,won,player,extra=False):
    return dict(archetype=group,player=player,won=int(won),main=[900]+([1] if carry and not extra else []),extra=[1] if carry and extra else [])


def test_same_archetype_weighting_avoids_simpson_reversal():
    samples=[]
    for group,carry,n,wins in (("A",True,90,72),("A",False,10,9),("B",True,10,1),("B",False,90,18)):
        samples += [sample(group,carry,i<wins,f"P{i%3}") for i in range(n)]
    r=summarize(samples,{1:"卡",900:"必带"},min_samples=5)["main_rows"][0]
    assert r["card"]==1 and r["classes"]==2
    assert r["delta"]==pytest.approx(-.1)
    assert r["with_rate"]==pytest.approx(.45) and r["without_rate"]==pytest.approx(.55)
    assert r["with_n"]==r["without_n"]==100


def test_same_name_artworks_player_switches_and_separate_extra():
    samples=[]
    for i in range(60):
        s=sample("A",i<30,i<20,f"P{i%3}")
        if i<30:s["main"]=[1,11,900]
        s["extra"]=[1] if i>=30 else []
        samples.append(s)
    result=summarize(samples,{1:"卡",11:"卡",900:"必带"})
    r=result["main_rows"][0]
    assert len(result["main_rows"])==1 and r["with_n"]==r["without_n"]==30
    assert r["comparisons"][0]["with_players"]==r["comparisons"][0]["without_players"]==3
    assert result["extra_rows"][0]["delta"]==-r["delta"]
    assert result["main_uncomparable"]==1


def test_missing_controls_and_low_diversity_do_not_become_zero_effect():
    samples=[sample("A",True,True,"One") for _ in range(30)]+[sample("A",False,False,"Two") for _ in range(30)]
    result=summarize(samples,{1:"卡",900:"必带"})
    assert result["main_rows"]==[] and result["main_uncomparable"]==2


def test_impact_counts_only_ranked_actor_once_per_match(tmp_path):
    store=ArchiveStore(tmp_path);now=time.time()
    key,_=store.begin({"id":"room"},["A","B"],{"A":50,"B":200},now-1000)
    with store.connect() as db:
        db.execute("UPDATE matches SET status='complete',normal_end=1,finished=? WHERE id=?",(now-100,key))
        for player in ("A","B"):
            db.execute("INSERT INTO observations VALUES(?,?,?,?)",(key,player,now-1000,json.dumps(dict(main=[1]*40,extra=[],side=[999]))))
    MatchResults(store).save(key,dict(fingerprint="one",winner="B",record={}),now=now)
    classify=lambda d,p:"A"
    a=impact_stats(store,now=now,classifier=classify,names={})
    b=impact_stats(store,now=now,classifier=classify,names={},rank_cutoff=500)
    assert a["samples"]==a["players"]==1 and b["samples"]==b["players"]==2
    assert a["main_uncomparable"]==1 and a["main_rows"]==[]
    with pytest.raises(ValueError):impact_stats(store,rank_cutoff=200)


def impact_fixture():
    samples=[sample("A",i<30,i<20,f"P{i%3}") for i in range(60)]
    return dict(days=30,rank_cutoff=100,samples=60,players=3,minimum_samples=20,minimum_players=3,**summarize(samples,{1:"测试卡",900:"必带卡"}))


def test_impact_png_empty_and_populated():
    data=impact_fixture()
    for extra in (False,True):
        raw=charts.render_impact(data,"北京时间",extra=extra)
        assert Image.open(BytesIO(raw)).format=="PNG" and len(raw)<4*1024**2


def test_impact_sections_share_snapshot_but_scopes_do_not(tmp_path,monkeypatch):
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts")
    calls=[]
    def build(store,days,now,rank_cutoff=100):
        calls.append(rank_cutoff);d=impact_fixture();d["rank_cutoff"]=rank_cutoff;return d
    monkeypatch.setattr(reports,"impact_stats",build)
    monkeypatch.setattr(reports,"render_impact",lambda d,stamp,page,extra:b"\x89PNG\r\n\x1a\n"+str((d["rank_cutoff"],extra)).encode())
    async def run():
        a=await service.image("impact")
        b=await service.image("impact-extra")
        c=await service.image("impact",rank_cutoff=500)
        assert len({a,b,c})==3
        assert await service.image("impact")==a
    asyncio.run(run())
    assert calls==[100,500]



def test_archetype_groups_sorted_by_appearances_then_card_delta():
    from services.mycard_archive.impact import ordered_impact_rows
    def row(card,name,n,delta):
        return dict(card=card,name=str(card),delta=delta,with_n=n//2,without_n=n-n//2,
                    comparisons=[dict(archetype=name,with_n=n//2,without_n=n-n//2)])
    cold=row(1,"A冷门",40,.9);hot1=row(2,"Z热门",100,.1);hot2=row(3,"Z热门",100,.3)
    data=dict(main_rows=[cold,hot1,hot2])
    assert [r["card"] for r in ordered_impact_rows(data)]==[3,2,1]


def test_impact_batch_uses_one_snapshot_for_five_pages(tmp_path,monkeypatch):
    service=reports.ChartReports(ArchiveStore(tmp_path/"archive"),tmp_path/"charts")
    calls=[]
    async def snapshot(kind,days,now,rank_cutoff):
        calls.append((kind,days,rank_cutoff))
        return dict(day="2026-10-27",key="impact-top100-30",generated_at="北京时间",data=dict(main_rows=[{}]*100,extra_rows=[]))
    monkeypatch.setattr(service,"snapshot",snapshot)
    monkeypatch.setattr(reports,"render_impact",lambda d,stamp,page,extra:b"\x89PNG\r\n\x1a\n"+str(page).encode())
    images=asyncio.run(service.impact_images())
    assert len(images)==5 and images[0].endswith(b"1") and images[-1].endswith(b"5")
    assert calls==[("impact",30,100)]
    assert len(list((tmp_path/"charts").glob("*.png")))==5


@pytest.mark.parametrize("group",[True,False])
def test_default_impact_command_sends_one_forward_record_with_five_images(tmp_path,monkeypatch,group):
    from types import SimpleNamespace
    from nonebot.adapters.onebot.v11 import Message
    from services.mycard_archive import commands
    registry={}
    class Matcher:
        def handle(self):
            def attach(fn):self.handler=fn;return fn
            return attach
    def command(name,**kwargs):registry[name]=Matcher();return registry[name]
    monkeypatch.setattr(commands,"on_command",command)
    store=ArchiveStore(tmp_path/"archive");factory=commands.register_commands(lambda:store,lambda:None)
    batches=[];sent=[]
    async def pages(days,rank_cutoff=100,extra=False):
        batches.append((days,rank_cutoff,extra));return [b"fixture"]*5
    monkeypatch.setattr(factory(),"impact_images",pages)
    class Bot:
        self_id="12345"
        async def send(self,*args):raise AssertionError("No separate image messages")
        async def call_api(self,name,**kwargs):sent.append((name,kwargs))
    event=SimpleNamespace(user_id=456,**({"group_id":789} if group else {}))
    asyncio.run(registry["卡片影响度"].handler(Bot(),event,Message("前500 7 额外")))
    assert batches==[(7,500,True)] and len(sent)==1
    name,args=sent[0]
    assert name==("send_group_forward_msg" if group else "send_private_forward_msg")
    assert len(args["messages"])==5
    for node in args["messages"]:
        assert node["type"]=="node"
        assert any(segment.type=="image" for segment in node["data"]["content"])
