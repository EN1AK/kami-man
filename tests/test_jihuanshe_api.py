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
    valid = {'id': 504446, 'card_id': 16724, 'name_cn': '原石之皇脉', 'number': 'LOCR-JP076', 'rarity': 'UTR', 'game': 'ygo', 'language': 'jp'}
    request = AsyncMock(return_value={'entries': [valid, valid, {**valid, 'id': 2, 'name_cn': '原石之皇脉卡套'}]})
    monkeypatch.setattr(api, 'bridge_request', request)
    name, entries = asyncio.run(api.find_versions('原石之皇脉'))
    assert name == '原石之皇脉' and entries == [valid]
    request.assert_awaited_once_with('/v1/versions', {'keyword': '原石の皇脈', 'game': 'ygo', 'language': 'jp'})


def test_zero_price_is_preserved_and_versions_remain_separate(monkeypatch):
    entries = [{'id': 1, 'number': 'PACK-JP001', 'rarity': 'SR', 'game': 'ygo', 'language': 'jp'}, {'id': 2, 'number': 'OTHER-JP001', 'rarity': 'SR', 'game': 'ygo', 'language': 'jp'}]
    monkeypatch.setattr(api, 'bridge_request', AsyncMock(return_value={'prices': [{'id': 1, 'game': 'ygo', 'language': 'jp', 'min_price': '0', 'market_price': None}, {'id': 2, 'error': True}]}))
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


def test_rarity_prompt_does_not_capture_other_commands():
    class Event:
        self_id = 123
        def __init__(self, text): self.text = text
        def get_session_id(self): return 'private_5'
        def get_plaintext(self): return self.text
    plugin.pending[plugin.session_key(Event(''))] = plugin.Selection('卡', [('SR', []), ('UTR', [])], float('inf'))
    for text in ('help', '历史', 'ck 青眼白龙', 'hello', 'UR'):
        assert not asyncio.run(plugin.awaiting_selection(Event(text)))
    for text in ('sr', 'UTR', '1', '取消'):
        assert asyncio.run(plugin.awaiting_selection(Event(text)))


@pytest.mark.parametrize('text,default_game,name,rarity,game,language', [
    ('原石之皇脉 简中 SR', 'ygo', '原石之皇脉', 'SR', 'ygo', 'sc'),
    ('日文 原石之皇脉 UTR', 'ygo', '原石之皇脉', 'UTR', 'ygo', 'jp'),
    ('原石之皇脉 UTR', 'ygo', '原石之皇脉', 'UTR', 'ygo', 'jp'),
    ('符文 OGN-119 英文', 'ygo', 'OGN-119', None, 'riftbound', 'en'),
    ('OGN-119', 'riftbound', 'OGN-119', None, 'riftbound', 'sc'),
    ('阿狸, 天真绮梦 异画（签名） 繁中', 'riftbound', '阿狸, 天真绮梦', '异画(签名)', 'riftbound', 'tc'),
])
def test_parse_game_language_and_rarity(text, default_game, name, rarity, game, language):
    assert api.parse_query(text, default_game) == api.PriceQuery(name, rarity, game, language)


def test_reject_conflicting_or_unsupported_languages():
    with pytest.raises(api.PriceError):
        api.parse_query('原石 简中 日文')
    with pytest.raises(api.PriceError):
        api.parse_query('阿狸 日文', 'riftbound')


def test_rift_code_excludes_other_editions_and_accessories(monkeypatch):
    monkeypatch.setattr(api, 'search_cards', AsyncMock(side_effect=AssertionError('Wrong game lookup')))
    base = {'id': 280, 'card_id': 263, 'name_cn': '阿狸, 天真绮梦', 'number': 'OGN·119/298·TC', 'rarity': '史诗', 'object_type': 'card', 'game': 'riftbound', 'language': 'tc'}
    request = AsyncMock(return_value={'entries': [base, {**base, 'id': 281, 'number': 'OGN·119a/298·TC'}, {**base, 'id': 1, 'object_type': 'goods'}]})
    monkeypatch.setattr(api, 'bridge_request', request)
    name, rows = asyncio.run(api.find_versions('OGN-119', 'riftbound', 'tc'))
    assert rows == [base] and name == '阿狸, 天真绮梦'
    request.assert_awaited_once_with('/v1/versions', {'keyword': 'OGN-119', 'game': 'riftbound', 'language': 'tc'})


def test_rift_subtitle_fallback_without_card_database(monkeypatch):
    monkeypatch.setattr(api, 'search_riftbound_cards', lambda *args: (_ for _ in ()).throw(FileNotFoundError()))
    base = {'id': 280, 'card_id': 263, 'name_cn': '阿狸, 天真绮梦', 'number': 'OGN·119/298', 'object_type': 'card', 'game': 'riftbound', 'language': 'sc'}
    request = AsyncMock(side_effect=[{'entries': [{**base, 'id': 9, 'object_type': 'goods'}]}, {'entries': [base, {**base, 'id': 66, 'card_id': 95, 'name_cn': '阿狸, 嫣然狐媚'}]}])
    monkeypatch.setattr(api, 'bridge_request', request)
    _, rows = asyncio.run(api.find_versions('阿狸 天真绮梦', 'riftbound', 'sc'))
    assert rows == [base] and request.await_args_list[1].args[1]['keyword'] == '阿狸'


def test_reject_versions_from_a_different_language(monkeypatch):
    monkeypatch.setattr(api, 'search_cards', AsyncMock(return_value=[]))
    monkeypatch.setattr(api, 'bridge_request', AsyncMock(return_value={'entries': [{'id': 1, 'game': 'ygo', 'language': 'jp'}]}))
    with pytest.raises(api.PriceError, match='语种不符'):
        asyncio.run(api.find_versions('卡', 'ygo', 'sc'))


def test_rift_rarity_reply_keeps_original_language(monkeypatch):
    entries = [{'id': 1, 'rarity': '史诗'}, {'id': 2, 'rarity': '异画'}]
    lookup = AsyncMock(return_value=('阿狸', entries))
    monkeypatch.setattr(plugin, 'find_versions', lookup)
    monkeypatch.setattr(plugin.rift_price, 'finish', AsyncMock(side_effect=FinishedException))
    monkeypatch.setattr(plugin.price_selection, 'finish', AsyncMock(side_effect=FinishedException))
    price = AsyncMock(return_value='价格')
    monkeypatch.setattr(plugin, 'price_message', price)
    class Event:
        self_id = 123
        def get_session_id(self): return 'group_1_5'
        def get_plaintext(self): return '异画'
    event = Event()
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_rift_price(event, Message('阿狸 英文')))
    lookup.assert_awaited_once_with('阿狸', 'riftbound', 'en')
    assert plugin.pending[plugin.session_key(event)].language == 'en'
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_selection(event))
    price.assert_awaited_once_with('阿狸', [entries[1]], 'riftbound', 'en')


def test_wrong_language_prices_are_not_displayed(monkeypatch):
    entries = [{'id': 1, 'number': 'OGN·119', 'rarity': '史诗', 'game': 'riftbound', 'language': 'en'}]
    monkeypatch.setattr(api, 'bridge_request', AsyncMock(return_value={'prices': [{'id': 1, 'game': 'riftbound', 'language': 'sc', 'min_price': '999'}]}))
    text = asyncio.run(api.price_message('阿狸', entries, 'riftbound', 'en'))
    assert '英文' in text and '999' not in text and '价格暂不可用' in text
