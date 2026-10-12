"""Official per-player arena rank with bounded cache and shared HTTP session."""
import asyncio
import time
import aiohttp

class RankCache:
    def __init__(self,session,cutoff=500,ttl=300):
        self.session=session;self.cutoff=cutoff;self.ttl=ttl
        self.values={};self.inflight={};self.slots=asyncio.Semaphore(4)

    async def fetch(self,player):
        async with self.slots:
            async with self.session.get("https://sapi.moecube.com:444/ygopro/arena/user",params={"username":player},timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status();data=await response.json()
        value=data.get("arena_rank") if isinstance(data,dict) else None
        if isinstance(value,str) and value.isdecimal():value=int(value)
        if type(value) is not int or value<1:raise ValueError("官方竞技场名次不可用")
        self.values[player]=(value,time.monotonic())
        if len(self.values)>5000:
            now=time.monotonic();self.values={k:v for k,v in self.values.items() if now-v[1]<self.ttl}
        return value

    async def rank(self,player):
        cached=self.values.get(player)
        if cached and time.monotonic()-cached[1]<self.ttl:return cached[0]
        task=self.inflight.get(player)
        if task is None:
            task=asyncio.create_task(self.fetch(player));self.inflight[player]=task
        try:return await asyncio.shield(task)
        finally:
            if task.done() and self.inflight.get(player) is task:self.inflight.pop(player,None)

    async def qualifying(self,players):
        values=await asyncio.gather(*(self.rank(p) for p in players),return_exceptions=True)
        ranks={p:r for p,r in zip(players,values) if type(r) is int}
        accepted={p:r for p,r in ranks.items() if r<=self.cutoff}
        if not accepted and len(ranks)<len(players):raise ValueError("尚未核实双方名次")
        return accepted,ranks

    async def close(self):
        tasks=list(self.inflight.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);self.inflight.clear()
