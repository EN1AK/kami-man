import asyncio
from contextlib import closing
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nonebot.adapters.onebot.v11 import Message,MessageSegment
from services import unified_agent as unified
from services import mention_chat_client as client
from services.mention_state import MentionState
from services.group_chat_client import GroupReply
from services.group_memes import MemeLibrary
from services.agent_usage import UsageStore
from services.ygo_rag_agent_api import YgoRagAgentResponse
from test_rift_rag_qa import FakeBot,make_group_event


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(unified,'route_state',MentionState(tmp_path/'routes.db'))
    monkeypatch.setattr(unified,'usage_store',UsageStore(tmp_path/'usage.db'))
    monkeypatch.setattr(unified,'is_exempt',lambda user:False)
    monkeypatch.setattr(unified,'style_context',lambda *args:('',[]))
    monkeypatch.setattr(unified,'mention_memes',SimpleNamespace(categories=lambda group:[],reserve=lambda *args:None))


def answer(text='严谨结论 [证据1]'):
    return YgoRagAgentResponse(answer=text,warnings=[],exhausted=False,tool_blocks=[])


def quote(event,text):
    event.reply=SimpleNamespace(sender=SimpleNamespace(user_id=12345),message=Message(text))


def test_casual_then_professional_omits_persona_quote_and_never_rewrites(monkeypatch):
    routes=AsyncMock(side_effect=['casual','professional'])
    casual=AsyncMock(return_value=GroupReply('哼，典型的小鲸鱼吐槽'))
    professional=AsyncMock(return_value=answer())
    monkeypatch.setattr(unified,'resolve_route',routes)
    monkeypatch.setattr(unified,'request_casual',casual)
    monkeypatch.setattr(unified,'query_ygo_rag_agent',professional)
    bot=FakeBot();event=make_group_event('消息')
    async def run():
        await unified.handle_question(bot,event,'今天又抽不到想要的卡')
        quote(event,'哼，典型的小鲸鱼吐槽')
        await unified.handle_question(bot,event,'这张卡能连锁发动吗')
    asyncio.run(run())
    assert casual.await_count==1 and professional.await_count==1
    assert professional.call_args.args==('这张卡能连锁发动吗',)
    assert professional.call_args.kwargs==dict(session_id=unified.session_key(bot,event)+':professional',quoted_reply='')
    assert routes.call_args.args[1:]==('casual','casual')
    assert bot.sent[-1].data['text']=='严谨结论 [证据1]'
    assert unified.usage_store.personal(event.user_id)[1]==2


@pytest.mark.parametrize('known',['professional','casual','unknown'])
def test_quote_provenance_only_forwards_verified_professional(monkeypatch,known):
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='professional'))
    query=AsyncMock(return_value=answer());monkeypatch.setattr(unified,'query_ygo_rag_agent',query)
    forbidden=AsyncMock(side_effect=AssertionError('Persona must not run'))
    monkeypatch.setattr(unified,'request_casual',forbidden)
    bot=FakeBot();event=make_group_event('为什么？');text='原始专业条件与引用 [R-1]'
    if known!='unknown':unified.route_state.record(unified.session_key(bot,event),known,text)
    quote(event,text)
    asyncio.run(unified.handle_question(bot,event,'为什么？'))
    assert query.call_args.kwargs['quoted_reply']==(text if known=='professional' else '')
    forbidden.assert_not_awaited()


def test_persona_cannot_implicitly_escalate(monkeypatch):
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='casual'))
    monkeypatch.setattr(unified,'request_casual',AsyncMock(return_value=None))
    query=AsyncMock(return_value=answer());monkeypatch.setattr(unified,'query_ygo_rag_agent',query)
    bot=FakeBot();event=make_group_event('需要精确信息')
    asyncio.run(unified.handle_question(bot,event,'需要精确信息'))
    query.assert_not_awaited()
    assert len(bot.sent)==1
    assert unified.usage_store.personal(event.user_id)[1:]==(0,1)


def test_persona_failure_refunds_without_polluting_professional(monkeypatch):
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='casual'))
    monkeypatch.setattr(unified,'request_casual',AsyncMock(side_effect=httpx.ConnectError('down')))
    query=AsyncMock();monkeypatch.setattr(unified,'query_ygo_rag_agent',query)
    event=make_group_event('闲聊')
    asyncio.run(unified.handle_question(FakeBot(),event,'闲聊'))
    query.assert_not_awaited()
    assert unified.usage_store.personal(event.user_id)[1:]==(0,1)


def test_quota_blocks_routing_and_casual_generation(monkeypatch):
    route=AsyncMock();chat=AsyncMock()
    monkeypatch.setattr(unified,'resolve_route',route);monkeypatch.setattr(unified,'request_casual',chat)
    event=make_group_event('你好')
    for _ in range(30):unified.usage_store.reserve(event.user_id)
    asyncio.run(unified.handle_question(FakeBot(),event,'你好'))
    route.assert_not_awaited();chat.assert_not_awaited()


