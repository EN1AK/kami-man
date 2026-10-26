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
    rows,pages=page_rows(data["rows"],page)
    titles=[str(names.get(r["card"]) or names.get(str(r["card"])) or r["card"]) for r in rows]
    duplicates=Counter(titles)
    labels=[label(title,18)+(f"\n[{r['card']}]" if duplicates[title]>1 else "") for title,r in zip(titles,rows)]
    positions,total=row_layout(labels)
    with _RENDER_LOCK:
        figure,ax,f=setup(total,f"前百卡片使用率 · 第{page}/{pages}页",
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
        figure.text(.045,.055,"统计主卡＋额外，不含Side；按卡号区分，同名显示卡号。图示为观测样本。",fontproperties=f,fontsize=11,color="#53647b")
        figure.text(.045,.025,"查询：前百卡片使用率 [页码]　｜　每天更新一次，当日各页使用同一快照。",fontproperties=f,fontsize=10,color="#53647b")
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
