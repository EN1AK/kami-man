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


def test_slow_account_auth_does_not_block_healthy_account():
    async def run():
        blocked = asyncio.Event()
        class Slow(Identity):
            async def get(self):
                await blocked.wait()
                return await super().get()
        pool = AccountPool([Slow("Slow"), Identity("Healthy")])
        try:
            identity = await asyncio.wait_for(pool.get_for([], asyncio.Event()), .5)
            assert identity[0] == "Healthy"
        finally:
            pool.release()
            await pool.close()
    asyncio.run(run())


def test_priority_queue_orders_waiters_and_cleans_cancelled_requests():
    async def run():
        pool = AccountPool([Identity("Observer")])
        await pool.get_for([], asyncio.Event())
        order = []
        async def waiter(label, score):
            try:
                identity = await pool.get_for([], asyncio.Event(), lambda: score)
                assert identity[0] == "Observer"
                order.append(label)
            finally:
                pool.release()
        tasks = [asyncio.create_task(waiter("fresh", (1, -1, 1))),
                 asyncio.create_task(waiter("stale", (1, -100, 2))),
                 asyncio.create_task(waiter("target", (0, 0, 3)))]
        cancelled = asyncio.create_task(waiter("cancelled", (-1, 0, 0)))
        await asyncio.sleep(.02)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        pool.release()
        await asyncio.wait_for(asyncio.gather(*tasks), 2)
        assert order == ["target", "stale", "fresh"]
        assert not pool.waiting and not pool.busy
        await pool.close()
    asyncio.run(run())


def test_queue_priority_uses_target_staleness_and_top100(tmp_path, monkeypatch):
    monkeypatch.setattr("services.mycard_archive.collector.time.time", lambda: 1_000_000)
    c = Collector(ArchiveConfig(tmp_path, tmp_path/"primary"))
    def room(name, rank=200, seen=1):
        return RoomState({"id":name}, [name,"opponent"], first_seen=seen,
                         eligible=(name,), ranks={name:rank})
    c.latest_observed.update(fresh=1_000_000, stale=900_000,
                            target=1_000_000, top=1_000_000)
    c.tracked.add("target")
    assert c.queue_priority(room("target")) < c.queue_priority(room("missing"))
    assert c.queue_priority(room("missing")) < c.queue_priority(room("stale"))
    assert c.queue_priority(room("stale")) < c.queue_priority(room("fresh"))
    assert c.queue_priority(room("top", rank=10)) < c.queue_priority(room("fresh"))
    assert c.queue_priority(room("fresh", seen=1)) < c.queue_priority(room("fresh", seen=2))
    c.tracked.clear()
    assert c.queue_priority(room("target"))[0] == 1
    asyncio.run(c.close())


def test_last_observed_uses_actual_observation_time(tmp_path):
    from services.mycard_archive.store import ArchiveStore
    store = ArchiveStore(tmp_path)
    assert store.last_observed([]) == {}
    assert store.last_observed(["Alice", "Alice", "Unknown"]) == {}
    match, _ = store.begin({"id":"room"}, ["Alice","Bob"], {}, 100)
    with store.connect() as db:
        db.execute("INSERT INTO observations VALUES (?,?,?,?)", (match,"Alice",123,"{}"))
    assert store.last_observed(["Alice","Unknown"]) == {"Alice":123}


def test_pool_total_capacity_respects_lower_global_limit():
    async def run():
        pool = AccountPool([Identity("One"), Identity("Two")], capacity=1)
        await pool.get_for([], asyncio.Event())
        ended = asyncio.Event()
        waiter = asyncio.create_task(pool.get_for([], ended))
        await asyncio.sleep(.15)
        assert not waiter.done() and len(pool.busy) == 1
        ended.set()
        assert await waiter is None
        pool.release()
        await pool.close()
    asyncio.run(run())
