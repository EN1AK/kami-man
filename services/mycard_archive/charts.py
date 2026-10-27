"""Headless PNG charts; no pyplot state or network access."""
from io import BytesIO
from pathlib import Path
import os
import threading
import textwrap
from .statistics import page_rows,matchup_matrix
from .impact import ordered_impact_rows,comparison_group

_RENDER_LOCK=threading.Lock()

def font():
    from matplotlib.font_manager import FontProperties
    configured=os.getenv("MYCARD_CHART_FONT")
    candidates=[configured] if configured else [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    for path in candidates:
        if path and Path(path).is_file():
            return FontProperties(fname=path)
    return FontProperties(family="sans-serif")

def label(text,width=16):
    return "\n".join(textwrap.wrap(str(text),width=width,break_long_words=True,break_on_hyphens=False))

def setup(count,title,subtitle,stamp):
    from matplotlib.figure import Figure
    figure=Figure(figsize=(15,max(6,3.8+count*.61)),dpi=130,facecolor="#f5f7fb")
    f=font()
    figure.text(.045,.97,title,fontproperties=f,fontsize=23,weight="bold",color="#15253d",va="top")
    figure.text(.045,.925,subtitle,fontproperties=f,fontsize=11,color="#53647b",va="top")
    figure.text(.955,.97,stamp,fontproperties=f,fontsize=10,color="#53647b",va="top",ha="right")
    ax=figure.add_axes([.32,.16,.49,.73],facecolor="#f5f7fb")
    for spine in ax.spines.values():spine.set_visible(False)
    ax.set_axisbelow(True);ax.grid(axis="x",alpha=.15,color="#53647b")
    ax.set_xlim(0,100);ax.set_xticks([0,25,50,75,100])
    ax.set_xticklabels(["0%","25%","50%","75%","100%"],fontproperties=f,fontsize=10,color="#53647b")
    ax.tick_params(axis="y",length=0,pad=12)
    return figure,ax,f

def row_layout(labels):
    positions=[]
    total=0
    for value in labels:
        weight=max(1,(value.count("\n")+1)*.6)
        positions.append(total+weight/2)
        total+=weight
    return positions,total

def png(figure):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    out=BytesIO()
    FigureCanvasAgg(figure).print_png(out)
    return out.getvalue()

def copy_text(row):
    distribution=row.get("distribution")
    if not distribution or not row.get("players"):return "暂无张数信息"
    def ratio(n):return distribution.get(n,distribution.get(str(n),0))/row["players"]
    text=f"1张 {ratio(1):.1%} · 2张 {ratio(2):.1%}\n3张 {ratio(3):.1%}"
    if distribution.get("4+"):text+=f" · 4+张 {ratio('4+'):.1%}"
    return text

def render_usage(data,names,stamp,page=1):
    rows,pages=page_rows(data["rows"][:100],page)
    titles=[str(r.get("name") or names.get(r["card"]) or names.get(str(r["card"])) or r["card"]) for r in rows]
    labels=[label(title,18) for title in titles]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"前五百主卡 / Side使用率 · 前100张 · 第{page}/{pages}页",
            f"覆盖 {data['covered']}/{data['total']} 人 · 缺失 {data['missing']} 人 · 观察到Side的玩家 {data.get('side_observed',0)} 人 · 归档排名未核验 {data.get('rank_unverified',0)} 人",stamp)
        figure.set_size_inches(20,figure.get_figheight())
        ax.set_position([.26,.16,.69,.73])
        ax.set_xlim(0,400);ax.set_xticks([]);ax.grid(False)
        for x in (100,200,300):ax.axvline(x,color="#dce3ef",linewidth=.7)
        for x,title in ((35,"主卡投入"),(135,"Side投入（观测）"),(235,"总使用率"),(345,"投入张数占比（携带者）")):
            ax.text(x,1.02,title,transform=ax.get_xaxis_transform(),ha="center",fontproperties=f,fontsize=11,color="#15253d")
        den=data["covered"] or 1
        for i,r in enumerate(rows):
            ax.text(305,positions[i],copy_text(r),fontproperties=f,fontsize=9.5,va="center",color="#15253d")
            values=((r.get("main",0)/den,r.get("main",0),r.get("main_copies",r.get("copies",0)),"#377ded"),
                    (r.get("side",0)/den,r.get("side",0),r.get("side_copies",0),"#e8ac5d"),
                    (r["rate"],r["players"],None,"#38a593"))
            for column,(rate,n,copies,color) in enumerate(values):
                base=column*100
                ax.barh(positions[i],68,height=.48,left=base,color="#e5eaf2")
                ax.barh(positions[i],rate*68,height=.48,left=base,color=color)
                note=f"{rate:.1%}\n{n}人/{copies}张" if copies is not None else f"{rate:.1%}\n{n}/{data['covered']}人"
                ax.text(base+72,positions[i],note,fontproperties=f,fontsize=8.2,va="center",color="#15253d",clip_on=False)
        if rows:
            ax.set_yticks(positions);ax.set_yticklabels(labels,fontproperties=f,fontsize=11,color="#15253d");ax.set_ylim(total,0)
        else:
            ax.set_yticks([]);ax.text(.5,.5,"暂无完整卡组样本",transform=ax.transAxes,fontproperties=f,fontsize=16,ha="center")
        figure.text(.045,.085,"投入率按携带人数计算；总使用率＝主卡与Side携带人数去重并集 ÷ 覆盖人数，非两率相加。",fontproperties=f,fontsize=10,color="#53647b")
        figure.text(.045,.055,"张数分布按携带者计算，主卡＋观测Side合算；Side未知可能低估，观测4+另列，不代表合法配置。",fontproperties=f,fontsize=10,color="#53647b")
        figure.text(.045,.025,"按总使用率排序，仅列前100张；同名不同卡号已合并。每天更新，按需查询：卡片使用率 [页码]",fontproperties=f,fontsize=10,color="#53647b")
        return png(figure)

