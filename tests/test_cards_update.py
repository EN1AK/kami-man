"""Catalog replacement must preserve the previous file on download failure."""
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import urllib.error
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location("cards_update", Path(__file__).resolve().parents[1] / "deploy/update_cards_db.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def catalog(path, *, marker=0):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE datas (id INTEGER PRIMARY KEY, alias, setcode, type, race, attribute, atk, def, level, category)")
        db.execute("CREATE TABLE texts (id INTEGER PRIMARY KEY, name, desc)")
        db.executemany("INSERT INTO datas VALUES (?,0,0,0,0,0,0,0,0,0)", ((i,) for i in range(10000)))
        db.executemany("INSERT INTO texts VALUES (?,?,'')", ((i, f'card-{marker}-{i}') for i in range(10000)))


class Response(io.BytesIO):
    headers = {"ETag": '"test-etag"'}


def test_replacement_backup_and_conditional_request(tmp_path):
    destination, incoming = tmp_path / "cards.cdb", tmp_path / "new.cdb"
    state, backup = tmp_path / "state.json", tmp_path / "previous.cdb"
    catalog(destination)
    catalog(incoming, marker=1)
    original = destination.read_bytes()
    with patch.object(updater.urllib.request, "urlopen", return_value=Response(incoming.read_bytes())):
        assert updater.update(destination, state, backup)
    assert backup.read_bytes() == original
    assert destination.read_bytes() == incoming.read_bytes()
    assert json.loads(state.read_text(encoding="utf-8"))["cards"] == 10000
    error = urllib.error.HTTPError(updater.SOURCE, 304, "unchanged", {}, None)
    with patch.object(updater.urllib.request, "urlopen", side_effect=error) as request:
        assert not updater.update(destination, state, backup)
    assert request.call_args.args[0].get_header("If-none-match") == '"test-etag"'


def test_bad_download_keeps_live_catalog_and_state(tmp_path):
    destination = tmp_path / "cards.cdb"
    state, backup = tmp_path / "state.json", tmp_path / "previous.cdb"
    catalog(destination)
    original = destination.read_bytes()
    for payload in (b"not a database",):
        with patch.object(updater.urllib.request, "urlopen", return_value=Response(payload)):
            with pytest.raises((sqlite3.Error, ValueError)):
                updater.update(destination, state, backup)
    assert destination.read_bytes() == original
    assert not state.exists()
    assert not backup.exists()
    assert not list(tmp_path.glob(".cards-download-*"))


def test_reject_incomplete_catalog(tmp_path):
    path = tmp_path / "cards.cdb"
    catalog(path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM texts WHERE id=123")
    with pytest.raises(ValueError, match="Incomplete"):
        updater.validate(path)


def test_set_names_validation_preserves_old_labels(tmp_path):
    destination, state, backup = tmp_path / "strings.conf", tmp_path / "state.json", tmp_path / "previous.conf"
    destination.write_text("previous labels", encoding="utf-8")
    with patch.object(updater.urllib.request, "urlopen", return_value=Response(b"<html>error</html>")):
        with pytest.raises(ValueError, match="Incomplete"):
            updater.update_strings(destination, state, backup)
    assert destination.read_text(encoding="utf-8") == "previous labels"
    assert not state.exists()
    payload = "\n".join(f"!setname 0x{i:x} 系列{i}" for i in range(1, 450)).encode("utf-8")
    with patch.object(updater.urllib.request, "urlopen", return_value=Response(payload)):
        assert updater.update_strings(destination, state, backup)
    assert backup.read_text(encoding="utf-8") == "previous labels"
    assert destination.read_bytes() == payload
