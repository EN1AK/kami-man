import asyncio,json,time
from types import SimpleNamespace
import pytest
from services.mycard_archive.store import ArchiveStore
from services.mycard_archive.tracking import TrackingStore
from services.mycard_archive.outcomes import MatchResults,match_result
from services.mycard_archive.statistics import card_usage,usage_text,matchup_stats,matchup_text,usable,page_rows
from services.mycard_archive.collector import Collector,ArchiveConfig,RoomState

def deck(card):
    return {"player":"fixture","main":[card]*40,"extra":[card+100],"side":[999]}

def archived(store,room,when,*,players=("Alice","Bob"),ranks=None,winner=None,cards=(1,2),complete=True):
    key,_=store.begin({"id":room},list(players),ranks or {players[0]:50,players[1]:200},when)
    with store.connect() as db:
        db.execute("UPDATE matches SET status=?,normal_end=?,finished=? WHERE id=?",
                   ("complete" if complete else "partial",int(complete),when+600,key))
        for player,card in zip(players,cards):
            db.execute("INSERT INTO observations VALUES (?,?,?,?)",(key,player,when,json.dumps(deck(card))))
    if winner:
        MatchResults(store).save(key,{"fingerprint":room,"winner":winner,"record":{"winner":winner}},now=when+600)
    return key

def test_targets_persist_exact_names_and_removal(tmp_path):
    store=ArchiveStore(tmp_path);targets=TrackingStore(store)
    targets.set("Alice");targets.set("Alice")
    assert TrackingStore(store).players()==["Alice"]
    assert "alice" not in targets.players()
    targets.set("Alice",False)
    assert targets.players()==[]
    with pytest.raises(ValueError):targets.set("")

def test_target_limit_allows_existing_member(tmp_path):
    targets=TrackingStore(ArchiveStore(tmp_path))
    for n in range(100):targets.set(str(n))
    targets.set("0")
    with pytest.raises(ValueError):targets.set("overflow")

def test_target_bypasses_rank_cutoff_without_inventing_rank(tmp_path):
    async def run():
        c=Collector(ArchiveConfig(tmp_path,tmp_path/"missing"))
        class Rank:
            async def qualifying(self,players):return {},{"Alice":999,"Bob":800}
            async def close(self):pass
        c.rank=Rank()
        try:
            assert (await c.qualify(["Alice","Bob"]))[0]=={}
            c.tracked={"Alice"}
            accepted,ranks=await c.qualify(["Alice","Bob"])
            assert accepted=={"Alice":999} and ranks["Alice"]==999
            async def fail(players):raise ValueError("rank unavailable")
            c.rank.qualifying=fail
            accepted,ranks=await c.qualify(["Alice","Bob"])
            assert accepted=={"Alice":None} and ranks=={}
            c.tracked=set()
            with pytest.raises(ValueError):await c.qualify(["Alice","Bob"])
        finally:await c.close()
    asyncio.run(run())

def test_new_target_reconsiders_previously_excluded_live_room(tmp_path):
    async def run():
        c=Collector(ArchiveConfig(tmp_path,tmp_path/"missing"))
        state=RoomState({"id":"room"},["Alice","Bob"])
        state.task=asyncio.create_task(asyncio.sleep(0));await state.task
        c.rooms["room"]=state
        called=[]
        async def collect(s):called.append(s)
        c.collect=collect
        try:
            await c.set_target("Alice")
            await state.task
            assert called==[state] and TrackingStore(c.store).players()==["Alice"]
        finally:await c.close()
    asyncio.run(run())

def official(start="2026-10-26T04:08:16.000Z",end="2026-10-26T04:26:44Z",winner="Alice"):
    return dict(usernamea="Alice",usernameb="Bob",start_time=start,end_time=end,winner=winner,pta=1600,ptb=1400)

def match_fixture():
    return dict(players=["Alice","Bob"],finished=1792988816)

def test_outcome_unique_time_pair_and_winner():
    rounds=[{"start_time":1792987698}]
    result=match_result(match_fixture(),rounds,[official()])
    assert result["winner"]=="Alice"
    assert match_result(match_fixture(),rounds,[official(),official()])==result
    assert match_result(match_fixture(),rounds,[official(winner="Nobody")]) is None
    assert match_result(match_fixture(),rounds,[official(start="2026-10-25T04:08:16Z")]) is None
    assert match_result(match_fixture(),[],[official()]) is None
    assert match_result(match_fixture(),rounds,[official(),official(start="2026-10-26T04:08:20Z")]) is None

