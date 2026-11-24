import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import Message,MessageSegment
from services.group_conversation import GroupConversation
from services.group_learning import GroupLearningStore
from services import group_chat_client as client,mention_chat_client as mention,unified_agent as unified
from test_rift_rag_qa import FakeBot,make_group_event

GROUP=819151070
NOW=1900000000


def event(text,mid,user=111,quoted=None):
    value=make_group_event(text);value.group_id=GROUP;value.message_id=mid;value.user_id=user
    if quoted:
        value.reply=SimpleNamespace(message_id=quoted,sender=SimpleNamespace(user_id=12345),message=Message('玩鸣潮'))
        value.message=MessageSegment.reply(quoted)+value.message
        value.to_me=True
    return value


def test_bot_and_reply_relationship_are_not_learning_samples(tmp_path):
    store=GroupLearningStore(tmp_path/'chat.db');context=GroupConversation(store)
    store.record(GROUP,1,111,'晚上玩什么',NOW)
    context.seed_recent(GROUP,NOW)
    context.record(GROUP,2,None,'玩鸣潮',bot=True,reply_to=1,now=NOW+1)
    context.record(GROUP,3,222,'为什么推荐这个',reply_to=2,now=NOW+2)
    messages=context.context(GROUP,3,NOW+3)
    assert [row['speaker'] for row in messages]==['成员1','机器人','成员2']
    assert messages[-1]['reply_to']==messages[-2]['id']
    assert messages[-2]['reply_to']==messages[0]['id']
    assert store.status(GROUP,NOW+3)['count']==1
    assert all(str(number) not in str(messages) for number in (GROUP,111,222))


def test_old_quote_chain_survives_busy_group_and_context_is_bounded(tmp_path):
    context=GroupConversation(GroupLearningStore(tmp_path/'chat.db'))
    context.record(GROUP,1,111,'最初的问题',now=NOW)
    context.record(GROUP,2,None,'最初的回答',bot=True,reply_to=1,now=NOW+1)
    for index in range(3,70):context.record(GROUP,index,222,'别的话题',now=NOW+index)
    context.record(GROUP,70,333,'接着问那个答案',reply_to=2,now=NOW+70)
    messages=context.context(GROUP,70,NOW+71)
    assert len(messages)==30
    assert any(row['text']=='最初的问题' for row in messages)
    assert any(row['text']=='最初的回答' for row in messages)
    assert messages[-1]['reply_to'] in {row['id'] for row in messages}
    assert context.context(123,70,NOW+71)==[]
    assert context.context(GROUP,70,NOW+2000)==[]


def test_collection_clear_stop_and_duplicate_claims(tmp_path):
    store=GroupLearningStore(tmp_path/'chat.db');context=GroupConversation(store)
    context.record(GROUP,1,111,'普通消息',now=NOW)
    assert context.claim_random(GROUP,1)
    assert not context.claim_random(GROUP,1)
    store.configure(GROUP,'collect_off',NOW+1)
    assert not context.context(GROUP,now=NOW+2)
    assert not context.record(GROUP,2,111,'停止后不能记录',now=NOW+2)
    store.configure(GROUP,'collect_on',NOW+3)
    context.record(GROUP,3,111,'重新开始',now=NOW+4)
    store.configure(GROUP,'clear',NOW+5)
    store.configure(GROUP,'collect_on',NOW+6)
    assert not context.context(GROUP,now=NOW+7)


@pytest.mark.parametrize('text',['翻译 hello','规则 攻击','我的手机号13800138000','https://example.org','密码: secret'])
def test_professional_or_private_text_not_captured(text):
    assert client.context_text(event(text,1),12345) is None


def test_quote_followup_reaches_explicit_persona_with_bot_history(monkeypatch):
    store=mention.learned_store;context=GroupConversation(store)
    context.record(GROUP,1,111,'晚上玩什么')
    context.record(GROUP,100,None,'玩鸣潮',bot=True,reply_to=1)
    req=event('为什么推荐这个',101,user=222,quoted=100)
    generate=AsyncMock(return_value=client.GroupReply('因为战斗比较合你口味'))
    monkeypatch.setattr(unified,'request_casual',generate)
    monkeypatch.setattr(unified,'style_context',lambda *args:('',[]))
    monkeypatch.setattr(unified,'mention_memes',SimpleNamespace(categories=lambda *a:[],reserve=lambda *a:None))
    monkeypatch.setattr(unified,'route_state',__import__('services.mention_state',fromlist=['MentionState']).MentionState(store.path.with_name('routes.db')))
    class Bot(FakeBot):
        async def send(self,event,message):
            await super().send(event,message);return {'message_id':200}
    bot=Bot()
    asyncio.run(unified._casual_reply(bot,req,'test-key','为什么推荐这个'))
    conversation,current_message_id=generate.call_args.args[-2:]
    assert next(row for row in conversation if row["id"] == current_message_id)["text"] == '为什么推荐这个'
    previous=next(row for row in conversation if row['role']=='assistant')
    assert previous['text']=='玩鸣潮'
    assert conversation[-1]['reply_to']==previous['id']
    assert context.context(GROUP)[-1]['text']=='因为战斗比较合你口味'
    assert store.status(GROUP)['count']==0


def test_random_context_contains_bot_and_unmentioned_quote_but_does_not_learn_quote(monkeypatch):
    store=mention.learned_store
    for index in range(3):store.record(GROUP,index,111,'聊天样本')
    context=GroupConversation(store)
    context.seed_recent(GROUP)
    context.record(GROUP,20,None,'玩鸣潮',bot=True,reply_to=2)
    req=event('这个我也玩',21,user=222)
    req.message=MessageSegment.reply(20)+req.message
    generate=AsyncMock(return_value=client.GroupReply('那可以组个队'))
    monkeypatch.setattr(client,'generate_reply',generate)
    asyncio.run(client.GroupChatService(store,draw=lambda:0).observe(FakeBot(),req))
    assert generate.await_count==1
    history=generate.call_args.args[1]
    assert any(row['role']=='assistant' and row['text']=='玩鸣潮' for row in history)
    assert history[-1]['reply_to'] in {row['id'] for row in history if row['role']=='assistant'}
    assert store.status(GROUP)['count']==3


def test_new_context_only_message_invalidates_pending_random_reply(monkeypatch):
    store=mention.learned_store
    for index in range(3):store.record(GROUP,index,111,'聊天样本')
    async def generate(*args):
        GroupConversation(store).record(GROUP,90,222,'上下文已变化')
        return client.GroupReply('过时的回复')
    monkeypatch.setattr(client,'generate_reply',generate)
    bot=FakeBot()
    asyncio.run(client.GroupChatService(store,draw=lambda:0).observe(bot,event('新的话',4)))
    assert not bot.sent


def test_context_failure_does_not_fail_a_persona_request(monkeypatch):
    monkeypatch.setattr(mention,'capture_group_context',AsyncMock(side_effect=RuntimeError('fixture storage failure')))
    assert asyncio.run(mention.conversation_context(FakeBot(),event('你好',1)))==([], "")
