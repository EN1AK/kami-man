"""MyCard replay archive lifecycle and QQ deck/file queries."""
import asyncio
import base64
from pathlib import Path
import sqlite3
import aiohttp
from nonebot import get_driver,logger,on_command
from nonebot.adapters.onebot.v11 import Bot,GroupMessageEvent,Message,MessageEvent,MessageSegment
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from services.mycard_api import get_bind_by_qq
from services.mycard_archive.collector import ArchiveConfig,Collector
from services.mycard_archive.presentation import deck_summary,moment
from services.mycard_archive.replay import ObservedDeck
from services.mycard_archive.store import ArchiveStore
from services.onebot_forward import make_forward_node
from services.ygo_rag_messages import chunk_text

_collector=None
_store=None
driver=get_driver()


def library():
    global _store
    if _store is None:_store=ArchiveStore(ArchiveConfig.from_env().root)
    return _store

@driver.on_startup
async def start_archive():
    global _collector,_store
    try:
        config=ArchiveConfig.from_env()
        if not config.enabled:return
        _collector=Collector(config);_store=_collector.store
        await _collector.start()
    except Exception as exc:
        logger.error("[mycard_archive] 启动失败："+type(exc).__name__)
        if _collector:await _collector.close()
        _collector=None

@driver.on_shutdown
async def stop_archive():
    global _collector
    if _collector:await _collector.close();_collector=None

status_command=on_command("MyCard采集状态",aliases={"mycard采集状态","MC采集状态"},permission=SUPERUSER,priority=5,block=True)
player_deck=on_command("卡组查询",aliases={"MyCard卡组","mycard卡组"},permission=SUPERUSER,priority=5,block=True)
deck_history=on_command("MyCard卡组历史",aliases={"mycard卡组历史"},permission=SUPERUSER,priority=5,block=True)
replay_history=on_command("MyCard录像",aliases={"mycard录像"},permission=SUPERUSER,priority=5,block=True)
archive_file=on_command("MyCard文件",aliases={"mycard文件"},permission=SUPERUSER,priority=5,block=True)
deck_file=on_command("MyCard卡组文件",aliases={"mycard卡组文件"},permission=SUPERUSER,priority=5,block=True)
top_decks=on_command("前排卡组信息",priority=5,block=True)


def player_arg(event,args):
    name=args.extract_plain_text().strip() or get_bind_by_qq(str(event.user_id))
    if not name or len(name)>100:raise ValueError("请提供 MyCard 用户名，或先绑定账号。")
    return name

async def reply_pages(bot,event,text):
    for part in chunk_text(text):await bot.send(event,MessageSegment.text(part))

async def upload(bot,event,raw,name):
    if len(raw)>8*1024*1024:raise ValueError("文件超过 QQ 上传上限；归档仍保存在服务器。")
    payload={"file":"base64://"+base64.b64encode(raw).decode("ascii"),"name":name}
    if isinstance(event,GroupMessageEvent):await bot.call_api("upload_group_file",group_id=event.group_id,**payload)
    else:await bot.call_api("upload_private_file",user_id=event.user_id,**payload)

@status_command.handle()
async def archive_status():
    text=await _collector.status() if _collector else "MyCard 采集未启用；已有归档仍可查询。"
    await status_command.finish(MessageSegment.text(text))

