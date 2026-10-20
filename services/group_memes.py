"""Local category memes with persistent admission limits; no model dependencies."""
import base64
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import time
import unicodedata

from services.group_chat_store import ALLOWED_GROUPS

MAX_BYTES = 4*1024*1024
DAILY_IMAGE_LIMIT = 5
IMAGE_COOLDOWN = 1800
IMAGE_PROBABILITY = 0.25
REPEAT_SECONDS = 7*86400
EXTENSIONS = {".png",".jpg",".jpeg",".webp",".gif"}
CHINA = timezone(timedelta(hours=8))


def category_key(text):
    if not isinstance(text,str):
        return None
    text = "".join(c for c in text if unicodedata.category(c)!="Cf")
    return text if re.fullmatch(r"[a-z_][a-z0-9_]{0,31}",text) else None


def image_bytes(data):
    return (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
            or data.startswith((b"GIF87a",b"GIF89a"))
            or (len(data)>=12 and data[:4]==b"RIFF" and data[8:12]==b"WEBP"))


@dataclass(frozen=True)
class MemeSelection:
    category: str
    image: str
    digest: str


class MemeLibrary:
    def __init__(self, root, db_path, *, draw=random.random, choose=random.choice, allowed_groups=ALLOWED_GROUPS):
        self.root = Path(root)
        self.db_path = Path(db_path)
        self.draw = draw
        self.choose = choose
        self.allowed_groups = allowed_groups

    def allowed(self, group):
        return type(group) is int and group>0 and (self.allowed_groups is None or group in self.allowed_groups)

    def inventory(self):
        # Re-scan a small local pack, never read all image contents into memory.
        if self.root.is_symlink():
            return {}
        manifest = self.root/"manifest.json"
        if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size>65536:
            return {}
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError,ValueError):
            return {}
        if not isinstance(data,dict) or not isinstance(data.get("categories"),dict):
            return {}
        descriptions = {}
        for name,item in data["categories"].items():
            key = category_key(name)
            desc = item.get("description") if isinstance(item,dict) else None
            if key and isinstance(desc,str) and 1<=len(desc)<=160:
                descriptions[key] = desc
        memes = self.root/"memes"
        if not memes.is_dir() or memes.is_symlink():
            return {}
        boundary = memes.resolve()
        result = {}
        for directory in sorted(memes.iterdir()):
            key = category_key(directory.name)
            if key not in descriptions or directory.is_symlink() or not directory.is_dir():
                continue
            files = []
            for path in sorted(directory.iterdir()):
                try:
                    if (path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS
                            or not path.resolve().is_relative_to(boundary) or not 12<=path.stat().st_size<=MAX_BYTES):
                        continue
                    files.append(path)
                except OSError:
                    continue
            if files:
                result[key] = (descriptions[key],files)
        return dict(list(result.items())[:32])

    def connect(self):
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        db = sqlite3.connect(self.db_path,timeout=5)
        db.execute("""CREATE TABLE IF NOT EXISTS group_meme_history (
            id INTEGER PRIMARY KEY,group_id INTEGER NOT NULL,day TEXT NOT NULL,
            category TEXT NOT NULL,digest TEXT NOT NULL,created REAL NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS group_meme_history_group ON group_meme_history(group_id,created)")
        db.commit()
        return db

    @staticmethod
    def day(now):
        return datetime.fromtimestamp(now,CHINA).date().isoformat()

    def capacity(self, db, group, now):
        count = db.execute("SELECT COUNT(*) FROM group_meme_history WHERE group_id=? AND day=?",(group,self.day(now))).fetchone()[0]
        last = db.execute("SELECT MAX(created) FROM group_meme_history WHERE group_id=?",(group,)).fetchone()[0]
        return count<DAILY_IMAGE_LIMIT and (last is None or now-last>=IMAGE_COOLDOWN)

    def categories(self, group, now=None):
        if not self.allowed(group):
            return []
        now = time.time() if now is None else now
        with closing(self.connect()) as db:
            if not self.capacity(db,group,now):
                return []
        return [dict(category=k,description=v[0]) for k,v in self.inventory().items()]

    def reserve(self, group, category, now=None):
        if not self.allowed(group) or category_key(category)!=category:
            return None
        if self.draw()>=IMAGE_PROBABILITY:
            return None
        now = time.time() if now is None else now
        inventory = self.inventory()
        if category not in inventory:
            return None
        paths = list(inventory[category][1])
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM group_meme_history WHERE created<?",(now-30*86400,))
            if not self.capacity(db,group,now):
                return None
            used = {r[0] for r in db.execute("SELECT digest FROM group_meme_history WHERE group_id=? AND created>=?",(group,now-REPEAT_SECONDS))}
            while paths:
                path = self.choose(paths)
                paths.remove(path)
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to((self.root/"memes").resolve()):
                        continue
                    with path.open("rb") as source:
                        content = source.read(MAX_BYTES+1)
                except OSError:
                    continue
                if len(content)>MAX_BYTES or not image_bytes(content):
                    continue
                digest = hashlib.sha256(content).hexdigest()
                if digest in used:
                    continue
                db.execute("INSERT INTO group_meme_history(group_id,day,category,digest,created) VALUES (?,?,?,?,?)",(group,self.day(now),category,digest,now))
                return MemeSelection(category,"base64://"+base64.b64encode(content).decode("ascii"),digest)
        return None

    def status(self, group, now=None):
        if not self.allowed(group):
            return None
        now = time.time() if now is None else now
        inventory = self.inventory()
        with closing(self.connect()) as db:
            attempts = db.execute("SELECT COUNT(*) FROM group_meme_history WHERE group_id=? AND day=?",(group,self.day(now))).fetchone()[0]
        return dict(categories=len(inventory),images=sum(len(v[1]) for v in inventory.values()),attempts=attempts,limit=DAILY_IMAGE_LIMIT)
