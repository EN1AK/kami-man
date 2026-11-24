import asyncio
import nonebot
from nonebot.adapters.onebot.v11 import PrivateMessageEvent, Message
from nonebot.adapters.onebot.v11.event import Sender

nonebot.init()

from services.admin_group_control import execute_admin_group_command as execute, is_admin_group_command
from services.group_learning import GroupLearningStore
import plugins.admin_group_control as plugin
from test_rift_rag_qa import FakeBot, make_group_event


def private(text, user=111):
    return PrivateMessageEvent(time=0, self_id=12345, post_type='message', message_type='private',
        sub_type='friend', message_id=1, user_id=user, message=Message(text),
        original_message=Message(text), raw_message=text, font=0, sender=Sender(user_id=user))


def test_controls_are_scoped_and_persisted(tmp_path):
    path = tmp_path / 'groups.db'
    store = GroupLearningStore(path)
    reply = execute(store, '群管理 875615212 随机聊天 关闭')
    assert '随机聊天：关闭' in reply
    assert not GroupLearningStore(path).status(875615212)['chat']
    assert store.status(819151070)['chat']
    assert store.status(875615212)['collect']
    execute(store, '群管理 875615212 群聊采集 关闭')
    assert not store.status(875615212)['collect']
    assert '无法开启' in execute(store, '群管理 875615212 随机聊天 开启')
    assert not store.status(875615212)['chat']
    execute(store, '群管理 875615212 群聊采集 开启')
    assert store.status(875615212)['collect'] and not store.status(875615212)['chat']
    execute(store, '/群管理 875615212 随机聊天 开启')
    assert store.status(875615212)['chat']
    assert '819151070' in execute(store, '群管理 列表')
    assert '875615212' in execute(store, '群管理 列表')


def test_bad_commands_never_modify_settings(tmp_path):
    store = GroupLearningStore(tmp_path / 'groups.db')
    for text in ['群管理 123 随机聊天 关闭', '群管理 875615212 随机聊天 关闭 多余参数',
                 '群管理 875615212 任意功能 开启', '群管理 875615212 群聊采集 清空']:
        execute(store, text)
        assert store.status(875615212)['chat'] and store.status(875615212)['collect']
    assert is_admin_group_command('/群管理 帮助')
    assert not is_admin_group_command('帮我群管理')
    assert '尚未生成' in execute(store, '群管理 875615212 群聊风格')
    assert '已学习' in execute(store, '群管理 875615212 群聊学习')


def test_private_permission_and_dispatch(monkeypatch, tmp_path):
    bot = FakeBot()
    store = GroupLearningStore(tmp_path / 'groups.db')
    monkeypatch.setattr(plugin, 'store', store)
    monkeypatch.setattr(plugin, 'is_exempt', lambda user: user == 111)
    command = '群管理 875615212 随机聊天 关闭'
    assert plugin.admin_group_control.priority == 1 and plugin.admin_group_control.block
    assert asyncio.run(plugin.is_private_control(private(command)))
    group = make_group_event(command)
    assert not asyncio.run(plugin.is_private_control(group))
    asyncio.run(plugin.handle_admin_group_control(bot, private(command, user=222)))
    asyncio.run(plugin.handle_admin_group_control(bot, group))
    assert not bot.sent and store.status(875615212)['chat']
    asyncio.run(plugin.handle_admin_group_control(bot, private(command)))
    assert len(bot.sent) == 1 and not store.status(875615212)['chat']
    asyncio.run(plugin.handle_admin_group_control(bot, private('群管理 格式不对')))
    assert '群管理指令' in str(bot.sent[-1])
