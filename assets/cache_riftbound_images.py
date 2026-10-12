"""Prefill preferred Riftbound images on the Linux bot server, never Windows."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from services.riftbound_api import fetch_image, image_cache_dir, image_cache_path, load_cards, valid_image


async def run(concurrency: int) -> int:
    cards = load_cards()
    directory = image_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(concurrency)
    report = {"total": len(cards), "ok": 0, "english": [], "failed": []}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        async def download(card):
            async with semaphore:
                image, language = None, None
                for field, lang in (("image_url_cn", "cn"), ("image_url_en", "en")):
                    url = card.get(field)
                    if not url:
                        continue
                    path = image_cache_path(url, directory)
                    if path.exists() and valid_image(await asyncio.to_thread(path.read_bytes)):
                        image, language = True, lang
                        break
                    # Download via the same validation/cache path used by the bot.
                    data = None
                    for attempt in range(3):
                        data = await fetch_image(url, client, directory)
                        if data and path.exists():
                            break
                        await asyncio.sleep(0.5 * (attempt + 1))
                    if data and path.exists():
                        image, language = True, lang
                        break
                if image:
                    report["ok"] += 1
                    if language == "en":
                        report["english"].append(card["card_key"])
                else:
                    report["failed"].append(card["card_key"])
                done = report["ok"] + len(report["failed"])
                if done % 100 == 0 or done == len(cards):
                    print(f"{done}/{len(cards)}: ok={report['ok']}, failed={len(report['failed'])}", flush=True)
        await asyncio.gather(*(download(card) for card in cards))
    report["english"].sort()
    report["failed"].sort()
    (directory / "download_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    if sys.platform == "win32":
        parser.error("Run this downloader on the Linux server; do not download images on Windows.")
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(asyncio.run(run(args.concurrency)))
