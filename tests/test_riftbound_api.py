import asyncio
from pathlib import Path
import sqlite3

import httpx
import pytest

from services import riftbound_api as api


@pytest.fixture
def card_db(tmp_path, monkeypatch):
    path = tmp_path / "cards.db"
    fields = ["card_key", "name_cn", "name_en", "sub_title_cn", "variant", "type_cn", "type_en",
              "text_cn", "text_en", "text_cn_filled", "cn_fill_note", "energy", "rune_power", "might",
              "might_bonus", "image_url_cn", "image_url_en", "errata_cn"]
    rows = [
        dict(card_key="OGN-066", name_cn="阿狸", sub_title_cn="嫣然狐媚", name_en="Ahri, Alluring", variant="base", energy=5, text_en="Hold: score 1."),
        dict(card_key="OGN-066a", name_cn="阿狸", sub_title_cn="嫣然狐媚", name_en="Ahri, Alluring", variant="alt", energy=5, text_en="Hold: score 1."),
        dict(card_key="OGN-119", name_cn="阿狸", sub_title_cn="天真绮梦", name_en="Ahri, Inquisitive", variant="base", energy=2, text_en="Draw 1."),
        dict(card_key="SFD-227*", name_cn="阿狸", sub_title_cn="天真绮梦", name_en="Ahri, Inquisitive", variant="star", energy=2, text_en="Draw 1."),
        dict(card_key="OGN-131", name_cn="沙丘亚龙", name_en="Dune Drake", variant="base", energy=0, text_cn="{{横置}}：获得{{1}}和{{红色}}。"),
        dict(card_key="UNL-T02", name_en="Recruit", variant="token", text_en="+1 :rb_might:"),
    ]
    with sqlite3.connect(path) as conn:
        conn.execute("create table cards (" + ",".join(field + " TEXT" for field in fields) + ")")
        for row in rows:
            conn.execute("insert into cards (" + ",".join(row) + ") values (" + ",".join("?" for _ in row) + ")", list(row.values()))
    monkeypatch.setenv("RIFTBOUND_CARDS_DB", str(path))
    api._read_cards.cache_clear()
    return path


def test_names_group_editions_but_keep_distinct_subtitles(card_db):
    cards = api.search_riftbound_cards("阿狸")
    assert {card["sub_title_cn"] for card in cards} == {"嫣然狐媚", "天真绮梦"}
    assert len(cards) == 2
    assert cards[0]["card_key"] == "OGN-066"
    assert [card["card_key"] for card in cards[0]["editions"]] == ["OGN-066", "OGN-066a"]


@pytest.mark.parametrize("query,code", [("ＯＧＮ·066a/298", "OGN-066a"), ("sfd-227*", "SFD-227*"), ("unl-t02", "UNL-T02")])
def test_exact_code_preserves_special_versions(card_db, query, code):
    cards = api.search_riftbound_cards(query)
    assert len(cards) == 1 and cards[0]["card_key"] == code
    assert len(cards[0]["editions"]) == 1


@pytest.mark.parametrize("query", ["阿狸 嫣然狐媚", "嫣然狐媚", "Ahri, Alluring", "ahri alluring"])
def test_full_name_and_subtitle(card_db, query):
    cards = api.search_riftbound_cards(query)
    assert len(cards) == 1 and cards[0]["card_key"] == "OGN-066"


def test_substring_typo_and_missing_code(card_db):
    assert api.search_riftbound_cards("沙丘")[0]["match_kind"] == "partial"
    typo = api.search_riftbound_cards("沙丘亚隆")[0]
    assert typo["card_key"] == "OGN-131" and typo["match_kind"] == "fuzzy"
    assert api.search_riftbound_cards("阿理")
    assert api.search_riftbound_cards("OGN-999") == []
    assert api.search_riftbound_cards("") == []


def test_database_refresh_and_missing_database(card_db, monkeypatch):
    api.load_cards()
    with sqlite3.connect(card_db) as conn:
        conn.execute("update cards set name_cn='沙丘巨龙' where card_key='OGN-131'")
    assert api.search_riftbound_cards("沙丘巨龙")[0]["card_key"] == "OGN-131"
    missing = card_db.parent / "missing.db"
    monkeypatch.setenv("RIFTBOUND_CARDS_DB", str(missing))
    with pytest.raises(FileNotFoundError):
        api.load_cards()
    assert not missing.exists()


def test_format_zero_cost_filled_text_errata_and_english(card_db):
    card = api.search_riftbound_cards("OGN-131")[0]
    card.update(energy=0, rune_power=0, text_cn_filled="{{S}}+2，{{A}}", cn_fill_note="非官方中文补译", errata_cn="本回合{{S}}+2。")
    text = api.format_riftbound_card(card)
    assert "能量费用：0" in text and "符能费用：0" in text
    assert "非官方中文补译" in text and "勘误：本回合[战力]+2。" in text
    assert "{{" not in text
    english = api.format_riftbound_card(api.search_riftbound_cards("UNL-T02")[0])
    assert "暂无中文效果" in english and "[战力]" in english


def test_candidate_output_does_not_choose_typo(card_db):
    text = api.format_candidates(api.search_riftbound_cards("阿理"))
    assert "相近卡片" in text and "rb OGN-066" in text


def test_image_fallback_cache_and_html_rejection(tmp_path):
    calls = []
    png = b"\x89PNG\r\n\x1a\n" + b"sample"
    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/cn":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>blocked</html>")
        return httpx.Response(200, headers={"content-type": "image/png"}, content=png)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            card = {"image_url_cn": "https://test/cn", "image_url_en": "https://test/en"}
            image, language = await api.card_image(card, client, tmp_path)
            assert image.startswith("base64://") and language == "en"
            assert not api.image_cache_path(card["image_url_cn"], tmp_path).exists()
            assert api.image_cache_path(card["image_url_en"], tmp_path).read_bytes() == png
            assert await api.fetch_image(card["image_url_en"], client, tmp_path) == png
    asyncio.run(run())
    assert calls == ["https://test/cn", "https://test/en"]


def test_failed_images_and_oversized_images(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "MAX_IMAGE_BYTES", 16)
    def respond(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await api.card_image({"image_url_cn": "https://test/large"}, client, tmp_path) == (None, None)
    asyncio.run(run())
    assert not list(tmp_path.iterdir())
