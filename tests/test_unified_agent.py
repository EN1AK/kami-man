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
def test_professional_uses_isolated_session_and_plain_reply(monkeypatch):
    query=AsyncMock(return_value=response())
    monkeypatch.setattr(unified,"query_ygo_rag_agent",query)
    bot=FakeBot();event=make_group_event("你好")
    asyncio.run(unified.handle_question(bot,event,"你好"))
    assert str(bot.sent[0])=="你好" and bot.forward_calls==[]
    assert query.call_args.kwargs["session_id"]=="qq:12345:group:67890:user:111:professional"
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


@pytest.fixture(autouse=True)
def isolated_usage(monkeypatch,tmp_path):
    from services.agent_usage import UsageStore
    monkeypatch.setattr(unified,"usage_store",UsageStore(tmp_path/"usage.db"))
    monkeypatch.setattr(unified,"is_exempt",lambda uid:str(uid)=="2954452539")
    from services.mention_state import MentionState
    monkeypatch.setattr(unified,"route_state",MentionState(tmp_path/"routes.db"))
    monkeypatch.setattr(unified,"resolve_route",AsyncMock(return_value="professional"))
    monkeypatch.setattr(unified,"clear_sessions",AsyncMock())


def test_quota_blocks_31st_across_groups(monkeypatch):
    query=AsyncMock(return_value=response())
    monkeypatch.setattr(unified,"query_ygo_rag_agent",query)
    bot=FakeBot();event=make_group_event("你好")
    async def run():
        for i in range(31):
            event.group_id=67890+i
            await unified.handle_question(bot,event,"你好")
    asyncio.run(run())
    assert query.await_count==30
    assert "额度已用完" in str(bot.sent[-1])
    assert unified.usage_store.personal(111)[1]==30


def test_owner_is_unlimited_and_recorded(monkeypatch):
    query=AsyncMock(return_value=response());monkeypatch.setattr(unified,"query_ygo_rag_agent",query)
    bot=FakeBot();event=make_group_event("你好");event.user_id=2954452539
    async def run():
        for _ in range(31):await unified.handle_question(bot,event,"你好")
    asyncio.run(run())
    assert query.await_count==31
    assert unified.usage_store.personal(event.user_id)[1]==31


def test_failed_request_refunds_quota(monkeypatch):
    monkeypatch.setattr(unified,"query_ygo_rag_agent",AsyncMock(side_effect=httpx.ConnectError("down")))
    asyncio.run(unified.handle_question(FakeBot(),make_group_event("你好"),"你好"))
    assert unified.usage_store.personal(111)[1:]==(0,1)


def test_usage_commands_and_clear_are_free_and_stats_are_private(monkeypatch):
    query=AsyncMock(return_value=response());monkeypatch.setattr(unified,"query_ygo_rag_agent",query)
    bot=FakeBot();event=make_group_event("消息")
    async def run():
        for text in ["用量","用量统计","清空对话",""]:await unified.handle_question(bot,event,text)
        event.user_id=2954452539
        await unified.handle_question(bot,event,"用量统计")
    asyncio.run(run())
    assert query.await_count==0
    assert unified.usage_store.personal(111)[1]==0
    assert any("仅限管理员" in str(x) for x in bot.sent)
    assert "使用人数" in str(bot.sent[-1])


def test_card_image_only_uses_vision_and_shared_quota(monkeypatch):
    from nonebot.adapters.onebot.v11 import MessageSegment
    from plugins.ygo_rag_qa import handle_rag_qa
    vision = AsyncMock(return_value=SimpleNamespace(original_image="base64://test-card", translation="中文卡名：测试卡\n效果：抽一张卡。"))
    agent = AsyncMock()
    monkeypatch.setattr(unified, "translate_card_image", vision)
    monkeypatch.setattr(unified, "query_ygo_rag_agent", agent)
    event = make_group_event("", with_at=True)
    event.message += MessageSegment.image("https://example.com/card.jpg")
    bot = FakeBot()
    asyncio.run(handle_rag_qa(bot, event))
    assert vision.await_count == 1 and agent.await_count == 0
    assert "中文卡名：测试卡" in str(bot.sent[0])
    assert unified.usage_store.personal(111)[1] == 1


def test_translation_command_with_image_uses_vision(monkeypatch):
    from nonebot.adapters.onebot.v11 import MessageSegment
    from plugins.ygo_rag_translate import handle_ygo_rag_translate
    vision = AsyncMock(return_value=SimpleNamespace(original_image="base64://test-card", translation="中文卡名：测试卡\n效果：测试"))
    monkeypatch.setattr(unified, "translate_card_image", vision)
    event = make_group_event("@神人 翻译 ")
    event.message += MessageSegment.image("https://example.com/card.jpg")
    asyncio.run(handle_ygo_rag_translate(FakeBot(), event))
    assert vision.await_count == 1


def test_unreadable_card_refunds_and_multiple_images_are_free(monkeypatch):
    from nonebot.adapters.onebot.v11 import MessageSegment
    vision = AsyncMock(side_effect=unified.CardImageError("请重新发送清晰卡图。"))
    monkeypatch.setattr(unified, "translate_card_image", vision)
    event = make_group_event("", with_at=True)
    event.message += MessageSegment.image("https://example.com/card.jpg")
    bot = FakeBot()
    asyncio.run(unified.handle_question(bot, event, ""))
    assert unified.usage_store.personal(111)[1:] == (0, 1)
    assert "清晰卡图" in str(bot.sent[-1])
    event.message += MessageSegment.image("https://example.com/second.jpg")
    asyncio.run(unified.handle_question(bot, event, ""))
    assert vision.await_count == 1
    assert "每次发送一张" in str(bot.sent[-1])


def test_card_image_obeys_daily_limit(monkeypatch):
    from nonebot.adapters.onebot.v11 import MessageSegment
    vision = AsyncMock()
    monkeypatch.setattr(unified, "translate_card_image", vision)
    for _ in range(unified.DAILY_LIMIT):
        unified.usage_store.reserve(111)
    event = make_group_event("", with_at=True)
    event.message += MessageSegment.image("https://example.com/card.jpg")
    bot = FakeBot()
    asyncio.run(unified.handle_question(bot, event, ""))
    assert vision.await_count == 0 and "额度已用完" in str(bot.sent[-1])