def render_extra(data,names,stamp,page=1):
    rows,pages=page_rows(data["extra_rows"][:100],page)
    titles=[str(r.get("name") or names.get(r["card"]) or names.get(str(r["card"])) or r["card"]) for r in rows]
    labels=[label(title,18) for title in titles]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"前五百额外卡组使用率 · 前100张 · 第{page}/{pages}页",
            f"完整卡组覆盖 {data['covered']}/{data['total']} 人  ·  缺失 {data['missing']} 人  ·  超过7天未更新 {data['stale']} 人 · 归档排名未核验 {data.get('rank_unverified',0)} 人",stamp)
        figure.set_size_inches(20,figure.get_figheight())
        ax.set_position([.26,.16,.42,.73])
        ax.text(145,1.02,"投入张数占比（携带者）",transform=ax.get_xaxis_transform(),ha="center",fontproperties=f,fontsize=11,color="#15253d")
        if rows:
            values=[r["rate"]*100 for r in rows]
            ax.barh(positions,values,height=.56,color="#377ded")
            ax.set_yticks(positions)
            ax.set_yticklabels(labels,fontproperties=f,fontsize=11,color="#15253d")
            ax.set_ylim(total,0)
            for i,r in enumerate(rows):
                ax.text(127,positions[i],copy_text(r),fontproperties=f,fontsize=10,va="center",color="#15253d",clip_on=False)
                ax.text(103,positions[i],f"{r['rate']:.1%}  ·  {r['players']}/{data['covered']}人",
                    fontproperties=f,fontsize=10,va="center",color="#15253d",clip_on=False)
        else:
            ax.set_yticks([])
            ax.text(.5,.5,"暂无完整卡组样本",transform=ax.transAxes,fontproperties=f,fontsize=16,ha="center")
        figure.text(.045,.085,"使用率 = 携带人数 ÷ 已覆盖人数；每人仅取最新一套观测卡组。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.055,"仅统计额外卡组；同名合并。张数占比以携带该卡的玩家为分母，非全部前五百。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.025,"查询：额外卡组使用率 [页码]　｜　每天更新一次，当日各页使用同一快照。",fontproperties=f,fontsize=10,color="#53647b")
        return png(figure)

