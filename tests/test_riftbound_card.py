import asyncio
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message
from nonebot.exception import FinishedException

nonebot.init()
import plugins.riftbound_card as plugin


def finish_capture(monkeypatch, matcher):
    finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(matcher, "finish", finish)
    return finish


def test_single_command_returns_candidates_without_image(monkeypatch):
    cards = [{"card_key": "OGN-066", "name_cn": "阿狸", "sub_title_cn": "嫣然狐媚", "match_kind": "fuzzy", "editions": [{}]}]
    monkeypatch.setattr(plugin, "lookup", AsyncMock(return_value=cards))
    image = AsyncMock()
    monkeypatch.setattr(plugin, "build_card_message", image)
    finish = finish_capture(monkeypatch, plugin.rb)
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_rb(Message("阿理")))
    assert "相近卡片" in str(finish.call_args.args[0])
    image.assert_not_called()


def test_single_command_returns_selected_card(monkeypatch):
    card = {"match_kind": "exact"}
    monkeypatch.setattr(plugin, "lookup", AsyncMock(return_value=[card]))
    build = AsyncMock(return_value=Message("卡片信息"))
    monkeypatch.setattr(plugin, "build_card_message", build)
    finish = finish_capture(monkeypatch, plugin.rb)
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_rb(Message("OGN-066")))
    build.assert_awaited_once_with(card)
    assert str(finish.call_args.args[0]) == "卡片信息"


@pytest.mark.parametrize("result,expected", [(None, "卡库暂不可用"), ([], "未找到卡片")])
def test_database_failure_and_no_match(monkeypatch, result, expected):
    monkeypatch.setattr(plugin, "lookup", AsyncMock(return_value=result))
    finish = finish_capture(monkeypatch, plugin.rb)
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_rb(Message("查找")))
    assert expected in str(finish.call_args.args[0])


def test_empty_command_does_not_search(monkeypatch):
    lookup = AsyncMock()
    monkeypatch.setattr(plugin, "lookup", lookup)
    finish = finish_capture(monkeypatch, plugin.rb)
    with pytest.raises(FinishedException):
        asyncio.run(plugin.handle_rb(Message("")))
    assert "请输入" in str(finish.call_args.args[0])
    lookup.assert_not_called()


def test_batch_is_limited_and_uses_forward(monkeypatch):
    cards = [{"match_kind": "partial", "number": n} for n in range(11)]
    monkeypatch.setattr(plugin, "lookup", AsyncMock(return_value=cards))
    build = AsyncMock(side_effect=lambda card, client: Message(str(card["number"])))
    monkeypatch.setattr(plugin, "build_card_message", build)
    forward = AsyncMock()
    monkeypatch.setattr(plugin, "send_forward_msg", forward)
    asyncio.run(plugin.handle_rb_pl(object(), object(), Message("阿狸")))
    assert build.await_count == 10
    messages = forward.call_args.args[2]
    assert len(messages) == 11 and "前10种" in str(messages[0])
    assert [str(message) for message in messages[1:]] == list(map(str, range(10)))


def test_image_failure_keeps_text_and_text_is_not_cq_code(monkeypatch):
    monkeypatch.setattr(plugin, "card_image", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(plugin, "format_riftbound_card", lambda card: "文本 [CQ:at,qq=all]")
    message = asyncio.run(plugin.build_card_message({}))
    assert "卡图暂不可用" in message.extract_plain_text()
    assert all(segment.type == "text" for segment in message)
