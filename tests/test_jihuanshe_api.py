import asyncio
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.exception import FinishedException
from nonebot.adapters.onebot.v11 import Message

from services import jihuanshe_api as api

nonebot.init()
import plugins.card_price as plugin


@pytest.fixture(autouse=True)
def clear_pending():
    plugin.pending.clear()
    yield
    plugin.pending.clear()


def test_same_user_selections_do_not_cross_chats():
    class Event:
        self_id = 123
        def __init__(self, session): self.session = session
        def get_session_id(self): return self.session
        def get_plaintext(self): return '1'
    plugin.pending[plugin.session_key(Event('group_1_5'))] = plugin.Selection('卡', [('SR', [])], float('inf'))
    assert asyncio.run(plugin.awaiting_selection(Event('group_1_5')))
    assert not asyncio.run(plugin.awaiting_selection(Event('group_2_5')))
    assert not asyncio.run(plugin.awaiting_selection(Event('group_1_6')))


def test_expired_selection_does_not_capture_messages(monkeypatch):
    class Event:
        self_id = 123
        def get_session_id(self): return 'group_1_5'
        def get_plaintext(self): return '1'
    event = Event()
    plugin.pending[plugin.session_key(event)] = plugin.Selection('卡', [('SR', [])], 10)
    monkeypatch.setattr(plugin.time, 'monotonic', lambda: 11)
    assert not asyncio.run(plugin.awaiting_selection(event))
    assert not plugin.pending


def test_search_filters_card_sleeves_and_deduplicates_versions(monkeypatch):
    card = {'cn_name': '原石之皇脉', 'jp_name': '原石の皇脈'}
    monkeypatch.setattr(api, 'search_cards', AsyncMock(return_value=[card]))
    valid = {'id': 504446, 'card_id': 16724, 'name_cn': '原石之皇脉', 'number': 'LOCR-JP076', 'rarity': 'UTR'}
    request = AsyncMock(return_value={'entries': [valid, valid, {**valid, 'id': 2, 'name_cn': '原石之皇脉卡套'}]})
    monkeypatch.setattr(api, 'bridge_request', request)
    name, entries = asyncio.run(api.find_versions('原石之皇脉'))
    assert name == '原石之皇脉' and entries == [valid]
    request.assert_awaited_once_with('/v1/versions', {'name_jp': '原石の皇脈'})


def test_zero_price_is_preserved_and_versions_remain_separate(monkeypatch):
    entries = [{'id': 1, 'number': 'PACK-JP001', 'rarity': 'SR'}, {'id': 2, 'number': 'OTHER-JP001', 'rarity': 'SR'}]
    monkeypatch.setattr(api, 'bridge_request', AsyncMock(return_value={'prices': [{'id': 1, 'min_price': '0', 'market_price': None}, {'id': 2, 'error': True}]}))
    message = asyncio.run(api.price_message('卡', entries))
    assert '最低价：¥0.00' in message and '集换价：暂无' in message
    assert 'PACK-JP001' in message and 'OTHER-JP001' in message and '价格暂不可用' in message


def test_price_error_is_sent_as_literal_text(monkeypatch):
    monkeypatch.setattr(plugin, 'find_versions', AsyncMock(side_effect=api.PriceError('[CQ:at,qq=all]')))
    finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(plugin.card_price, 'finish', finish)
    class Event:
        self_id = 123
        def get_session_id(self): return 'private_5'
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_price(Event(), Message('青眼白龙')))
    assert finish.call_args.args[0].type == 'text'


def test_rarity_number_and_name_select_same_versions():
    groups = [('SR', [{'id': 1}, {'id': 2}]), ('UTR', [{'id': 3}])]
    assert api.select_rarity(groups, '1') == api.select_rarity(groups, 'sr')
    assert api.select_rarity(groups, '0') is None
    assert api.select_rarity(groups, '3') is None