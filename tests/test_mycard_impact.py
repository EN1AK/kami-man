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
