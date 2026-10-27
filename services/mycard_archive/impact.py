"""Within-archetype card inclusion associations, never causal or draw effects."""
from collections import Counter
import json
import time
from .archetypes import classify_archetype
from .replay import ObservedDeck
from .statistics import usable,card_names,page_rows

MIN_SAMPLES=20
MIN_PLAYERS=3


def summarize(samples,names,min_samples=MIN_SAMPLES,min_players=MIN_PLAYERS):
    codes={c for s in samples for kind in ("main","extra") for c in s[kind]}
    representatives={};canonical={};labels={}
    for c in sorted(codes):
        name=names.get(c);name=name.strip() if isinstance(name,str) else ""
        key=("name",name) if name else ("id",c)
        canonical[c]=representatives.setdefault(key,c)
        labels[canonical[c]]=name or str(c)
    totals={};present={kind:{} for kind in ("main","extra")}
    for s in samples:
        group=totals.setdefault(s["archetype"],dict(n=0,wins=0,players=Counter()))
        group["n"]+=1;group["wins"]+=s["won"];group["players"][s["player"]]+=1
        for kind in present:
            for card in {canonical[c] for c in s[kind]}:
                row=present[kind].setdefault(card,{}).setdefault(s["archetype"],dict(n=0,wins=0,players=Counter()))
                row["n"]+=1;row["wins"]+=s["won"];row["players"][s["player"]]+=1
    result={"archetype_counts":{name:r["n"] for name,r in totals.items()}}
    for kind,entries in present.items():
        rows=[]
        for card,groups in entries.items():
            comparisons=[]
            for archetype,yes in groups.items():
                total=totals[archetype];n0=total["n"]-yes["n"]
                no_players=sum(n>yes["players"][p] for p,n in total["players"].items())
                if min(yes["n"],n0)<min_samples or min(len(yes["players"]),no_players)<min_players:continue
                comparisons.append(dict(archetype=archetype,with_n=yes["n"],without_n=n0,
                    with_players=len(yes["players"]),without_players=no_players,
                    with_rate=yes["wins"]/yes["n"],without_rate=(total["wins"]-yes["wins"])/n0,
                    weight=yes["n"]*n0/total["n"]))
            if not comparisons:continue
            weight=sum(r["weight"] for r in comparisons)
            with_rate=sum(r["with_rate"]*r["weight"] for r in comparisons)/weight
            without_rate=sum(r["without_rate"]*r["weight"] for r in comparisons)/weight
            comparisons.sort(key=lambda r:(-r["weight"],r["archetype"]))
            rows.append(dict(card=card,name=labels[card],delta=with_rate-without_rate,
                with_rate=with_rate,without_rate=without_rate,
                with_n=sum(r["with_n"] for r in comparisons),without_n=sum(r["without_n"] for r in comparisons),
                classes=len(comparisons),comparisons=comparisons))
        rows.sort(key=lambda r:(-abs(r["delta"]),-(r["with_n"]+r["without_n"]),r["card"]))
        result[kind+"_rows"]=rows[:100]
        result[kind+"_uncomparable"]=len(entries)-len(rows)
        result[kind+"_comparable"]=len(rows)
    return result


