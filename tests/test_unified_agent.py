import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from nonebot.adapters.onebot.v11 import Message
from services import unified_agent as unified
from services.ygo_rag_agent_api import YgoRagAgentResponse,AgentToolBlock,AGENT_TIMEOUT,AGENT_NETWORK_ERROR
from test_rift_rag_qa import FakeBot,make_group_event

def response(blocks=None):
    return YgoRagAgentResponse(answer="你好",warnings=[],exhausted=False,tool_blocks=blocks or [])
def test_chat_uses_isolated_session_and_plain_reply(monkeypatch):
    query=AsyncMock(return_value=response())
    monkeypatch.setattr(unified,"query_ygo_rag_agent",query)
    bot=FakeBot();event=make_group_event("你好")
    asyncio.run(unified.handle_question(bot,event,"你好"))
    assert str(bot.sent[0])=="你好" and bot.forward_calls==[]
    assert query.call_args.kwargs["session_id"]=="qq:12345:group:67890:user:111"
    other=SimpleNamespace(group_id=67891,user_id=111)
    assert unified.session_key(bot,event)!=unified.session_key(bot,other)
    other.user_id=112;other.group_id=67890
    assert unified.session_key(bot,event)!=unified.session_key(bot,other)

def test_only_quoted_bot_reply_is_used():
    bot=FakeBot()
    event=SimpleNamespace(reply=SimpleNamespace(sender=SimpleNamespace(user_id=12345),message=Message("阿狸 OGN-066")))
    assert unified.quoted_reply(bot,event)=="阿狸 OGN-066"
    event.reply.sender.user_id=999
    assert unified.quoted_reply(bot,event)==""

@pytest.mark.parametrize("error,expected",[(httpx.TimeoutException("slow"),AGENT_TIMEOUT),(httpx.ConnectError("down"),AGENT_NETWORK_ERROR)])
def test_shared_client_error_mapping(monkeypatch,error,expected):
    monkeypatch.setattr(unified,"query_ygo_rag_agent",AsyncMock(side_effect=error))
    bot=FakeBot()
    asyncio.run(unified.handle_question(bot,make_group_event("消息"),"消息"))
    assert bot.sent==[expected]

def test_rift_sources_and_ambiguity_survive_forwarding(monkeypatch):
    block=AgentToolBlock(tool="rift_rules",ok=True,summary="完成",result={"answer":"结论 [R-CR-1]","sources":[{"rule_id":"R-CR-1","topic":"来源"}],"coverage":{"unresolved_mentions":["未知卡"]},"exhausted":True})
    monkeypatch.setattr(unified,"query_ygo_rag_agent",AsyncMock(return_value=response([block])))
    bot=FakeBot();event=make_group_event("问题")
    asyncio.run(unified.handle_question(bot,event,"问题"))
    text="\n".join(str(node["data"]["content"]) for node in bot.forward_calls[0][1]["messages"])
    assert "R-CR-1" in text and "未知卡" in text and "部分证据" in text

def test_forward_failure_preserves_text(monkeypatch):
    block=AgentToolBlock(tool="rift_rules",ok=True,summary="完成",result={"answer":"裁定结论","sources":[]})
    monkeypatch.setattr(unified,"query_ygo_rag_agent",AsyncMock(return_value=response([block])))
    bot=FakeBot(forward_fails=True)
    asyncio.run(unified.handle_question(bot,make_group_event("问题"),"问题"))
    assert any("裁定结论" in str(message) for message in bot.sent)

def test_translation_entry_uses_same_dispatcher(monkeypatch):
    from plugins.ygo_rag_translate import handle_ygo_rag_translate
    handler=AsyncMock();monkeypatch.setattr(unified,"handle_question",handler)
    bot=FakeBot();event=make_group_event("@神人 翻译 hello")
    asyncio.run(handle_ygo_rag_translate(bot,event))
    assert handler.await_count==1 and "hello" in handler.call_args.args[2]
