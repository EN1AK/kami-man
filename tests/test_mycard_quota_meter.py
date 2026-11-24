from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from services.mycard_archive.store import ArchiveStore, ArchiveLimitReached


def full_size(store):
    return sum(store.allocated_bytes(p) for p in store.root.rglob("*") if p.is_file())


def test_accounting_replacement_failure_and_external_change(tmp_path, monkeypatch):
    store = ArchiveStore(tmp_path)
    path = store.directory("a" * 24) / "manifest.json"
    assert store.usage_bytes() == full_size(store)
    scan = store.usage.scan
    scans = []

    def counted(directory, recurse):
        if recurse:
            scans.append(directory)
        return scan(directory, recurse)

    monkeypatch.setattr(store.usage, "scan", counted)
    for body in (b"a" * 9000, b"x", b"z" * 18000):
        store._write_evidence(path, body)
        assert store.usage_bytes() == full_size(store)
    assert not scans
    with pytest.raises(RuntimeError):
        with store.usage.changing(path):
            path.unlink()
            raise RuntimeError()
    assert store.usage_bytes() == full_size(store)
    assert scans
    external = path.with_name("external")
    external.write_bytes(b"x" * 8000)
    monkeypatch.setattr(store.usage, "reconcile_seconds", 0)
    assert store.usage_bytes() == full_size(store)


def test_separate_stores_share_capacity(tmp_path):
    stores = [ArchiveStore(tmp_path), ArchiveStore(tmp_path)]
    barrier = Barrier(2)
    for store in stores:
        store.limit_bytes = store.usage_bytes() + store.reserve_bytes + store.usage.unit

    def write(index):
        store = stores[index]
        path = store.directory("b" * 24) / str(index)
        barrier.wait()
        try:
            store._write_evidence(path, b"test", capture=True)
        except ArchiveLimitReached:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, range(2))) == [False, True]
    assert all(s.usage_bytes() == full_size(s) for s in stores)
