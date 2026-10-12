"""Persistent, atomic per-QQ daily quota for the unified Agent."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

DAILY_LIMIT = 30
CHINA_TZ = ZoneInfo("Asia/Shanghai")

@dataclass(frozen=True)
class UsageTicket:
    day: str
    user_id: str

class UsageStore:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def day(now=None):
        return (now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ).date().isoformat()

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("""CREATE TABLE IF NOT EXISTS daily_usage (
            day TEXT NOT NULL, user_id TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(day, user_id))""")
        db.commit()
        return db

    def reserve(self, user_id, *, exempt=False, now=None):
        day, user_id = self.day(now), str(user_id)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO daily_usage(day,user_id) VALUES (?,?)", (day,user_id))
            changed = db.execute("UPDATE daily_usage SET used=used+1 WHERE day=? AND user_id=? AND (used<? OR ?)",
                                 (day,user_id,DAILY_LIMIT,int(exempt))).rowcount
            return UsageTicket(day,user_id) if changed else None

    def refund(self, ticket):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE daily_usage SET used=MAX(0,used-1), failures=failures+1 WHERE day=? AND user_id=?",
                       (ticket.day,ticket.user_id))

    def personal(self, user_id, *, now=None):
        day = self.day(now)
        with closing(self.connect()) as db:
            row = db.execute("SELECT used,failures FROM daily_usage WHERE day=? AND user_id=?", (day,str(user_id))).fetchone()
        return day, *(row or (0,0))

    def summary(self, *, now=None):
        day = self.day(now)
        with closing(self.connect()) as db:
            totals = db.execute("SELECT COUNT(*),COALESCE(SUM(used),0),COALESCE(SUM(failures),0) FROM daily_usage WHERE day=? AND used+failures>0", (day,)).fetchone()
            rows = db.execute("SELECT user_id,used,failures FROM daily_usage WHERE day=? AND used+failures>0 ORDER BY used DESC,user_id LIMIT 20", (day,)).fetchall()
        return day, totals, rows

usage_store = UsageStore(Path(__file__).resolve().parents[1] / "data" / "agent_usage.db")

def is_exempt(user_id):
    from nonebot import get_driver
    return str(user_id) in {str(user) for user in get_driver().config.superusers}