def render_matchups(data,stamp,page=1):
    if page!=1:raise ValueError("对阵热力图只有1页")
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle
    matrix=matchup_matrix(data)
    names=matrix["names"];count=len(names)
    cutoff=data.get("rank_cutoff",100)
    with _RENDER_LOCK:
        f=font()
        figure=Figure(figsize=(21,21),dpi=140,facecolor="#f5f7fb")
        figure.text(.045,.97,f"卡组对阵热力图 · 前{cutoff}样本 · 出场前20 · 近{data['days']}天",fontproperties=f,fontsize=25,weight="bold",color="#15253d",va="top")
        figure.text(.955,.97,stamp,fontproperties=f,fontsize=10,color="#53647b",ha="right",va="top")
        figure.text(.045,.94,f"有效样本 {data['used']} 场 · 图中双方均入选 {matrix['shown_matches']} 场 · 展示 {count} 类；按全部有效对局出场次数排序，内战双方各计一次。",fontproperties=f,fontsize=12,color="#53647b")
        figure.text(.045,.918,f"行卡组对列卡组的胜率｜n＝该组合完整Match场数；未核实 {data['missing_result']} · 缺卡组 {data['missing_deck']} · 未识别 {data['unclassified']}",fontproperties=f,fontsize=11,color="#53647b")
        ax=figure.add_axes([.20,.22,.68,.68])
        if count:
            cmap=LinearSegmentedColormap.from_list("matchup_winrate",["#b95724","#f9f9f5","#246db4"])
            cmap.set_bad("#e1e5ed")
            values=np.array([[np.nan if r is None else r*100 for r in row] for row in matrix["rates"]])
            plot=ax.imshow(np.ma.masked_invalid(values),cmap=cmap,vmin=0,vmax=100,aspect="equal",interpolation="nearest")
            ax.set_xticks(range(count));ax.set_yticks(range(count))
            ax.set_xticklabels([label(f"{i+1}. {name}",11) for i,name in enumerate(names)],rotation=55,ha="right",rotation_mode="anchor",fontproperties=f,fontsize=10)
            ax.set_yticklabels([label(f"{i+1}. {name}",14)+f"\n{matrix['appearances'][i]} 次" for i,name in enumerate(names)],fontproperties=f,fontsize=10)
            ax.tick_params(length=0,pad=8,colors="#15253d")
            ax.set_xticks(np.arange(-.5,count,1),minor=True);ax.set_yticks(np.arange(-.5,count,1),minor=True)
            ax.grid(which="minor",color="#f5f7fb",linewidth=1.3);ax.tick_params(which="minor",length=0)
            for i in range(count):
                for j in range(count):
                    n=matrix["samples"][i][j];rate=matrix["rates"][i][j]
                    if i==j:
                        ax.add_patch(Rectangle((j-.5,i-.5),1,1,facecolor="#c9d1df",edgecolor="#f5f7fb",linewidth=1.3))
                        note=f"内战\nn={n}"
                    elif rate is None:note="—"
                    else:note=f"{rate:.0%}"+("*" if n<10 else "")+f"\nn={n}"
                    color="#ffffff" if rate is not None and (rate<.2 or rate>.8) else "#15253d"
                    ax.text(j,i,note,ha="center",va="center",fontproperties=f,fontsize=8.5,color=color)
            for spine in ax.spines.values():spine.set_visible(False)
            color_ax=figure.add_axes([.905,.28,.014,.56])
            bar=figure.colorbar(plot,cax=color_ax,ticks=[0,25,50,75,100])
            bar.ax.set_yticklabels(["0%","25%","50%","75%","100%"],fontproperties=f,fontsize=10)
            bar.set_label("行方胜率",fontproperties=f,fontsize=11,labelpad=10)
            bar.outline.set_visible(False)
        else:
            ax.set_axis_off();ax.text(.5,.5,"暂无可核实的对阵样本",transform=ax.transAxes,fontproperties=f,fontsize=20,ha="center")
        figure.text(.045,.075,"蓝色＝行方胜率高，橙色＝行方胜率低，浅色＝接近50%；* 少于10场，样本较少。灰色“—”＝无样本。",fontproperties=f,fontsize=12,color="#53647b")
        figure.text(.045,.05,f"对角线仅列内战场数，不填50%胜率。至少一方采集时前{cutoff}；官方核实胜负，每场Match只计一次。观战样本非全平台胜率。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.025,"查询：卡组对阵胜率 [前100/前500] [天数1～90]　｜　默认前100；热力图共一页，每天更新，完整列表加“文字”。",fontproperties=f,fontsize=11,color="#53647b")
        return png(figure)



def render_impact(data,stamp,page=1,extra=False):
    kind="extra" if extra else "main"
    rows,pages=page_rows(ordered_impact_rows(data,extra),page)
    labels=[label(r["name"],16)+"\n"+label("对照大类："+"、".join(comparison_group(r)[1]),18) for r in rows]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"卡片携带胜率差 · {'额外' if extra else '主卡'} · 前{data['rank_cutoff']} · 近{data['days']}天 · {page}/{pages}页",
            f"有效玩家对局 {data['samples']} 次 / {data['players']} 人 · 同体系比较后加权 · 不可比较卡 {data[kind+'_uncomparable']} 种",stamp)
        figure.set_size_inches(21,figure.get_figheight())
        ax.set_position([.24,.18,.35,.68]);ax.set_xlim(-100,100)
        ax.set_xticks([-100,-50,0,50,100]);ax.set_xticklabels(["−100pp","−50pp","0","+50pp","+100pp"],fontproperties=f,fontsize=10)
        ax.axvline(0,color="#53647b",linewidth=1)
        for x,title in ((.64,"加权携带 / 未携带胜率"),(.80,"携带 / 未携带样本 · 体系数")):
            figure.text(x,.88,title,fontproperties=f,fontsize=11,color="#15253d")
        for i in range(1,len(rows)):
            if comparison_group(rows[i])!=comparison_group(rows[i-1]):
                ax.axhline((positions[i]+positions[i-1])/2,color="#c6d0df",linewidth=1)
        for y,r in zip(positions,rows):
            delta=r["delta"]*100
            ax.barh(y,delta,height=.53,color="#2676c9" if delta>=0 else "#c26b35")
            ax.text(delta+(2 if delta>=0 else -2),y,f"{delta:+.1f}pp",ha="left" if delta>=0 else "right",va="center",fontproperties=f,fontsize=10,color="#15253d")
            ax.text(125,y,f"{r['with_rate']:.1%} / {r['without_rate']:.1%}",fontproperties=f,fontsize=11,va="center",clip_on=False,color="#15253d")
            ax.text(215,y,f"{r['with_n']} / {r['without_n']} 次 · {r['classes']}类",fontproperties=f,fontsize=11,va="center",clip_on=False,color="#15253d")
        if rows:
            ax.set_yticks(positions);ax.set_yticklabels(labels,fontproperties=f,fontsize=11);ax.set_ylim(total,0)
        else:
            ax.set_yticks([]);ax.text(.5,.5,"暂无满足双组样本门槛的卡片",transform=ax.transAxes,ha="center",fontproperties=f,fontsize=16)
        figure.text(.045,.11,f"每个体系携带、未携带各至少{data['minimum_samples']}次且各至少{data['minimum_players']}位玩家；缺少对照不等于零影响。按对照大类分组，组内按差值绝对值排序；多类加权单列。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.075,"卡名下列出全部对照大类；多类为同体系差值的加权汇总，单位为百分点。同名异画合并，每名玩家每场记一次。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.045,"相关差异并非因果提升；未控制玩家水平、对手构成及先后手。仅首份观测主卡/额外，不含不完整Side。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.02,"查询：卡片影响度 [前100/前500] [天数] [页码] [额外]；每天更新，可加“文字”查看各对照大类的差值和样本量。",fontproperties=f,fontsize=10,color="#53647b")
        return png(figure)
