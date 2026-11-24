import asyncio
from types import SimpleNamespace

import pytest
from test_rift_rag_qa import FakeBot,make_group_event
from plugins import mycard_archive as entry
from services.mycard_archive import presentation as p


@pytest.mark.parametrize('value,expected',[(1531.1349,'1531.13 分'),(1500,'1500 分'),('1499.5','1499.5 分'),(None,'分数未知'),(True,'分数未知'),(float('nan'),'分数未知'),('bad','分数未知')])
def test_arena_score_format(value,expected):
    assert p.arena_score_text(value)==expected


def version():
    return dict(player='测试玩家',main=[26077387]*3,extra=[],side=[],first_seen=100,last_seen=1700000000,observations=12,match_id='INTERNAL-ARCHIVE-ID')


def test_top_entry_has_score_name_freshness_and_link_without_archive_noise(monkeypatch,tmp_path):
    monkeypatch.setattr(p,'classify',lambda *args:'闪刀')
    text=p.top_deck_entry(1,dict(username='测试玩家',pt=1531.1349),version(),tmp_path/'rules.json')
    assert text.startswith('1. 测试玩家｜1531.13 分')
    assert '卡组：闪刀' in text and '卡组更新：' in text and 'http://deck.ourygo.top/' in text
    assert all(s not in text for s in ['INTERNAL-ARCHIVE-ID','首次观察','同版本观察','Side 不完整','主卡 3','最近归档'])


def test_missing_deck_still_displays_score(tmp_path):
    text=p.top_deck_entry(2,dict(username='未收录',pt=1500),None,tmp_path/'rules.json')
    assert text=='2. 未收录｜1500 分\n暂无已采集卡组'


def test_top_command_preserves_leaderboard_score_and_forward_preview(monkeypatch,tmp_path):
    rows=[dict(username=f'玩家{i}',pt=1531.1349-i) for i in range(100)]
    class Response:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def raise_for_status(self):pass
        async def json(self):return rows
    class Session:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def get(self,*args,**kwargs):return Response()
    monkeypatch.setattr(entry.aiohttp,'ClientSession',Session)
    monkeypatch.setattr(entry,'library',lambda:SimpleNamespace(rules_path=tmp_path/'rules.json',latest=lambda name:None))
    bot=FakeBot();asyncio.run(entry.top_deck_info(bot,make_group_event('前排卡组信息')))
    api,payload=bot.forward_calls[0]
    assert api=='send_group_forward_msg' and len(payload['messages'])==100
    first=payload['messages'][0]['data']['content'].extract_plain_text()
    assert '1531.13 分' in first and '暂无已采集卡组' in first
    assert '分数' in payload['summary']
