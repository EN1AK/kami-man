"""Archive sample statistics with explicit player/deck and match denominators."""
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import time
import aiohttp
from .replay import ObservedDeck
from .presentation import classify

async def top_players(session):
    async with session.get("https://sapi.moecube.com:444/ygopro/arena/users",params={"o":"pt"},
            timeout=aiohttp.ClientTimeout(total=15)) as response:
        response.raise_for_status()
        rows=await response.json()
    if not isinstance(rows,list) or len(rows)<100:
        raise ValueError("官方前100榜单不完整")
    names=[x.get("username") if isinstance(x,dict) else None for x in rows[:100]]
    if any(not isinstance(x,str) or not x for x in names) or len(set(names))!=100:
        raise ValueError("官方榜单玩家格式异常")
    return names

def usable(deck):
    return isinstance(deck,dict) and isinstance(deck.get("main"),list) and isinstance(deck.get("extra"),list) and (
        40<=len(deck["main"])<=60 and len(deck["extra"])<=15
        and all(type(x) is int and x>0 for x in deck["main"]+deck["extra"]))

def card_usage(store,players,now=None):
    now=time.time() if now is None else now
    players=list(dict.fromkeys(players))
    counts,copies,main_counts,extra_counts=Counter(),Counter(),Counter(),Counter()
    covered=stale=0
    times=[]
    with store.connect() as db:
        for player in players:
            row=db.execute("SELECT deck,observed FROM observations WHERE player=? ORDER BY observed DESC,match_id DESC LIMIT 1",(player,)).fetchone()
            if not row:
                continue
            deck=json.loads(row["deck"])
            if not usable(deck):
                continue
            covered+=1;times.append(row["observed"]);stale+=row["observed"]<now-7*86400
            main,extra=deck["main"],deck["extra"]
            counts.update(set(main+extra));copies.update(main+extra)
            main_counts.update(set(main));extra_counts.update(set(extra))
    rows=[dict(card=card,players=n,copies=copies[card],main=main_counts[card],extra=extra_counts[card],
               rate=n/covered if covered else 0) for card,n in counts.items()]
    rows.sort(key=lambda x:(-x["players"],-x["copies"],x["card"]))
    return dict(total=len(players),covered=covered,missing=len(players)-covered,stale=stale,
                oldest=min(times) if times else None,newest=max(times) if times else None,rows=rows)

def card_names(codes):
    codes=list(dict.fromkeys(codes))
    names={}
    path=Path(os.getenv("MYCARD_CARD_DB", str(Path(__file__).resolve().parents[3]/"ygo-rag/data/cards.cdb"))).resolve()
    if not path.is_file():
        return names
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as db:
        for start in range(0,len(codes),500):
            part=codes[start:start+500]
            if part:
                names.update(db.execute("SELECT id,name FROM texts WHERE id IN ("+",".join("?" for _ in part)+")",part))
    return names