def test_card_image_bypasses_route_and_persona(monkeypatch):
    route=AsyncMock();chat=AsyncMock()
    monkeypatch.setattr(unified,'resolve_route',route);monkeypatch.setattr(unified,'request_casual',chat)
    monkeypatch.setattr(unified,'translate_card_image',AsyncMock(return_value=SimpleNamespace(translation='卡名：测试',original_image='base64://test')))
    event=make_group_event('',with_at=True);event.message+=MessageSegment.image('https://example.com/card.jpg')
    bot=FakeBot();asyncio.run(unified.handle_question(bot,event,''))
    route.assert_not_awaited();chat.assert_not_awaited()
    assert [seg.type for seg in bot.sent[0]]==['image','text']


def test_casual_meme_sent_without_rewriting_text(monkeypatch):
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='casual'))
    monkeypatch.setattr(unified,'request_casual',AsyncMock(return_value=GroupReply('下把一定','happy')))
    monkeypatch.setattr(unified,'mention_memes',SimpleNamespace(categories=lambda group:[dict(category='happy',description='开心')],reserve=lambda *args:SimpleNamespace(image='base64://test')))
    bot=FakeBot();event=make_group_event('闲聊')
    asyncio.run(unified.handle_question(bot,event,'闲聊'))
    assert [seg.type for seg in bot.sent[0]]==['text','image']
    assert bot.sent[0][0].data['text']=='下把一定'


def test_clear_waits_for_casual_send_then_clears_provenance(monkeypatch):
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='casual'))
    clear=AsyncMock();monkeypatch.setattr(unified,'clear_sessions',clear)
    bot=FakeBot();event=make_group_event('你好')
    async def run():
        started,release=asyncio.Event(),asyncio.Event()
        async def generate(*args):started.set();await release.wait();return GroupReply('旧闲聊回复')
        monkeypatch.setattr(unified,'request_casual',generate)
        pending=asyncio.create_task(unified.handle_question(bot,event,'你好'))
        await started.wait()
        clearing=asyncio.create_task(unified.handle_question(bot,event,'清空对话'))
        await asyncio.sleep(0)
        clear.assert_not_awaited()
        release.set();await pending;await clearing
    asyncio.run(run())
    assert '已清空' in str(bot.sent[-1])
    assert unified.route_state.metadata(unified.session_key(bot,event),'旧闲聊回复')==('','')
    assert unified.route_state._locks=={}
    assert unified.usage_store.personal(event.user_id)[1]==1


def test_provenance_is_scoped_bounded_hashes_only(tmp_path):
    state=MentionState(tmp_path/'state.db');state.record('a','casual','角色秘密')
    assert state.metadata('b','角色秘密')==('','')
    assert state.metadata('a','角色秘密')==('casual','casual')
    state.record('a','professional','角色秘密')
    assert state.metadata('a','角色秘密')[1]==''
    with closing(state.connect()) as db:
        assert 'text' not in {r[1] for r in db.execute('pragma table_info(mention_outputs)')}
        assert '角色秘密' not in str(db.execute('select * from mention_outputs').fetchall())


def test_other_group_does_not_read_learned_style(monkeypatch):
    class Forbidden:
        def status(self,*args):raise AssertionError('Cross-group learning access')
    monkeypatch.setattr(client,'learned_store',Forbidden())
    assert client.style_context(123,'你好')==('',[])


def test_http_client_payload_and_conservative_failure(monkeypatch):
    real=httpx.AsyncClient
    capture=[]
    def handle(request):
        data=json.loads(request.content);capture.append((request.url.path,data))
        if request.url.path.endswith('mention-route'):return httpx.Response(503)
        return httpx.Response(200,json=dict(route='casual',reply='你好',meme_category=None))
    monkeypatch.setattr(client.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.resolve_route('测试','casual','professional'))
    assert set(capture[0][1])=={'text'}
    assert asyncio.run(client.request_casual(123,'key','你好','',[],[]))=='你好'
    assert 'quoted_reply' not in capture[1][1]


def test_explicit_mention_media_scope_without_changing_random_scope(tmp_path):
    lib=MemeLibrary(tmp_path/'missing',tmp_path/'memes.db')
    assert not lib.allowed(123)
    direct=MemeLibrary(tmp_path/'missing',tmp_path/'memes.db',allowed_groups=None)
    assert direct.allowed(123) and not direct.allowed(-1) and not direct.allowed(True)


@pytest.mark.parametrize('text',['短回复。','第一句。'*180,'甲'*2000,'段落一。\n\n'*90,'价格是3.14。然后呢？'*80])
def test_persona_split_preserves_every_character_and_bounds(text):
    from services.persona_reply_segments import split_persona_reply
    parts=split_persona_reply(text)
    assert ''.join(parts)==text.strip()
    assert 1<=len(parts)<=4 and all(p.strip() for p in parts)


def test_persona_split_keeps_fenced_code_together():
    from services.persona_reply_segments import split_persona_reply
    text='说明。'*100+'\n```python\nprint(1)\n```'
    assert split_persona_reply(text)==[text]
    with pytest.raises(ValueError):split_persona_reply('长'*2001)


