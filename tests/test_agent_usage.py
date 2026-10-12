from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from services.agent_usage import UsageStore


def test_atomic_cap_with_concurrent_reservations(tmp_path):
    store=UsageStore(tmp_path/"usage.db")
    with ThreadPoolExecutor(max_workers=12) as pool:
        tickets=list(pool.map(lambda _:store.reserve(111),range(60)))
    assert sum(x is not None for x in tickets)==30
    assert store.personal(111)[1]==30
    assert store.reserve(112) is not None


def test_china_midnight_persistence_and_refund_original_day(tmp_path):
    path=tmp_path/"usage.db";store=UsageStore(path)
    before=datetime(2026,10,12,15,59,tzinfo=timezone.utc)
    after=datetime(2026,10,12,16,0,tzinfo=timezone.utc)
    tickets=[store.reserve(111,now=before) for _ in range(30)]
    assert store.reserve(111,now=before) is None
    restarted=UsageStore(path)
    assert restarted.personal(111,now=before)[1]==30
    assert restarted.reserve(111,now=after) is not None
    restarted.refund(tickets[0])
    assert restarted.personal(111,now=before)==("2026-10-12",29,1)
    assert restarted.personal(111,now=after)==("2026-10-13",1,0)