@player_deck.handle()
async def query_deck(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
    try:
        player=player_arg(event,args);store=library()
        version=await asyncio.to_thread(store.latest,player)
        text=await asyncio.to_thread(deck_summary,version,store.rules_path) if version else player+"：暂无已采集卡组。录像需要观战账号配置好后才能收集。"
    except (ValueError,sqlite3.Error,OSError) as exc:
        logger.warning("[mycard_archive] 卡组查询失败："+type(exc).__name__)
        await player_deck.finish("卡组查询失败，请检查用户名、归档库或分类规则。")
    await reply_pages(bot,event,text)

@deck_history.handle()
async def query_deck_history(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
    try:
        player=player_arg(event,args);versions=await asyncio.to_thread(library().versions,player)
    except (ValueError,sqlite3.Error,OSError):await deck_history.finish("请提供有效用户名；归档库暂不可用时请稍后重试。")
    text=f"{player}：共 {len(versions)} 个连续卡组版本（最近12个）"
    for i,version in list(enumerate(versions,1))[-12:][::-1]:
        text+=f"\n版本{i}：主{len(version['main'])}/额{len(version['extra'])}/观测Side{len(version['side'])}，{moment(version['last_seen'])}，{version['observations']}场；归档 {version['match_id']}"
    await reply_pages(bot,event,text)

@replay_history.handle()
async def query_replays(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
    player=args.extract_plain_text().strip()
    if len(player)>100:await replay_history.finish("用户名过长。")
    try:rows=await asyncio.to_thread(library().recent,player or None)
    except (sqlite3.Error,OSError):await replay_history.finish("归档库暂不可用。")
    lines=["最近10场已收到录像的归档"+(f"：{player}" if player else "")]
    for row in rows:
        lines.append(f"{row['id']}\n{' vs '.join(row['players'])}｜{moment(row['first_seen'])}｜{'正常结束' if row['normal_end'] else '部分录像'}")
    if not rows:lines.append("暂无录像；可发送 MyCard采集状态 查看配置与采集状态。")
    await reply_pages(bot,event,"\n\n".join(lines))

@archive_file.handle()
async def export_match(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
    match_id=args.extract_plain_text().strip()
    try:
        path=await asyncio.to_thread(library().bundle,match_id)
        raw=await asyncio.to_thread(path.read_bytes)
        await upload(bot,event,raw,"mycard-"+match_id+".zip")
    except ValueError as exc:await archive_file.finish(MessageSegment.text(str(exc)))
    except (sqlite3.Error,OSError):await archive_file.finish("归档文件暂不可用。")
    except Exception as exc:
        logger.warning("[mycard_archive] 归档上传失败："+type(exc).__name__)
        await archive_file.finish("QQ 文件上传失败；服务器上的原始归档已保留。")
    await archive_file.finish("已发送原始录像、逐小局 YDK、观测 Side 汇总及归档清单。")

@deck_file.handle()
async def export_deck(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
    try:
        player=player_arg(event,args);version=await asyncio.to_thread(library().latest,player)
        if version is None:await deck_file.finish("该玩家暂无已采集卡组。")
        deck=ObservedDeck(player,tuple(version["main"]),tuple(version["extra"]),tuple(version["side"]))
        await upload(bot,event,deck.ydk().encode("utf-8"),"mycard-observed-deck.ydk")
    except ValueError as exc:await deck_file.finish(MessageSegment.text(str(exc)))
    except (sqlite3.Error,OSError):await deck_file.finish("归档库暂不可用。")
    except Exception as exc:
        from nonebot.exception import FinishedException
        if isinstance(exc,FinishedException):raise
        logger.warning("[mycard_archive] 卡组上传失败："+type(exc).__name__)
        await deck_file.finish("QQ 文件上传失败，原始卡组仍保存在服务器。")
    await deck_file.finish("已发送观测卡组；Side 只包含实际观察到的换入卡。")

@top_decks.handle()
async def top_deck_info(bot:Bot,event:MessageEvent):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get("https://sapi.moecube.com:444/ygopro/arena/users",params={"o":"pt"}) as response:
                response.raise_for_status();rows=await response.json()
        if not isinstance(rows,list) or len(rows)<100:raise ValueError("官方前100榜单不完整")
        names=[row.get("username") for row in rows[:100]]
        if any(not isinstance(name,str) or not name for name in names) or len(set(names))!=100:raise ValueError("榜单格式错误")
        store=library()
        def summaries():
            text=[]
            for i,name in enumerate(names,1):
                version=store.latest(name)
                text.append(f"{i}. {name}\n"+(deck_summary(version,store.rules_path) if version else "暂无已采集卡组"))
            return text
        entries=await asyncio.to_thread(summaries)
    except Exception as exc:
        logger.warning("[mycard_archive] 前排卡组查询失败："+type(exc).__name__)
        await top_decks.finish("官方前排榜单或卡组归档暂不可用，请稍后重试。")
    nodes=[make_forward_node(int(bot.self_id),"MyCard前100卡组",Message(MessageSegment.text(entry))) for entry in entries]
    try:
        preview={"source":"前排卡组信息","summary":"官方前100，逐人显示已归档卡组","prompt":"[前排卡组信息]","news":[{"text":"MyCard 官方前100卡组"}]}
        if isinstance(event,GroupMessageEvent):await bot.call_api("send_group_forward_msg",group_id=event.group_id,messages=nodes,**preview)
        else:await bot.call_api("send_private_forward_msg",user_id=event.user_id,messages=nodes,**preview)
    except Exception as exc:
        logger.warning("[mycard_archive] 前排信息转发失败："+type(exc).__name__)
        await top_decks.finish("QQ 未确认前排信息发送结果，请检查聊天记录后重试。")
