import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import AsyncMock

import pytest
from services.group_learning import GroupLearningStore, update_learning
from services import group_learning as learning
from services import group_chat_client as chat
from test_group_chat import event
from test_rift_rag_qa import FakeBot

GROUP = 819151070
NOW = 1700000000


def seed(store,start=0,count=100,now=NOW):
    for i in range(start,start+count):
        store.record(GROUP,i,i%3,f"今天抽卡又寄了，主打一个参与{i}",now)


def pair(job):
    return dict(situation="自嘲抽卡运气不好",expression="主打一个参与",source_id=job["samples"][0]["source_id"])


def test_threshold_atomic_jobs_and_evidence_validation(tmp_path):
    store=GroupLearningStore(tmp_path/'group.db')
    seed(store,count=99)
    assert store.reserve_learning(GROUP,NOW) is None
    seed(store,start=99,count=1)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=list(pool.map(lambda _:store.reserve_learning(GROUP,NOW),range(3)))
    assert sum(job is not None for job in jobs)==1
    job=next(job for job in jobs if job)
    assert 3<=len(job['samples'])<=8
    invalid=dict(situation='胡乱概括',expression='样本里根本没有这句',source_id='s1')
    assert store.finish_learning(job,[pair(job),invalid,dict(pair(job),source_id='s9')],NOW+1)
    assert not store.finish_learning(job,[pair(job)],NOW+2)
    assert store.learning_status(GROUP,NOW+2)['count']==1
    with closing(store.connect()) as db:
        assert db.execute('select count(*) from group_expression_evidence').fetchone()[0]==1
    assert store.retrieve(GROUP,[dict(text='抽卡运气又不好了')],NOW+2)
    assert not store.retrieve(GROUP,[dict(text='晚上去哪里吃烤肉')],NOW+2)
    assert not store.reserve_learning(123,NOW)


def test_learning_caps_restart_and_date_rollover(tmp_path):
    store=GroupLearningStore(tmp_path/'group.db'); seed(store)
    assert store.finish_learning(store.reserve_learning(GROUP,NOW),[],NOW+1)
    seed(store,start=100,count=49,now=NOW+2)
    assert store.reserve_learning(GROUP,NOW+3601) is None
    seed(store,start=149,count=1,now=NOW+2)
    assert store.finish_learning(store.reserve_learning(GROUP,NOW+3601),[],NOW+3602)
    seed(store,start=150,count=50,now=NOW+3603)
    assert GroupLearningStore(store.path).reserve_learning(GROUP,NOW+7202) is None
    assert store.reserve_learning(GROUP,NOW+86400)


def test_watermark_remains_valid_after_all_samples_expire(tmp_path):
    store=GroupLearningStore(tmp_path/'group.db');seed(store)
    job=store.reserve_learning(GROUP,NOW)
    assert store.finish_learning(job,[],NOW+1)
    store.status(GROUP,NOW+31*86400)
    assert store.status(GROUP,NOW+31*86400)['count']==0
    seed(store,start=500,count=50,now=NOW+31*86400)
    assert store.learning_status(GROUP,NOW+31*86400)['new_count']==50
    assert store.reserve_learning(GROUP,NOW+31*86400)


def test_job_finishing_after_midnight_counts_for_completion_day(tmp_path):
    from datetime import datetime
    from services.group_chat_store import CHINA_TZ
    now=datetime(2026,10,17,23,59,30,tzinfo=CHINA_TZ).timestamp()
    store=GroupLearningStore(tmp_path/'group.db');seed(store,now=now)
    job=store.reserve_learning(GROUP,now)
    assert store.finish_learning(job,[],now+40)
    assert store.learning_status(GROUP,now+41)['successes']==1


@pytest.mark.parametrize('action',['clear','collect_off'])
def test_stop_invalidates_jobs_and_reply_epoch(tmp_path,action):
    store=GroupLearningStore(tmp_path/'group.db'); seed(store)
    job=store.reserve_learning(GROUP,NOW)
    checkpoint=store.reply_checkpoint(GROUP)
    store.configure(GROUP,action,NOW+1)
    store.configure(GROUP,'collect_on',NOW+2)
    store.configure(GROUP,'chat_on',NOW+2)
    assert not store.finish_learning(job,[pair(job)],NOW+3)
    assert not store.reply_allowed(GROUP,checkpoint,'不能发送',NOW+3)


