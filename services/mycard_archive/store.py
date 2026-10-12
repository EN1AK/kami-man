"""Transactional index, replay evidence, match exports and consecutive deck versions."""
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
import zipfile
from .replay import ObservedDeck,parse_replay,consolidate,MAX_PAYLOAD


def atomic_bytes(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        temp.write_bytes(data);temp.replace(path)
    finally:temp.unlink(missing_ok=True)

class ArchiveStore:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/"archive.sqlite3";self.rules_path=self.root/"deck-rules.json"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY, room_id TEXT UNIQUE NOT NULL,
                players TEXT NOT NULL, ranks TEXT NOT NULL, room TEXT NOT NULL,
                first_seen REAL NOT NULL, finished REAL,
                status TEXT NOT NULL DEFAULT 'active', normal_end INTEGER NOT NULL DEFAULT 0,
                issues TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS replays (
                match_id TEXT NOT NULL REFERENCES matches(id), digest TEXT NOT NULL,
                ordinal INTEGER NOT NULL, received REAL NOT NULL, metadata TEXT NOT NULL,
                PRIMARY KEY(match_id,digest));
            CREATE TABLE IF NOT EXISTS observations (
                match_id TEXT NOT NULL REFERENCES matches(id), player TEXT NOT NULL,
                observed REAL NOT NULL, deck TEXT NOT NULL,
                PRIMARY KEY(match_id,player));
            CREATE INDEX IF NOT EXISTS observations_player ON observations(player,observed);
            """)
        if not self.rules_path.exists():atomic_bytes(self.rules_path,b'{"version":1,"rules":[]}\n')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def check_id(match_id):
        if not isinstance(match_id,str) or re.fullmatch(r"[0-9a-f]{24}",match_id) is None:raise ValueError("归档ID格式不正确")
        return match_id

    def directory(self,match_id):return self.root/"matches"/self.check_id(match_id)

    def begin(self,room,players,ranks,first_seen=None):
        key=hashlib.sha256(room["id"].encode("utf-8")).hexdigest()[:24]
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO matches(id,room_id,players,ranks,room,first_seen) VALUES(?,?,?,?,?,?)",
                       (key,room["id"],json.dumps(players,ensure_ascii=False),json.dumps(ranks,ensure_ascii=False),json.dumps(room,ensure_ascii=False),first_seen or time.time()))
            active=db.execute("SELECT status FROM matches WHERE id=?",(key,)).fetchone()[0]=="active"
        return key,active

    def active(self):
        with self.connect() as db:return [dict(row) for row in db.execute("SELECT * FROM matches WHERE status='active'")]

    def issue(self,match_id,text):
        with self.connect() as db:
            row=db.execute("SELECT issues FROM matches WHERE id=?",(self.check_id(match_id),)).fetchone()
            if row is None:raise ValueError("没有该归档")
            issues=json.loads(row[0])
            if text not in issues:issues.append(text[:250])
            db.execute("UPDATE matches SET issues=? WHERE id=?",(json.dumps(issues[-20:],ensure_ascii=False),match_id))

    def replays(self,match_id):
        with self.connect() as db:
            rows=db.execute("SELECT * FROM replays WHERE match_id=? ORDER BY ordinal",(self.check_id(match_id),)).fetchall()
        return [dict(json.loads(row["metadata"]),digest=row["digest"],ordinal=row["ordinal"],filename=row["digest"]+".yrp") for row in rows]

    def save_replay(self,match_id,raw):
        if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_PAYLOAD+80:raise ValueError("录像大小超限")
        directory=self.directory(match_id);digest=hashlib.sha256(raw).hexdigest()
        try:
            parsed=parse_replay(raw)
            if {deck.player for deck in parsed.decks}!=set(self.match(match_id)["players"]):
                raise ValueError("录像玩家与公开房间不一致，未绑定卡组")
            metadata={"start_time":parsed.start_time,"decks":[asdict(deck) for deck in parsed.decks],"error":""}
        except ValueError as exc:
            metadata={"start_time":0,"decks":[],"error":str(exc)}
        # Write the original even when its metadata cannot be interpreted.
        atomic_bytes(directory/(digest+".yrp"),raw)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ordinal=db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM replays WHERE match_id=?",(match_id,)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO replays(match_id,digest,ordinal,received,metadata) VALUES(?,?,?,?,?)",
                       (match_id,digest,ordinal,time.time(),json.dumps(metadata,ensure_ascii=False)))
        if metadata["error"]:self.issue(match_id,"录像卡组提取失败："+metadata["error"])
        return digest

    def recover(self,match_id):
        directory=self.directory(match_id)
        known={r["digest"] for r in self.replays(match_id)}
        if not directory.exists():return
        for path in sorted(directory.glob("*.yrp"),key=lambda p:p.stat().st_mtime):
            if re.fullmatch(r"[0-9a-f]{64}\.yrp",path.name) and path.stem not in known:
                if path.stat().st_size<=MAX_PAYLOAD+80:self.save_replay(match_id,path.read_bytes())

    def finish(self,match_id,normal_end=False,status=None):
        rounds=self.replays(match_id);decks=consolidate(rounds)
        for row in rounds:
            for i,data in enumerate(row["decks"],1):
                deck=ObservedDeck(data["player"],tuple(data["main"]),tuple(data["extra"]))
                atomic_bytes(self.directory(match_id)/f"round-{row['ordinal']:02}-player-{i}.ydk",deck.ydk().encode("utf-8"))
        for i,deck in enumerate(decks,1):atomic_bytes(self.directory(match_id)/f"merged-player-{i}.ydk",deck.ydk().encode("utf-8"))
        final=status or ("complete" if normal_end and rounds and all(not row["error"] for row in rounds) else "partial" if rounds else "unavailable")
        with self.connect() as db:
            match=db.execute("SELECT * FROM matches WHERE id=?",(match_id,)).fetchone()
            if match is None:raise ValueError("没有该归档")
            if match["status"]!="active":return
            observed=min([row["start_time"] for row in rounds if row["start_time"]>0] or [match["first_seen"]])
            for deck in decks:
                db.execute("INSERT OR IGNORE INTO observations(match_id,player,observed,deck) VALUES(?,?,?,?)",
                           (match_id,deck.player,observed,json.dumps(asdict(deck),ensure_ascii=False)))
            db.execute("UPDATE matches SET status=?,normal_end=?,finished=? WHERE id=?",(final,int(normal_end),time.time(),match_id))
        self.write_manifest(match_id)

    def match(self,match_id):
        with self.connect() as db:row=db.execute("SELECT * FROM matches WHERE id=?",(self.check_id(match_id),)).fetchone()
        if row is None:raise ValueError("没有该归档")
        data=dict(row)
        for key in ["players","ranks","room","issues"]:data[key]=json.loads(data[key])
        return data

    def write_manifest(self,match_id):
        data=self.match(match_id);data["replays"]=self.replays(match_id)
        data["side_complete"]=False;data["first_seen_is_monitor_time"]=True
        atomic_bytes(self.directory(match_id)/"manifest.json",json.dumps(data,ensure_ascii=False,indent=2).encode("utf-8"))

    def bundle(self,match_id):
        data=self.match(match_id)
        if data["status"]=="active":raise ValueError("对局仍在采集中，结束后再导出")
        if not self.replays(match_id):raise ValueError("该对局没有收到录像")
        self.write_manifest(match_id)
        directory=self.directory(match_id);output=directory/"archive.zip";temp=directory/(uuid.uuid4().hex+".zip.tmp")
        try:
            with zipfile.ZipFile(temp,"w",zipfile.ZIP_DEFLATED) as zip_file:
                for path in sorted(directory.iterdir()):
                    if path.name=="manifest.json" or path.suffix in {".ydk",".yrp"}:zip_file.write(path,path.name)
            temp.replace(output)
        finally:temp.unlink(missing_ok=True)
        return output

    def recent(self,player=None,limit=10,offset=0):
        with self.connect() as db:
            if player:
                rows=db.execute("SELECT DISTINCT m.* FROM matches m JOIN observations o ON o.match_id=m.id WHERE o.player=? ORDER BY m.first_seen DESC LIMIT ? OFFSET ?",(player,limit,offset)).fetchall()
            else:rows=db.execute("SELECT * FROM matches WHERE EXISTS(SELECT 1 FROM replays r WHERE r.match_id=matches.id) ORDER BY first_seen DESC LIMIT ? OFFSET ?",(limit,offset)).fetchall()
        return [dict(row,players=json.loads(row["players"])) for row in rows]

    def versions(self,player):
        with self.connect() as db:
            rows=db.execute("SELECT o.*,m.finished FROM observations o JOIN matches m ON m.id=o.match_id WHERE o.player=? ORDER BY o.observed,m.id",(player,)).fetchall()
        versions=[]
        for row in rows:
            deck=json.loads(row["deck"])
            for key in ["main","extra","side"]:deck[key]=sorted(deck[key])
            current=dict(deck,first_seen=row["observed"],last_seen=row["finished"],observations=1,match_id=row["match_id"])
            previous=versions[-1] if versions else None
            side=Counter(previous["side"])|Counter(deck["side"]) if previous else Counter()
            if previous and previous["main"]==deck["main"] and previous["extra"]==deck["extra"] and sum(side.values())<=15:
                previous.update(side=sorted(side.elements()),last_seen=max(previous["last_seen"],row["finished"]),observations=previous["observations"]+1,match_id=row["match_id"])
            else:versions.append(current)
        return versions

    def latest(self,player):
        versions=self.versions(player)
        return versions[-1] if versions else None

    def stats(self):
        with self.connect() as db:
            result={row[0]:row[1] for row in db.execute("SELECT status,COUNT(*) FROM matches GROUP BY status")}
            result["replays"]=db.execute("SELECT COUNT(*) FROM replays").fetchone()[0]
            result["players"]=db.execute("SELECT COUNT(DISTINCT player) FROM observations").fetchone()[0]
        return result
