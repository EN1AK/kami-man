import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_rift_rag_qa import FakeBot,make_group_event
from plugins import group_chat as control
from plugins import ygo_rag_qa as qa
from services import unified_agent

@pytest.mark.parametrize('text',['群聊风格','群聊风格 查看','群聊风格 状态','群聊学习','群聊学习 状态'])
@pytest.mark.parametrize('group',[819151070,67890])
def test_status_commands_owned_by_control_not_persona(text,group,monkeypatch):
    bot=FakeBot();event=make_group_event(text,with_at=True);event.group_id=group
    dispatch=AsyncMock();monkeypatch.setattr(unified_agent,'handle_question',dispatch)
    assert asyncio.run(control.is_control(bot,event))
    assert not asyncio.run(qa.is_group_bot_mention(bot,event))
    asyncio.run(qa.handle_rag_qa(bot,event))
    dispatch.assert_not_awaited()
    assert control.control.priority<qa.rag_qa.priority and control.control.block


def test_other_group_status_does_not_access_allowed_group_data(monkeypatch):
    class Forbidden:
        def __getattr__(self,name):raise AssertionError('No cross-group state access')
    monkeypatch.setattr(control,'store',Forbidden())
    bot=FakeBot();event=make_group_event('群聊学习 状态',with_at=True)
    asyncio.run(control.handle_control(bot,event))
    assert len(bot.sent)==1 and '本群未启用' in str(bot.sent[0])


def test_enabled_group_style_returns_status_without_model(monkeypatch):
    monkeypatch.setattr(control,'store',SimpleNamespace(profile=lambda group:dict(summary='测试风格',source_count=200,new_count=5)))
    bot=FakeBot();event=make_group_event('群聊风格',with_at=True);event.group_id=819151070
    asyncio.run(control.handle_control(bot,event))
    assert '当前群聊风格' in str(bot.sent[0]) and '测试风格' in str(bot.sent[0])


def test_ordinary_style_discussion_still_routes_to_chat():
    event=make_group_event('你觉得群聊风格怎么样',with_at=True)
    assert not asyncio.run(control.is_control(FakeBot(),event))
    assert asyncio.run(qa.is_group_bot_mention(FakeBot(),event))
