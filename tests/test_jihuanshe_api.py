import asyncio
from unittest.mock import AsyncMock

import httpx
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


YGO_A = {'id': 1, 'cn_name': '原石A', 'jp_name': '原石A日文'}
YGO_B = {'id': 2, 'cn_name': '原石B', 'jp_name': '原石B日文'}


def test_fuzzy_ygo_search_requires_choice_before_market_lookup(monkeypatch):
    search = AsyncMock(return_value=[YGO_A, YGO_B, YGO_B])
    bridge = AsyncMock()
    monkeypatch.setattr(api, 'search_cards', search)
    monkeypatch.setattr(api, 'bridge_request', bridge)
    with pytest.raises(api.CardChoices) as result:
        asyncio.run(api.find_versions('原石', 'ygo', 'sc'))
    assert [card.password for card in result.value.candidates] == ['00000001', '00000002']
    search.assert_awaited_once_with('原石')
    bridge.assert_not_awaited()


@pytest.mark.parametrize('query', ['原石B', '00000002'])
def test_exact_ygo_name_or_password_wins_over_search_order(monkeypatch, query):
    monkeypatch.setattr(api, 'search_cards', AsyncMock(return_value=[YGO_A, YGO_B]))
    assert asyncio.run(api.resolve_ygo_card(query)) == YGO_B


class ChoiceEvent:
    self_id = 123
    def __init__(self, text='', session='group_1_5'):
        self.text = text
        self.session = session
    def get_session_id(self): return self.session
    def get_plaintext(self): return self.text


def market_rows(language='sc'):
    return [
        {'id': 10, 'card_id': 100, 'name_cn': '原石B', 'number': 'PACK-001', 'rarity': 'SR', 'game': 'ygo', 'language': language},
        {'id': 20, 'card_id': 100, 'name_cn': '原石B', 'number': 'PACK-002', 'rarity': 'UTR', 'game': 'ygo', 'language': language},
    ]


def test_choose_card_then_rarity_reuses_chosen_card_and_keeps_language(monkeypatch):
    search = AsyncMock(return_value=[YGO_A, YGO_B])
    bridge = AsyncMock(side_effect=[{'entries': market_rows()}, {'prices': [{'id': 20, 'game': 'ygo', 'language': 'sc', 'min_price': '4'}]}])
    monkeypatch.setattr(api, 'search_cards', search)
    monkeypatch.setattr(api, 'bridge_request', bridge)
    initial_finish = AsyncMock(side_effect=FinishedException)
    followup_finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(plugin.card_price, 'finish', initial_finish)
    monkeypatch.setattr(plugin.price_selection, 'finish', followup_finish)
    event = ChoiceEvent()
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_price(event, Message('原石 简中')))
    assert initial_finish.call_args.args[0].type == 'text'
    assert isinstance(plugin.pending[plugin.session_key(event)], plugin.CardSelection)
    event.text = '2'
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_selection(event))
    assert isinstance(plugin.pending[plugin.session_key(event)], plugin.Selection)
    assert '请选择罕贵' in followup_finish.call_args.args[0].data['text']
    event.text = 'UTR'
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_selection(event))
    text = followup_finish.call_args.args[0].data['text']
    assert '原石B' in text and '简中' in text and '¥4.00' in text
    search.assert_awaited_once_with('原石')
    assert bridge.await_args_list[0].args == ('/v1/versions', {'keyword': '原石B日文', 'game': 'ygo', 'language': 'sc'})
    assert bridge.await_args_list[1].args == ('/v1/prices', {'version_ids': [20], 'game': 'ygo', 'language': 'sc'})
    assert all(call.args[0].type == 'text' for call in followup_finish.call_args_list)
    assert plugin.session_key(event) not in plugin.pending


def test_card_password_reply_preserves_explicit_rarity(monkeypatch):
    monkeypatch.setattr(api, 'search_cards', AsyncMock(return_value=[YGO_A, YGO_B]))
    bridge = AsyncMock(side_effect=[{'entries': market_rows('en')}, {'prices': [{'id': 10, 'game': 'ygo', 'language': 'en', 'min_price': '7'}]}])
    monkeypatch.setattr(api, 'bridge_request', bridge)
    monkeypatch.setattr(plugin.card_price, 'finish', AsyncMock(side_effect=FinishedException))
    finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(plugin.price_selection, 'finish', finish)
    event = ChoiceEvent('00000002')
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_price(event, Message('原石 英文 SR')))
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_selection(event))
    text = finish.call_args.args[0].data['text']
    assert '英文' in text and '¥7.00' in text and '请选择罕贵' not in text
    assert bridge.await_args_list[1].args[1] == {'version_ids': [10], 'game': 'ygo', 'language': 'en'}
    assert plugin.session_key(event) not in plugin.pending


def test_card_choices_are_isolated_and_do_not_capture_unrelated_commands(monkeypatch):
    event = ChoiceEvent()
    choice = api.CardCandidate('原石B', '00000002', YGO_B)
    state = plugin.CardSelection(api.parse_query('原石 简中'), [choice], float('inf'))
    plugin.pending[plugin.session_key(event)] = state
    for text in ('1', '00000002', '原石B', '取消'):
        assert asyncio.run(plugin.awaiting_selection(ChoiceEvent(text)))
    for text in ('help', 'ck 青眼白龙', '历史', 'SR'):
        assert not asyncio.run(plugin.awaiting_selection(ChoiceEvent(text)))
    assert not asyncio.run(plugin.awaiting_selection(ChoiceEvent('1', 'group_2_5')))
    finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(plugin.price_selection, 'finish', finish)
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_selection(ChoiceEvent('99')))
    assert plugin.pending[plugin.session_key(event)] is state
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_selection(ChoiceEvent('取消')))
    assert not plugin.pending


def test_expired_card_choices_do_not_capture_replies(monkeypatch):
    event = ChoiceEvent('1')
    plugin.pending[plugin.session_key(event)] = plugin.CardSelection(api.parse_query('原石'), [api.CardCandidate('卡')], 10)
    monkeypatch.setattr(plugin.time, 'monotonic', lambda: 11)
    assert not asyncio.run(plugin.awaiting_selection(event))
    assert not plugin.pending


def test_fallback_market_choices_keep_version_groups_without_fake_passwords(monkeypatch):
    monkeypatch.setattr(api, 'search_cards', AsyncMock(side_effect=httpx.ConnectError('offline')))
    rows = market_rows()
    rows[1] = {**rows[1], 'card_id': 200, 'name_cn': '原石C'}
    monkeypatch.setattr(api, 'bridge_request', AsyncMock(return_value={'entries': rows}))
    with pytest.raises(api.CardChoices) as result:
        asyncio.run(api.find_versions('原石', 'ygo', 'sc'))
    candidates = result.value.candidates
    assert len(candidates) == 2
    assert candidates[0].entries == [rows[0]] and candidates[1].entries == [rows[1]]
    assert all(candidate.password is None for candidate in candidates)


def test_large_candidate_list_is_limited_and_marks_more(monkeypatch):
    cards = [{'id': i, 'cn_name': f'候选{i}', 'jp_name': f'候选{i}日文'} for i in range(1, 27)]
    monkeypatch.setattr(api, 'search_cards', AsyncMock(return_value=cards))
    with pytest.raises(api.CardChoices) as result:
        asyncio.run(api.resolve_ygo_card('候选'))
    assert result.value.more and len(result.value.candidates) == 25
    text = plugin.card_prompt(ChoiceEvent(), api.parse_query('候选'), result.value)
    assert '仅显示前25张' in text and '候选26' not in text
