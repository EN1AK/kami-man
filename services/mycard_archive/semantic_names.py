"""Text-defined deck cores not represented by a dedicated setcode."""
from collections import Counter
from functools import lru_cache
import json
import sqlite3
from pathlib import Path
from .statistics import CARD_ALIASES_FILE,card_db_path


def signature(path):
    try:
        s=path.stat();return str(path.resolve()),s.st_mtime_ns,s.st_size,s.st_ino
    except OSError:return str(path),0,0,0


@lru_cache(maxsize=4)
def catalog(db_stamp,alias_stamp):
    with sqlite3.connect(Path(db_stamp[0]).as_uri()+"?mode=ro",uri=True) as db:
        # Only main-deck cards whose text literally mentions the shared core.
        result={code:name for code,name in db.execute(
            "SELECT d.id,t.name FROM datas d JOIN texts t USING(id) WHERE (d.type & ?)=0 AND (t.name=? OR t.desc LIKE ?)",
            (64|8192|8388608|16384,"时间黑魔术师","%「时间黑魔术师」%"))}
    try:
        aliases=json.loads(CARD_ALIASES_FILE.read_text(encoding="utf-8"))
    except (OSError,ValueError):aliases={}
    if isinstance(aliases,dict):
        names=set(result.values())
        for code,info in aliases.items():
            if str(code).isdecimal() and isinstance(info,dict):
                name=result.get(info.get("id")) or (info.get("name") if info.get("name") in names else None)
                if name:result[int(code)]=name
    return result


def jounouchi_core(deck):
    try:
        known=catalog(signature(card_db_path()),signature(CARD_ALIASES_FILE))
    except (OSError,sqlite3.Error):
        return None
    counts=Counter(deck.main)
    codes={code for code in counts if code in known}
    copies=sum(counts[c] for c in codes)
    unique=len({known[c] for c in codes})
    # One support card/playset is insufficient to identify the entire deck.
    if copies>=6 and unique>=3:
        return dict(label="城之内",copies=copies,unique=unique,anchored=True,codes=codes)
    return None
