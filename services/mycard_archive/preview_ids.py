"""Resolve archived preview IDs against the current official catalog."""
import json
from pathlib import Path

CARD_ALIASES_FILE = Path(__file__).resolve().parents[2] / "data/ygo_card_aliases.json"


def alias_stamp():
    try:
        stat = CARD_ALIASES_FILE.stat()
        return CARD_ALIASES_FILE, stat.st_mtime_ns, stat.st_size, stat.st_ino
    except FileNotFoundError:
        return CARD_ALIASES_FILE, 0, 0, 0


def add_preview_ids(catalog, stamp):
    """Extend a freshly loaded catalog without overwriting official IDs."""
    try:
        entries = json.loads(stamp[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return catalog
    if isinstance(entries, dict):
        additions = {}
        for source, entry in entries.items():
            if not source.isascii() or not source.isdecimal() or not isinstance(entry, dict):
                continue
            target = entry.get("id")
            if type(target) is int and target in catalog and int(source) not in catalog:
                additions[int(source)] = catalog[target]
        catalog.update(additions)
    return catalog