def test_long_persona_sends_in_order_records_chunks_and_appends_image_once(monkeypatch):
    from services.persona_reply_segments import split_persona_reply
    text='这是一段完整的回复。'*65
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='casual'))
    monkeypatch.setattr(unified,'request_casual',AsyncMock(return_value=GroupReply(text,'happy')))
    monkeypatch.setattr(unified,'mention_memes',SimpleNamespace(categories=lambda group:[dict(category='happy',description='开心')],reserve=lambda *args:SimpleNamespace(image='base64://test')))
    sleeper=AsyncMock();monkeypatch.setattr(unified.asyncio,'sleep',sleeper)
    query=AsyncMock();monkeypatch.setattr(unified,'query_ygo_rag_agent',query)
    bot=FakeBot();event=make_group_event('展开聊聊')
    asyncio.run(unified.handle_question(bot,event,'展开聊聊'))
    parts=split_persona_reply(text)
    assert [m.extract_plain_text() for m in bot.sent]==parts
    assert sum(seg.type=='image' for m in bot.sent for seg in m)==1
    assert bot.sent[-1][-1].type=='image'
    assert sleeper.await_count==len(parts)-1
    assert all(.8<=c.args[0]<=1.6 for c in sleeper.call_args_list)
    for part in parts:assert unified.route_state.metadata(unified.session_key(bot,event),part)[1]=='casual'
    assert unified.usage_store.personal(event.user_id)[1]==1
    query.assert_not_awaited()


def test_same_group_segmented_persona_replies_do_not_interleave(monkeypatch):
    real_sleep=asyncio.sleep
    async def pause(seconds):await real_sleep(0)
    monkeypatch.setattr(unified.asyncio,'sleep',pause)
    monkeypatch.setattr(unified,'request_casual',AsyncMock(side_effect=lambda group,key,text,*args:GroupReply(text*600)))
    bot=FakeBot();a=make_group_event('甲');b=make_group_event('乙');b.user_id=222
    async def run():
        await asyncio.gather(unified._casual_reply(bot,a,'a','甲'),unified._casual_reply(bot,b,'b','乙'))
    asyncio.run(run())
    labels=[m.extract_plain_text()[0] for m in bot.sent]
    assert labels==sorted(labels) or labels==sorted(labels,reverse=True)
    assert len(set(labels))==2 and unified.route_state._locks=={}


def test_client_long_reply_limit_and_whole_reply_validation(monkeypatch):
    real=httpx.AsyncClient
    payload=dict(route='casual',reply='长'*2000,meme_category=None)
    monkeypatch.setattr(client.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=payload)),**kw))
    assert len(asyncio.run(client.request_casual(67890,'key','展开','',[],[])))==2000
    payload['reply']='长'*2001
    with pytest.raises(ValueError):asyncio.run(client.request_casual(67890,'key','展开','',[],[]))
    payload['reply']='长'*500+'https://example.com'
    with pytest.raises(ValueError):asyncio.run(client.request_casual(67890,'key','展开','',[],[]))


def test_long_professional_reply_keeps_original_delivery(monkeypatch):
    text='专业原文。'*150
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='professional'))
    monkeypatch.setattr(unified,'query_ygo_rag_agent',AsyncMock(return_value=answer(text)))
    sleeper=AsyncMock();monkeypatch.setattr(unified.asyncio,'sleep',sleeper)
    bot=FakeBot();asyncio.run(unified.handle_question(bot,make_group_event('裁定 测试'),'裁定 测试'))
    assert len(bot.sent)==1 and bot.sent[0].data['text']==text
    sleeper.assert_not_awaited()


@pytest.mark.parametrize('text,expected',[
    ('第一句。\n第二句。',2),
    ('第一段。\n\n第二段。\n\n第三段。',3),
    ('第一句。\r\n第二句。',2),
    ('甲\n乙\n丙\n丁\n戊\n己',4),
    ('单行短回复。',1),
])
def test_explicit_newlines_split_even_short_replies(text,expected):
    from services.persona_reply_segments import split_persona_reply
    parts=split_persona_reply(text)
    assert len(parts)==expected
    assert ''.join(parts)==text.strip()
    assert all(p.strip() for p in parts)


def test_short_multiline_reply_sends_separate_messages(monkeypatch):
    monkeypatch.setattr(unified,'resolve_route',AsyncMock(return_value='casual'))
    monkeypatch.setattr(unified,'request_casual',AsyncMock(return_value=GroupReply('第一句。\n第二句。\n第三句。')))
    sleeper=AsyncMock();monkeypatch.setattr(unified.asyncio,'sleep',sleeper)
    bot=FakeBot();event=make_group_event('聊聊')
    asyncio.run(unified.handle_question(bot,event,'聊聊'))
    assert [m.extract_plain_text().strip() for m in bot.sent]==['第一句。','第二句。','第三句。']
    assert sleeper.await_count==2
    assert unified.usage_store.personal(event.user_id)[1]==1
