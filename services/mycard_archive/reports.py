"""Daily aggregate snapshots and bounded PNG cache; never sends QQ messages."""
import asyncio
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
import time
import uuid
from zoneinfo import ZoneInfo
import aiohttp
from .charts import render_usage,render_extra,render_matchups
from .outcomes import MatchResults
from .statistics import top_players,card_usage,card_names,matchup_stats

CHINA=ZoneInfo("Asia/Shanghai")
SNAPSHOT_VERSION=7
CACHE_LIMIT=32*1024**2
FILE_NAME=re.compile(r"^(\d{4}-\d{2}-\d{2})-(usage|extra|matchups-[1-9]\d?)(?:-v[1-9]\d*)?(?:-p[1-9]\d*)?\.(json|png)$")

class ChartReports:
    def __init__(self,store,root=None,clock=time.time):
        self.store=store
        self.root=Path(root) if root else store.root.parent/"mycard_reports"
        self.clock=clock
        self.lock=asyncio.Lock()

    def prune(self,day,protected=()):
        self.root.mkdir(parents=True,exist_ok=True)
        cutoff=(datetime.fromisoformat(day)-timedelta(days=2)).date().isoformat()
        files=[]
        keep={day+"-usage.json",day+"-matchups-30.json",*protected}
        for path in self.root.iterdir():
            match=FILE_NAME.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():continue
            if match[1]<cutoff:
                path.unlink();continue
            files.append(path)
        size=sum(p.stat().st_size for p in files)
        for path in sorted(files,key=lambda p:p.stat().st_mtime):
            if size<=CACHE_LIMIT:break
            if path.name in keep:continue
            size-=path.stat().st_size;path.unlink()
        if size>CACHE_LIMIT:
            raise ValueError("图表缓存超出上限")

    def save(self,path,body,day):
        if len(body)>4*1024**2:raise ValueError("图表或快照过大")
        self.root.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            temp.write_bytes(body);temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        self.prune(day,{path.name})

    async def snapshot(self,kind,days,now):
        day=datetime.fromtimestamp(now,CHINA).date().isoformat()
        key="usage" if kind=="usage" else f"matchups-{days}"
        path=self.root/f"{day}-{key}.json"
        if path.is_file() and not path.is_symlink():
            try:
                value=await asyncio.to_thread(path.read_text,encoding="utf-8")
                snapshot=json.loads(value)
                if snapshot.get("day")==day and snapshot.get("key")==key and snapshot.get("version")==SNAPSHOT_VERSION:
                    return snapshot
            except (OSError,ValueError,AttributeError):pass
        if kind=="usage":
            async with aiohttp.ClientSession() as session:
                players=await top_players(session,self.store)
            data=await asyncio.to_thread(card_usage,self.store,players,now)
            names=await asyncio.to_thread(card_names,[r["card"] for r in data["rows"]+data["extra_rows"]])
        else:
            await asyncio.to_thread(MatchResults,self.store)
            data=await asyncio.to_thread(matchup_stats,self.store,days,now)
            names={}
        snapshot=dict(day=day,key=key,data=data,names=names,version=SNAPSHOT_VERSION,
            generated_at=datetime.fromtimestamp(now,CHINA).strftime("%Y-%m-%d %H:%M 北京时间"))
        await asyncio.to_thread(self.save,path,json.dumps(snapshot,ensure_ascii=False).encode("utf-8"),day)
        return snapshot

    async def image(self,kind,page=1,days=30):
        if kind not in {"usage","extra","matchups"} or type(page) is not int or page<1 or type(days) is not int or not 1<=days<=90:
            raise ValueError("图表参数无效")
        async with self.lock:
            now=self.clock()
            snapshot=await self.snapshot("usage" if kind=="extra" else kind,days,now)
            image_key="extra" if kind=="extra" else snapshot["key"]
            path=self.root/f"{snapshot['day']}-{image_key}-v{SNAPSHOT_VERSION}-p{page}.png"
            if path.is_file() and not path.is_symlink():
                raw=await asyncio.to_thread(path.read_bytes)
                if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw)<=4*1024**2:
                    return raw
            if kind=="usage":
                raw=await asyncio.to_thread(render_usage,snapshot["data"],snapshot["names"],snapshot["generated_at"],page)
            elif kind=="extra":
                raw=await asyncio.to_thread(render_extra,snapshot["data"],snapshot["names"],snapshot["generated_at"],page)
            else:
                raw=await asyncio.to_thread(render_matchups,snapshot["data"],snapshot["generated_at"],page)
            await asyncio.to_thread(self.save,path,raw,snapshot["day"])
            return raw

    async def refresh(self):
        await self.image("usage")
        await self.image("extra")
        await self.image("matchups",days=30)
