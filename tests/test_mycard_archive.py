import asyncio
import base64
from dataclasses import asdict
import hashlib
import json
import lzma
import struct
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest
from services.mycard_archive.replay import ObservedDeck, parse_replay, consolidate, MAX_PAYLOAD
from services.mycard_archive.store import ArchiveStore, ArchiveLimitReached
from services.mycard_archive.presentation import deck_url, classify
from services.mycard_archive.protocol import Credentials, CredentialsUnavailable, join_request, watch
from services.mycard_archive.ranking import RankCache
from services.mycard_archive.collector import ArchiveConfig, Collector, RoomState, room_slot


def replay(main=(1,1,2), extra=(10,), *, start=100, names=("Alice","Bob"), compressed=False, extended=False):
    body=b"".join(n.encode("utf-16-le").ljust(40,b"\0") for n in names)+bytes(16)
    for i in range(len(names)):
        for cards in (main if i==0 else (20+i,),extra):
            body+=struct.pack("<I",len(cards))+struct.pack("<"+"I"*len(cards),*cards)
    flags=16|(2 if len(names)==4 else 0)|(1 if compressed else 0)
    header=struct.pack("<6I",0x32707279 if extended else 0x31707279,0x1362,flags,0,len(body),start)
    if compressed:
        stream=lzma.compress(body,format=lzma.FORMAT_ALONE)
        header+=stream[:5]+bytes(3);body=stream[13:]
    else:header+=bytes(8)
    if extended:header=header.ljust(64,b"\0")+struct.pack("<I",1)+bytes(12)
    return header+body


def begin(store,room_id="room",start=100):
    return store.begin({"id":room_id},["Alice","Bob"],{"Alice":500},start)[0]


@pytest.mark.parametrize("compressed,extended",[(False,False),(True,False),(False,True),(True,True)])
def test_replay_formats(compressed,extended):
    parsed=parse_replay(replay(compressed=compressed,extended=extended))
    assert parsed.start_time==100
    assert parsed.decks[0]==ObservedDeck("Alice",(1,1,2),(10,))
    assert parsed.decks[1].player=="Bob"


@pytest.mark.parametrize("raw",[b"",b"x"*32,replay()[:40],replay()[:120],b"x"*(MAX_PAYLOAD+81)])
def test_invalid_replays(raw):
    with pytest.raises(ValueError):parse_replay(raw)


@pytest.mark.parametrize("offset,value",[(0,0),(4,0x12cf),(8,8),(8,32),(8,0),(128,101)])
def test_invalid_replay_fields(offset,value):
    raw=bytearray(replay());struct.pack_into("<I",raw,offset,value)
    with pytest.raises(ValueError):parse_replay(bytes(raw))


def test_extended_and_compression_bounds():
    raw=bytearray(replay(extended=True));struct.pack_into("<I",raw,64,2)
    with pytest.raises(ValueError):parse_replay(bytes(raw))
    raw=bytearray(replay(compressed=True));struct.pack_into("<I",raw,16,MAX_PAYLOAD+1)
    with pytest.raises(ValueError):parse_replay(bytes(raw))
    with pytest.raises(ValueError):parse_replay(replay(compressed=True)[:-8])


def test_tag_mapping():
    parsed=parse_replay(replay(names=("Alice","Bob","Carol","Dan")))
    assert [d.player for d in parsed.decks]==["Alice","Bob","Dan","Carol"]


def test_side_max_multiplicity_and_chronology():
    rows=[{"ordinal":i,"start_time":t,"decks":[asdict(d)]} for i,t,d in [
        (1,200,ObservedDeck("Alice",(1,9,9),(10,))),
        (2,100,ObservedDeck("Alice",(1,1,2),(10,))),
        (3,300,ObservedDeck("Alice",(1,9,9),(11,)))]]
    merged=consolidate(rows)[0]
    assert merged.main==(1,1,2) and merged.extra==(10,) and merged.side==(9,9,11)


