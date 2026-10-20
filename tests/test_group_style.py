import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from services import group_style as style
from services.group_style import GroupStyleStore

GROUP=819151070
NOW=1700000000


def seed(store,start=0,count=200,now=NOW,speakers=3):
    for index in range(start,start+count):
        store.record(GROUP,index,index%speakers,f"群聊测试短句{index}，主打一个参与",now)


def test_initial_threshold_and_member_diversity(tmp_path):
    store=GroupStyleStore(tmp_path/'style.db')
    seed(store,count=199)
    assert store.reserve_summary(GROUP,NOW) is None
    seed(store,start=199,count=1)
    job=store.reserve_summary(GROUP,NOW)
    assert job and 3<=len(job['style_samples'])<=8
    assert job['statistics']['message_count']==200
    assert job['statistics']['participant_count']==3
    assert not any('speaker' in key for key in job)
    other=GroupStyleStore(tmp_path/'one-speaker.db')
    seed(other,speakers=1)
    assert other.reserve_summary(GROUP,NOW) is None
    assert other.reserve_summary(123,NOW) is None


def test_refresh_requires_new_messages_and_later_beijing_day(tmp_path):
    store=GroupStyleStore(tmp_path/'style.db'); seed(store)
    job=store.reserve_summary(GROUP,NOW)
    assert store.finish_summary(job,'短句口语，常用自嘲。',NOW+1)
    seed(store,start=200,count=100,now=NOW+2)
    assert store.reserve_summary(GROUP,NOW+4000) is None
    assert store.profile(GROUP,NOW+4000)['new_count']==100
    next_job=store.reserve_summary(GROUP,NOW+86400)
    assert next_job['previous_summary']=='短句口语，常用自嘲。'
    assert next_job['source_count']==100
    assert store.finish_summary(next_job,'短句为主，接梗随意。',NOW+86401)
    assert store.profile(GROUP,NOW+86402)['new_count']==0


def test_jobs_are_atomic_persistent_and_failures_bounded(tmp_path):
    store=GroupStyleStore(tmp_path/'style.db'); seed(store)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=list(pool.map(lambda _:store.reserve_summary(GROUP,NOW),range(3)))
    assert sum(job is not None for job in jobs)==1
    assert GroupStyleStore(store.path).reserve_summary(GROUP,NOW+121) is None
    assert store.reserve_summary(GROUP,NOW+3601)
    assert store.reserve_summary(GROUP,NOW+7202)
    assert store.reserve_summary(GROUP,NOW+10803) is None


@pytest.mark.parametrize('action',['clear','collect_off'])
def test_stop_or_clear_invalidates_inflight_summary(tmp_path,action):
    store=GroupStyleStore(tmp_path/'style.db'); seed(store)
    job=store.reserve_summary(GROUP,NOW)
    store.configure(GROUP,action,NOW+1)
    store.configure(GROUP,'collect_on',NOW+2)
    assert not store.finish_summary(job,'不允许写回',NOW+3)
    assert store.profile(GROUP,NOW+3)['summary']==''


def test_clear_deletes_existing_profile_and_retention_expires_it(tmp_path):
    store=GroupStyleStore(tmp_path/'style.db'); seed(store)
    assert store.finish_summary(store.reserve_summary(GROUP,NOW),'短句，随意。',NOW+1)
    assert store.profile(GROUP,NOW+style.RETENTION_SECONDS+2)['summary']==''
    assert store.profile(GROUP,NOW+style.RETENTION_SECONDS+2)['new_count']==0


def test_summary_request_sends_only_bounded_samples_and_aggregates(monkeypatch):
    import json
    job=dict(group_id=GROUP,token='private-job-id',source_seq=99,source_count=200,
             previous_summary='',style_samples=['短句一','短句二','短句三'],
             statistics=dict(message_count=200,participant_count=3,mean_length=8,short_message_ratio=1))
    real_client=httpx.AsyncClient
    def handle(request):
        payload=json.loads(request.content)
        assert set(payload)=={'group_id','previous_summary','style_samples','statistics'}
        assert len(payload['style_samples'])<=8
        assert request.url.path.endswith('/api/group-style')
        return httpx.Response(200,json={'summary':'本群以短句、随意口语为主。'})
    monkeypatch.setattr(style.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handle),**kwargs))
    assert asyncio.run(style.request_summary(job))=='本群以短句、随意口语为主。'


def test_scheduler_does_nothing_without_samples(tmp_path,monkeypatch):
    request=AsyncMock(); monkeypatch.setattr(style,'request_summary',request)
    assert not asyncio.run(style.update_style(GroupStyleStore(tmp_path/'style.db'),GROUP))
    request.assert_not_awaited()


def test_style_profile_is_sent_with_group_reply(monkeypatch):
    import json
    from services import group_chat_client as client
    real_client=httpx.AsyncClient
    def handle(request):
        assert json.loads(request.content)['style_profile']=='本群习惯短句自嘲。'
        return httpx.Response(200,json={'reply':'主打一个陪伴'})
    monkeypatch.setattr(client.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handle),**kwargs))
    result=asyncio.run(client.generate_reply(GROUP,[{'speaker':'成员1','text':'抽牌又寄了'}],[],'本群习惯短句自嘲。'))
    assert result=='主打一个陪伴'


def test_translated_card_first_reply_contains_exact_original_once(monkeypatch,tmp_path):
    from nonebot.adapters.onebot.v11 import MessageSegment
    from services import unified_agent as unified
    from services.agent_usage import UsageStore
    from test_rift_rag_qa import FakeBot,make_group_event
    monkeypatch.setattr(unified,'usage_store',UsageStore(tmp_path/'usage.db'))
    monkeypatch.setattr(unified,'is_exempt',lambda user:False)
    result=SimpleNamespace(translation='译文第一段\n译文第二段',original_image='base64://exact-original-bytes')
    monkeypatch.setattr(unified,'translate_card_image',AsyncMock(return_value=result))
    monkeypatch.setattr(unified,'chunk_text',lambda text:['译文第一段','译文第二段'])
    event=make_group_event('',with_at=True)
    event.message+=MessageSegment.image('https://gchat.qpic.cn/card.jpg')
    bot=FakeBot()
    asyncio.run(unified.handle_question(bot,event,''))
    assert len(bot.sent)==2
    assert [seg.type for seg in bot.sent[0]]==['image','text']
    assert bot.sent[0][0].data['file']=='base64://exact-original-bytes'
    assert all(seg.type=='text' for seg in bot.sent[1])
    assert '译文第一段' in str(bot.sent[0]) and '译文第二段' in str(bot.sent[1])


def test_group_style_can_be_inspected_without_mutating_controls(monkeypatch,tmp_path):
    import plugins.group_chat as plugin
    from test_rift_rag_qa import FakeBot,make_group_event
    store=GroupStyleStore(tmp_path/'style.db')
    monkeypatch.setattr(plugin,'store',store)
    event=make_group_event('@神人 群聊风格'); event.group_id=GROUP
    bot=FakeBot()
    asyncio.run(plugin.handle_control(bot,event))
    assert '尚未生成风格描述' in str(bot.sent[-1])
    assert store.status(GROUP)['collect']
