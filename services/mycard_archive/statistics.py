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

class RankedPlayers(list):
    """Only archived players need rank checks; unobserved top-500 remain missing."""
    def __init__(self,players,unverified=0):
        super().__init__(players)
        self.unverified=unverified

async def top_players(session,store):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import asyncio
    from .ranking import RankCache
    from .store import atomic_bytes
    day=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    path=store.root.parent/"mycard_reports"/"ranking.json"
    try:
        cached=json.loads(path.read_text(encoding="utf-8"))
        if cached.get("day")==day and cached.get("scope")==500:
            return RankedPlayers(cached["players"],cached["unverified"])
    except (OSError,ValueError,KeyError,TypeError):pass
    def candidates():
        with store.connect() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT player FROM observations ORDER BY player")]
    players=await asyncio.to_thread(candidates)
    rank=RankCache(session)
    failures=0
    consecutive=0
    async def check(player):
        nonlocal failures,consecutive
        try:
            value=await rank.rank(player)
            consecutive=0
            return value
        except Exception as exc:
            failures+=1;consecutive+=1
            if consecutive>=8 or failures>max(5,len(players)*.05):
                raise ValueError("官方排名服务暂不可用，已停止批量核验") from None
            return exc
    tasks=[asyncio.create_task(check(p)) for p in players]
    try:
        results=await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await rank.close()
    unverified=sum(type(r) is not int for r in results)
    if players and (unverified==len(players) or unverified>max(5,len(players)*.05)):
        raise ValueError("官方排名核验失败过多，请稍后再试")
    selected=[p for p,r in zip(players,results) if type(r) is int and 1<=r<=500]
    body=dict(day=day,scope=500,players=selected,unverified=unverified)
    await asyncio.to_thread(atomic_bytes,path,json.dumps(body,ensure_ascii=False).encode("utf-8"))
    return RankedPlayers(selected,unverified)

def usable(deck):
    return isinstance(deck,dict) and isinstance(deck.get("main"),list) and isinstance(deck.get("extra"),list) and (
        40<=len(deck["main"])<=60 and len(deck["extra"])<=15
        and all(type(x) is int and x>0 for x in deck["main"]+deck["extra"]))

def card_usage(store,players,now=None,names=None):
    now=time.time() if now is None else now
    population=500 if isinstance(players,RankedPlayers) else len(set(players))
    rank_unverified=getattr(players,"unverified",0)
    players=list(dict.fromkeys(players))
    decks=[]
    codes=set()
    for player in players:
        deck=store.latest(player)
        if not deck or not usable(deck):continue
        side=deck.get("side",[])
        if not isinstance(side,list) or any(type(c) is not int or c<=0 for c in side):side=[]
        decks.append((deck,side))
        codes.update(deck["main"]+deck["extra"]+side)
    names=card_names(codes) if names is None else names
    representatives={};canonical={};labels={}
    for code in sorted(codes):
        name=names.get(code)
        name=name.strip() if isinstance(name,str) else ""
        representative=representatives.setdefault(name,code) if name else code
        canonical[code]=representative
        if name:labels[representative]=name
    main_counts,side_counts,total_counts,extra_counts=Counter(),Counter(),Counter(),Counter()
    main_copies,side_copies,extra_copies=Counter(),Counter(),Counter()
    distributions={};extra_distributions={}
    covered=stale=side_observed=0
    times=[]
    for deck,side in decks:
        observed=deck.get("last_seen") or deck.get("first_seen") or now
        covered+=1;times.append(observed);stale+=observed<now-7*86400
        main=[canonical[c] for c in deck["main"]]
        extra=[canonical[c] for c in deck["extra"]]
        side=[canonical[c] for c in side]
        side_observed+=bool(side)
        main_counts.update(set(main));side_counts.update(set(side))
        total_counts.update(set(main)|set(side));extra_counts.update(set(extra))
        mc,sc,ec=Counter(main),Counter(side),Counter(extra)
        main_copies.update(mc);side_copies.update(sc);extra_copies.update(ec)
        for card in set(mc)|set(sc):
            count=mc[card]+sc[card]
            distributions.setdefault(card,Counter())[count if count<=3 else "4+"]+=1
        for card,count in ec.items():
            extra_distributions.setdefault(card,Counter())[count if count<=3 else "4+"]+=1
    rows=[dict(card=card,name=labels.get(card),players=n,main=main_counts[card],side=side_counts[card],
               copies=main_copies[card]+side_copies[card],main_copies=main_copies[card],
               side_copies=side_copies[card],distribution=dict(distributions[card]),rate=n/covered if covered else 0)
          for card,n in total_counts.items()]
    extra_rows=[dict(card=card,name=labels.get(card),players=n,extra=n,copies=extra_copies[card],distribution=dict(extra_distributions[card]),rate=n/covered if covered else 0)
                for card,n in extra_counts.items()]
    for entries in (rows,extra_rows):
        entries.sort(key=lambda x:(-x["players"],-x["copies"],x["card"]))
    return dict(total=population,covered=covered,missing=max(0,population-covered),stale=stale,rank_unverified=rank_unverified,
                side_observed=side_observed,oldest=min(times) if times else None,newest=max(times) if times else None,
                total_cards=len(rows),extra_total_cards=len(extra_rows),rows=rows[:100],extra_rows=extra_rows[:100])

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
        if not any(type(rank) is int and 1<=rank<=500 for rank in ranks.values()):
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