def test_store_dedupe_and_bundle(tmp_path):
    store=ArchiveStore(tmp_path);key=begin(store)
    raw=replay();store.save_replay(key,raw);store.save_replay(key,raw)
    assert len(store.replays(key))==1
    with pytest.raises(ValueError):store.bundle(key)
    store.finish(key,True);store.finish(key,True)
    assert store.stats()=={"complete":1,"replays":1,"players":2}
    assert store.latest("Alice")["observations"]==1
    with zipfile.ZipFile(store.bundle(key)) as archive:
        assert "manifest.json" in archive.namelist()
        assert any(n.endswith(".yrp") for n in archive.namelist())
        assert "merged-player-1.ydk" in archive.namelist()
        assert all("/" not in n and ".." not in n for n in archive.namelist())
        manifest=json.loads(archive.read("manifest.json"))
        assert manifest["side_complete"] is False and manifest["normal_end"]==1
    assert store.recent("Alice")[0]["id"]==key


def test_archive_quota_preserves_saved_replays(tmp_path):
    store=ArchiveStore(tmp_path);key=begin(store)
    first=replay()
    digest=store.save_replay(key,first)
    store.limit_bytes=store.usage_bytes()+store.reserve_bytes
    with pytest.raises(ArchiveLimitReached):
        store.save_replay(key,replay(start=101))
    assert store.save_replay(key,first)==digest
    assert len(store.replays(key))==1
    assert (store.directory(key)/(digest+".yrp")).read_bytes()==first


def test_archive_quota_rejects_export_without_partial_zip(tmp_path):
    store=ArchiveStore(tmp_path);key=begin(store)
    digest=store.save_replay(key,replay())
    store.finish(key,True)
    store.limit_bytes=store.usage_bytes()+store.reserve_bytes
    with pytest.raises(ArchiveLimitReached):
        store.bundle(key)
    assert not (store.directory(key)/"archive.zip").exists()
    assert (store.directory(key)/(digest+".yrp")).exists()
    assert not list(tmp_path.parent.glob(".mycard-archive-*.zip.tmp"))


def test_archive_quota_serializes_simultaneous_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=ArchiveStore(tmp_path);key=begin(store)
    store.limit_bytes=store.usage_bytes()+store.reserve_bytes+4096
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda raw: capture_result(store,key,raw),[replay(start=101),replay(start=102)]))
    assert sorted(outcomes)==["saved","stopped"]
    assert len(store.replays(key))==1


def capture_result(store,key,raw):
    try:store.save_replay(key,raw);return "saved"
    except ArchiveLimitReached:return "stopped"


@pytest.mark.parametrize("raw",[b"unsupported replay",replay(names=("SomeoneElse","Bob"))])
def test_raw_preserved_without_false_assignment(tmp_path,raw):
    store=ArchiveStore(tmp_path);key=begin(store)
    digest=store.save_replay(key,raw);store.finish(key,True)
    assert (store.directory(key)/(digest+".yrp")).read_bytes()==raw
    assert store.match(key)["status"]=="partial" and store.latest("Alice") is None
    assert store.replays(key)[0]["error"]


def test_orphan_recovery_and_empty_finish(tmp_path):
    store=ArchiveStore(tmp_path);key=begin(store);raw=replay();digest=hashlib.sha256(raw).hexdigest()
    store.directory(key).mkdir(parents=True)
    (store.directory(key)/(digest+".yrp")).write_bytes(raw)
    store.recover(key);store.recover(key);store.finish(key)
    assert len(store.replays(key))==1 and store.match(key)["status"]=="partial"
    empty=begin(store,"empty");store.finish(empty)
    assert store.match(empty)["status"]=="unavailable"
    with pytest.raises(ValueError):store.bundle(empty)


@pytest.mark.parametrize("key",["../outside","a"*23,"A"*24,"a"*24+"/x",None])
def test_safe_ids(tmp_path,key):
    with pytest.raises(ValueError):ArchiveStore(tmp_path).directory(key)


def test_versions_and_observed_side(tmp_path):
    store=ArchiveStore(tmp_path)
    for n,main,side in [(1,(1,1,2),(9,9,2)),(2,(1,1,2),(8,8,2)),(3,(4,4,2),None),(4,(1,1,2),None)]:
        key=begin(store,str(n),100*n)
        store.save_replay(key,replay(main,start=100*n))
        if side:store.save_replay(key,replay(side,start=100*n+1))
        store.finish(key,True)
    versions=store.versions("Alice")
    assert len(versions)==3
    assert versions[0]["observations"]==2 and versions[0]["side"]==[8,8,9,9]
    assert versions[1]["main"]==[2,4,4]
    assert versions[2]["main"]==[1,1,2]