def test_official_match_cannot_be_reused_for_two_archives(tmp_path):
    store=ArchiveStore(tmp_path);results=MatchResults(store)
    a=archived(store,"a",100);b=archived(store,"b",100)
    result=match_result(match_fixture(),[{"start_time":1792987698}],[official()])
    results.save(a,result);results.save(b,result)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(winner) FROM official_match_results").fetchone()[0]==1

def test_pending_only_complete_and_backoff(tmp_path):
    now=time.time();store=ArchiveStore(tmp_path);results=MatchResults(store)
    a=archived(store,"a",now-1000)
    archived(store,"partial",now-1000,complete=False)
    assert [r["id"] for r in results.pending(now=now)]==[a]
    results.save(a,None,now=now)
    assert results.pending(now=now)==[]
    assert len(results.pending(now=now+1801))==1

def test_usage_latest_version_includes_side_and_separates_extra(tmp_path):
    store=ArchiveStore(tmp_path)
    archived(store,"old",100,cards=(1,2))
    archived(store,"new",200,cards=(3,2))
    data=card_usage(store,["Alice","Bob","Missing"],now=1000)
    assert data["covered"]==2 and data["missing"]==1
    rows={x["card"]:x for x in data["rows"]}
    assert 1 not in rows and 999 in rows
    assert rows[999]["side"]==2 and rows[999]["rate"]==1
    assert 103 not in rows and 103 in {x["card"] for x in data["extra_rows"]}
    assert rows[3]["players"]==1 and rows[3]["rate"]==.5 and rows[3]["copies"]==40
    assert "1/2人" in usage_text(data)
    assert not usable({"main":[1],"extra":[]})

def test_matchups_use_confirmed_matches_not_replay_count(tmp_path):
    store=ArchiveStore(tmp_path);results=MatchResults(store);now=time.time()
    archived(store,"win",now-1000,winner="Alice")
    archived(store,"loss",now-900,winner="Bob")
    archived(store,"unverified",now-800)
    archived(store,"not-top100",now-700,ranks={"Alice":101,"Bob":200},winner="Alice")
    archived(store,"mirror",now-600,cards=(1,1),winner="Alice")
    archived(store,"unknown",now-500,cards=(4,2),winner="Alice")
    def classify(deck,rules):
        return {1:"A",2:"B"}.get(deck.main[0],"未识别")
    data=matchup_stats(store,now=now,classifier=classify)
    assert data["eligible"]==5 and data["used"]==3 and data["missing_result"]==1 and data["unclassified"]==1
    pair=next(x for x in data["rows"] if x["a"]!=x["b"])
    assert pair=={"a":"A","b":"B","matches":2,"a_wins":1,"b_wins":1}
    text=matchup_text(data)
    assert "50.0%" in text and "内战" in text and "小样本" in text
    with pytest.raises(ValueError):page_rows(data["rows"],0)
    with pytest.raises(ValueError):matchup_stats(store,days=91)


def test_pending_prioritizes_top100(tmp_path):
    now=time.time();store=ArchiveStore(tmp_path);results=MatchResults(store)
    archived(store,"new-outside",now-100,ranks={"Alice":200,"Bob":300})
    expected=archived(store,"older-top100",now-1000,ranks={"Alice":100})
    assert results.pending(limit=1,now=now)[0]["id"]==expected


def test_commands_register_permissions_and_persist_without_live_collector(tmp_path,monkeypatch):
    from services.mycard_archive import commands
    from nonebot.adapters.onebot.v11 import Message
    from nonebot.permission import SUPERUSER
    registry={}
    class Matcher:
        def __init__(self,options):self.options=options
        def handle(self):
            def register(fn):self.handler=fn;return fn
            return register
    def command(name,**options):
        registry[name]=Matcher(options);return registry[name]
    monkeypatch.setattr(commands,"on_command",command)
    store=ArchiveStore(tmp_path)
    commands.register_commands(lambda:store,lambda:None)
    assert len(registry)==6
    for name in ("卡组采集","停止卡组采集","卡组采集列表"):
        assert registry[name].options["permission"] is SUPERUSER
    assert "permission" not in registry["前百卡片使用率"].options
    sent=[]
    class Bot:
        async def send(self,event,message):sent.append(str(message))
    async def run():
        bot=Bot();event=SimpleNamespace()
        await registry["卡组采集"].handler(bot,event,Message("Alice"))
        assert TrackingStore(store).players()==["Alice"]
        await registry["卡组采集列表"].handler(bot,event)
        assert "Alice" in sent[-1]
        await registry["停止卡组采集"].handler(bot,event,Message("Alice"))
        assert TrackingStore(store).players()==[]
    asyncio.run(run())


