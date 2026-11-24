"""Safely refresh the shared Chinese card catalog; run via systemd timer."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.request

SOURCE = "https://raw.githubusercontent.com/mycard/ygopro-database/master/locales/zh-CN/cards.cdb"
STRINGS_SOURCE = "https://raw.githubusercontent.com/Fluorohydride/ygopro/master/strings.conf"
MAX_BYTES = 32 * 1024 * 1024
REQUIRED = {
    "datas": {"id", "alias", "setcode", "type", "race", "attribute", "atk", "def", "level", "category"},
    "texts": {"id", "name", "desc"},
}


def validate(path: Path, *, minimum: int = 10000) -> int:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        for table, columns in REQUIRED.items():
            actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if not columns.issubset(actual):
                raise ValueError(f"Invalid catalog schema: {table}")
        count = db.execute("SELECT COUNT(*) FROM datas").fetchone()[0]
        named = db.execute("SELECT COUNT(*) FROM datas d JOIN texts t ON t.id=d.id WHERE trim(t.name) != ''").fetchone()[0]
        text_count = db.execute("SELECT COUNT(*) FROM texts").fetchone()[0]
        if count < minimum or named != count or text_count != count:
            raise ValueError(f"Incomplete catalog: datas={count}, texts={text_count}, named={named}")
        return count


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(128 * 1024):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def update_strings(destination: Path, state_path: Path, backup: Path) -> bool:
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    current_hash = digest(destination) if destination.exists() else None
    headers = {"User-Agent": "kami-man-card-catalog-updater/1"}
    if state.get("source") == STRINGS_SOURCE and state.get("sha256") == current_hash and state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    try:
        response = urllib.request.urlopen(urllib.request.Request(STRINGS_SOURCE, headers=headers), timeout=45)
    except urllib.error.HTTPError as error:
        if error.code == 304:
            print("Set names unchanged")
            return False
        raise
    with response:
        payload = response.read(1024 * 1024 + 1)
        etag = response.headers.get("ETag")
    if len(payload) > 1024 * 1024:
        raise ValueError("Strings download exceeds size limit")
    names = {}
    for line in payload.decode("utf-8-sig").splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "!setname":
            name = parts[2].split("\t", 1)[0].split("|", 1)[0].strip()
            code = int(parts[1], 16)
            if not 0 < code <= 0xffff or not name:
                raise ValueError("Invalid set name record")
            names[code] = name
    if len(names) < 400:
        raise ValueError("Incomplete set name catalog")
    new_hash = hashlib.sha256(payload).hexdigest()
    changed = new_hash != current_hash
    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".conf.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.chmod(0o644)
            if destination.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup_tmp = backup.with_suffix(".tmp")
                shutil.copy2(destination, backup_tmp)
                os.replace(backup_tmp, backup)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    atomic_json(state_path, {"source": STRINGS_SOURCE, "etag": etag, "sha256": new_hash, "fields": len(names)})
    print(f"Set names {'updated' if changed else 'unchanged'}: {len(names)} fields")
    return changed


def update(destination: Path, state_path: Path, backup: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    current_count = validate(destination) if destination.exists() else 0
    current_hash = digest(destination) if destination.exists() else None
    headers = {"User-Agent": "kami-man-card-catalog-updater/1"}
    if state.get("source") == SOURCE and state.get("sha256") == current_hash and state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    request = urllib.request.Request(SOURCE, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=45)
    except urllib.error.HTTPError as error:
        if error.code == 304:
            print(f"Catalog unchanged ({current_count} cards)")
            return False
        raise
    fd, temporary_name = tempfile.mkstemp(prefix=".cards-download-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with response, os.fdopen(fd, "wb") as stream:
            size = 0
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Catalog download exceeds size limit")
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
            etag = response.headers.get("ETag")
        count = validate(temporary, minimum=max(10000, int(current_count * 0.95)))
        new_hash = digest(temporary)
        changed = new_hash != current_hash
        if changed:
            if destination.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup_tmp = backup.with_suffix(backup.suffix + ".tmp")
                shutil.copy2(destination, backup_tmp)
                os.replace(backup_tmp, backup)
                temporary.chmod(destination.stat().st_mode & 0o777)
            else:
                temporary.chmod(0o644)
            os.replace(temporary, destination)
        atomic_json(state_path, {
            "source": SOURCE, "etag": etag, "sha256": new_hash, "cards": count,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Catalog {'updated' if changed else 'unchanged'}: {current_count} -> {count}; sha256={new_hash}")
        return changed
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--strings", type=Path)
    args = parser.parse_args()
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with args.state.with_suffix(".lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another catalog update is running")
            return
        update(args.destination, args.state, args.backup)
        if args.strings:
            update_strings(args.strings, args.state.with_name("strings-state.json"), args.backup.with_name("previous-strings.conf"))


if __name__ == "__main__":
    main()
