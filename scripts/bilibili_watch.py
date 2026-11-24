"""Scan one Bilibili UP's uploads once and print only matching video links."""

import argparse
from contextlib import closing
import sqlite3
import subprocess
import sys
import time

import httpx

from bilibili_link_preview import BVID, bilibili_data, bilibili_headers, classify_video


PAGE_SIZE = 30
DEMO_RULE = "视频实际讲解《游戏王 Master Duel》的入门操作、卡组构筑、卡片用法或对局打法。"
SCAN_ERRORS = (httpx.HTTPError, subprocess.TimeoutExpired, KeyError, TypeError, ValueError, OSError)


def fetch_uploads(client, uid, page):
    space = f"https://space.bilibili.com/{uid}/"
    headers = bilibili_headers(space)
    data = bilibili_data(client, "/x/space/arc/search", {
        "mid": uid, "pn": page, "ps": PAGE_SIZE, "order": "pubdate",
    }, headers)
    rows = data["list"]["vlist"]
    if any(int(row["mid"]) != uid for row in rows):
        raise ValueError("投稿列表含有其他 UP 主")
    uploads = [(row["bvid"], int(row["created"])) for row in rows]
    if any(not BVID.fullmatch(bvid) or published <= 0 for bvid, published in uploads):
        raise ValueError("B 站返回了无效投稿记录")
    return uploads


def scan(db, client, uid):
    with db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT watermark FROM channels WHERE uid = ?", (uid,)).fetchone()
        uploads = fetch_uploads(client, uid, 1)
        if current is None:
            watermark = max((published for _, published in uploads), default=int(time.time()))
            db.execute("INSERT INTO channels VALUES (?, ?)", (uid, watermark))
            db.executemany(
                "INSERT OR IGNORE INTO uploads VALUES (?, ?, ?, 'baseline')",
                ((uid, bvid, published) for bvid, published in uploads),
            )
            print(f"UID {uid} 已建立基线（{len(uploads)} 条）", file=sys.stderr)
            return

        watermark = current[0]
        page = 1
        batch = uploads
        while len(batch) >= PAGE_SIZE and min(date for _, date in batch) >= watermark:
            page += 1
            if page > 10:
                raise ValueError("新投稿超过单次扫描范围，扫描状态未推进")
            batch = fetch_uploads(client, uid, page)
            uploads.extend(batch)
        db.executemany(
            "INSERT OR IGNORE INTO uploads VALUES (?, ?, ?, 'pending')",
            ((uid, bvid, published) for bvid, published in uploads if published >= watermark),
        )
        latest = max((published for _, published in uploads), default=watermark)
        db.execute("UPDATE channels SET watermark = MAX(watermark, ?) WHERE uid = ?", (latest, uid))


def process_pending(db, client, uid, rule, asr_seconds, max_checks):
    pending = db.execute(
        "SELECT bvid FROM uploads WHERE uid = ? AND status = 'pending' ORDER BY published, bvid LIMIT ?",
        (uid, max_checks),
    ).fetchall()
    failed = False
    for (bvid,) in pending:
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                status = db.execute("SELECT status FROM uploads WHERE uid = ? AND bvid = ?", (uid, bvid)).fetchone()
                if status != ("pending",):
                    continue
                result = classify_video(client, bvid, rule, asr_seconds=asr_seconds)
                db.execute("UPDATE uploads SET status = ? WHERE uid = ? AND bvid = ?",
                           (result["decision"], uid, bvid))
                if result["message_preview"]:
                    print(result["message_preview"], flush=True)
        except SCAN_ERRORS as exc:
            failed = True
            print(f"{bvid} 判定失败，下次重试 ({type(exc).__name__})", file=sys.stderr)
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", required=True, type=int, help="Bilibili UP's numeric UID")
    parser.add_argument("--state", required=True, help="Persistent SQLite database path")
    parser.add_argument("--rule", default=DEMO_RULE, help="Content matching rule (default: demo rule)")
    parser.add_argument("--asr-seconds", type=int, default=75, help="Opening audio sample when captions are unavailable")
    parser.add_argument("--max-checks", type=int, default=3, help="Maximum pending videos classified per scan")
    args = parser.parse_args()
    if args.uid <= 0 or not 1 <= args.asr_seconds <= 120 or args.max_checks < 1:
        parser.error("UID 和 --max-checks 必须大于 0，--asr-seconds 必须为 1–120")
    try:
        with closing(sqlite3.connect(args.state, timeout=5)) as db, httpx.Client(timeout=45) as client:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS channels (
                    uid INTEGER PRIMARY KEY,
                    watermark INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS uploads (
                    uid INTEGER NOT NULL,
                    bvid TEXT NOT NULL,
                    published INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (uid, bvid)
                );
            """)
            scan(db, client, args.uid)
            return int(process_pending(db, client, args.uid, args.rule, args.asr_seconds, args.max_checks))
    except (*SCAN_ERRORS, sqlite3.Error) as exc:
        print(f"UID {args.uid} 扫描失败 ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
