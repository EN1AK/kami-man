"""Capacity scans cannot starve unrelated mention work in the default pool."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

import pytest
from services.mycard_archive.collector import Collector,ArchiveConfig


def test_capacity_burst_single_flight_does_not_starve_default_pool(tmp_path):
    async def run():
        started,release=threading.Event(),threading.Event()
        calls=[]
        def scan():
            calls.append(1);started.set()
            assert release.wait(5)
            return True
        c=Collector(ArchiveConfig(tmp_path,tmp_path/'missing'),store=SimpleNamespace(capture_available=scan))
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        pending=[asyncio.create_task(c.capacity_available()) for _ in range(100)]
        try:
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.01)
            assert started.is_set()
            # The same pool needed by quota/style lookup must remain available.
            assert await asyncio.wait_for(asyncio.to_thread(lambda:'mention-ready'),1)=='mention-ready'
            pending[0].cancel()
            with pytest.raises(asyncio.CancelledError):await pending[0]
            release.set()
            assert all(await asyncio.gather(*pending[1:]))
            assert len(calls)==1
            assert await c.capacity_available()
            assert len(calls)==1
            c.capacity_checked_at-=6
            assert await c.capacity_available()
            assert len(calls)==2
        finally:
            release.set()
            await c.close()
    asyncio.run(run())


def test_capacity_error_is_not_cached_as_permission(tmp_path):
    async def run():
        calls=[]
        def scan():
            calls.append(1)
            if len(calls)==1:raise OSError('scan failed')
            return False
        c=Collector(ArchiveConfig(tmp_path,tmp_path/'missing'),store=SimpleNamespace(capture_available=scan))
        try:
            with pytest.raises(OSError):await c.capacity_available()
            assert c.capacity_checked_at is None
            assert await c.capacity_available() is False
            assert len(calls)==2
        finally:await c.close()
    asyncio.run(run())
