import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import PrivateMessageEvent,Message,MessageSegment
from nonebot.adapters.onebot.v11.event import Sender
from test_rift_rag_qa import FakeBot,make_group_event
from plugins import admin_private_chat as entry
from services import unified_agent as u
from services.mention_state import MentionState
from services.agent_usage import UsageStore
from services.group_chat_client import GroupReply
from services.ygo_rag_agent_api import YgoRagAgentResponse,AgentToolBlock


def private(text='你好',user=111):
    return PrivateMessageEvent(time=0,self_id=12345,post_type='message',message_type='private',sub_type='friend',message_id=1,user_id=user,message=Message(text),original_message=Message(text),raw_message=text,font=0,sender=Sender(user_id=user,nickname='test'))


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(u,'route_state',MentionState(tmp_path/'routes.db'))
    monkeypatch.setattr(u,'usage_store',UsageStore(tmp_path/'usage.db'))
    monkeypatch.setattr(u,'is_exempt',lambda user:user==111)
    monkeypatch.setattr(entry,'is_exempt',lambda user:user==111)
    monkeypatch.setattr(u,'private_memes',SimpleNamespace(categories=lambda user:[],reserve=lambda *args:None))
    def forbidden(*args):raise AssertionError('Private chat must never read group style')
    monkeypatch.setattr(u,'style_context',forbidden)
    monkeypatch.setattr(u,'resolve_route',AsyncMock(return_value='casual'))
    monkeypatch.setattr(u,'request_casual',AsyncMock(return_value=GroupReply('私聊回复')))


def test_admin_private_matches_without_at_and_other_users_do_not(monkeypatch):
    bot=FakeBot();dispatch=AsyncMock();monkeypatch.setattr(u,'handle_question',dispatch)
    assert asyncio.run(entry.is_admin_private(bot,private()))
    assert not asyncio.run(entry.is_admin_private(bot,private(user=222)))
    assert not asyncio.run(entry.is_admin_private(bot,make_group_event('你好')))
    asyncio.run(entry.handle_admin_private(bot,private('你好')))
    assert dispatch.call_args.args[2]=='你好'
    dispatch.reset_mock()
    asyncio.run(entry.handle_admin_private(bot,private(user=222)))
    dispatch.assert_not_awaited()


def test_dispatcher_rejects_nonadmin_before_quota_or_model():
    bot=FakeBot();event=private(user=222)
    asyncio.run(u.handle_question(bot,event,'你好'))
    u.resolve_route.assert_not_awaited();u.request_casual.assert_not_awaited()
    assert bot.sent==[] and not u.usage_store.path.exists()


def test_private_casual_has_independent_session_and_no_group_style():
    bot=FakeBot();event=private();key=u.session_key(bot,event)
    assert key=='qq:12345:private:user:111'
    assert key!=u.session_key(bot,make_group_event('你好'))
    asyncio.run(u.handle_question(bot,event,'你好'))
    assert u.request_casual.call_args.args[:5]==(None,key,'你好','',[])
    assert u.route_state.metadata(key,'私聊回复')[1]=='casual'
    assert len(bot.sent)==1


def test_private_structured_professional_uses_plain_private_messages(monkeypatch):
    monkeypatch.setattr(u,'resolve_route',AsyncMock(return_value='professional'))
    block=AgentToolBlock(tool='rift_rules',ok=True,summary='规则',result={'answer':'专业答案','sources':[]})
    query=AsyncMock(return_value=YgoRagAgentResponse(answer='专业答案',warnings=[],exhausted=False,tool_blocks=[block]))
    monkeypatch.setattr(u,'query_ygo_rag_agent',query)
    bot=FakeBot();asyncio.run(u.handle_question(bot,private('规则 测试'),'规则 测试'))
    assert query.call_args.kwargs['session_id']=='qq:12345:private:user:111:professional'
    assert bot.sent and bot.forward_calls==[]
    u.request_casual.assert_not_awaited()


def test_private_image_keeps_original_translation_path(monkeypatch):
    translate=AsyncMock(return_value=SimpleNamespace(translation='中文卡名效果',original_image='base64://test'))
    monkeypatch.setattr(u,'translate_card_image',translate)
    event=private('');event.message+=MessageSegment.image('https://example.com/card.jpg')
    bot=FakeBot();asyncio.run(u.handle_question(bot,event,''))
    assert [s.type for s in bot.sent[0]]==['image','text']
    u.resolve_route.assert_not_awaited();u.request_casual.assert_not_awaited()


def test_private_clear_only_targets_private_scope(monkeypatch):
    clear=AsyncMock();monkeypatch.setattr(u,'clear_sessions',clear)
    bot=FakeBot();event=private('清空对话');groupkey=u.session_key(bot,make_group_event('群消息'))
    u.route_state.record(groupkey,'casual','群聊回复')
    asyncio.run(u.handle_question(bot,event,'清空对话'))
    clear.assert_awaited_once_with('qq:12345:private:user:111')
    assert u.route_state.metadata(groupkey,'群聊回复')[1]=='casual'
    assert not u.usage_store.path.exists()


def test_private_meme_uses_private_recipient_counter(monkeypatch):
    used=[]
    monkeypatch.setattr(u,'private_memes',SimpleNamespace(categories=lambda user:[],reserve=lambda user,category:(used.append((user,category)) or SimpleNamespace(image='base64://test'))))
    monkeypatch.setattr(u,'request_casual',AsyncMock(return_value=GroupReply('私聊表情','happy')))
    bot=FakeBot();asyncio.run(u.handle_question(bot,private(),'你好'))
    assert used==[(111,'happy')]
    assert [s.type for s in bot.sent[0]]==['text','image']


def test_private_group_controls_never_call_persona(monkeypatch):
    dispatch=AsyncMock();monkeypatch.setattr(u,'handle_question',dispatch)
    bot=FakeBot();asyncio.run(entry.handle_admin_private(bot,private('群聊风格')))
    dispatch.assert_not_awaited()
    assert '群内' in str(bot.sent[0])



def test_private_short_multiline_reply_sends_separately(monkeypatch):
    monkeypatch.setattr(u,'request_casual',AsyncMock(return_value=GroupReply('第一段。\n\n第二段。')))
    monkeypatch.setattr(u.asyncio,'sleep',AsyncMock())
    bot=FakeBot();asyncio.run(u.handle_question(bot,private(),'你好'))
    assert [m.extract_plain_text().strip() for m in bot.sent]==['第一段。','第二段。']
