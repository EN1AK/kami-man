"""Persistent, sample-bounded group style summaries."""
import asyncio
from collections import defaultdict
from contextlib import closing
import statistics
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

import httpx
from nonebot import logger

from services.group_chat_store import ALLOWED_GROUPS, RETENTION_SECONDS, GroupChatStore
from services.ygo_rag_agent_api import YgoRagAgentSettings

INITIAL_MESSAGES = 200
UPDATE_MESSAGES = 100
MIN_SPEAKERS = 3


class GroupStyleStore(GroupChatStore):
    def connect(self):
        db = super().connect()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS group_style_profiles (
                group_id INTEGER PRIMARY KEY, summary TEXT NOT NULL,
                source_seq INTEGER NOT NULL, source_count INTEGER NOT NULL,
                updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS group_style_runs (
                group_id INTEGER PRIMARY KEY, day TEXT NOT NULL,
                attempts INTEGER NOT NULL, last_attempt REAL NOT NULL,
                token TEXT NOT NULL, lease_until REAL NOT NULL);
        """)
        db.commit()
        return db

    def prune(self, db, group, now):
        super().prune(db, group, now)
        db.execute("DELETE FROM group_style_profiles WHERE group_id=? AND updated<?", (group, now-RETENTION_SECONDS))

    def profile(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return None
        now = time.time() if now is None else now
        with closing(self.connect()) as db, db:
            self.prune(db, group, now)
            row = db.execute("SELECT summary,source_seq,source_count,updated FROM group_style_profiles WHERE group_id=?", (group,)).fetchone()
            summary, seq, count, updated = row or ("", 0, 0, 0)
            new_count = db.execute("SELECT COUNT(*) FROM group_samples WHERE group_id=? AND seq>?", (group,seq)).fetchone()[0]
            return dict(summary=summary, source_seq=seq, source_count=count, updated=updated, new_count=new_count)

    def configure(self, group, action, now=None):
        # Invalidate outstanding summary jobs before a clear/collection stop commits.
        if group not in ALLOWED_GROUPS:
            raise ValueError("Group is not enabled")
        if action in {"clear", "collect_off"}:
            with closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE group_settings SET collect=0,chat=0 WHERE group_id=?", (group,))
                db.execute("UPDATE group_style_runs SET token='',lease_until=0 WHERE group_id=?", (group,))
                if action == "clear":
                    db.execute("DELETE FROM group_samples WHERE group_id=?", (group,))
                    db.execute("DELETE FROM group_style_profiles WHERE group_id=?", (group,))
            return self.status(group, now)
        return super().configure(group, action, now)

    def reserve_summary(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return None
        now = time.time() if now is None else now
        day = self.day(now)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.prune(db, group, now)
            if not db.execute("SELECT collect FROM group_settings WHERE group_id=?", (group,)).fetchone()[0]:
                return None
            profile = db.execute("SELECT summary,source_seq,updated FROM group_style_profiles WHERE group_id=?", (group,)).fetchone()
            previous, source_seq, updated = profile or ("", 0, 0)
            if updated and self.day(updated) == day:
                return None
            rows = db.execute("SELECT seq,speaker,text FROM group_samples WHERE group_id=? AND seq>? ORDER BY seq", (group, source_seq)).fetchall()
            if len(rows) < (UPDATE_MESSAGES if previous else INITIAL_MESSAGES):
                return None
            buckets = defaultdict(list)
            for seq, speaker, text in rows:
                buckets[speaker].append(text)
            if len(buckets) < MIN_SPEAKERS:
                return None
            # Balance speakers, spread within their timelines, and send at most 8 examples.
            speakers = sorted(buckets, key=lambda speaker: (-len(buckets[speaker]), speaker))[:8]
            samples = []
            for index in range(8):
                bucket = buckets[speakers[index % len(speakers)]]
                text = bucket[min(len(bucket)-1, (index//len(speakers))*max(1,len(bucket)//3))]
                if text not in samples:
                    samples.append(text)
            if len(samples) < 3:
                return None
            run = db.execute("SELECT day,attempts,last_attempt,lease_until FROM group_style_runs WHERE group_id=?", (group,)).fetchone()
            attempts = run[1] if run and run[0] == day else 0
            if run and (run[3] > now or now-run[2] < 3600):
                return None
            if attempts >= 3:
                return None
            token = uuid4().hex
            db.execute("INSERT OR REPLACE INTO group_style_runs VALUES (?,?,?,?,?,?)", (group,day,attempts+1,now,token,now+120))
            lengths = [len(row[2]) for row in rows]
            stats = {"message_count":len(rows), "participant_count":len(buckets),
                     "mean_length":round(statistics.mean(lengths),1),
                     "short_message_ratio":round(sum(length<=20 for length in lengths)/len(lengths),2)}
            return dict(group_id=group, token=token, source_seq=rows[-1][0], source_count=len(rows),
                        previous_summary=previous, style_samples=samples, statistics=stats)

    def finish_summary(self, job, summary, now=None):
        group = job["group_id"]
        if group not in ALLOWED_GROUPS or not isinstance(summary,str) or not 1 <= len(summary) <= 600:
            return False
        now = time.time() if now is None else now
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            enabled = db.execute("SELECT collect FROM group_settings WHERE group_id=?", (group,)).fetchone()[0]
            run = db.execute("SELECT token,lease_until FROM group_style_runs WHERE group_id=?", (group,)).fetchone()
            if not enabled or not run or run[0] != job["token"] or run[1] < now:
                return False
            db.execute("INSERT OR REPLACE INTO group_style_profiles VALUES (?,?,?,?,?)", (group,summary,job["source_seq"],job["source_count"],now))
            db.execute("UPDATE group_style_runs SET token='',lease_until=0 WHERE group_id=?", (group,))
            return True


async def request_summary(job):
    settings = YgoRagAgentSettings.from_env()
    parts = urlsplit(settings.api_url)
    endpoint = urlunsplit((parts.scheme,parts.netloc,parts.path.rsplit("/",1)[0]+"/group-style", "", ""))
    payload = {key:job[key] for key in ("group_id","previous_summary","style_samples","statistics")}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(endpoint,json=payload)
        response.raise_for_status()
        summary = response.json().get("summary")
    if not isinstance(summary,str) or not 1 <= len(summary.strip()) <= 600:
        raise ValueError("Invalid group style summary")
    return summary.strip()


async def update_style(store, group):
    try:
        job = await asyncio.to_thread(store.reserve_summary,group)
        if job is None:
            return False
        summary = await request_summary(job)
        return await asyncio.to_thread(store.finish_summary,job,summary)
    except Exception as exc:
        logger.warning("Group style update skipped ({})",type(exc).__name__)
        return False