def matchup_stats(store,days=30,now=None,classifier=classify):
    if type(days) is not int or not 1<=days<=90:
        raise ValueError("统计天数应为 1～90")
    now=time.time() if now is None else now
    with store.connect() as db:
        rows=db.execute("""SELECT m.id,m.players,m.ranks,m.first_seen,r.winner,
            a.deck AS deck_a,b.deck AS deck_b
            FROM matches m LEFT JOIN official_match_results r ON r.match_id=m.id
            LEFT JOIN observations a ON a.match_id=m.id AND a.player=json_extract(m.players,'$[0]')
            LEFT JOIN observations b ON b.match_id=m.id AND b.player=json_extract(m.players,'$[1]')
            WHERE m.status='complete' AND m.normal_end=1 AND m.first_seen>=?""",(now-days*86400,)).fetchall()
    eligible=missing_result=missing_deck=unclassified=used=0
    pairs={};cache={}
    def label(deck):
        key=(tuple(sorted(deck["main"])),tuple(sorted(deck["extra"])))
        if key not in cache:
            cache[key]=classifier(ObservedDeck("",tuple(deck["main"]),tuple(deck["extra"]),()),store.rules_path)
        return cache[key]
    for row in rows:
        ranks=json.loads(row["ranks"])
        if not any(type(rank) is int and 1<=rank<=100 for rank in ranks.values()):
            continue
        eligible+=1;players=json.loads(row["players"])
        if row["winner"] not in players:
            missing_result+=1;continue
        decks=[json.loads(row[k]) if row[k] else None for k in ("deck_a","deck_b")]
        if not all(usable(d) for d in decks):
            missing_deck+=1;continue
        labels=[label(d) for d in decks]
        if any(not x or x=="未识别" for x in labels):
            unclassified+=1;continue
        used+=1
        a,b=sorted(labels)
        entry=pairs.setdefault((a,b),dict(a=a,b=b,matches=0,a_wins=0,b_wins=0))
        entry["matches"]+=1
        if a!=b:
            winner_label=labels[players.index(row["winner"])]
            entry["a_wins" if winner_label==a else "b_wins"]+=1
    ordered=sorted(pairs.values(),key=lambda x:(-x["matches"],x["a"],x["b"]))
    return dict(days=days,eligible=eligible,used=used,missing_result=missing_result,
                missing_deck=missing_deck,unclassified=unclassified,rows=ordered)

def page_rows(rows,page,size=20):
    pages=max(1,(len(rows)+size-1)//size)
    if type(page) is not int or not 1<=page<=pages:
        raise ValueError(f"页码应为 1～{pages}")
    return rows[(page-1)*size:page*size],pages

def usage_text(data,page=1,names=None):
    rows,pages=page_rows(data["rows"],page)
    names=names or {}
    lines=[f"当前前百卡片使用率｜{page}/{pages}页",
        f"覆盖 {data['covered']}/{data['total']} 位玩家；缺失或卡组不完整 {data['missing']} 人；超过7天未更新 {data['stale']} 人。",
        "每人最新一套观测卡组；使用率=携带人数/覆盖人数；统计主卡+额外，不统计不完整的Side。"]
    for i,row in enumerate(rows,(page-1)*20+1):
        lines.append(f"{i}. {names.get(row['card']) or str(row['card'])}｜{row['rate']:.1%}（{row['players']}/{data['covered']}人），共{row['copies']}张；主{row['main']}人/额外{row['extra']}人")
    if not rows:
        lines.append("暂无完整卡组样本；需要先采集到前百玩家的对局。")
    lines.append("这是已观测样本，不代表全部前百玩家的真实使用率。翻页：前百卡片使用率 2")
    return "\n".join(lines)

def matchup_text(data,page=1):
    rows,pages=page_rows(data["rows"],page)
    lines=[f"前百卡组分类对阵胜率｜近{data['days']}天｜{page}/{pages}页",
        f"采集时至少一方前100的完整归档 {data['eligible']} 场；有效样本 {data['used']} 场。",
        f"未核实胜负 {data['missing_result']}；卡组不完整 {data['missing_deck']}；分类未识别 {data['unclassified']}。",
        "每场Match只计一次；按官方胜者核对，不以录像结束推断胜负；分类沿用当前卡组命名规则。"]
    for row in rows:
        if row["a"]==row["b"]:
            lines.append(f"{row['a']} 内战：{row['matches']}场（不展示方向胜率）")
        else:
            note="｜小样本" if row["matches"]<10 else ""
            lines.append(f"{row['a']} vs {row['b']}：{row['a_wins']}胜/{row['b_wins']}负，{row['a_wins']/row['matches']:.1%}（{row['matches']}场）{note}")
    if not rows:
        lines.append("暂无可核实的对阵样本；后台核对完成后可增加样本；无法唯一匹配的对局不会计入。")
    lines.append("观战样本存在偏差，非全平台胜率。用法：卡组对阵胜率 [天数1～90] [页码]")
    return "\n".join(lines)
