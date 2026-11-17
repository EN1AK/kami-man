"""Resolve simulator-only IDs used in MyCard recordings through YGOCDB."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile

import httpx

from services.mycard_archive.statistics import CARD_ALIASES_FILE


async def refresh_aliases(database, unknown):
    path = CARD_ALIASES_FILE
    try:
        aliases = {int(k): v for k, v in json.loads(path.read_text()).items()}
    except (OSError, ValueError, AttributeError):
        aliases = {}
    before = dict(aliases)
    with closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        for code in list(aliases):
            if db.execute("SELECT 1 FROM texts WHERE id=?", (code,)).fetchone():
                aliases.pop(code)
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            for code in [i for i in unknown if i not in aliases][:250]:
                try:
                    response = await client.get(f"https://ygocdb.com/api/v0/card/{code}")
                    if response.status_code == 429:
                        break
                    if not response.is_success:
                        continue
                    card = response.json()
                    target = card.get("id")
                    info = card.get("text") or {}
                    name = info.get("sc_name") or info.get("name") or info.get("jp_name")
                    if type(target) is not int or target <= 0 or not isinstance(name, str) or not 1 <= len(name.strip()) <= 150:
                        continue
                    aliases[code] = {"id": target, "name": name.strip()}
                except (httpx.HTTPError, ValueError, AttributeError, TypeError):
                    pass
                finally:
                    await asyncio.sleep(.15)
    if aliases != before:
        path.parent.mkdir(exist_ok=True, parents=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(aliases, handle, ensure_ascii=False, sort_keys=True)
            tmp = Path(handle.name)
        try:
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    print(f"preview aliases: {len(aliases)}, added={len(aliases.keys()-before.keys())}", flush=True)
    return aliases
