"""Bounded background room discovery, top-rank admission and replay collection."""
import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass,field
import os
from pathlib import Path
import shutil
import time
import aiohttp
from nonebot import logger
from .protocol import Credentials,CredentialsUnavailable,watch
from .ranking import RankCache
from .store import ArchiveStore,ArchiveLimitReached,DEFAULT_ARCHIVE_LIMIT

@dataclass(frozen=True)
class ArchiveConfig:
    root: Path
    credentials: Path
    enabled: bool = False
    concurrency: int = 4
    cutoff: int = 500
    ws_url: str = "wss://tiramisu.moecube.com:8923/?filter=started"
    host: str = "tiramisu.moecube.com"
    port: int = 8911
    version: int = 0x1362
    join_interval: float = 2
    archive_limit_bytes: int = DEFAULT_ARCHIVE_LIMIT

    @classmethod
    def from_env(cls):
        project=Path(__file__).resolve().parents[2]
        root=Path(os.getenv("MYCARD_ARCHIVE_DIR",str(project/"data/mycard_archive"))).resolve()
        config=cls(root,Path(os.getenv("MYCARD_CREDENTIALS_FILE",str(root/"credentials.json"))).resolve(),
                   os.getenv("MYCARD_CAPTURE_ENABLED","false").lower() in {"1","true","yes"},
                   int(os.getenv("MYCARD_CAPTURE_CONCURRENCY","4")),int(os.getenv("MYCARD_RANK_CUTOFF","500")),
                   os.getenv("MYCARD_ROOM_WS","wss://tiramisu.moecube.com:8923/?filter=started"),
                   os.getenv("MYCARD_SPECTATOR_HOST","tiramisu.moecube.com"),int(os.getenv("MYCARD_SPECTATOR_PORT","8911")),
                   int(os.getenv("MYCARD_SPECTATOR_VERSION","0x1362"),0),float(os.getenv("MYCARD_JOIN_INTERVAL","2")),
                   int(os.getenv("MYCARD_ARCHIVE_MAX_GB","10"))*1024**3)
        if not 1<=config.concurrency<=16 or not 1<=config.cutoff<=500 or not 0<=config.version<=65535 or not 1<=config.port<=65535 or config.join_interval<0.5 or not 1<=config.archive_limit_bytes//(1024**3)<=1000:
            raise ValueError("MyCard 采集配置超出范围")
        return config

@dataclass
class RoomState:
    room: dict
    players: list[str]
    first_seen: float = field(default_factory=time.time)
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task|None = None
    match_id: str|None = None
    connected: bool = False

async def pause_or_end(event,seconds):
    if event.is_set():return True
    try:await asyncio.wait_for(event.wait(),seconds);return True
    except asyncio.TimeoutError:return False

@asynccontextmanager
async def room_slot(semaphore,ended):
    acquiring=asyncio.create_task(semaphore.acquire());ending=asyncio.create_task(ended.wait());acquired=False
    try:
        await asyncio.wait([acquiring,ending],return_when=asyncio.FIRST_COMPLETED)
        if acquiring.done() and not acquiring.cancelled() and acquiring.exception() is None:acquired=True
        yield acquired and not ended.is_set()
    finally:
        for task in [acquiring,ending]:
            if not task.done():task.cancel()
        await asyncio.gather(acquiring,ending,return_exceptions=True)
        # Acquisition can finish at the cancellation boundary; always release exactly once.
        if not acquired and acquiring.done() and not acquiring.cancelled() and acquiring.exception() is None:acquired=True
        if acquired:semaphore.release()

