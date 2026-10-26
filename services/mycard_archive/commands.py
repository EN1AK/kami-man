"""QQ commands registered in the archive plugin's existing lifecycle."""
import asyncio
import base64
import time
import aiohttp
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot,MessageEvent,Message,MessageSegment
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from .reports import ChartReports
from .tracking import TrackingStore
from .outcomes import MatchResults
from .statistics import top_players,card_usage,card_names,usage_text,matchup_stats,matchup_text
from services.ygo_rag_messages import chunk_text

def register_commands(library,collector):
    capture=on_command("卡组采集",aliases={"MyCard采集"},permission=SUPERUSER,priority=5,block=True)
    stop=on_command("停止卡组采集",aliases={"MyCard停止采集"},permission=SUPERUSER,priority=5,block=True)
    targets=on_command("卡组采集列表",aliases={"MyCard采集列表"},permission=SUPERUSER,priority=5,block=True)
    usage=on_command("前百卡片使用率",aliases={"MyCard卡片使用率"},priority=5,block=True)
    extra_usage=on_command("额外卡组使用率",aliases={"前百额外使用率","MyCard额外使用率"},priority=5,block=True)
    matchups=on_command("卡组对阵胜率",aliases={"MyCard对阵胜率"},priority=5,block=True)
    reports=None
    def report_service():
        nonlocal reports
        if reports is None:reports=ChartReports(library())
        return reports

    cache={}
    lock=asyncio.Lock()

    async def send(bot,event,text):
        for part in chunk_text(text):
            await bot.send(event,MessageSegment.text(part))

    async def set_target(bot,event,args,enabled):
        try:
            name=TrackingStore.validate(args.extract_plain_text())
            active=collector()
            if active:
                await active.set_target(name,enabled)
            else:
                await asyncio.to_thread(lambda: TrackingStore(library()).set(name,enabled))
            text=(f"已添加卡组采集：{name}。\n按完整用户名精确匹配，不受前500排名限制；等待公开且允许观战的对局，不会补回过去录像。"
                  if enabled else f"已停止后续卡组采集：{name}。正在进行的采集会继续完成；前500自动采集规则仍然有效。")
            if active is None:
                text+="\n当前采集器未运行，名单已保存，启用后生效。"
        except Exception as exc:
            # FinishedException is not used here; never display raw provider errors.
            text=str(exc) if isinstance(exc,ValueError) else "采集名单暂不可用，请稍后再试。"
        await send(bot,event,text)

    @capture.handle()
    async def add_target(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
        await set_target(bot,event,args,True)

    @stop.handle()
    async def remove_target(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
        await set_target(bot,event,args,False)

    @targets.handle()
    async def list_targets(bot:Bot,event:MessageEvent):
        try:
            names=await asyncio.to_thread(lambda: TrackingStore(library()).players())
            text=f"指定卡组采集名单：{len(names)}/100人\n"+("\n".join(names) if names else "暂无指定玩家")
            text+="\n这些玩家在公开可观战对局中会加入采集候选，仍受观战并发和存储上限限制。"
        except Exception:
            text="采集名单暂不可用，请稍后再试。"
        await send(bot,event,text)

    async def cached(key,build):
        async with lock:
            entry=cache.get(key)
            if entry and time.monotonic()-entry[0]<60:
                return entry[1]
            result=await build()
            if len(cache)>=8:cache.pop(next(iter(cache)))
            cache[key]=(time.monotonic(),result)
            return result

    async def show_card_usage(bot,event,args,kind):
        try:
            parts=args.extract_plain_text().split()
            text_mode=bool(parts and parts[-1]=="文字")
            if text_mode:parts.pop()
            if len(parts)>1:raise ValueError("参数过多")
            page=int(parts[0]) if parts else 1
            if not text_mode:
                raw=await report_service().image(kind,page)
                await bot.send(event,MessageSegment.image("base64://"+base64.b64encode(raw).decode("ascii")))
                return
            async def build():
                async with aiohttp.ClientSession() as session:
                    names=await top_players(session)
                return await asyncio.to_thread(card_usage,library(),names)
            data=await cached("usage",build)
            names=await asyncio.to_thread(card_names,[x["card"] for x in data["rows"]+data["extra_rows"]])
            text=usage_text(data,page,names,kind=="extra")
        except ValueError:
            text="参数或榜单暂不可用；用法：前百卡片使用率 [页码]。请使用范围内的正整数页码。"
        except Exception:
            text="官方前百榜单或归档统计暂不可用，请稍后再试。"
        await send(bot,event,text)

    @usage.handle()
    async def show_usage(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
        await show_card_usage(bot,event,args,"usage")

    @extra_usage.handle()
    async def show_extra_usage(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
        await show_card_usage(bot,event,args,"extra")

    @matchups.handle()
    async def show_matchups(bot:Bot,event:MessageEvent,args:Message=CommandArg()):
        try:
            parts=args.extract_plain_text().split()
            text_mode=bool(parts and parts[-1]=="文字")
            if text_mode:parts.pop()
            if len(parts)>2:raise ValueError("参数过多")
            days=int(parts[0]) if parts else 30
            page=int(parts[1]) if len(parts)>1 else 1
            if not 1<=days<=90 or page<1:raise ValueError("参数范围")
            if not text_mode:
                raw=await report_service().image("matchups",page,days)
                await bot.send(event,MessageSegment.image("base64://"+base64.b64encode(raw).decode("ascii")))
                return
            async def build():
                await asyncio.to_thread(MatchResults,library())
                return await asyncio.to_thread(matchup_stats,library(),days)
            data=await cached(("matchups",days),build)
            text=matchup_text(data,page)
        except ValueError:
            text="用法：卡组对阵胜率 [天数1～90] [页码]，默认近30天。页码须在实际范围内。"
        except Exception:
            text="对阵统计暂不可用，请稍后再试。"
        await send(bot,event,text)

    return report_service
