"""Cache missing card images on the server. Rerun to resume."""
import asyncio
from collections import Counter
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.ygo_api import IMAGE_DIR, MAX_IMAGE_BYTES, PRIMARY_IMG, FALLBACK_IMG, LEGACY_IMG, valid_card_image

GIB = 1024**3


def readonly(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))


async def main(database):
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with readonly(database) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM datas WHERE id > 0")}
    popular = Counter()
    archive = IMAGE_DIR.parent / "mycard_archive" / "archive.sqlite3"
    if archive.is_file():
        with readonly(archive) as db:
            for (raw,) in db.execute("SELECT deck FROM observations ORDER BY rowid DESC LIMIT 4000"):
                d = json.loads(raw)
                popular.update(set(d.get("main", []) + d.get("extra", []) + d.get("side", [])))
    order = dict.fromkeys([89631139,46986414,56506740] + [i for i,_ in popular.most_common()] + sorted(ids))
    pending = [i for i in order if i in ids and not (IMAGE_DIR/f"{i}.img").is_file()]
    queue = iter(pending)
    used = sum(p.stat().st_blocks*512 for p in IMAGE_DIR.glob("*.img"))
    print(f"cards={len(ids)} pending={len(pending)}")
    lock = asyncio.Lock()
    next_request = 0.
    stop = False
    misses = 0
    counts = Counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(5,connect=3),follow_redirects=True) as client:
        async def worker():
            nonlocal used, next_request, stop, misses
            for i in queue:
                if stop: return
                for template in (PRIMARY_IMG,FALLBACK_IMG,LEGACY_IMG):
                    try:
                        async with lock:
                            await asyncio.sleep(max(0,next_request-time.monotonic()))
                            if stop: return
                            next_request = time.monotonic()+1/25
                        async with client.stream("GET",template.format(id=i)) as r:
                            if r.status_code == 429:
                                stop = True
                                print("stopped: upstream rate limit")
                                return
                            if r.status_code != 200: continue
                            data = bytearray()
                            async for chunk in r.aiter_bytes():
                                data.extend(chunk)
                                if len(data)>MAX_IMAGE_BYTES: break
                        if not valid_card_image(data): continue
                        with Image.open(BytesIO(data)) as im:
                            if not (100<=im.width<=4096 and 100<=im.height<=4096): continue
                            im.verify()
                    except (httpx.HTTPError,OSError,ValueError,SyntaxError):
                        continue
                    size = (len(data)+4095)//4096*4096
                    if stop: return
                    if used+size>1.5*GIB or shutil.disk_usage(IMAGE_DIR).free-size<2*GIB:
                        stop = True
                        print("stopped: disk budget")
                        return
                    dest=IMAGE_DIR/f"{i}.img"
                    temp=dest.with_suffix(".part")
                    try:
                        temp.write_bytes(data)
                        temp.replace(dest)
                    finally:
                        temp.unlink(missing_ok=True)
                    used+=size
                    counts["downloaded"]+=1
                    misses=0
                    break
                else:
                    counts["unavailable"]+=1
                    misses+=1
                    if misses>=40:
                        stop=True
                        print("stopped: repeated upstream failures")
                if sum(counts.values())%250==0: print(dict(counts))
        await asyncio.gather(*(worker() for _ in range(12)))
    print(f"finished {dict(counts)} allocated_mib={used/1024**2:.1f} stopped={stop}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
