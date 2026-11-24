"""Query-only official QQ commands. No subscriptions or legacy identity writes."""
import asyncio
import base64
from contextlib import closing, contextmanager
from datetime import datetime
from io import BytesIO
import logging
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from matplotlib.figure import Figure
from nonebot import on_message, logger
from nonebot.adapters.qq import Bot, MessageSegment
from nonebot.adapters.qq.event import C2CMessageCreateEvent, GroupAtMessageCreateEvent, GroupMessageCreateEvent
from nonebot.rule import Rule
from official_qq.media import VerifiedMarkdown, prepare, release

from services import ygo_api as ygo, riftbound_api as rift, jihuanshe_api as price, mycard_api as mc
from services.mycard_archive.store import ArchiveStore
from services.mycard_archive.presentation import deck_summary

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("Asia/Shanghai")
SLOTS = asyncio.Semaphore(3)
ALIASES = {
    "帮助":"help", "help":"help", "菜单":"help",
    "ck":"ck", "查卡":"ck", "卡图":"pic", "查卡图":"pic", "pl":"pl", "批量查卡":"pl",
    "rb":"rb", "符文查卡":"rb", "rbpl":"rbpl", "符文批量":"rbpl", "符文批量查卡":"rbpl",
    "裁定":"ruling", "查裁定":"ruling", "卡价":"price", "卡价查询":"price", "查价格":"price",
    "符文卡价":"rbprice", "符文查价":"rbprice", "历史":"history", "胜率查询":"winrate", "首胜查询":"first",
    "卡组查询":"deck", "卡片使用率":"usage", "额外卡组使用率":"extra",
    "卡组对阵胜率":"matchups", "卡片影响度":"impact",
}
PATTERN=re.compile("^("+"|".join(map(re.escape, sorted(ALIASES,key=len,reverse=True)))+r")(?=$|\s|[：:])",re.I)
HISTORY=re.compile(r"^(?:(\d{2,4})年)?(\d{1,2})月历史(?=$|\s)")
HELP="""查卡：查卡 / 卡图 / 批量查卡 / 符文查卡 / 符文批量 / 裁定 卡名
查价：卡价 卡名 [语种] [罕贵]；符文卡价同理
MyCard：历史 玩家名 / 11月历史 玩家名 / 胜率查询 玩家名 / 首胜查询 玩家名 / 卡组查询 玩家名
统计：卡片使用率 / 额外卡组使用率 / 卡组对阵胜率 / 卡片影响度（现有图表）
群里请 @ 我。官方入口暂不继承旧 QQ 绑定、订阅或管理权限。"""


def escape(value):
    return re.sub(r"([\\`*_{}\[\]()#+.!>|~<>])",r"\\\1",str(value))


def heading(title,body=""):
    return f"**{escape(title)}**" + ("\n\n"+body if body else "")


def parse(text):
    text=text.strip().lstrip("/").strip()
    match=HISTORY.match(text)
    if match:
        year,month=match.groups()
        year=int(year) if year else datetime.now(ZONE).year
        return "history",text[match.end():].strip(),(year+2000 if year<100 else year,int(month))
    match=PATTERN.match(text)
    if match:
        return ALIASES[match[1].lower()],text[match.end():].lstrip(" :：\t"),None


def raw_image(value):
    if value and value.startswith("base64://"):
        return base64.b64decode(value.removeprefix("base64://"))


class ReadOnlyArchive(ArchiveStore):
    def __init__(self, root):
        self.path=root/"archive.sqlite3"
        self.rules_path=root/"deck-rules.json"

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path.as_uri()+"?mode=ro",uri=True,timeout=4)) as db:
            db.row_factory=sqlite3.Row
            yield db


