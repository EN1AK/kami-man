"""Stable core-archetype categories, separate from descriptive deck names."""
from collections import Counter
from functools import lru_cache
import json
import os
from pathlib import Path
import sqlite3

DEFAULT_RULES=Path(__file__).with_name("archetype_rules.json")


def stamp(path):
    stat=path.stat()
    return str(path.resolve()),stat.st_mtime_ns,stat.st_size,stat.st_ino


def validate_rules(data):
    if not isinstance(data,dict) or type(data.get("version")) is not int or data.get("version")!=1:
        raise ValueError("大类规则需要version: 1")
    for key in ("minimum_copies","minimum_unique","hybrid_minimum"):
        if type(data.get(key)) is not int or not 1<=data[key]<=60:
            raise ValueError("大类规则阈值应为1～60的整数")
    ratio=data.get("hybrid_ratio")
    if type(ratio) not in (int,float) or not .5<=ratio<=1:
        raise ValueError("混合体系比例应为0.5～1")
    fields=data.get("field_names")
    if not isinstance(fields,dict) or any(not str(k).isdecimal() or not 0<int(k)<=0xfff or not isinstance(v,str) or not v.strip() for k,v in fields.items()):
        raise ValueError("系列字段名称无效")
    ignored=data.get("ignored_fields",[])
    if not isinstance(ignored,list) or any(type(f) is not int or not 0<f<=0xfff for f in ignored):
        raise ValueError("忽略字段无效")
    groups=data.get("groups")
    if not isinstance(groups,list):raise ValueError("大类规则需要groups数组")
    labels=set();claimed=set()
    for rule in groups:
        if not isinstance(rule,dict):raise ValueError("大类规则应为对象")
        label=rule.get("label")
        if not isinstance(label,str) or not label.strip() or len(label)>40 or any(ord(c)<32 for c in label) or label in labels:
            raise ValueError("大类名称无效或重复")
        labels.add(label)
        if "require_core" in rule and type(rule["require_core"]) is not bool:raise ValueError("require_core应为布尔值")
        group_fields=rule.get("fields",[]);cards=rule.get("core_cards",[])
        if not isinstance(group_fields,list) or not isinstance(rule.get("cards",[]),list) or not (group_fields or rule.get("cards")) or any(type(f) is not int or not 0<f<=0xfff or f in claimed for f in group_fields):
            raise ValueError("大类字段无效或重复归属")
        claimed.update(group_fields)
        if not isinstance(cards,list) or any(type(c) is not int or c<=0 for c in cards+rule.get("cards",[])):raise ValueError("核心卡号无效")
        for key in ("minimum_copies","minimum_unique"):
            if key in rule and (type(rule[key]) is not int or not 1<=rule[key]<=60):raise ValueError("大类阈值无效")
    return data


@lru_cache(maxsize=8)
def read_rules(body):
    return validate_rules(json.loads(body))


@lru_cache(maxsize=4)
def read_catalog(path,modified,size,inode):
    with sqlite3.connect(Path(path).as_uri()+"?mode=ro",uri=True) as db:
        return {code:(int(fields)&((1<<64)-1),name) for code,fields,name in db.execute(
            "SELECT d.id,d.setcode,t.name FROM datas d JOIN texts t ON t.id=d.id")}


def recognize_archetype(deck,rules,catalog):
    counts=Counter(deck.main)
    field_names={int(k):v for k,v in rules["field_names"].items()}
    ignored=set(rules.get("ignored_fields",[]))
    explicit={f:r["label"] for r in rules["groups"] for f in r["fields"]}
    group_rules={r["label"]:r for r in rules["groups"]}
    memberships={};identities={}
    for code in counts:
        fields,name=catalog.get(code,(0,""))
        # Printed names identify alternate artworks for uniqueness and anchors.
        identities[code]=name or f"#{code}"
        labels=set()
        for shift in range(0,64,16):
            family=((fields>>shift)&0xffff)&0xfff
            if family and family not in ignored:
                label=explicit.get(family) or field_names.get(family)
                if label:labels.add(label)
        for label in labels:memberships.setdefault(label,set()).add(code)
    for rule in rules["groups"]:
        explicit_names={catalog[c][1] for c in rule.get("cards",[]) if c in catalog and catalog[c][1]}
        for code in counts:
            if identities[code] in explicit_names:memberships.setdefault(rule["label"],set()).add(code)
    candidates=[]
    for label,codes in memberships.items():
        rule=group_rules.get(label,{})
        anchor_names={catalog[c][1] for c in rule.get("core_cards",[]) if c in catalog and catalog[c][1]}
        anchored=bool(set(identities[c] for c in codes)&anchor_names)
        if rule.get("require_core") and not anchored:continue
        # Low-copy engines need direct core-card evidence; otherwise use the conservative default.
        minimum=rule.get("minimum_copies",rules["minimum_copies"]) if anchored else rules["minimum_copies"]
        unique_min=rule.get("minimum_unique",rules["minimum_unique"]) if anchored else rules["minimum_unique"]
        copies=sum(counts[c] for c in codes)
        unique=len({identities[c] for c in codes})
        if copies>=minimum and unique>=unique_min:
            candidates.append(dict(label=label,copies=copies,unique=unique,anchored=anchored,codes=codes))
    candidates.sort(key=lambda r:(-r["copies"],-r["unique"],r["label"]))
    if not candidates:return dict(name="未识别",cores=[],evidence=[])
    primary=candidates[0];cores=[primary]
    for candidate in candidates[1:]:
        minimum=6 if primary["anchored"] and candidate["anchored"] else rules["hybrid_minimum"]
        if candidate["copies"]<minimum or primary["copies"]<minimum or candidate["copies"]<primary["copies"]*rules["hybrid_ratio"]:continue
        # Overlapping family tags describe the same core, not independent engines.
        if any(sum(counts[c] for c in core["codes"]&candidate["codes"])>=min(core["copies"],candidate["copies"])*.5 for core in cores):continue
        cores.append(candidate)
    labels=sorted(r["label"] for r in cores)
    name=labels[0] if len(labels)==1 else "混合："+"＋".join(labels)
    return dict(name=name,cores=labels,evidence=[{k:v for k,v in r.items() if k!="codes"} for r in candidates])


def classify_archetype(deck,rules_path=None):
    configured=os.getenv("MYCARD_ARCHETYPE_RULES")
    custom=Path(configured) if configured else Path(rules_path).with_name("archetype-rules.json") if rules_path else None
    path=custom if configured or custom and custom.is_file() else DEFAULT_RULES
    rules=read_rules(path.read_text(encoding="utf-8"))
    db=Path(os.getenv("MYCARD_CARD_DB",str(Path(__file__).resolve().parents[3]/"ygo-rag/data/cards.cdb")))
    return recognize_archetype(deck,rules,read_catalog(*stamp(db)))["name"]
