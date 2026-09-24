import asyncio

import httpx
import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

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
        message = Message.segment.at(12345) + message
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
    for text in ("问规则 麦田圈在对方回合能发动吗", "规则 什么是迅捷", "问下规则 反制堆叠上限"):
        event = make_group_event(text)

        assert asyncio.run(is_group_rift_alias(FakeBot(), event)) is True


def test_group_alias_or_trigger_ignores_group_message_without_alias():
    event = make_group_event("今天符文战场怎么组卡")

    assert asyncio.run(is_group_rift_alias(FakeBot(), event)) is False


def test_group_alias_or_trigger_rejects_ygo_bot_mention():
    event = make_group_event("问规则 伤害怎么结算", with_at=True)

    assert asyncio.run(is_group_rift_alias(FakeBot(), event)) is False


def test_handler_gives_private_or_non_group_no_reply():
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, object()))

    assert bot.sent == []
    assert bot.forward_calls == []


def test_handler_empty_question_replies_fixed_text(monkeypatch):
    query, calls = fake_query()
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则")))

    assert bot.sent == [EMPTY_QUESTION_TEXT]
    assert calls == []


def test_handler_queries_service_and_forwards_nodes(monkeypatch):
    response = make_response(
        resolved_cards=[{"card_id": "OGN-242", "name_cn": "海兽钓钩"}],
    )
    query, calls = fake_query(response=response)
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()
    event = make_group_event("问规则 海兽钓钩的放逐怎么处理", card="群名片")

    asyncio.run(handle_rift_rag_qa(bot, event))

    assert calls == ["海兽钓钩的放逐怎么处理"]
    assert bot.sent == []
    assert len(bot.forward_calls) == 1
    api, kwargs = bot.forward_calls[0]
    assert api == "send_group_forward_msg"
    assert kwargs["group_id"] == 67890
    nodes = kwargs["messages"]
    assert nodes[0]["data"]["content"].startswith(
        "问题：海兽钓钩的放逐怎么处理\n识别卡牌：海兽钓钩（OGN-242）"
    )
    assert nodes[0]["data"]["name"] == "群名片"
    assert nodes[0]["data"]["uin"] == "111"
    assert nodes[-1]["data"]["content"].endswith(
        "回答生成自 http://127.0.0.1:7862"
    )


def test_handler_forwards_exhausted_response_normally(monkeypatch):
    response = make_response(answer="部分证据下的结论", exhausted=True)
    query, _ = fake_query(response=response)
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则 什么是迅捷")))

    assert len(bot.forward_calls) == 1
    question_node = bot.forward_calls[0][1]["messages"][0]["data"]["content"]
    assert "已达检索步数上限，答案基于部分证据" in question_node


def test_handler_maps_connection_failure(monkeypatch):
    query, _ = fake_query(error=httpx.ConnectError("down"))
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则 什么是迅捷")))

    assert bot.sent == [RIFT_QA_CONNECT_ERROR]


def test_handler_maps_timeout(monkeypatch):
    query, _ = fake_query(error=httpx.TimeoutException("slow"))
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则 什么是迅捷")))

    assert bot.sent == [RIFT_QA_TIMEOUT]


def test_handler_maps_internal_error(monkeypatch):
    query, _ = fake_query(
        error=httpx.HTTPStatusError(
            "bad",
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(500),
        )
    )
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则 什么是迅捷")))

    assert bot.sent == [RIFT_QA_INTERNAL_ERROR]


def test_handler_maps_empty_result(monkeypatch):
    query, _ = fake_query(error=ValueError(RIFT_QA_EMPTY_RESULT))
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot()

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则 什么是迅捷")))

    assert bot.sent == [RIFT_QA_EMPTY_RESULT]


def test_handler_falls_back_to_plain_messages_only_on_forward_failure(monkeypatch):
    query, _ = fake_query()
    monkeypatch.setattr(rift_qa, "query_rift_rag", query)
    bot = FakeBot(forward_fails=True)

    asyncio.run(handle_rift_rag_qa(bot, make_group_event("问规则 伤害怎么结算")))

    assert bot.sent[0] == FORWARD_FALLBACK_NOTICE
    forwarded = bot.forward_calls[0][1]["messages"]
    assert bot.sent[1:] == [node["data"]["content"] for node in forwarded]


def test_matcher_runs_below_commands_and_does_not_block():
    assert rift_rag_qa.priority > 1
    assert rift_rag_qa.block is False
