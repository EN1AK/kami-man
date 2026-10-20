import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nonebot
nonebot.init()
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from services import group_chat_client as client
from services.group_chat_store import DAILY_LIMIT, COOLDOWN_SECONDS, RETENTION_SECONDS
from services.group_learning import GroupLearningStore as GroupChatStore
from test_rift_rag_qa import FakeBot, make_group_event

GROUP = 819151070
NOW = 1700000000


def event(text="这牌也太离谱了", mid=1):
    value = make_group_event(text)
    value.group_id = GROUP
    value.message_id = mid
    return value


def test_only_enabled_group_is_stored_and_deduplicated(tmp_path):
    store = GroupChatStore(tmp_path/"samples.db")
    assert not store.record(123, 1, 111, "其他群", NOW)
    assert not store.path.exists()
    assert store.record(GROUP, 1, 111, "测试样本", NOW)
    assert not store.record(GROUP, 1, 111, "重复事件", NOW)
    assert store.status(GROUP, NOW)["count"] == 1
    recent, _ = store.context(GROUP, NOW)
    assert recent == [{"speaker": "成员1", "text": "测试样本"}]


@pytest.mark.parametrize("text", ["@神人 你好", "/ck 黑魔术师", "查卡 黑魔术师", "我的手机号13800138000", "https://example.com", "邮箱 x@y.com", "密码: secret", "[CQ:at,qq=1]", "x"*501])
def test_commands_and_private_text_are_not_collected(text):
    assert client.clean_text(event(text), 12345) is None


def test_nontext_and_bot_messages_are_not_collected():
    value = event()
    value.message += MessageSegment.image("https://example.com/a.jpg")
    assert client.clean_text(value, 12345) is None
    value = event(); value.user_id = 12345
    assert client.clean_text(value, 12345) is None


def test_atomic_limits_survive_restart_and_day_rollover(tmp_path):
    store = GroupChatStore(tmp_path/"samples.db")
    with ThreadPoolExecutor(max_workers=4) as pool:
        tickets = list(pool.map(lambda _: store.reserve(GROUP, NOW), range(4)))
    assert sum(ticket is not None for ticket in tickets) == 1
    assert GroupChatStore(store.path).reserve(GROUP, NOW+1) is None
    for index in range(1, DAILY_LIMIT):
        assert store.reserve(GROUP, NOW+index*COOLDOWN_SECONDS) is not None
    assert store.reserve(GROUP, NOW+DAILY_LIMIT*COOLDOWN_SECONDS) is None
    assert store.reserve(GROUP, NOW+86400) is not None


def test_retention_limit_and_switches(tmp_path, monkeypatch):
    import services.group_chat_store as module
    monkeypatch.setattr(module, "MAX_MESSAGES", 2)
    store = GroupChatStore(tmp_path/"samples.db")
    store.record(GROUP, 0, 111, "已过期", NOW-RETENTION_SECONDS-1)
    for index in range(1, 4):
        store.record(GROUP, index, 111, "近期样本", NOW)
    assert store.status(GROUP, NOW)["count"] == 2
    store.configure(GROUP, "collect_off", NOW)
    assert not store.record(GROUP, 9, 111, "不采集", NOW)
    assert store.reserve(GROUP, NOW) is None
    store.configure(GROUP, "clear", NOW)
    assert store.status(GROUP, NOW)["count"] == 0


def test_proactive_reply_uses_only_group_samples_and_is_throttled(tmp_path, monkeypatch):
    store = GroupChatStore(tmp_path/"samples.db")
    service = client.GroupChatService(store, draw=lambda: 0)
    generate = AsyncMock(return_value="这下真成抽卡游戏了")
    monkeypatch.setattr(client, "generate_reply", generate)
    bot = FakeBot()
    async def run():
        for index in range(5):
            await service.observe(bot, event(mid=index))
    asyncio.run(run())
    assert generate.await_count == 1 and len(bot.sent) == 1
    assert store.status(GROUP)["count"] == 5 and store.status(GROUP)["sent"] == 1
    assert generate.call_args.args[0] == GROUP
    assert all(item["speaker"].startswith("成员") for item in generate.call_args.args[1])


def test_paused_inflight_result_is_not_sent(tmp_path, monkeypatch):
    store = GroupChatStore(tmp_path/"samples.db")
    for index in range(3):
        store.record(GROUP, index, 111, "聊天样本")
    async def generate(*args):
        store.configure(GROUP, "chat_off")
        return "不能发送这句"
    monkeypatch.setattr(client, "generate_reply", generate)
    bot = FakeBot()
    asyncio.run(client.GroupChatService(store, draw=lambda: 0).observe(bot, event(mid=4)))
    assert not bot.sent


def test_failed_or_empty_generation_does_not_spam_group(tmp_path, monkeypatch):
    store = GroupChatStore(tmp_path/"samples.db")
    for index in range(3):
        store.record(GROUP, index, 111, "聊天样本")
    monkeypatch.setattr(client, "generate_reply", AsyncMock(side_effect=TimeoutError()))
    bot = FakeBot()
    asyncio.run(client.GroupChatService(store, draw=lambda: 0).observe(bot, event(mid=4)))
    assert not bot.sent
    assert store.status(GROUP)["attempts"] == 1


def test_old_events_do_not_trigger_or_collect(tmp_path, monkeypatch):
    store = GroupChatStore(tmp_path/"samples.db")
    value = event(); value.time = NOW
    asyncio.run(client.GroupChatService(store, draw=lambda: 0).observe(FakeBot(), value))
    assert store.status(GROUP)["count"] == 0


def test_admin_controls_do_not_pass_into_chat(tmp_path, monkeypatch):
    import plugins.group_chat as plugin
    store = GroupChatStore(tmp_path/"samples.db")
    monkeypatch.setattr(plugin, "store", store)
    monkeypatch.setattr(plugin, "is_exempt", lambda user: False)
    value = event("@神人 随机聊天 关闭")
    bot = FakeBot()
    asyncio.run(plugin.handle_control(bot, value))
    assert store.status(GROUP)["chat"] and "仅群主" in str(bot.sent[-1])
    value.sender.role = "admin"
    asyncio.run(plugin.handle_control(bot, value))
    assert not store.status(GROUP)["chat"]
    assert plugin.control.block and plugin.control.priority == 2