def test_side_union_exceeding_fifteen_keeps_evidence(tmp_path):
    store=ArchiveStore(tmp_path);base=tuple(range(1,21))
    for n in range(2):
        key=begin(store,str(n));store.save_replay(key,replay(base,start=100+n*10))
        store.save_replay(key,replay(tuple(range(100+n*10,110+n*10))+tuple(range(11,21)),start=101+n*10))
        store.finish(key,True)
    versions=store.versions("Alice")
    assert len(versions)==2 and sum(len(v["side"]) for v in versions)==20


def test_share_code_round_trip_and_rules(tmp_path):
    deck=ObservedDeck("Alice & Bob",(1,1,2),(10,),(9,9))
    query=parse_qs(urlparse(deck_url(deck)).query);token=query["d"][0]
    data=base64.urlsafe_b64decode(token+"="*((-len(token))%4))
    bits="".join(f"{b:08b}" for b in data);assert bits[:16]=="0000001000010001"
    decoded=[];cursor=16
    for _ in range(4):
        decoded.append((int(bits[cursor:cursor+2],2),int(bits[cursor+2:cursor+29],2)));cursor+=29
    assert decoded==[(2,1),(1,2),(1,10),(2,9)] and query["name"]==[deck.player]
    rules=tmp_path/"rules.json";rules.write_text(json.dumps({"version":1,"rules":[{"name":"pair","requires":{"1":2}},{"name":"missing","requires":{"9":1}}]}))
    assert classify(deck,rules)=="pair"
    with pytest.raises(ValueError):deck_url(ObservedDeck("A",(1,)*4,()))


def test_join_packets_are_identity_and_join_only():
    raw=join_request(("Alice",65535),"123",0x1362);packets=[]
    while raw:
        length=struct.unpack_from("<H",raw)[0];packets.append(raw[2:2+length]);raw=raw[2+length:]
    assert [p[0] for p in packets]==[0x10,0x12]
    assert packets[0][1:].decode("utf-16-le").rstrip("\0")=="Alice"
    assert struct.unpack_from("<H",packets[1],1)[0]==0x1362
    password=packets[1][9:].decode("utf-16-le").rstrip("\0")
    assert password==base64.b64encode(struct.pack("<3H",0x30D1,1,1)).decode()+"123"
    with pytest.raises(ValueError):join_request(("x"*21,1),"123",0x1362)


def test_missing_and_static_credentials(tmp_path):
    async def scenario():
        c=Credentials(tmp_path/"credentials.json",None)
        with pytest.raises(CredentialsUnavailable,match="尚未配置"):await c.get()
        c.path.write_text(json.dumps({"username":"Alice","u16_secret":3}))
        assert await c.get()==("Alice",3)
        c.path.write_text(json.dumps({"username":"Bob","u16_secret":4}))
        assert await c.get()==("Bob",4)
        c.path.write_text(json.dumps({"username":"Alice","u16_secret":True}))
        with pytest.raises(CredentialsUnavailable):await c.get()
    asyncio.run(scenario())


def test_rank_boundary_cache_and_unverified():
    async def scenario():
        cache=RankCache(None);calls=[]
        async def fetch(name):
            calls.append(name);await asyncio.sleep(0)
            if name=="unknown":raise ValueError("unknown")
            value={"top":500,"outside":501}[name]
            import time
            cache.values[name]=(value,time.monotonic());return value
        cache.fetch=fetch
        assert await asyncio.gather(cache.rank("top"),cache.rank("top"))==[500,500]
        assert calls==["top"] and await cache.rank("top")==500
        assert (await cache.qualifying(["top","unknown"]))[0]=={"top":500}
        assert (await cache.qualifying(["outside"]))[0]=={}
        with pytest.raises(ValueError):await cache.qualifying(["outside","unknown"])
        await cache.close()
    asyncio.run(scenario())


