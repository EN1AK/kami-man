import asyncio

import nonebot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

nonebot.init()

from nonebot.adapters.onebot.v11.event import Sender

from plugins.rift_rag_qa import is_group_rift_alias, rift_rag_qa


class FakeBot:
    self_id = 12345


def make_group_event(text: str, *, with_at: bool = False) -> GroupMessageEvent:
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
        sender=Sender(user_id=111, nickname="tester"),
    )


def test_rule_rejects_non_group_event():
    event = make_group_event("符文规则 伤害怎么结算")

    triggered = asyncio.run(is_group_rift_alias(FakeBot(), object()))

    assert triggered is False
    assert isinstance(event, GroupMessageEvent)


def test_rule_accepts_group_alias_message():
    event = make_group_event("符文规则 伤害怎么结算")

    triggered = asyncio.run(is_group_rift_alias(FakeBot(), event))

    assert triggered is True


def test_rule_ignores_group_message_without_alias():
    event = make_group_event("今天符文战场怎么组卡")

    triggered = asyncio.run(is_group_rift_alias(FakeBot(), event))

    assert triggered is False


def test_rule_rejects_ygo_bot_mention_even_with_alias_text():
    event = make_group_event("符文规则 伤害怎么结算", with_at=True)

    triggered = asyncio.run(is_group_rift_alias(FakeBot(), event))

    assert triggered is False


def test_matcher_runs_below_commands_and_does_not_block():
    assert rift_rag_qa.priority > 1
    assert rift_rag_qa.block is False
