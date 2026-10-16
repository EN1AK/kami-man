"""Move finished MyCard replay evidence to a verified home-host batch archive."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import time
import uuid

from .store import ArchiveStore, atomic_bytes

GIB = 1024 ** 3
DEFAULT_BATCH = 512 * 1024 ** 2
BATCH_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
RAW_NAME = re.compile(r"^[0-9a-f]{64}\.yrp$")
YDK_NAME = re.compile(r"^(round-[0-9]+-player-[0-9]+|merged-player-[0-9]+)\.ydk$")


def stream_digest(source):
    result = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def digest(path):
    with path.open("rb") as source:
        return stream_digest(source)


class ArchiveOffloader:
    def __init__(self, store, *, trigger_bytes=None, batch_bytes=DEFAULT_BATCH):
        if trigger_bytes is None:
            trigger_bytes = max(1, store.capture_ceiling - 1024 ** 2)
        if not 0 < trigger_bytes < store.limit_bytes:
            raise ValueError("转存阈值必须低于归档上限")
        if batch_bytes <= 0:
            raise ValueError("单批容量无效")
        self.store = store
        self.trigger_bytes = trigger_bytes
        self.batch_bytes = batch_bytes
        self.stage = store.root.parent / "mycard_offload_stage"
        self.stage.mkdir(parents=True, exist_ok=True)
        self.plan_path = self.stage / "pending.json"
        self.lock_path = self.stage / "offload.lock"

    @contextmanager
    def locked(self):
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def pending(self):
        if not self.plan_path.exists():
            return None
        plan = json.loads(self.plan_path.read_text("utf-8"))
        if not BATCH_ID.fullmatch(plan["id"]) or not re.fullmatch(r"[0-9a-f]{64}", plan["sha256"]):
            raise ValueError("待传输归档清单无效")
        if not isinstance(plan["matches"], dict) or not plan["matches"]:
            raise ValueError("待传输对局清单无效")
        for match_id, files in plan["matches"].items():
            self.store.check_id(match_id)
            for entry in files:
                if not (RAW_NAME.fullmatch(entry["name"]) or entry["name"] == "archive.zip"):
                    raise ValueError("待清理文件名无效")
                if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                    raise ValueError("待清理文件校验值无效")
        if not (self.stage / (plan["id"] + ".tar")).is_file():
            raise FileNotFoundError("待传输归档包丢失；请人工核对后重试")
        return plan

    def eligible(self):
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("""
                SELECT m.id FROM matches m
                WHERE m.status != 'active'
                  AND EXISTS (SELECT 1 FROM replays r WHERE r.match_id=m.id)
                  AND NOT EXISTS (SELECT 1 FROM offloads o WHERE o.match_id=m.id)
                ORDER BY m.first_seen,m.id""")]
        selected = []
        total = 0
        for match_id in ids:
            directory = self.store.directory(match_id)
            if directory.is_symlink() or not directory.is_dir() or not directory.resolve().is_relative_to(self.store.root):
                continue
            files = []
            for path in sorted(directory.iterdir()):
                if path.is_symlink() or not path.is_file():
                    continue
                if RAW_NAME.fullmatch(path.name) or YDK_NAME.fullmatch(path.name) or path.name in {"manifest.json", "archive.zip"}:
                    files.append(path)
            if not any(RAW_NAME.fullmatch(path.name) for path in files):
                continue
            size = sum(((path.stat().st_size + 511) // 512) * 512 + 2048 for path in files)
            if selected and total + size > self.batch_bytes:
                break
            selected.append((match_id, files))
            total += size
            if total >= self.batch_bytes:
                break
        return selected, total

    def prepare(self, *, force=False):
        with self.locked():
            plan = self.pending()
            if plan:
                return plan
            for orphan in self.stage.glob("*.tar"):
                if not orphan.is_symlink() and BATCH_ID.fullmatch(orphan.stem):
                    orphan.unlink()
            if not force and self.store.usage_bytes() < self.trigger_bytes:
                return None
            selected, size = self.eligible()
            if not selected:
                return None
            if shutil.disk_usage(self.stage).free < size + 256 * 1024 ** 2:
                raise OSError("服务器没有足够的临时空间制作转存包")
            batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
            archive = self.stage / (batch_id + ".tar")
            removals = {}
            try:
                with tarfile.open(archive, "w") as tar:
                    for match_id, files in selected:
                        removals[match_id] = []
                        for path in files:
                            tar.add(path, arcname=f"matches/{match_id}/{path.name}", recursive=False)
                # Hash the packed bytes so a later local change cannot be mistaken for this copy.
                with tarfile.open(archive, "r") as tar:
                    for member in tar:
                        _, match_id, name = member.name.split("/")
                        if RAW_NAME.fullmatch(name) or name == "archive.zip":
                            with tar.extractfile(member) as source:
                                removals[match_id].append({"name": name, "sha256": stream_digest(source)})
                plan = {
                    "id": batch_id,
                    "sha256": digest(archive),
                    "bytes": archive.stat().st_size,
                    "matches": removals,
                    "created": time.time(),
                }
                atomic_bytes(self.plan_path, json.dumps(plan, separators=(",", ":")).encode("utf-8"))
            except BaseException:
                archive.unlink(missing_ok=True)
                raise
            return plan

    def fetch(self, batch_id, destination):
        if not BATCH_ID.fullmatch(batch_id):
            raise ValueError("转存包编号无效")
        with self.locked():
            plan = self.pending()
            if not plan or plan["id"] != batch_id:
                raise ValueError("没有该待传输归档包")
            with (self.stage / (batch_id + ".tar")).open("rb") as source:
                shutil.copyfileobj(source, destination, 1024 * 1024)

    def commit(self, batch_id, checksum):
        if not BATCH_ID.fullmatch(batch_id) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("转存确认参数无效")
        with self.locked():
            plan = self.pending()
            if not plan:
                with self.store.connect() as db:
                    count = db.execute("SELECT COUNT(*) FROM offloads WHERE batch_id=?", (batch_id,)).fetchone()[0]
                if count:
                    return 0
                raise ValueError("没有待确认的转存包")
            if plan["id"] != batch_id or plan["sha256"] != checksum:
                raise ValueError("转存包校验值不匹配，服务器文件未删除")
            # Raw evidence is immutable. If it changed after packing, retain the server copy.
            for match_id, files in plan["matches"].items():
                for entry in files:
                    if not RAW_NAME.fullmatch(entry["name"]):
                        continue
                    path = self.store.directory(match_id) / entry["name"]
                    if path.exists() and digest(path) != entry["sha256"]:
                        raise ValueError("录像在打包后发生变化，服务器文件未删除")
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                for match_id in plan["matches"]:
                    db.execute("INSERT OR IGNORE INTO offloads(match_id,batch_id,transferred) VALUES(?,?,?)",
                               (match_id, batch_id, time.time()))
            removed = 0
            for match_id, files in plan["matches"].items():
                for entry in files:
                    path = self.store.directory(match_id) / entry["name"]
                    if path.exists() and digest(path) == entry["sha256"]:
                        removed += self.store.allocated_bytes(path)
                        path.unlink()
            self.plan_path.unlink(missing_ok=True)
            (self.stage / (batch_id + ".tar")).unlink(missing_ok=True)
            return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Transfer finished MyCard evidence to home")
    parser.add_argument("--root", type=Path, default=Path(os.getenv("MYCARD_ARCHIVE_DIR", Path(__file__).resolve().parents[2] / "data/mycard_archive")))
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--force", action="store_true")
    prepare.add_argument("--batch-mib", type=int, default=512)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("batch_id")
    commit = sub.add_parser("commit")
    commit.add_argument("batch_id")
    commit.add_argument("sha256")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root, int(os.getenv("MYCARD_ARCHIVE_MAX_GB", "10")) * GIB)
    manager = ArchiveOffloader(store, batch_bytes=getattr(args, "batch_mib", 512) * 1024 ** 2)
    if args.command == "prepare":
        plan = manager.prepare(force=args.force)
        if plan:
            print("\t".join((plan["id"], plan["sha256"], str(plan["bytes"]), str(len(plan["matches"])))))
        else:
            print("NONE")
    elif args.command == "fetch":
        manager.fetch(args.batch_id, sys.stdout.buffer)
    elif args.command == "commit":
        print(manager.commit(args.batch_id, args.sha256))
    else:
        used = store.usage_bytes()
        plan = manager.pending()
        print(f"used_gib={used/GIB:.3f} trigger_gib={manager.trigger_bytes/GIB:.1f} "
              f"offloaded={store.offload_count()} pending={plan['id'] if plan else 'none'}")


if __name__ == "__main__":
    main()