def test_slots_release_when_ended_or_cancelled():
    async def scenario():
        sem=asyncio.Semaphore(1);end=asyncio.Event()
        async with room_slot(sem,end) as allowed:
            assert allowed and sem.locked()
        assert not sem.locked()
        await sem.acquire();end.set()
        async with room_slot(sem,end) as allowed:assert not allowed
        sem.release();assert sem._value==1
        end.clear();await sem.acquire()
        async def waiting():
            async with room_slot(sem,end):raise AssertionError()
        task=asyncio.create_task(waiting());await asyncio.sleep(0);task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        sem.release();assert sem._value==1
    asyncio.run(scenario())


def test_room_reconciliation_and_restart(tmp_path):
    async def scenario():
        c=Collector(ArchiveConfig(tmp_path,tmp_path/"missing"))
        key=begin(c.store,"gone");c.store.save_replay(key,replay())
        async def collect(state):await state.ended.wait()
        c.collect=collect
        room={"id":"live","users":[{"username":"Alice","position":0},{"username":"Bob","position":1}]}
        await c.process({"event":"init","data":[room]})
        assert c.store.match(key)["status"]=="partial" and len(c.rooms)==1
        await c.process({"event":"update","data":room});assert len(c.rooms)==1
        await c.process({"event":"init","data":[]});assert c.rooms["live"].ended.is_set()
        await asyncio.sleep(0)
        await c.process({"event":"delete","data":"live"});assert not c.rooms
        await c.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode",["missing","no_watch","own","capture"])
def test_collector_admission_without_false_captures(tmp_path,mode):
    async def scenario():
        called=[]
        async def fake_watch(room,identity,ended,save,**kwargs):
            called.append(room);kwargs["on_connected"]();await save(replay());return True
        c=Collector(ArchiveConfig(tmp_path,tmp_path/"missing"),watch_room=fake_watch)
        class Rank:
            async def qualifying(self,players):return {"Alice":500},{"Alice":500,"Bob":900}
        class Identity:
            async def get(self):return ("Alice" if mode=="own" else "Observer",3)
        c.rank=Rank();c.credentials=Identity()
        room={"id":"test","options":{"no_watch":mode=="no_watch"}}
        state=RoomState(room,["Alice","Bob"])
        if mode=="missing":
            async def no_identity(state):return None
            c.identity=no_identity
        await c.collect(state)
        key=begin(c.store,"test");row=c.store.match(key)
        assert bool(called)==(mode=="capture")
        assert row["status"]==("complete" if mode=="capture" else "skipped" if mode=="own" else "unavailable")
        assert c.store.stats()["replays"]==(1 if mode=="capture" else 0)
    asyncio.run(scenario())


@pytest.mark.parametrize("kind",["valid","before_role","wrong_role","drain","handshake_timeout"])
def test_observer_requires_confirmed_role_and_drains(kind):
    async def scenario():
        tasks=[];received=[];ended=asyncio.Event()
        async def serve(reader,writer):
            try:
                await reader.readexactly(94)
                def send(k,p=b""):writer.write(struct.pack("<H",len(p)+1)+bytes([k])+p)
                if kind=="handshake_timeout":await asyncio.sleep(.1);return
                if kind=="before_role":send(0x17,replay());await writer.drain();return
                send(0x13,b"\x07" if kind!="wrong_role" else b"\x00")
                await writer.drain()
                if kind=="drain":ended.set();await asyncio.sleep(.01)
                send(0x17,replay());send(0x16);await writer.drain()
            finally:writer.close();await writer.wait_closed()
        def connect(r,w):tasks.append(asyncio.create_task(serve(r,w)))
        server=await asyncio.start_server(connect,"127.0.0.1",0)
        async def save(raw):received.append(raw)
        try:
            args=dict(host="127.0.0.1",port=server.sockets[0].getsockname()[1],handshake_seconds=.03,drain_seconds=.2)
            if kind in {"valid","drain"}:
                assert await watch("123",("Observer",3),ended,save,**args) is True
                assert received==[replay()]
            else:
                with pytest.raises((CredentialsUnavailable,ValueError,TimeoutError)):await watch("123",("Observer",3),ended,save,**args)
                assert not received
        finally:
            server.close();await server.wait_closed()
            await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(scenario())
