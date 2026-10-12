import asyncio

import httpx
import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

nonebot.init()

from nonebot.adapters.onebot.v11.event import Sender

import plugins.rift_rag_qa as rift_qa
from plugins.rift_rag_qa import (
    EMPTY_QUESTION_TEXT,
    FORWARD_FALLBACK_NOTICE,
    handle_rift_rag_qa,
    is_group_rift_alias,
    rift_rag_qa,
)
from services.qa_common import (
    RIFT_QA_CONNECT_ERROR,
    RIFT_QA_EMPTY_RESULT,
    RIFT_QA_INTERNAL_ERROR,
    RIFT_QA_TIMEOUT,
)
from services.rift_rag_api import RagSource, RiftRagResponse


class FakeBot:
    self_id = 12345

    def __init__(self, *, forward_fails=False):
        self.sent = []
        self.forward_calls = []
        self.forward_fails = forward_fails

    async def send(self, event, message):
        self.sent.append(message)

    async def call_api(self, api, **kwargs):
        self.forward_calls.append((api, kwargs))
        if self.forward_fails:
            raise RuntimeError("forward failed")


def make_group_event(text: str, *, with_at: bool = False, card: str = "") -> GroupMessageEvent:
    message = Message(text)
    if with_at:
        message = MessageSegment.at(12345) + message
    return GroupMessageEvent(
        time=0,
        self_id=12345,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        group_id=67890,
        user_id=111,
        message=message,
        original_message=message,
        raw_message=str(message),
        font=0,
        sender=Sender(user_id=111, nickname="tester", card=card),
    )


def make_response(**overrides) -> RiftRagResponse:
    defaults = {
        "answer": "结论 [R-CR-465.2]",
        "warnings": [],
        "sources": [RagSource(rule_id="R-CR-465.2", topic="465.2 Step 2")],
    }
    defaults.update(overrides)
    return RiftRagResponse(**defaults)


def fake_query(response=None, error=None):
    calls = []

    async def _query(question, settings=None):
        calls.append(question)
        if error is not None:
            raise error
        return response if response is not None else make_response()

    return _query, calls


def test_group_alias_or_trigger_rejects_non_group_event():
    triggered = asyncio.run(is_group_rift_alias(FakeBot(), object()))

    assert triggered is False


def test_group_alias_or_trigger_accepts_group_alias_messages():
    for text in ("符文规则 麦田圈在对方回合能发动吗", "符文裁定 什么是迅捷", "符文裁定 反制堆叠上限"):
        event = make_group_event(text)

        assert asyncio.run(is_group_rift_alias(FakeBot(), event)) is True


def test_group_alias_or_trigger_ignores_group_message_without_alias():
    event = make_group_event("今天符文战场怎么组卡")

    assert asyncio.run(is_group_rift_alias(FakeBot(), event)) is False


def test_group_alias_or_trigger_rejects_ygo_bot_mention():
    event = make_group_event("符文裁定 伤害怎么结算", with_at=True)

    assert asyncio.run(is_group_rift_alias(FakeBot(), event)) is False


def test_handler_gives_private_or_non_group_no_reply():
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, object()))

    assert bot.sent == []
    assert bot.forward_calls == []


def test_alias_handler_delegates_to_unified_agent(monkeypatch):
    import services.unified_agent as unified
    from unittest.mock import AsyncMock
    handler=AsyncMock()
    monkeypatch.setattr(unified,"handle_question",handler)
    bot=FakeBot()
    event=make_group_event("符文规则 海兽钓钩的放逐怎么处理")
    asyncio.run(handle_rift_rag_qa(bot,event))
    handler.assert_awaited_once_with(bot,event,"符文战场规则：海兽钓钩的放逐怎么处理")

def test_empty_alias_delegates_empty_request(monkeypatch):
    import services.unified_agent as unified
    from unittest.mock import AsyncMock
    handler=AsyncMock()
    monkeypatch.setattr(unified,"handle_question",handler)
    bot=FakeBot();event=make_group_event("符文裁定")
    asyncio.run(handle_rift_rag_qa(bot,event))
    handler.assert_awaited_once_with(bot,event,"")