class Collector:
    def __init__(self,config,*,store=None,watch_room=watch):
        self.config=config;self.store=store or ArchiveStore(config.root,config.archive_limit_bytes);self.watch_room=watch_room
        self.rooms={};self.session=None;self.rank=None;self.credentials=None;self.ws_task=None
        self.closed=False;self.ws_connected=False;self.initialized=False;self.last_error="";self.excluded=0
        self.slots=asyncio.Semaphore(config.concurrency);self.join_lock=asyncio.Lock()
        self.next_join=0.;self.cooldown_until=0.;self.failed_joins=0
        # Room discovery must not flood asyncio's shared pool with full-tree scans.
        self.capacity_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="mycard-capacity")
        self.capacity_task=None;self.capacity_checked_at=None;self.capacity_cached=False

    async def _scan_capacity(self):
        available=await asyncio.get_running_loop().run_in_executor(self.capacity_executor,self.store.capture_available)
        self.capacity_cached=available;self.capacity_checked_at=time.monotonic()
        return available

    async def capacity_available(self):
        # Advisory admission only. ArchiveStore.require_capacity still enforces
        # the exact hard limit under its write lock before storing evidence.
        if self.capacity_checked_at is not None and time.monotonic()-self.capacity_checked_at<5:
            return self.capacity_cached
        if self.capacity_task is None or self.capacity_task.done():
            self.capacity_task=asyncio.create_task(self._scan_capacity(),name="mycard-capacity-scan")
        # One cancelled room must not cancel the scan shared with other rooms.
        return await asyncio.shield(self.capacity_task)

    def error(self,message):
        if message!=self.last_error:logger.warning("[mycard_archive] "+message)
        self.last_error=message

    async def start(self):
        self.session=aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=12))
        self.rank=RankCache(self.session,self.config.cutoff)
        self.credentials=Credentials(self.config.credentials,self.session)
        self.ws_task=asyncio.create_task(self.feed(),name="mycard-archive-room-feed")

    async def feed(self):
        backoff=2
        while not self.closed:
            try:
                async with self.session.ws_connect(self.config.ws_url,heartbeat=30,max_msg_size=4*1024*1024) as socket:
                    self.ws_connected=True;backoff=2
                    logger.info("[mycard_archive] 公开房间监听已连接")
                    async for message in socket:
                        if message.type==aiohttp.WSMsgType.TEXT:
                            try:await self.process(message.json())
                            except (ValueError,TypeError,KeyError):self.error("公开房间消息格式异常，已跳过")
                        elif message.type in {aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR}:break
            except asyncio.CancelledError:raise
            except Exception as exc:self.error("公开房间连接异常："+type(exc).__name__)
            finally:self.ws_connected=False
            await asyncio.sleep(backoff);backoff=min(60,backoff*2)

    async def process(self,payload):
        if not isinstance(payload,dict):return
        event,data=payload.get("event"),payload.get("data")
        if event=="init" and isinstance(data,list):
            present={str(room.get("id")) for room in data if isinstance(room,dict) and room.get("id")}
            for key,state in list(self.rooms.items()):
                if key not in present:
                    state.ended.set()
                    if state.task is None or state.task.done():self.rooms.pop(key,None)
            if not self.initialized:
                for previous in await asyncio.to_thread(self.store.active):
                    await asyncio.to_thread(self.store.recover,previous["id"])
                    if previous["room_id"] not in present:
                        await asyncio.to_thread(self.store.issue,previous["id"],"重启后房间已结束，未确认全部录像")
                        await asyncio.to_thread(self.store.finish,previous["id"],False)
                self.initialized=True
            for room in data[:1000]:await self.add(room)
        elif event in {"create","update"} and isinstance(data,dict):await self.add(data)
        elif event=="delete":
            keys=data if isinstance(data,list) else [data.get("id") if isinstance(data,dict) else data]
            for key in keys:
                state=self.rooms.get(str(key))
                if state:
                    state.ended.set()
                    if state.task is None or state.task.done():self.rooms.pop(str(key),None)

    async def add(self,room):
        if not isinstance(room,dict) or not isinstance(room.get("id"),str) or not room["id"] or len(room["id"])>100:return
        key=room["id"]
        if key in self.rooms or len(self.rooms)>=1000:return
        users=room.get("users",[])
        if not isinstance(users,list):return
        players=list(dict.fromkeys(u["username"] for u in users if isinstance(u,dict) and isinstance(u.get("username"),str) and u["username"] and u.get("position",0) in range(4)))
        if len(players)!=2:return
        state=RoomState({k:room[k] for k in ["id","title","options","arena","users"] if k in room},players)
        self.rooms[key]=state
        state.task=asyncio.create_task(self.collect(state),name="mycard-archive-room")

    async def admit(self,ended):
        while not ended.is_set():
            async with self.join_lock:
                now=time.monotonic();delay=max(self.next_join,self.cooldown_until)-now
                if delay<=0:
                    self.next_join=now+self.config.join_interval;return True
            if await pause_or_end(ended,delay):return False
        return False

    async def identity(self,state):
        while not state.ended.is_set():
            if not await self.capacity_available():
                self.error("MyCard 归档达到容量上限，录像采集暂停")
                if await pause_or_end(state.ended,60):return None
                continue
            if shutil.disk_usage(self.store.root).free<256*1024*1024:
                self.error("可用磁盘空间不足，录像采集暂停")
                if await pause_or_end(state.ended,60):return None
                continue
            try:return await self.credentials.get()
            except CredentialsUnavailable as exc:
                self.error(str(exc))
                if await pause_or_end(state.ended,30):return None
        return None

    async def collect(self,state):
        try:
            qualifying=None
            while not state.ended.is_set():
                if not await self.capacity_available():
                    self.error("MyCard 归档达到容量上限，录像采集暂停")
                    if await pause_or_end(state.ended,60):return
                    continue
                try:qualifying,ranks=await self.rank.qualifying(state.players);break
                except Exception:
                    self.error("玩家名次暂不可用，等待核实后再观战")
                    if await pause_or_end(state.ended,60):return
            if not qualifying:self.excluded+=1;return
            match_id,active=await asyncio.to_thread(self.store.begin,state.room,state.players,ranks,state.first_seen)
            state.match_id=match_id
            if not active:return
            await asyncio.to_thread(self.store.recover,match_id)
            options=state.room.get("options") or {}
            if not isinstance(options,dict) or options.get("no_watch") not in {None,False,0}:
                await asyncio.to_thread(self.store.issue,match_id,"房间不允许观战，未尝试入场")
                await asyncio.to_thread(self.store.finish,match_id,False,"unavailable");return
            identity=await self.identity(state)
            if identity is None:
                await asyncio.to_thread(self.store.issue,match_id,"对局结束前没有可用的观战凭据或存储空间")
                await asyncio.to_thread(self.store.finish,match_id,False);return
            if identity[0] in state.players:
                await asyncio.to_thread(self.store.issue,match_id,"观战账号正在参赛，已跳过")
                await asyncio.to_thread(self.store.finish,match_id,False,"skipped");return
            normal_end=False
            async with room_slot(self.slots,state.ended) as admitted:
                if admitted:
                    for attempt in range(5):
                        identity=await self.identity(state)
                        if identity is None or not await self.admit(state.ended):break
                        if identity[0] in state.players:
                            await asyncio.to_thread(self.store.finish,match_id,False,"skipped");return
                        async def save(raw):
                            write=asyncio.create_task(asyncio.to_thread(self.store.save_replay,match_id,raw))
                            try:await asyncio.shield(write)
                            except asyncio.CancelledError:
                                await write;raise
                        def connected():
                            state.connected=True;self.failed_joins=0;self.cooldown_until=0
                        try:
                            normal_end=await self.watch_room(state.room["id"],identity,state.ended,save,host=self.config.host,port=self.config.port,version=self.config.version,on_connected=connected)
                            if normal_end or state.ended.is_set():break
                            await asyncio.to_thread(self.store.issue,match_id,"观战流中断，曾尝试重连")
                        except asyncio.CancelledError:raise
                        except ArchiveLimitReached:
                            self.error("MyCard 归档达到容量上限，录像采集暂停")
                            await asyncio.to_thread(self.store.issue,match_id,"归档达到容量上限，未保存后续录像")
                            break
                        except Exception as exc:
                            self.failed_joins+=1
                            if self.failed_joins>=3:self.cooldown_until=time.monotonic()+min(300,30*2**min(self.failed_joins-3,4))
                            if isinstance(exc,CredentialsUnavailable):self.credentials.invalidate()
                            self.error("观战连接失败："+type(exc).__name__)
                            await asyncio.to_thread(self.store.issue,match_id,self.last_error)
                        finally:state.connected=False
                        if await pause_or_end(state.ended,min(60,5*2**attempt)):break
                else:await asyncio.to_thread(self.store.issue,match_id,"对局在等待观战名额时结束")
            if not normal_end:await asyncio.to_thread(self.store.issue,match_id,"未确认正常结束信号；完整性以实际收到的录像为准")
            await asyncio.to_thread(self.store.finish,match_id,normal_end)
        except asyncio.CancelledError:raise  # active rows are recovered after restart
        except Exception as exc:self.error("归档处理失败："+type(exc).__name__)
        finally:
            state.connected=False
            if state.ended.is_set() or self.closed:self.rooms.pop(state.room["id"],None)

    async def status(self):
        stats=await asyncio.to_thread(self.store.stats)
        used=await asyncio.to_thread(self.store.usage_bytes)
        limit=self.store.limit_bytes
        offloaded=await asyncio.to_thread(self.store.offload_count)
        quota=f"归档空间：{used/1024**3:.2f}/{limit/1024**3:.0f} GiB；{'已达上限，采集暂停' if used>=self.store.capture_ceiling else '额度正常'}"
        eligible=sum(state.match_id is not None and state.task is not None and not state.task.done() for state in self.rooms.values())
        pending="已配置" if self.config.credentials.exists() else "未配置，录像采集等待登录凭据"
        return (f"MyCard 前 {self.config.cutoff} 归档\n公开房间监听：{'已连接' if self.ws_connected else '重连中'}\n"
                f"观战凭据：{pending}\n已跟踪房间 {len(self.rooms)}；前排待采集 {eligible}；正在观战 {sum(s.connected for s in self.rooms.values())}/{self.config.concurrency}\n"
                f"正常结束 {stats.get('complete',0)}；部分录像 {stats.get('partial',0)}；未收到录像 {stats.get('unavailable',0)}\n"
                f"已保存录像 {stats['replays']}；卡组玩家 {stats['players']}；home 已转存 {offloaded} 场\n{quota}\n入场冷却 {max(0,int(self.cooldown_until-time.monotonic()))} 秒\n最近状态：{self.last_error or '无异常'}")

    async def close(self):
        self.closed=True
        tasks=[state.task for state in self.rooms.values() if state.task]
        if self.ws_task:tasks.append(self.ws_task)
        if self.capacity_task:tasks.append(self.capacity_task)
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if self.rank:await self.rank.close()
        if self.session:await self.session.close()
        self.rooms.clear()
        self.capacity_executor.shutdown(wait=False,cancel_futures=True)
