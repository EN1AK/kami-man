"""Readable archive/deck summaries and independently encoded OURYGO links."""
from collections import Counter
from datetime import datetime
import base64
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Shanghai")

def moment(value):
    return datetime.fromtimestamp(value,TZ).strftime("%Y-%m-%d %H:%M") if value else "未知"

def deck_url(deck,*,title=None):
    parts=[Counter(deck.main),Counter(deck.extra),Counter(deck.side)]
    if len(parts[0])>255 or len(parts[1])>15 or len(parts[2])>15:raise ValueError("分享码无法容纳此观测卡组")
    bits=0;width=0
    def append(value,length):
        nonlocal bits,width
        bits=(bits<<length)|value;width+=length
    for entries,length in zip(parts,[8,4,4]):append(len(entries),length)
    for entries in parts:
        for code,count in sorted(entries.items()):
            if not 0<code<134217728 or not 1<=count<=3:raise ValueError("卡号或数量不受分享码支持")
            append(count,2);append(code,27)
    padding=(-width)%8
    encoded=(bits<<padding).to_bytes((width+padding)//8,"big")
    token=base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
    return "http://deck.ourygo.top/?"+urlencode({"ygotype":"deck","v":"1","d":token,"name":deck.player if title is None else title})

def classify(deck,rules_path):
    from .naming import deck_name
    return deck_name(deck,rules_path)


def deck_summary(version,rules_path):
    from .replay import ObservedDeck
    deck=ObservedDeck(version["player"],tuple(version["main"]),tuple(version["extra"]),tuple(version["side"]))
    name=classify(deck,rules_path)
    lines=[f"玩家：{deck.player}",f"卡组：{name}",f"主卡 {len(deck.main)} / 额外 {len(deck.extra)} / 已观察 Side {len(deck.side)}",
           f"首次观察：{moment(version['first_seen'])}",f"最近观察：{moment(version['last_seen'])}；同版本观察 {version['observations']} 场",
           "Side 不完整：只包含实际观察到的换入卡，未使用的备牌未知。"]
    title=deck.player+("〖"+name+"〗" if name!="未识别" else "")
    try:lines.append("卡组链接："+deck_url(deck,title=title))
    except ValueError:lines.append("此观测结果无法编码为单个分享链接，原始 YDK 仍完整保留。")
    lines.append("最近归档："+version["match_id"])
    return "\n".join(lines)
