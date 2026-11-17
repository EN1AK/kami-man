"""Short-lived public group dialogue; never fed into expression/style learning."""
from contextlib import closing
import hashlib
import time
from uuid import uuid4

from services.group_chat_store import ALLOWED_GROUPS

TTL = 1800
WINDOW = 30


class GroupConversation:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _prune(db,group,now):
        db.execute("DELETE FROM group_conversation WHERE created<?",(now-TTL,))
        db.execute("DELETE FROM group_conversation WHERE group_id=? AND seq NOT IN (SELECT seq FROM group_conversation WHERE group_id=? ORDER BY seq DESC LIMIT 200)",(group,group))

    def seed_recent(self,group,now=None):
        if group not in ALLOWED_GROUPS:return
        now=time.time() if now is None else now
        with closing(self.store.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            self._prune(db,group,now)
            if not db.execute("SELECT collect FROM group_settings WHERE group_id=?",(group,)).fetchone()[0]:return
            if db.execute("SELECT 1 FROM group_conversation WHERE group_id=? LIMIT 1",(group,)).fetchone():return
            rows=db.execute("SELECT message_id,speaker,text,created FROM group_samples WHERE group_id=? AND created>=? ORDER BY seq DESC LIMIT 30",
                (group,now-TTL)).fetchall()[::-1]
            db.executemany("INSERT OR IGNORE INTO group_conversation(group_id,message_id,speaker,role,text,created) VALUES (?,?,?,'user',?,?)",
                [(group,message_id,speaker,text[:500],created) for message_id,speaker,text,created in rows])

    def record(self, group, message_id, user, text, *, bot=False, reply_to="", now=None):
        if group not in ALLOWED_GROUPS or not isinstance(text,str) or not text.strip():
            return False
        now = time.time() if now is None else now
        message_id = str(message_id) if message_id is not None else "bot:"+uuid4().hex
        speaker = "bot" if bot else hashlib.sha256(f"{group}:{user}".encode("utf-8")).hexdigest()[:16]
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._prune(db,group,now)
            if not db.execute("SELECT collect FROM group_settings WHERE group_id=?",(group,)).fetchone()[0]:
                return False
            parent = db.execute("SELECT message_id FROM group_conversation WHERE group_id=? AND message_id=? AND created>=?",
                (group,str(reply_to),now-TTL)).fetchone() if reply_to else None
            inserted = db.execute("INSERT OR IGNORE INTO group_conversation(group_id,message_id,speaker,role,text,reply_to,created) VALUES (?,?,?,?,?,?,?)",
                (group,message_id,speaker,"assistant" if bot else "user",text.strip()[:500],parent[0] if parent else "",now)).rowcount
            self._prune(db,group,now)
            return bool(inserted)

    def claim_random(self, group, message_id):
        if group not in ALLOWED_GROUPS:return False
        with closing(self.store.connect()) as db, db:
            return bool(db.execute("UPDATE group_conversation SET random_checked=1 WHERE group_id=? AND message_id=? AND role='user' AND random_checked=0",
                (group,str(message_id))).rowcount)

    def remember_legacy_quote(self,group,message_id,text,now=None):
        if group not in ALLOWED_GROUPS or not message_id:return
        now=time.time() if now is None else now
        with closing(self.store.connect()) as db:
            row=db.execute("SELECT created FROM group_own_replies WHERE group_id=? AND text=? AND created>=? ORDER BY created DESC LIMIT 1",
                (group,text,now-TTL)).fetchone()
        if row:self.record(group,message_id,None,text,bot=True,now=row[0])

    def checkpoint(self, group):
        with closing(self.store.connect()) as db:
            return db.execute("SELECT COALESCE(MAX(seq),0) FROM group_conversation WHERE group_id=?",(group,)).fetchone()[0]

    def context(self, group, target=None, now=None):
        messages, _ = self.context_with_target(group, target, now)
        return messages

    def context_with_target(self, group, target=None, now=None):
        """Return the context and the local ID of the requested message."""
        if group not in ALLOWED_GROUPS:return [], ""
        now = time.time() if now is None else now
        with closing(self.store.connect()) as db, db:
            self._prune(db,group,now)
            if not db.execute("SELECT collect FROM group_settings WHERE group_id=?",(group,)).fetchone()[0]:return [], ""
            rows = db.execute("SELECT seq,message_id,speaker,role,text,reply_to FROM group_conversation WHERE group_id=? AND created>=? ORDER BY created DESC,seq DESC LIMIT 200",
                (group,now-TTL)).fetchall()[::-1]
        by_id = {row[1]:row for row in rows}
        pinned = set()
        current = by_id.get(str(target)) if target is not None else (rows[-1] if rows else None)
        # Preserve the current quote chain even in a fast-moving group.
        for _ in range(5):
            if not current or current[0] in pinned:break
            pinned.add(current[0]);current=by_id.get(current[5])
        selected = set(pinned)
        for row in reversed(rows):
            if len(selected)>=WINDOW:break
            selected.add(row[0])
        rows = [row for row in rows if row[0] in selected]
        ids = {row[1]:f"m{index}" for index,row in enumerate(rows,1)}
        speakers = {}
        messages = []
        for _,message_id,speaker,role,text,reply_to in rows:
            if role=="assistant":name="机器人"
            else:
                if speaker not in speakers:speakers[speaker]=f"成员{len(speakers)+1}"
                name=speakers[speaker]
            item=dict(id=ids[message_id],speaker=name,role=role,text=text)
            if reply_to in ids:item["reply_to"]=ids[reply_to]
            messages.append(item)
        return messages, ids.get(str(target), "") if target is not None else ""