def test_card_names_uses_local_configured_catalog(tmp_path,monkeypatch):
    import sqlite3
    from services.mycard_archive.statistics import card_names
    path=tmp_path/"cards.cdb"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE texts(id INTEGER PRIMARY KEY,name TEXT)")
        db.execute("INSERT INTO texts VALUES (1,'测试卡')")
    monkeypatch.setenv("MYCARD_CARD_DB",str(path))
    assert card_names([1,1,2])=={1:"测试卡"}


def test_main_side_union_does_not_double_count_same_player(tmp_path):
    store=ArchiveStore(tmp_path);key=archived(store,"overlap",100)
    with store.connect() as db:
        value=deck(1);value["side"]=[1,777]
        db.execute("UPDATE observations SET deck=? WHERE match_id=? AND player='Alice'",(json.dumps(value),key))
    result=card_usage(store,["Alice","Bob"],now=1000)
    row=next(x for x in result["rows"] if x["card"]==1)
    assert row["main"]==1 and row["side"]==1 and row["players"]==1 and row["rate"]==.5
    assert 101 not in {x["card"] for x in result["rows"]}

def test_side_uses_accumulated_observations_of_latest_same_version(tmp_path):
    store=ArchiveStore(tmp_path)
    for room,when,side in (("first",100,[777]),("second",200,[888])):
        key=archived(store,room,when)
        value=deck(1);value["side"]=side
        with store.connect() as db:
            db.execute("UPDATE observations SET deck=? WHERE match_id=? AND player='Alice'",(json.dumps(value),key))
    data=card_usage(store,["Alice"],now=1000)
    assert {777,888}<={x["card"] for x in data["rows"]}
    assert data["side_observed"]==1

def test_each_card_list_is_limited_to_top100(tmp_path):
    store=ArchiveStore(tmp_path);players=[]
    for i in range(8):
        player=f"P{i}";players.append(player)
        key=archived(store,str(i),100+i,players=(player,f"Opponent{i}"))
        value={"player":player,"main":list(range(1000+i*40,1040+i*40)),"extra":list(range(10000+i*15,10015+i*15)),"side":[]}
        with store.connect() as db:
            db.execute("UPDATE observations SET deck=? WHERE match_id=? AND player=?",(json.dumps(value),key,player))
    data=card_usage(store,players,now=1000,names={})
    assert data["total_cards"]==320 and data["extra_total_cards"]==120
    assert len(data["rows"])==len(data["extra_rows"])==100


def test_same_names_merge_before_player_and_copy_counts():
    decks={
        "A":{"main":[1,2]+[900]*38,"side":[3],"extra":[11,12]},
        "B":{"main":[2]+[900]*39,"side":[],"extra":[12]},
        "C":{"main":[1,3]+[900]*38,"side":[],"extra":[11]*3},
        "D":{"main":[900]*40,"side":[],"extra":[]},
    }
    store=SimpleNamespace(latest=decks.get)
    data=card_usage(store,list(decks)+["Missing"],now=1000,
                    names={1:" 测试卡 ",2:"测试卡",3:"测试卡",11:"额外卡",12:"额外卡"})
    row=next(r for r in data["rows"] if r["card"]==1)
    assert row["name"]=="测试卡" and row["players"]==3 and row["rate"]==.75
    assert row["main"]==3 and row["side"]==1 and row["copies"]==6
    assert row["distribution"]=={1:1,2:1,3:1}
    assert not {2,3}&{r["card"] for r in data["rows"]}
    extra=next(r for r in data["extra_rows"] if r["card"]==11)
    assert extra["players"]==3 and extra["copies"]==6
    assert extra["distribution"]=={1:1,2:1,3:1}
    assert data["covered"]==4 and data["missing"]==1
    assert "1张 33.3%" in usage_text(data)


def test_unknown_names_stay_separate_and_large_observed_counts_explicit():
    store=SimpleNamespace(latest=lambda p:{"main":[1]*4+[2]+[3]*35,"side":[],"extra":[4,5]})
    data=card_usage(store,["A"],now=1000,names={})
    rows={r["card"]:r for r in data["rows"]}
    assert set(rows)=={1,2,3} and rows[1]["distribution"]=={"4+":1}
    assert rows[2]["distribution"]=={1:1}
    assert len(data["extra_rows"])==2
    for row in data["rows"]+data["extra_rows"]:
        assert sum(row["distribution"].values())==row["players"]
