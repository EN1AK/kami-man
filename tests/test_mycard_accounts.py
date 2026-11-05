import asyncio
from pathlib import Path
import pytest
from services.mycard_archive.accounts import AccountPool
from services.mycard_archive.protocol import CredentialsUnavailable
from services.mycard_archive.collector import ArchiveConfig, Collector, RoomState


class Identity:
    def __init__(self, name):
        self.name = name
        self.invalidations = 0
        self.calls = 0

    async def get(self):
        self.calls += 1
        if self.name is None:
            raise CredentialsUnavailable("expired")
        return self.name, 3

    def invalidate(self):
        self.invalidations += 1


def test_distinct_accounts_capture_two_rooms_without_username_overlap(tmp_path):
    async def run():
        pool = AccountPool([Identity("Observer1"), Identity("Observer2")])
        release = asyncio.Event()
        active = set()
        seen = []
        async def watch(room, identity, ended, save, **kwargs):
            assert identity[0] not in active
            active.add(identity[0]); seen.append(identity[0])
            kwargs["on_connected"]()
            try:
                await release.wait()
                return True
            finally:
                active.remove(identity[0])
        c = Collector(ArchiveConfig(tmp_path, tmp_path/"primary", concurrency=2,
                      extra_credentials=(tmp_path/"second",)), watch_room=watch)
        c.credentials = pool
        class Rank:
            async def qualifying(self, players):
                return {"Alice": 1}, {"Alice": 1}
            async def close(self): pass
        c.rank = Rank()
        async def admit(ended): return True
        c.admit = admit
        tasks = [asyncio.create_task(c.collect(RoomState({"id": str(i)}, ["Alice", "Bob"]))) for i in range(3)]
        try:
            for _ in range(100):
                if len(seen) == 2: break
                await asyncio.sleep(.01)
            assert set(seen) == {"Observer1", "Observer2"}
            assert len(pool.busy) == 2
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 3)
            assert len(seen) == 3 and not pool.busy and not pool.leases
        finally:
            for t in tasks: t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await c.close()
    asyncio.run(run())


def test_duplicate_username_cannot_add_capacity_and_waiter_ends():
    async def run():
        pool = AccountPool([Identity("Same"), Identity("Same")])
        assert (await pool.get_for([], asyncio.Event()))[0] == "Same"
        ended = asyncio.Event()
        waiter = asyncio.create_task(pool.get_for([], ended))
        await asyncio.sleep(.02)
        assert not waiter.done() and len(pool.busy) == 1
        ended.set()
        assert await asyncio.wait_for(waiter, 1) is None
        pool.release()
        assert not pool.busy
    asyncio.run(run())


def test_invalid_account_falls_back_and_does_not_flood_auth():
    async def run():
        bad, good = Identity(None), Identity("Good")
        pool = AccountPool([bad, good])
        assert await pool.get_for([], asyncio.Event()) == ("Good", 3)
        pool.invalidate()
        assert good.invalidations == 1
        pool.release()
        assert await pool.get_for([], asyncio.Event()) == ("Good", 3)
        assert bad.calls == 1
        pool.release()
    asyncio.run(run())


def test_account_playing_in_room_is_excluded():
    async def run():
        pool = AccountPool([Identity("Alice"), Identity("Observer")])
        assert await pool.get_for(["Alice", "Bob"], asyncio.Event()) == ("Observer", 3)
        pool.release()
    asyncio.run(run())


def test_collector_cancellation_releases_account(tmp_path):
    async def run():
        c = Collector(ArchiveConfig(tmp_path, tmp_path/"primary"))
        c.credentials = AccountPool([Identity("Observer")])
        acquired = asyncio.Event()
        async def job():
            try:
                await c.credentials.get_for([], asyncio.Event())
                acquired.set()
                await asyncio.Event().wait()
            finally:
                c.credentials.release()
        task = asyncio.create_task(job())
        await acquired.wait(); task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not c.credentials.busy
        assert await c.credentials.get_for([], asyncio.Event()) == ("Observer", 3)
        c.credentials.release()
        await c.close()
    asyncio.run(run())


def test_single_account_default_and_capacity_clamp(tmp_path, monkeypatch):
    monkeypatch.delenv("MYCARD_CAPTURE_CONCURRENCY", raising=False)
    monkeypatch.delenv("MYCARD_EXTRA_CREDENTIALS_FILES", raising=False)
    assert ArchiveConfig.from_env().concurrency == 1
    c = Collector(ArchiveConfig(tmp_path, tmp_path/"primary", concurrency=4))
    assert c.capture_slots == 1
    asyncio.run(c.close())
