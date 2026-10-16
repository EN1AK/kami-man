"""Deterministic deck names from feature cards; runtime rules hot-reload without network access."""
from collections import Counter
from functools import lru_cache
import json
import os
from pathlib import Path
import sqlite3

DEFAULT_RULES = Path(__file__).with_name("deck_names.json")


def _stamp(path):
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size, stat.st_ino


def validate_rules(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("命名规则需要 version: 1")
    if not isinstance(data.get("rules"), list):
        raise ValueError("命名规则需要 rules 数组")
    if "use_defaults" in data and type(data["use_defaults"]) is not bool:
        raise ValueError("use_defaults 必须为 true 或 false")
    result = []
    for rule in data["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("每条命名规则必须是对象")
        label = rule.get("label", rule.get("name"))
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40 or any(ord(c) < 32 for c in label):
            raise ValueError("卡组名称应为 1-40 字的单行文字")
        label = label.strip()
        if "requires" in rule:
            requires = rule["requires"]
            if not isinstance(requires, dict) or not requires:
                raise ValueError("requires 应为非空卡号与最低张数映射")
            minimum = {}
            for code, amount in requires.items():
                if not str(code).isdecimal() or not 0 < int(code) < 2**32 or type(amount) is not int or not 1 <= amount <= 60:
                    raise ValueError("requires 中卡号或张数无效")
                minimum[int(code)] = amount
            result.append({"label": label, "cards": tuple(minimum), "match": "all", "minimum": minimum})
        else:
            cards = rule.get("cards")
            if not isinstance(cards, list) or not cards or any(type(c) is not int or not 0 < c < 2**32 for c in cards):
                raise ValueError("cards 应为非空的正整数卡号数组")
            mode = rule.get("match", "any")
            if mode not in {"any", "all"}:
                raise ValueError("match 只能为 any 或 all")
            result.append({"label": label, "cards": tuple(dict.fromkeys(cards)), "match": mode, "minimum": {}})
    return tuple(result)


@lru_cache(maxsize=16)
def _read(path, modified, size, inode):
    data = json.loads(Path(path).read_text("utf-8"))
    return data, validate_rules(data)


def load_rules(path, *, defaults=DEFAULT_RULES):
    path = Path(path)
    if path.exists():
        data, custom = _read(*_stamp(path))
    else:
        data, custom = {}, ()
    baseline = _read(*_stamp(Path(defaults)))[1] if data.get("use_defaults", True) else ()
    overrides = {rule["label"] for rule in custom}
    return tuple(rule for rule in baseline if rule["label"] not in overrides) + custom


@lru_cache(maxsize=4)
def _catalog(path, modified, size, inode):
    with sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT d.id,d.alias,t.name FROM datas d JOIN texts t ON t.id=d.id").fetchall()
    by_id = {code: (alias, name) for code, alias, name in rows}
    result = {}
    for code, (alias, name) in by_id.items():
        current, seen = code, {code}
        while True:
            target = by_id.get(current, (0, ""))[0]
            # Only explicit aliases with the same printed name are alternate identities.
            if not target or target in seen or target not in by_id or by_id[target][1] != name:
                break
            seen.add(target)
            current = target
        result[code] = current
    return result


def canonical_codes(path=None):
    if path is None:
        path = Path(os.getenv("MYCARD_CARD_DB", str(Path(__file__).resolve().parents[3] / "ygo-rag/data/cards.cdb")))
    try:
        return _catalog(*_stamp(Path(path)))
    except (OSError, sqlite3.Error):
        return {}


def recognize(deck, rules, *, identities=None):
    identities = canonical_codes() if identities is None else identities
    counts = Counter(identities.get(code, code) for code in deck.main)
    evidence = {}
    for rule in rules:
        codes = {identities.get(code, code) for code in rule["cards"]}
        matched = codes.intersection(counts)
        if not matched or rule["match"] == "all" and not codes.issubset(counts):
            continue
        minimum = {}
        for code, amount in rule["minimum"].items():
            canonical = identities.get(code, code)
            minimum[canonical] = max(minimum.get(canonical, 0), amount)
        if any(counts[code] < amount for code, amount in minimum.items()):
            continue
        evidence.setdefault(rule["label"], set()).update(matched)
    scores = {label: sum(counts[code] for code in cards) for label, cards in evidence.items()}
    labels = sorted(evidence, key=scores.get)
    name = "".join(labels)
    if name and len(deck.main) == 60:
        name = "60" + name
    return {"name": name or "未识别", "labels": labels, "counts": scores}


def deck_name(deck, path):
    return recognize(deck, load_rules(path))["name"]