def usage_text(data,page=1,names=None,extra=False):
    rows,pages=page_rows(data["extra_rows"] if extra else data["rows"],page)
    names=names or {}
    title="前五百额外卡组使用率" if extra else "前五百主卡/Side使用率"
    lines=[f"{title}｜前100张｜{page}/{pages}页",
        f"覆盖 {data['covered']}/{data['total']} 人；缺失 {data['missing']} 人；超过7天未更新 {data['stale']} 人；归档排名未核验 {data.get('rank_unverified',0)} 人。",
        "每人最新卡组版本；同版本Side合并已观察换入。按玩家人数计算投入率，非卡片张数占比。"]
    for i,row in enumerate(rows,(page-1)*20+1):
        name=row.get("name") or names.get(row["card"]) or str(row["card"])
        if extra:
            lines.append(f"{i}. {name}｜额外使用率 {row['rate']:.1%}（{row['players']}/{data['covered']}人），共{row['copies']}张")
        else:
            den=data["covered"] or 1
            lines.append(f"{i}. {name}｜主卡 {row['main']/den:.1%}（{row['main']}人/{row['main_copies']}张）"
                         f"｜观测Side {row['side']/den:.1%}（{row['side']}人/{row['side_copies']}张）"
                         f"｜总使用率 {row['rate']:.1%}（{row['players']}/{data['covered']}人）")
    if not rows:lines.append("暂无完整卡组样本。")
    for row in rows:
        distribution=row.get("distribution",{})
        if distribution:
            lines.append((row.get("name") or names.get(row["card"]) or str(row["card"]))+" 张数分布（携带者中）："+" / ".join(f"{n}张 {distribution.get(n,distribution.get(str(n),0))/row['players']:.1%}" for n in (1,2,3))+ (f" / 4+张 {distribution['4+']/row['players']:.1%}" if distribution.get("4+") else ""))
    lines.append("Side不完整，未曝光备牌未知；总使用率是主卡与已观测Side携带人数的去重并集，属于观测下界。"
                 if not extra else "额外卡组单独统计，不混入主卡/Side总使用率。")
    return "\n".join(lines)

def matchup_text(data,page=1):
    rows,pages=page_rows(data["rows"],page)
    lines=[f"前五百卡组分类对阵胜率｜近{data['days']}天｜{page}/{pages}页",
        f"采集时至少一方前500的完整归档 {data['eligible']} 场；有效样本 {data['used']} 场。",
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