def impact_stats(store,days=30,now=None,rank_cutoff=100,classifier=classify_archetype,names=None):
    if type(days) is not int or not 1<=days<=90 or type(rank_cutoff) is not int or rank_cutoff not in (100,500):
        raise ValueError("统计范围应为前100/前500，天数1～90")
    now=time.time() if now is None else now
    with store.connect() as db:
        rows=db.execute("""SELECT m.players,m.ranks,r.winner,a.deck deck_a,b.deck deck_b
            FROM matches m LEFT JOIN official_match_results r ON r.match_id=m.id
            LEFT JOIN observations a ON a.match_id=m.id AND a.player=json_extract(m.players,'$[0]')
            LEFT JOIN observations b ON b.match_id=m.id AND b.player=json_extract(m.players,'$[1]')
            WHERE m.status='complete' AND m.normal_end=1 AND m.first_seen>=?""",(now-days*86400,)).fetchall()
    samples=[];cache={};eligible=missing_result=missing_deck=unclassified=0
    for row in rows:
        players=json.loads(row["players"]);ranks=json.loads(row["ranks"])
        selected=[p for p in players if type(ranks.get(p)) is int and 1<=ranks[p]<=rank_cutoff]
        if not selected:continue
        eligible+=1
        if row["winner"] not in players:missing_result+=1;continue
        for index,player in enumerate(players):
            if player not in selected:continue
            raw=row["deck_a" if index==0 else "deck_b"]
            deck=json.loads(raw) if raw else None
            if not usable(deck):missing_deck+=1;continue
            key=tuple(sorted(deck["main"]))
            if key not in cache:cache[key]=classifier(ObservedDeck("",tuple(deck["main"]),tuple(deck["extra"]),()),store.rules_path)
            archetype=cache[key]
            if not archetype or archetype=="未识别":unclassified+=1;continue
            samples.append(dict(player=player,archetype=archetype,main=deck["main"],extra=deck["extra"],won=int(player==row["winner"])))
    if names is None:names=card_names(c for s in samples for kind in ("main","extra") for c in s[kind])
    return dict(days=days,rank_cutoff=rank_cutoff,eligible=eligible,missing_result=missing_result,
        missing_deck=missing_deck,unclassified=unclassified,samples=len(samples),
        players=len({s["player"] for s in samples}),archetypes=len({s["archetype"] for s in samples}),
        minimum_samples=MIN_SAMPLES,minimum_players=MIN_PLAYERS,**summarize(samples,names))



def comparison_group(row):
    names=tuple(sorted({c["archetype"] for c in row["comparisons"]}))
    return (int(len(names)>1),names)


def ordered_impact_rows(data,extra=False):
    rows=data["extra_rows" if extra else "main_rows"]
    counts=dict(data.get("archetype_counts",{}))
    for row in rows:
        for c in row["comparisons"]:counts.setdefault(c["archetype"],c["with_n"]+c["without_n"])
    def key(row):
        multi,names=comparison_group(row)
        return (multi,-sum(counts.get(name,0) for name in names),names,-abs(row["delta"]),-(row["with_n"]+row["without_n"]),row["card"])
    return sorted(rows,key=key)

def impact_text(data,page=1,extra=False):
    kind="extra" if extra else "main"
    rows,pages=page_rows(ordered_impact_rows(data,extra),page)
    lines=[f"卡片携带胜率差｜前{data['rank_cutoff']}｜近{data['days']}天｜{'额外' if extra else '主卡'}｜{page}/{pages}页",
        f"有效玩家对局 {data['samples']} 次 / {data['players']} 人；同体系比较后按重叠样本权重合并。",
        f"每个体系携带/未携带各至少{data['minimum_samples']}次、各至少{data['minimum_players']}人；不可比较卡 {data[kind+'_uncomparable']} 种。"]
    previous=None
    for r in rows:
        group=comparison_group(r)
        if group!=previous:
            lines.append("【"+("多类加权：" if group[0] else "大类：")+"、".join(group[1])+"】")
            previous=group
        lines.append(f"{r['name']}：{r['delta']*100:+.1f}个百分点｜加权携带 {r['with_rate']:.1%} / 未携带 {r['without_rate']:.1%}"
                     f"｜样本 {r['with_n']}/{r['without_n']} 次｜{r['classes']}个体系")
        lines.append("对照大类："+"；".join(f"{c['archetype']} {100*(c['with_rate']-c['without_rate']):+.1f}pp（{c['with_n']}/{c['without_n']}次）" for c in r["comparisons"]))
    if not rows:lines.append("暂无达到双组样本门槛的卡片；缺少对照不代表影响为0。")
    lines.append("只比较首份观测主卡/额外，不含Side；相关差异不是因果提升，未控制玩家水平、对手构成和先后手。")
    return "\n".join(lines)