def history_plot(values,labels=None):
    figure=Figure(figsize=(6,3),dpi=120,layout="tight")
    ax=figure.subplots(); ax.plot(range(1,len(values)+1),values,"o-",markersize=2.5,color="#345cbd")
    ax.grid(alpha=.2)
    if labels:
        ax.set(ylim=(0,100),ylabel="Win rate (%)",xlabel="Month")
        step=max(1,(len(labels)+9)//10)
        ax.set_xticks(range(1,len(labels)+1,step),labels[::step],rotation=30)
    else: ax.set(xlabel="Match",ylabel="Score")
    buf=BytesIO();figure.savefig(buf,format="png");return buf.getvalue()


async def history(player,when,all_months=False):
    now=datetime.now(ZONE);year,month=when or (now.year,now.month)
    if not 1<=month<=12 or not 2000<=year<=now.year:
        return heading("日期无效","请用：11月历史 玩家名"),None
    records=await (mc.fetch_player_history(player) if all_months else mc.get_month_records(player,month,year))
    if records is None:return heading("MyCard 暂时查询失败"),None
    valid=[r for r in records if not mc.is_zero_delta_match(r,player)]
    if not valid:return heading(player,"没有找到这个范围内的有效对局。"),None
    wins=sum(r.get("winner")==player for r in valid)
    base=f"**{len(valid)} 场 · {wins} 胜 · 胜率 {wins/len(valid):.2%}**"
    if all_months:
        months={}
        for record in valid:
            key=datetime.fromisoformat(record["start_time"].replace("Z","+00:00")).astimezone(ZONE).strftime("%Y-%m")
            n,w=months.get(key,(0,0));months[key]=n+1,w+(record.get("winner")==player)
        keys=sorted(months);values=[100*months[k][1]/months[k][0] for k in keys]
        return heading(player+"｜历月胜率",base+f"\n\n有对局的月份：{len(keys)}"),await asyncio.to_thread(history_plot,values,keys)
    valid.sort(key=lambda r:r.get("start_time",""))
    scores=[mc.get_score_before(valid[0],player)]+[mc.get_score_after(r,player) for r in valid]
    scores=[x for x in scores if isinstance(x,(float,int))]
    if scores:base+=f"\n\n最近记录：**{scores[-1]:.2f} 分**"
    return heading(f"{player}｜{year}年{month}月战绩",base),(await asyncio.to_thread(history_plot,scores)) if scores else None


async def query(command,arg,when):
    if command=="help":return heading("Kami Man｜官方 QQ 测试入口",HELP),None
    if command in {"usage","extra","matchups","impact"}:
        prefix={"usage":"usage","extra":"extra","matchups":"matchups-top100-30","impact":"impact-top100-30"}[command]
        if arg and (not arg.isdecimal() or not 1<=int(arg)<=5):return heading("请使用页码 1～5"),None
        page=int(arg or 1)
        files=sorted((ROOT/"data/mycard_reports").glob(f"????-??-??-{prefix}-v*-p{page}.png"),key=lambda p:p.stat().st_mtime)
        return (heading("MyCard 统计",f"快照日期：{files[-1].name[:10]} · 第 {page} 页"),files[-1].read_bytes()) if files else (heading("暂无这一页统计图"),None)
    if not arg:return heading("请提供卡名、卡号或 MyCard 玩家名","发送「帮助」看命令。"),None
    if command in {"ck","pic","pl","ruling"}:
        cards=await ygo.search_cards(arg)
        if not cards:return heading("未找到卡片",escape(arg)),None
        card=cards[0];title=card.get("cn_name") or arg;detail=card.get("text") or {}
        if command=="pl":
            return heading(f"{arg}｜查卡结果", "\n\n".join(f"{i}. **{escape(x.get('cn_name') or x['id'])}** · {x['id']}" for i,x in enumerate(cards[:10],1))),None
        if command=="ruling":
            rows=await ygo.fetch_card_faqs(card["id"])
            body="\n\n".join(f"**{i}. {escape(r['question'])}**\n\n{escape(r['answer'])}" for i,r in enumerate(rows[:3],1))
            return heading(title+f"｜裁定（前 {min(len(rows),3)} 条）",body or "暂无裁定。"),None
        pic=raw_image(await ygo.download_image_base64(card["id"]))
        if command=="pic":return heading(title),pic
        name=card.get("jp_name") or detail.get("jp_name")
        pieces=(["> "+escape(name)] if name else [])+(["**"+escape(detail.get("types"))+"**"] if detail.get("types") else [])
        if detail.get("pdesc"):pieces.append("**灵摆效果**\n\n"+escape(detail["pdesc"]))
        if detail.get("desc"):pieces.append(escape(detail["desc"]))
        return heading(title,"\n\n".join(pieces)),pic
    if command in {"rb","rbpl"}:
        cards=rift.search_riftbound_cards(arg)
        if not cards:return heading("未找到符文卡片",escape(arg)),None
        if command=="rbpl" or len(cards)>1:
            lines=[f"{i}. **{escape(rift.card_title(c))}** · {escape(c['card_key'])}" for i,c in enumerate(cards[:10],1)]
            return heading("符文卡片候选","\n\n".join(lines)+"\n\n回复「rb 卡号」查看详情。"),None
        card=cards[0]; image,_=await rift.card_image(card)
        return heading(rift.card_title(card),escape("\n".join(rift.format_riftbound_card(card).splitlines()[1:]))),raw_image(image)
    if command in {"price","rbprice"}:
        request=price.parse_query(arg,"riftbound" if command=="rbprice" else "ygo")
        try:name,entries=await price.find_versions(request.name,request.game,request.language)
        except price.CardChoices as e:
            return heading("找到多张卡", "\n\n".join(f"{i}. {escape(c.name)}" for i,c in enumerate(e.candidates[:10],1))+"\n\n请用完整卡名重查。"),None
        groups=price.rarity_groups(entries)
        chosen=price.select_rarity(groups,request.rarity or '1') if request.rarity or len(groups)==1 else None
        if not chosen:
            return heading(name,"可选罕贵："+escape("、".join(r for r,_ in groups))+"\n\n请在命令末尾加上罕贵。"),None
        raw=(await price.price_message(name,chosen,request.game,request.language)).splitlines()
        return heading(raw[0],"\n\n".join("**"+escape(line)+"**" if line.startswith(("最低价：","集换价：")) else escape(line) for line in raw[1:] if line)),None
    if command in {"history","winrate"}:return await history(arg,when,command=="winrate")
    if command=="first":return heading(arg,"今日首胜："+("已完成" if await mc.is_first_win(arg) else "未完成或无记录")),None
    if command=="deck":
        archive=ReadOnlyArchive(Path(os.getenv("MYCARD_ARCHIVE_DIR",str(ROOT/"data/mycard_archive"))).resolve())
        version=await asyncio.to_thread(archive.latest,arg)
        if not version:return heading(arg,"暂无采集记录。"),None
        raw=await asyncio.to_thread(deck_summary,version,archive.rules_path)
        lines=raw.splitlines(); return heading(arg,"\n\n".join(escape(x) if not x.startswith("卡组链接：") else x for x in lines[1:])),None
    return heading("发送「帮助」查看可用命令"),None


async def is_command(event):
    if not isinstance(event,(C2CMessageCreateEvent,GroupAtMessageCreateEvent,GroupMessageCreateEvent)):
        return False
    if isinstance(event,GroupMessageCreateEvent) and not isinstance(event,GroupAtMessageCreateEvent) and not event.is_tome():
        return False
    return parse(event.get_plaintext()) is not None


matcher=on_message(rule=Rule(is_command),priority=5,block=True)


@matcher.handle()
async def reply(bot: Bot, event: C2CMessageCreateEvent | GroupAtMessageCreateEvent | GroupMessageCreateEvent):
    args=parse(event.get_plaintext())
    if args is None:return
    try:
        async with asyncio.timeout(55):
            async with SLOTS:
                text,image=await query(*args)
    except price.PriceError as exc:text,image=heading("查价",escape(exc)),None
    except Exception as exc:
        logger.warning("Official QQ query {} failed: {}",args[0],type(exc).__name__)
        text,image=heading("查询暂时不可用","请稍后重试。"),None
    if len(text)>1800:text=text[:1750]+"\n\n内容较长，已截取预览。"
    if image:
        try:
            async with asyncio.timeout(22):
                material=await prepare(bot,image)
        except Exception as exc:
            logger.warning("Official QQ material unavailable: {}",type(exc).__name__)
        else:
            ident,name,reference=material
            try:
                await bot.send(event,MessageSegment.markdown(VerifiedMarkdown(content=text+"\n\n"+reference)))
            except Exception as exc:
                # Do not blindly resend after a network timeout (the platform could have sent it).
                logger.warning("Official QQ combined send failed: {}",type(exc).__name__)
                status=getattr(getattr(exc,"response",None),"status_code",None)
                if status not in {400,401,403,404,413,429}:return
            else:
                image=None
            try:await release(bot,ident,name)
            except Exception as exc:logger.warning("Official QQ material cleanup failed: {}",type(exc).__name__)
            if image is None:return
    try:await bot.send(event,MessageSegment.markdown(text))
    except Exception as exc:
        logger.warning("Official QQ Markdown send failed: {}",type(exc).__name__)
        return
    if image:
        try:await bot.send(event,MessageSegment.file_image(image))
        except Exception as exc:logger.warning("Official QQ image send failed: {}",type(exc).__name__)
