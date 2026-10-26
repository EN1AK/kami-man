"""Headless PNG charts; no pyplot state or network access."""
from io import BytesIO
from collections import Counter
from pathlib import Path
import os
import threading
import textwrap
from .statistics import page_rows

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

def render_usage(data,names,stamp,page=1):
    rows,pages=page_rows(data["rows"][:100],page)
    titles=[str(names.get(r["card"]) or names.get(str(r["card"])) or r["card"]) for r in rows]
    duplicates=Counter(titles)
    labels=[label(title,18)+(f"\n[{r['card']}]" if duplicates[title]>1 else "") for title,r in zip(titles,rows)]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"前百主卡 / Side使用率 · 前100张 · 第{page}/{pages}页",
            f"覆盖 {data['covered']}/{data['total']} 人 · 缺失 {data['missing']} 人 · 观察到Side的玩家 {data.get('side_observed',0)} 人",stamp)
        ax.set_position([.32,.16,.62,.73])
        ax.set_xlim(0,300);ax.set_xticks([]);ax.grid(False)
        for x in (100,200):ax.axvline(x,color="#dce3ef",linewidth=.7)
        for x,title in ((35,"主卡投入"),(135,"Side投入（观测）"),(235,"总使用率")):
            ax.text(x,1.02,title,transform=ax.get_xaxis_transform(),ha="center",fontproperties=f,fontsize=11,color="#15253d")
        den=data["covered"] or 1
        for i,r in enumerate(rows):
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
        figure.text(.045,.055,"Side仅包含已观测换入；未曝光备牌未知，Side与总使用率是观测下界。额外卡组另表统计。",fontproperties=f,fontsize=10,color="#53647b")
        figure.text(.045,.025,"按总使用率排序，仅列前100张；同名显示卡号。每天更新，按需查询：前百卡片使用率 [页码]",fontproperties=f,fontsize=10,color="#53647b")
        return png(figure)

def render_extra(data,names,stamp,page=1):
    rows,pages=page_rows(data["extra_rows"][:100],page)
    titles=[str(names.get(r["card"]) or names.get(str(r["card"])) or r["card"]) for r in rows]
    duplicates=Counter(titles)
    labels=[label(title,18)+(f"\n[{r['card']}]" if duplicates[title]>1 else "") for title,r in zip(titles,rows)]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"前百额外卡组使用率 · 前100张 · 第{page}/{pages}页",
            f"完整卡组覆盖 {data['covered']}/{data['total']} 人  ·  缺失 {data['missing']} 人  ·  超过7天未更新 {data['stale']} 人",stamp)
        if rows:
            values=[r["rate"]*100 for r in rows]
            ax.barh(positions,values,height=.56,color="#377ded")
            ax.set_yticks(positions)
            ax.set_yticklabels(labels,fontproperties=f,fontsize=11,color="#15253d")
            ax.set_ylim(total,0)
            for i,r in enumerate(rows):
                ax.text(103,positions[i],f"{r['rate']:.1%}  ·  {r['players']}/{data['covered']}人",
                    fontproperties=f,fontsize=10,va="center",color="#15253d",clip_on=False)
        else:
            ax.set_yticks([])
            ax.text(.5,.5,"暂无完整卡组样本",transform=ax.transAxes,fontproperties=f,fontsize=16,ha="center")
        figure.text(.045,.085,"使用率 = 携带人数 ÷ 已覆盖人数；每人仅取最新一套观测卡组。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.055,"只统计额外卡组投入，不混入主卡/Side表；按卡号区分。图示为观测样本。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.025,"查询：额外卡组使用率 [页码]　｜　每天更新一次，当日各页使用同一快照。",fontproperties=f,fontsize=10,color="#53647b")
        return png(figure)

def render_matchups(data,stamp,page=1):
    rows,pages=page_rows(data["rows"],page)
    labels=[label(r["a"],17) if r["a"]==r["b"] else label(r["a"],17)+"\nvs "+label(r["b"],15) for r in rows]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"卡组分类对阵胜率 · 近{data['days']}天 · 第{page}/{pages}页",
            f"有效样本 {data['used']} 场 / 完整归档 {data['eligible']} 场；未核实胜负 {data['missing_result']} · 缺卡组 {data['missing_deck']} · 未识别 {data['unclassified']}",stamp)
        for i,r in enumerate(rows):
            y=positions[i]
            n=r["matches"]
            if r["a"]==r["b"]:
                ax.barh(y,100,height=.56,color="#c7d0df")
                note=f"内战 {n}场"
            else:
                rate=r["a_wins"]/n*100
                alpha=.55 if n<10 else 1
                ax.barh(y,rate,height=.56,color="#377ded",alpha=alpha)
                ax.barh(y,100-rate,left=rate,height=.56,color="#e8ac5d",alpha=alpha)
                note=f"{rate:.1f}%  ·  {r['a_wins']}胜{r['b_wins']}负"+(" *" if n<10 else "")
            ax.text(103,y,note,fontproperties=f,fontsize=10,va="center",color="#15253d",clip_on=False)
        if rows:
            ax.set_yticks(positions);ax.set_yticklabels(labels,fontproperties=f,fontsize=10,color="#15253d");ax.set_ylim(total,0)
        else:
            ax.set_yticks([])
            ax.text(.5,.5,"暂无可核实的对阵样本",transform=ax.transAxes,fontproperties=f,fontsize=16,ha="center")
        figure.text(.045,.085,"蓝色＝每行第一方卡组获胜，橙色＝对手获胜；* 少于10场，样本较少。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.055,"至少一方采集时前100；按官方胜者核对，每场Match只计一次。观战样本非全平台胜率。",fontproperties=f,fontsize=10,color="#53647b")
        figure.text(.045,.025,"查询：卡组对阵胜率 [天数1～90] [页码]　｜　每天更新一次；灰色内战不计算方向胜率。",fontproperties=f,fontsize=10,color="#53647b")
        return png(figure)
