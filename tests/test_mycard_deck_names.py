import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from services.mycard_archive.naming import (
    canonical_codes, deck_name, load_rules, recognize, validate_rules,
)
from services.mycard_archive.presentation import deck_summary
from services.mycard_archive.replay import ObservedDeck
from services.mycard_archive.store import atomic_bytes


def rules(*entries):
    return validate_rules({"version": 1, "rules": list(entries)})


def test_main_only_copy_counts_and_overlap_sorting():
    deck = ObservedDeck("P", (1, 1, 1, 2, 2, 3, 4), (5,), (6,))
    result = recognize(deck, rules(
        {"label": "核心", "cards": [1, 2]},
        {"label": "核心", "cards": [1]},
        {"label": "组件甲", "cards": [3]},
        {"label": "组件乙", "cards": [4]},
        {"label": "额外", "cards": [5]},
        {"label": "备牌", "cards": [6]},
    ), identities={})
    assert result["name"] == "组件甲组件乙核心"
    assert result["counts"] == {"核心": 5, "组件甲": 1, "组件乙": 1}


def test_any_all_and_legacy_minimum_copies():
    deck = ObservedDeck("P", (1, 1, 2), ())
    result = recognize(deck, rules(
        {"label": "任一", "cards": [1, 9]},
        {"label": "缺少", "cards": [1, 9], "match": "all"},
        {"label": "齐备", "cards": [1, 2], "match": "all"},
        {"name": "旧格式", "requires": {"1": 2}},
        {"name": "不足", "requires": {"1": 3}},
    ), identities={})
    assert result["labels"] == ["任一", "旧格式", "齐备"]


def test_sixty_prefix_only_for_identified_main():
    known = rules({"label": "烙印", "cards": [1]})
    assert recognize(ObservedDeck("P", (1,) * 60, ()), known, identities={})["name"] == "60烙印"
    assert recognize(ObservedDeck("P", (1,) * 59, (2,)), known, identities={})["name"] == "烙印"
    assert recognize(ObservedDeck("P", (2,) * 60, (1,)), known, identities={})["name"] == "未识别"


def test_explicit_same_name_aliases_only(tmp_path):
    path = tmp_path / "cards.cdb"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE datas(id INTEGER,alias INTEGER);CREATE TABLE texts(id INTEGER,name TEXT);")
        db.executemany("INSERT INTO datas VALUES(?,?)", [(1, 0), (10, 1), (11, 10), (20, 1)])
        db.executemany("INSERT INTO texts VALUES(?,?)", [(1, "A"), (10, "A"), (11, "A"), (20, "B")])
    identities = canonical_codes(path)
    assert identities[10] == identities[11] == 1
    assert identities[20] == 20
    result = recognize(ObservedDeck("P", (10, 11, 20), ()), rules({"label": "A", "cards": [1]}), identities=identities)
    assert result["counts"] == {"A": 2}
    assert canonical_codes(tmp_path / "missing.cdb") == {}


def test_runtime_overrides_and_hot_reload(tmp_path):
    defaults, custom = tmp_path / "defaults.json", tmp_path / "custom.json"
    defaults.write_text(json.dumps({"version": 1, "rules": [{"label": "A", "cards": [1]}]}))
    custom.write_text('{"version":1,"rules":[]}')
    deck = ObservedDeck("P", (1,), ())
    assert recognize(deck, load_rules(custom, defaults=defaults), identities={})["name"] == "A"
    atomic_bytes(custom, b'{"version":1,"rules":[{"label":"A","cards":[2]}]}')
    assert recognize(deck, load_rules(custom, defaults=defaults), identities={})["name"] == "未识别"
    atomic_bytes(custom, b'{"version":1,"use_defaults":false,"rules":[{"label":"B","cards":[1]}]}')
    assert recognize(deck, load_rules(custom, defaults=defaults), identities={})["name"] == "B"


@pytest.mark.parametrize("data", [
    {"version": 2, "rules": []},
    {"version": 1, "rules": [{"label": "", "cards": [1]}]},
    {"version": 1, "rules": [{"label": "A", "cards": [True]}]},
    {"version": 1, "rules": [{"label": "A", "cards": [1], "match": "guess"}]},
    {"version": 1, "rules": [{"name": "A", "requires": {"1": 0}}]},
    {"version": 1, "use_defaults": "false", "rules": []},
])
def test_invalid_rules_rejected(data):
    with pytest.raises(ValueError):
        validate_rules(data)


def test_bundled_names_are_ready_without_custom_rules(tmp_path):
    assert deck_name(ObservedDeck("P", (44362883,), ()), tmp_path / "missing.json") == "烙印"
    # Generic hand traps alone must not invent an archetype.
    assert deck_name(ObservedDeck("P", (14558127, 23434538), ()), tmp_path / "missing.json") == "未识别"
    assert len({rule["label"] for rule in load_rules(tmp_path / "missing.json")}) >= 90


def test_summary_and_share_title_use_current_name(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text('{"version":1,"use_defaults":false,"rules":[{"label":"Core","cards":[1]}]}')
    version = {"player": "A & B", "main": [1] * 3 + list(range(100, 137)), "extra": [], "side": [],
               "first_seen": 100, "last_seen": 200, "observations": 2, "match_id": "a" * 24}
    summary = deck_summary(version, path)
    assert "卡组：Core" in summary
    link = next(line.split("：", 1)[1] for line in summary.splitlines() if line.startswith("卡组链接："))
    assert parse_qs(urlparse(link).query)["name"] == ["A & B〖Core〗"]
