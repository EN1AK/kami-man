"""Bounded group-only chat samples and persistent proactive-chat limits."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3
import time

ALLOWED_GROUPS = frozenset({819151070})
PROBABILITY = 0.03
COOLDOWN_SECONDS = 300
DAILY_LIMIT = 20
RETENTION_SECONDS = 30 * 86400
MAX_MESSAGES = 10000
CHINA_TZ = timezone(timedelta(hours=8))


class GroupChatStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS group_settings (
                group_id INTEGER PRIMARY KEY, collect INTEGER NOT NULL DEFAULT 1,
                chat INTEGER NOT NULL DEFAULT 1, last_attempt REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS group_samples (
                seq INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
                message_id TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL,
                created REAL NOT NULL, UNIQUE(group_id,message_id));
            CREATE INDEX IF NOT EXISTS group_samples_time ON group_samples(group_id,created);
            CREATE TABLE IF NOT EXISTS group_chat_usage (
                group_id INTEGER NOT NULL, day TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(group_id,day));
        """)
        for group in ALLOWED_GROUPS:
            db.execute("INSERT OR IGNORE INTO group_settings(group_id) VALUES (?)", (group,))
        db.commit()
        return db

    @staticmethod
    def day(now):
        return datetime.fromtimestamp(now, CHINA_TZ).date().isoformat()

    def prune(self, db, group, now):
        db.execute("DELETE FROM group_samples WHERE group_id=? AND created<?", (group, now-RETENTION_SECONDS))
        db.execute("""DELETE FROM group_samples WHERE group_id=? AND seq NOT IN
            (SELECT seq FROM group_samples WHERE group_id=? ORDER BY seq DESC LIMIT ?)""", (group, group, MAX_MESSAGES))
        db.execute("DELETE FROM group_chat_usage WHERE day<?", (self.day(now-RETENTION_SECONDS),))

    def status(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return None
        now = time.time() if now is None else now
        with closing(self.connect()) as db, db:
            self.prune(db, group, now)
            collect, chat, last_attempt = db.execute("SELECT collect,chat,last_attempt FROM group_settings WHERE group_id=?", (group,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM group_samples WHERE group_id=?", (group,)).fetchone()[0]
            usage = db.execute("SELECT attempts,sent FROM group_chat_usage WHERE group_id=? AND day=?", (group, self.day(now))).fetchone() or (0, 0)
            return dict(collect=bool(collect), chat=bool(chat), count=count, attempts=usage[0], sent=usage[1], last_attempt=last_attempt)

    def configure(self, group, action, now=None):
        if group not in ALLOWED_GROUPS:
            raise ValueError("Group is not enabled")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if action == "collect_on":
                db.execute("UPDATE group_settings SET collect=1 WHERE group_id=?", (group,))
            elif action == "collect_off":
                db.execute("UPDATE group_settings SET collect=0,chat=0 WHERE group_id=?", (group,))
            elif action == "chat_on":
                db.execute("UPDATE group_settings SET chat=collect WHERE group_id=?", (group,))
            elif action == "chat_off":
                db.execute("UPDATE group_settings SET chat=0 WHERE group_id=?", (group,))
            elif action == "clear":
                db.execute("DELETE FROM group_samples WHERE group_id=?", (group,))
                db.execute("UPDATE group_settings SET collect=0,chat=0 WHERE group_id=?", (group,))
            else:
                raise ValueError("Unknown group-chat action")
        return self.status(group, now)

    def record(self, group, message_id, user_id, text, now=None):
        if group not in ALLOWED_GROUPS:
            return False
        now = time.time() if now is None else now
        speaker = hashlib.sha256(f"{group}:{user_id}".encode("utf-8")).hexdigest()[:16]
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            enabled = db.execute("SELECT collect FROM group_settings WHERE group_id=?", (group,)).fetchone()[0]
            if not enabled:
                return False
            inserted = db.execute("INSERT OR IGNORE INTO group_samples(group_id,message_id,speaker,text,created) VALUES (?,?,?,?,?)", (group,str(message_id),speaker,text,now)).rowcount
            self.prune(db, group, now)
            return bool(inserted)

    def reserve(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return None
        now = time.time() if now is None else now
        day = self.day(now)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            collect, chat, last = db.execute("SELECT collect,chat,last_attempt FROM group_settings WHERE group_id=?", (group,)).fetchone()
            if not collect or not chat or now-last < COOLDOWN_SECONDS:
                return None
            db.execute("INSERT OR IGNORE INTO group_chat_usage(group_id,day) VALUES (?,?)", (group,day))
            changed = db.execute("UPDATE group_chat_usage SET attempts=attempts+1 WHERE group_id=? AND day=? AND attempts<?", (group,day,DAILY_LIMIT)).rowcount
            if not changed:
                return None
            db.execute("UPDATE group_settings SET last_attempt=? WHERE group_id=?", (now,group))
            return day

    def sent(self, group, day):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE group_chat_usage SET sent=sent+1 WHERE group_id=? AND day=?", (group,day))

    def context(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return [], []
        now = time.time() if now is None else now
        with closing(self.connect()) as db:
            recent = db.execute("SELECT speaker,text FROM group_samples WHERE group_id=? AND created>=? ORDER BY seq DESC LIMIT 15", (group,now-600)).fetchall()[::-1]
            # Spread examples across older samples rather than repeating the current topic.
            older = db.execute("SELECT text FROM group_samples WHERE group_id=? AND created>=? AND created<? ORDER BY seq DESC LIMIT 200", (group,now-RETENTION_SECONDS,now-600)).fetchall()
        names = {}
        messages = []
        for speaker, text in recent:
            if speaker not in names:
                names[speaker] = f"成员{len(names)+1}"
            messages.append({"speaker": names[speaker], "text": text})
        step = max(1, len(older)//8)
        samples = [row[0] for row in older[::step]][:8]
        return messages, samples
