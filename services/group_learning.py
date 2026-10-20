"""Evidence-backed local expression memory without embedding dependencies."""
import asyncio
from collections import defaultdict
from contextlib import closing
from difflib import SequenceMatcher
import hashlib
import re
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

import httpx
from nonebot import logger

from services.group_chat_store import ALLOWED_GROUPS, RETENTION_SECONDS
from services.group_style import GroupStyleStore
from services.ygo_rag_agent_api import YgoRagAgentSettings

UNSAFE = re.compile(r"\[CQ:|[@＠]|https?://|www\.|\d{7,}|密码|验证码|api[_ -]?key|token|身份证|手机号|住址",re.I)


def terms(text):
    words = set(re.findall(r"[a-z0-9_]{2,}", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+",text):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return words


def normalize(text):
    return re.sub(r"[\W_]", "",text).lower()


class GroupLearningStore(GroupStyleStore):
    def connect(self):
        db = super().connect()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS group_expressions (
                id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
                situation TEXT NOT NULL, expression TEXT NOT NULL,
                updated REAL NOT NULL, UNIQUE(group_id,situation,expression));
            CREATE TABLE IF NOT EXISTS group_expression_evidence (
                expression_id INTEGER NOT NULL, source_seq INTEGER NOT NULL,
                PRIMARY KEY(expression_id,source_seq));
            CREATE TABLE IF NOT EXISTS group_learning_runs (
                group_id INTEGER PRIMARY KEY, source_seq INTEGER NOT NULL DEFAULT 0,
                learned INTEGER NOT NULL DEFAULT 0, day TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0,
                last_attempt REAL NOT NULL DEFAULT 0, token TEXT NOT NULL DEFAULT '',
                lease_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS group_reply_epoch (
                group_id INTEGER PRIMARY KEY, epoch TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS group_own_replies (
                id INTEGER PRIMARY KEY,group_id INTEGER NOT NULL,text TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS group_sample_clock (
                id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL);
        """)
        for group in ALLOWED_GROUPS:
            db.execute("INSERT OR IGNORE INTO group_learning_runs(group_id) VALUES (?)",(group,))
            db.execute("INSERT OR IGNORE INTO group_reply_epoch VALUES (?,?)",(group,uuid4().hex))
        db.execute("""INSERT OR IGNORE INTO group_sample_clock VALUES (1,MAX(
            (SELECT COALESCE(MAX(seq),0) FROM group_samples),
            (SELECT COALESCE(MAX(source_seq),0) FROM group_learning_runs),
            (SELECT COALESCE(MAX(source_seq),0) FROM group_style_profiles)))""")
        db.commit()
        return db

    def record(self, group, message_id, user_id, text, now=None):
        if group not in ALLOWED_GROUPS:
            return False
        now = time.time() if now is None else now
        speaker = hashlib.sha256(f"{group}:{user_id}".encode("utf-8")).hexdigest()[:16]
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT collect FROM group_settings WHERE group_id=?",(group,)).fetchone()[0]:
                return False
            # A durable clock prevents SQLite rowid reuse after clear/expiry.
            db.execute("UPDATE group_sample_clock SET seq=MAX(seq,(SELECT COALESCE(MAX(seq),0) FROM group_samples))+1 WHERE id=1")
            seq = db.execute("SELECT seq FROM group_sample_clock WHERE id=1").fetchone()[0]
            inserted = db.execute("INSERT OR IGNORE INTO group_samples(seq,group_id,message_id,speaker,text,created) VALUES (?,?,?,?,?,?)",(seq,group,str(message_id),speaker,text,now)).rowcount
            self.prune(db,group,now)
            return bool(inserted)

    def prune(self, db, group, now):
        super().prune(db,group,now)
        db.execute("DELETE FROM group_expressions WHERE group_id=? AND updated<?",(group,now-RETENTION_SECONDS))
        db.execute("""DELETE FROM group_expressions WHERE group_id=? AND id NOT IN
            (SELECT id FROM group_expressions WHERE group_id=? ORDER BY updated DESC,id DESC LIMIT 300)""",(group,group))
        db.execute("DELETE FROM group_expression_evidence WHERE expression_id NOT IN (SELECT id FROM group_expressions)")
        db.execute("DELETE FROM group_own_replies WHERE created<?",(now-86400,))
        db.execute("""DELETE FROM group_own_replies WHERE group_id=? AND id NOT IN
            (SELECT id FROM group_own_replies WHERE group_id=? ORDER BY id DESC LIMIT 20)""",(group,group))

    def configure(self, group, action, now=None):
        if group not in ALLOWED_GROUPS:
            raise ValueError("Group is not enabled")
        if action not in {"clear","collect_off","chat_off"}:
            return super().configure(group,action,now)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE group_reply_epoch SET epoch=? WHERE group_id=?",(uuid4().hex,group))
            if action == "chat_off":
                db.execute("UPDATE group_settings SET chat=0 WHERE group_id=?",(group,))
            else:
                db.execute("UPDATE group_settings SET collect=0,chat=0 WHERE group_id=?",(group,))
                db.execute("UPDATE group_style_runs SET token='',lease_until=0 WHERE group_id=?",(group,))
                db.execute("UPDATE group_learning_runs SET token='',lease_until=0 WHERE group_id=?",(group,))
            if action == "clear":
                db.execute("DELETE FROM group_samples WHERE group_id=?",(group,))
                db.execute("DELETE FROM group_style_profiles WHERE group_id=?",(group,))
                db.execute("DELETE FROM group_expressions WHERE group_id=?",(group,))
                db.execute("DELETE FROM group_expression_evidence WHERE expression_id NOT IN (SELECT id FROM group_expressions)")
                db.execute("DELETE FROM group_own_replies WHERE group_id=?",(group,))
                # Preserve attempts/success limits across clear and re-enable.
                db.execute("UPDATE group_learning_runs SET source_seq=0,learned=0 WHERE group_id=?",(group,))
        return self.status(group,now)

    def learning_status(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return None
        now = time.time() if now is None else now
        with closing(self.connect()) as db, db:
            self.prune(db,group,now)
            seq, learned, day, attempts, successes = db.execute("SELECT source_seq,learned,day,attempts,successes FROM group_learning_runs WHERE group_id=?",(group,)).fetchone()
            new = db.execute("SELECT COUNT(*) FROM group_samples WHERE group_id=? AND seq>?",(group,seq)).fetchone()[0]
            count = db.execute("SELECT COUNT(*) FROM group_expressions WHERE group_id=?",(group,)).fetchone()[0]
            return dict(count=count,new_count=new,threshold=50 if learned else 100,
                        attempts=attempts if day==self.day(now) else 0,
                        successes=successes if day==self.day(now) else 0)

    def reserve_learning(self, group, now=None):
        if group not in ALLOWED_GROUPS:
            return None
        now = time.time() if now is None else now
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.prune(db,group,now)
            if not db.execute("SELECT collect FROM group_settings WHERE group_id=?",(group,)).fetchone()[0]:
                return None
            source, learned, day, attempts, successes, last, token, lease = db.execute("SELECT source_seq,learned,day,attempts,successes,last_attempt,token,lease_until FROM group_learning_runs WHERE group_id=?",(group,)).fetchone()
            if day != self.day(now):
                attempts, successes = 0, 0
            if lease>now or now-last<3600 or attempts>=3 or successes>=2:
                return None
            rows = db.execute("SELECT seq,speaker,text FROM group_samples WHERE group_id=? AND seq>? ORDER BY seq",(group,source)).fetchall()
            buckets = defaultdict(list)
            for row in rows:
                if not UNSAFE.search(row[2]):
                    buckets[row[1]].append(row)
            if len(rows)<(50 if learned else 100) or len(buckets)<3:
                return None
            # Balance speakers and sample across time, bounded to eight total messages.
            speakers = sorted(buckets,key=lambda s:(-len(buckets[s]),s))[:8]
            selected = {}
            for i in range(8):
                bucket = buckets[speakers[i%len(speakers)]]
                row = bucket[min(len(bucket)-1,(i//len(speakers))*max(1,len(bucket)//3))]
                selected[row[0]] = row
            if len(selected)<3:
                return None
            samples, sources = [], {}
            for i,row in enumerate(sorted(selected.values()),1):
                sid = f"s{i}"
                samples.append(dict(source_id=sid,text=row[2]))
                sources[sid] = row[0]
            token = uuid4().hex
            db.execute("""UPDATE group_learning_runs SET day=?,attempts=?,successes=?,last_attempt=?,
                token=?,lease_until=? WHERE group_id=?""",(self.day(now),attempts+1,successes,now,token,now+120,group))
            return dict(group_id=group,token=token,source_seq=rows[-1][0],samples=samples,sources=sources)

    def finish_learning(self, job, items, now=None):
        group = job["group_id"]
        if group not in ALLOWED_GROUPS or not isinstance(items,list) or len(items)>5:
            return False
        now = time.time() if now is None else now
        texts = {s["source_id"]:s["text"] for s in job["samples"]}
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            enabled = db.execute("SELECT collect FROM group_settings WHERE group_id=?",(group,)).fetchone()[0]
            run = db.execute("SELECT token,lease_until,day FROM group_learning_runs WHERE group_id=?",(group,)).fetchone()
            if not enabled or run[0]!=job["token"] or run[1]<now:
                return False
            for item in items:
                if not isinstance(item,dict):
                    continue
                sid, situation, expression = item.get("source_id"),item.get("situation"),item.get("expression")
                if not isinstance(sid,str) or sid not in texts or not isinstance(situation,str) or not isinstance(expression,str):
                    continue
                situation, expression = situation.strip(),expression.strip()
                if not 2<=len(situation)<=60 or not 2<=len(expression)<=80 or expression not in texts[sid] or UNSAFE.search(situation+expression):
                    continue
                seq = job["sources"][sid]
                if not db.execute("SELECT 1 FROM group_samples WHERE seq=? AND group_id=? AND text=?",(seq,group,texts[sid])).fetchone():
                    continue
                db.execute("INSERT OR IGNORE INTO group_expressions(group_id,situation,expression,updated) VALUES (?,?,?,?)",(group,situation,expression,now))
                eid = db.execute("SELECT id FROM group_expressions WHERE group_id=? AND situation=? AND expression=?",(group,situation,expression)).fetchone()[0]
                if db.execute("INSERT OR IGNORE INTO group_expression_evidence VALUES (?,?)",(eid,seq)).rowcount:
                    db.execute("UPDATE group_expressions SET updated=? WHERE id=?",(now,eid))
            if run[2] != self.day(now):
                db.execute("UPDATE group_learning_runs SET day=?,attempts=0,successes=0 WHERE group_id=?",(self.day(now),group))
            db.execute("""UPDATE group_learning_runs SET source_seq=?,learned=1,successes=successes+1,
                token='',lease_until=0 WHERE group_id=?""",(job["source_seq"],group))
            self.prune(db,group,now)
            return True

    def retrieve(self, group, messages, now=None):
        if group not in ALLOWED_GROUPS:
            return []
        now = time.time() if now is None else now
        query = terms(" ".join(m["text"] for m in messages[-4:]))
        if not query:
            return []
        with closing(self.connect()) as db:
            rows = db.execute("""SELECT e.situation,e.expression,e.updated,COUNT(v.source_seq)
                FROM group_expressions e LEFT JOIN group_expression_evidence v ON v.expression_id=e.id
                WHERE e.group_id=? AND e.updated>=? GROUP BY e.id""",(group,now-RETENTION_SECONDS)).fetchall()
        ranked = []
        for situation,expression,updated,count in rows:
            overlap = query & terms(situation+" "+expression)
            if overlap:
                score = len(overlap) + min(count,5)*0.05 + max(0,1-(now-updated)/RETENTION_SECONDS)*0.1
                ranked.append((score,situation,expression))
        return [dict(situation=s,expression=e) for _,s,e in sorted(ranked,reverse=True)[:5]]

    def reply_checkpoint(self, group):
        with closing(self.connect()) as db:
            return db.execute("""SELECT epoch,(SELECT COALESCE(MAX(seq),0) FROM group_samples WHERE group_id=?)
                FROM group_reply_epoch WHERE group_id=?""",(group,group)).fetchone()

    def reply_allowed(self, group, checkpoint, reply, now=None):
        if self.reply_checkpoint(group)!=checkpoint:
            return False
        now = time.time() if now is None else now
        with closing(self.connect()) as db:
            rows = db.execute("SELECT text FROM group_own_replies WHERE group_id=? AND created>=?",(group,now-86400)).fetchall()
        current = normalize(reply)
        return bool(current) and all(SequenceMatcher(None,current,normalize(row[0])).ratio()<0.85 for row in rows)

    def record_reply(self, group, reply, now=None):
        if group not in ALLOWED_GROUPS:
            return
        now = time.time() if now is None else now
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO group_own_replies(group_id,text,created) VALUES (?,?,?)",(group,reply,now))
            self.prune(db,group,now)


def endpoint(name):
    parts = urlsplit(YgoRagAgentSettings.from_env().api_url)
    return urlunsplit((parts.scheme,parts.netloc,parts.path.rsplit("/",1)[0]+"/"+name,"",""))


async def request_learning(job):
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(endpoint("group-learning"),json=dict(group_id=job["group_id"],samples=job["samples"]))
        response.raise_for_status()
        items = response.json().get("expressions")
    if not isinstance(items,list) or len(items)>5:
        raise ValueError("Invalid expression response")
    return items


async def update_learning(store, group):
    try:
        job = await asyncio.to_thread(store.reserve_learning,group)
        if job is None:
            return False
        items = await request_learning(job)
        return await asyncio.to_thread(store.finish_learning,job,items)
    except Exception as exc:
        logger.warning("Group expression learning skipped ({})",type(exc).__name__)
        return False


async def budget_status():
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(endpoint("group-chat/status"))
        response.raise_for_status()
        return response.json()
