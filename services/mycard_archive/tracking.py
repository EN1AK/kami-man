"""Persistent exact-name opt-in capture targets."""
import time

class TrackingStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS capture_targets(player TEXT PRIMARY KEY, created REAL NOT NULL)")

    @staticmethod
    def validate(player):
        if not isinstance(player,str) or not 1<=len(player.strip())<=100 or any(ord(c)<32 for c in player):
            raise ValueError("请提供 1～100 字符的完整 MyCard 用户名。")
        return player.strip()

    def players(self):
        with self.store.connect() as db:
            return [r[0] for r in db.execute("SELECT player FROM capture_targets ORDER BY created,player")]

    def set(self, player, enabled=True):
        player=self.validate(player)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if enabled:
                present=db.execute("SELECT 1 FROM capture_targets WHERE player=?",(player,)).fetchone()
                if not present and db.execute("SELECT COUNT(*) FROM capture_targets").fetchone()[0]>=100:
                    raise ValueError("指定采集名单最多 100 人，请先停止不需要的玩家。")
                db.execute("INSERT OR IGNORE INTO capture_targets VALUES (?,?)",(player,time.time()))
            else:
                db.execute("DELETE FROM capture_targets WHERE player=?",(player,))
        return player