def test_clear_and_retention_remove_expressions_and_bot_replies(tmp_path):
    store=GroupLearningStore(tmp_path/'group.db'); seed(store)
    job=store.reserve_learning(GROUP,NOW)
    assert store.finish_learning(job,[pair(job)],NOW+1)
    store.record_reply(GROUP,'这下真寄了！',NOW+2)
    before=store.status(GROUP,NOW+3)['count']
    assert before==100  # Own replies never become human learning samples.
    assert not store.reply_allowed(GROUP,store.reply_checkpoint(GROUP),'这下真寄了',NOW+3)
    assert not store.reply_allowed(GROUP,store.reply_checkpoint(GROUP),'！！！',NOW+3)
    store.configure(GROUP,'clear',NOW+4)
    assert store.learning_status(GROUP,NOW+5)['count']==0
    with closing(store.connect()) as db:
        assert db.execute('select count(*) from group_own_replies').fetchone()[0]==0
    store.configure(GROUP,'collect_on',NOW+6)
    seed(store,start=500,now=NOW+6)
    # Finish a later day so the one-hour retry interval has elapsed.
    job=store.reserve_learning(GROUP,NOW+86400)
    assert store.finish_learning(job,[pair(job)],NOW+86401)
    assert store.learning_status(GROUP,NOW+32*86400)['count']==0


def test_cap_and_failure_retries_are_persistent(tmp_path):
    store=GroupLearningStore(tmp_path/'group.db'); seed(store)
    for i in range(3):
        assert GroupLearningStore(store.path).reserve_learning(GROUP,NOW+i*3601)
    assert not store.reserve_learning(GROUP,NOW+10803)
    with closing(store.connect()) as db,db:
        db.executemany('insert into group_expressions(group_id,situation,expression,updated) values (?,?,?,?)',
                       [(GROUP,'情景'+str(i),'表达'+str(i),NOW+i) for i in range(301)])
    assert store.learning_status(GROUP,NOW+400)['count']==300


def test_changed_context_drops_reply(tmp_path,monkeypatch):
    store=GroupLearningStore(tmp_path/'group.db')
    for i in range(3): store.record(GROUP,i,111,'聊天样本')
    async def generate(*args):
        store.record(GROUP,99,222,'话题已经改变')
        return '已经过时的回复'
    monkeypatch.setattr(chat,'generate_reply',generate)
    bot=FakeBot()
    asyncio.run(chat.GroupChatService(store,draw=lambda:0).observe(bot,event(mid=4)))
    assert not bot.sent


def test_reference_budget_and_repeated_reply(tmp_path,monkeypatch):
    store=GroupLearningStore(tmp_path/'group.db')
    for i in range(3): store.record(GROUP,i,111,'聊天样本')
    monkeypatch.setattr(store,'context',lambda *args:([dict(speaker='成员1',text='样本')]*4,['旧样本']*8))
    monkeypatch.setattr(store,'retrieve',lambda *args:[dict(situation='当前情景',expression='相关表达')]*5)
    generate=AsyncMock(return_value='又是熟悉的剧情')
    monkeypatch.setattr(chat,'generate_reply',generate)
    store.record_reply(GROUP,'又是熟悉的剧情')
    bot=FakeBot()
    asyncio.run(chat.GroupChatService(store,draw=lambda:0).observe(bot,event(mid=4)))
    assert len(generate.call_args.args[2])+len(generate.call_args.args[4])==8
    assert not bot.sent


def test_learning_status_command_and_bounded_payload(tmp_path,monkeypatch):
    import json,httpx
    import plugins.group_chat as plugin
    from test_rift_rag_qa import make_group_event
    store=GroupLearningStore(tmp_path/'group.db'); seed(store)
    job=store.reserve_learning(GROUP,NOW)
    real=httpx.AsyncClient
    def handle(request):
        data=json.loads(request.content)
        assert set(data)=={'group_id','samples'}
        assert len(data['samples'])<=8
        assert all(set(s)=={'source_id','text'} for s in data['samples'])
        return httpx.Response(200,json={'expressions':[pair(job)]})
    monkeypatch.setattr(learning.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    assert asyncio.run(learning.request_learning(job))==[pair(job)]
    monkeypatch.setattr(plugin,'store',store)
    monkeypatch.setattr(plugin,'budget_status',AsyncMock(return_value=dict(estimated_cny=.03,monthly_limit_cny=10,
        daily_estimated_cny=.02,daily_limit_cny=1,calls=3,input_tokens=100,output_tokens=20,uncertain_calls=1)))
    value=make_group_event('@神人 群聊学习 状态'); value.group_id=GROUP
    bot=FakeBot()
    asyncio.run(plugin.handle_control(bot,value))
    assert '场景表达' in str(bot.sent[-1]) and '¥10' in str(bot.sent[-1])


def test_no_samples_no_learning_calls(tmp_path,monkeypatch):
    request=AsyncMock();monkeypatch.setattr(learning,'request_learning',request)
    assert not asyncio.run(update_learning(GroupLearningStore(tmp_path/'group.db'),GROUP))
    request.assert_not_awaited()
