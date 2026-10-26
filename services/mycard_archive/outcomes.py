"""Conservative official-history matching; replay completion never implies a win."""
import asyncio
from datetime import datetime
import hashlib
import json
import time
import aiohttp

def timestamp(value):
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.timestamp() if dt.tzinfo is not None else None
    except (ValueError,TypeError,AttributeError):
        return None

def match_result(match, rounds, records):
    players=set(json.loads(match["players"]) if isinstance(match["players"],str) else match["players"])
    starts=[r.get("start_time") for r in rounds if type(r.get("start_time")) in (int,float) and r["start_time"]>0]
    if len(players)!=2 or not starts or not match.get("finished"):
        return None
    start=min(starts)
    candidates={}
    for record in records:
        if not isinstance(record,dict) or not all(isinstance(record.get(k),str) for k in ("usernamea","usernameb","winner")):
            continue
        if {record["usernamea"],record["usernameb"]}!=players:
            continue
        began,ended=timestamp(record.get("start_time")),timestamp(record.get("end_time"))
        winner=record.get("winner")
        if began is None or ended is None or abs(began-start)>15 or not began<=ended<=match["finished"]+300 or winner not in players:
            continue
        body={k:record.get(k) for k in ("usernamea","usernameb","winner","start_time","end_time","pta","ptb","pta_ex","ptb_ex")}
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
        candidates[fingerprint]=body
    if len(candidates)!=1:
        return None
    fingerprint,body=next(iter(candidates.items()))
    return dict(fingerprint=fingerprint,winner=body["winner"],record=body)

class MatchResults:
    def __init__(self,store):
        self.store=store
        self.cache={}
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS official_match_results(
                match_id TEXT PRIMARY KEY REFERENCES matches(id), checked REAL NOT NULL,
                fingerprint TEXT UNIQUE, winner TEXT, record TEXT)""")

    def pending(self,limit=12,now=None):
        now=time.time() if now is None else now
        with self.store.connect() as db:
            rows=db.execute("""SELECT m.* FROM matches m LEFT JOIN official_match_results r ON r.match_id=m.id
                WHERE m.status='complete' AND m.normal_end=1 AND m.first_seen>=?
                AND r.winner IS NULL AND (r.checked IS NULL OR r.checked<?)
                ORDER BY r.checked IS NOT NULL,
                NOT EXISTS(SELECT 1 FROM json_each(m.ranks) j WHERE j.type='integer' AND j.value BETWEEN 1 AND 500),
                m.first_seen DESC LIMIT ?""",(now-90*86400,now-1800,limit)).fetchall()
        return [dict(row) for row in rows]

    def save(self,match_id,result,now=None):
        now=time.time() if now is None else now
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if result:
                duplicate=db.execute("SELECT match_id FROM official_match_results WHERE fingerprint=?",(result["fingerprint"],)).fetchone()
                if duplicate and duplicate[0]!=match_id:
                    result=None
            db.execute("""INSERT INTO official_match_results(match_id,checked) VALUES (?,?)
                ON CONFLICT(match_id) DO UPDATE SET checked=excluded.checked""",(match_id,now))
            if result:
                db.execute("""UPDATE official_match_results SET fingerprint=?,winner=?,record=?
                    WHERE match_id=? AND winner IS NULL""",
                    (result["fingerprint"],result["winner"],json.dumps(result["record"],ensure_ascii=False),match_id))

    async def history(self,session,player):
        cached=self.cache.get(player)
        if cached and time.monotonic()-cached[0]<300:
            return cached[1]
        async with session.get("https://sapi.moecube.com:444/ygopro/arena/history",
                params={"username":player,"type":0,"page_num":100},timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            data=await response.json()
        if not isinstance(data,dict) or not isinstance(data.get("data"),list):
            raise ValueError("官方战绩结构异常")
        rows=data["data"]
        if len(self.cache)>=512:
            self.cache.pop(next(iter(self.cache)))
        self.cache[player]=(time.monotonic(),rows)
        return rows

    async def reconcile(self,session,limit=12):
        pending=await asyncio.to_thread(self.pending,limit)
        slots=asyncio.Semaphore(2)
        async def one(match):
            async with slots:
                try:
                    players=json.loads(match["players"])
                    records=await self.history(session,players[0])
                    rounds=await asyncio.to_thread(self.store.replays,match["id"])
                    result=match_result(match,rounds,records)
                    await asyncio.to_thread(self.save,match["id"],result)
                    return int(result is not None)
                except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,KeyError,IndexError):
                    await asyncio.to_thread(self.save,match["id"],None)
                    return 0
        return sum(await asyncio.gather(*(one(m) for m in pending)))

    def progress(self):
        with self.store.connect() as db:
            checked,matched=db.execute("SELECT COUNT(*),COUNT(winner) FROM official_match_results").fetchone()
        return checked,matched
