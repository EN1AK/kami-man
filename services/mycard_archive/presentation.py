"""Readable archive/deck summaries and independently encoded OURYGO links."""
from collections import Counter
from datetime import datetime
import base64
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Shanghai")

def moment(value):
    return datetime.fromtimestamp(value,TZ).strftime("%Y-%m-%d %H:%M") if value else "未知"

def deck_url(deck):
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
    return "http://deck.ourygo.top/?"+urlencode({"ygotype":"deck","v":"1","d":token,"name":deck.player})

def classify(deck,rules_path):
    if not rules_path.exists():return "未分类"
    rules=json.loads(rules_path.read_text(encoding="utf-8"))
    if not isinstance(rules,dict) or not isinstance(rules.get("rules"),list):raise ValueError("卡组分类规则格式错误")
    counts=Counter(deck.main+deck.extra)
    labels=[]
    for rule in rules["rules"]:
        if not isinstance(rule,dict) or not isinstance(rule.get("name"),str) or not isinstance(rule.get("requires"),dict):raise ValueError("卡组分类规则格式错误")
        required=rule["requires"]
        if not required:continue
        if any(not str(code).isdecimal() or type(amount) is not int or amount<1 for code,amount in required.items()):raise ValueError("卡组分类规则数量错误")
        if all(counts[int(code)]>=amount for code,amount in required.items()):labels.append(rule["name"])
    return "/".join(labels) or "未分类"

def deck_summary(version,rules_path):
    from .replay import ObservedDeck
    deck=ObservedDeck(version["player"],tuple(version["main"]),tuple(version["extra"]),tuple(version["side"]))
    lines=[f"玩家：{deck.player}",f"卡组：{classify(deck,rules_path)}",f"主卡 {len(deck.main)} / 额外 {len(deck.extra)} / 已观察 Side {len(deck.side)}",
           f"首次观察：{moment(version['first_seen'])}",f"最近观察：{moment(version['last_seen'])}；同版本观察 {version['observations']} 场",
           "Side 不完整：只包含实际观察到的换入卡，未使用的备牌未知。"]
    try:lines.append("卡组链接："+deck_url(deck))
    except ValueError:lines.append("此观测结果无法编码为单个分享链接，原始 YDK 仍完整保留。")
    lines.append("最近归档："+version["match_id"])
    return "\n".join(lines)
