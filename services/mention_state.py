"""Route provenance hashes and per-session serialization; no raw quote copies."""
import asyncio
from contextlib import asynccontextmanager,closing
import hashlib
from pathlib import Path
import sqlite3
import time


class MentionState:
    def __init__(self,path):
        self.path = Path(path)
        self._locks = {}

    @asynccontextmanager
    async def locked(self,key):
        lock,count = self._locks.get(key,(asyncio.Lock(),0))
        self._locks[key] = (lock,count+1)
        try:
            async with lock:
                yield
        finally:
            _,count = self._locks[key]
            if count==1:del self._locks[key]
            else:self._locks[key]=(lock,count-1)

    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db = sqlite3.connect(self.path,timeout=5)
        db.execute("""CREATE TABLE IF NOT EXISTS mention_outputs (
            id INTEGER PRIMARY KEY,session TEXT NOT NULL,route TEXT NOT NULL,
            digest TEXT NOT NULL,created REAL NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS mention_outputs_session ON mention_outputs(session,id)")
        db.commit()
        return db

    @staticmethod
    def digest(text):
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def record(self,key,route,text):
        if route not in {"casual","professional"}:
            raise ValueError("Invalid route")
        with closing(self.connect()) as db,db:
            db.execute("DELETE FROM mention_outputs WHERE created<?",(time.time()-7*86400,))
            db.execute("INSERT INTO mention_outputs(session,route,digest,created) VALUES (?,?,?,?)",(key,route,self.digest(text),time.time()))
            db.execute("DELETE FROM mention_outputs WHERE session=? AND id NOT IN (SELECT id FROM mention_outputs WHERE session=? ORDER BY id DESC LIMIT 60)",(key,key))
            db.execute("DELETE FROM mention_outputs WHERE id NOT IN (SELECT id FROM mention_outputs ORDER BY id DESC LIMIT 10000)")

    def metadata(self,key,quote=""):
        with closing(self.connect()) as db:
            previous = db.execute("SELECT route FROM mention_outputs WHERE session=? AND created>? ORDER BY id DESC LIMIT 1",(key,time.time()-1800)).fetchone()
            rows = db.execute("SELECT DISTINCT route FROM mention_outputs WHERE session=? AND digest=? AND created>?",(key,self.digest(quote),time.time()-7*86400)).fetchall() if quote else []
        kinds = {r[0] for r in rows}
        # If identical text was ever emitted by both paths, do not trust it as professional.
        quoted = next(iter(kinds)) if len(kinds)==1 else ""
        return (previous[0] if previous else "",quoted)

    def clear(self,key):
        with closing(self.connect()) as db,db:
            db.execute("DELETE FROM mention_outputs WHERE session=?",(key,))
