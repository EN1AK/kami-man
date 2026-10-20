import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import struct
from unittest.mock import AsyncMock
import zlib

import httpx
import pytest
from services import group_chat_client as chat
from services.group_learning import GroupLearningStore
from services.group_memes import MemeLibrary,MAX_BYTES,category_key
from test_group_chat import event
from test_rift_rag_qa import FakeBot

GROUP=819151070
NOW=1700000000


def png(value=0):
    def chunk(tag,data):return struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+bytes([value,0,0])))+chunk(b'IEND',b'')


def library(tmp_path,count=8,draw=lambda:0):
    root=tmp_path/'pack';(root/'memes/happy').mkdir(parents=True)
    (root/'manifest.json').write_text(json.dumps({'categories':{'happy':{'description':'开心'}}}),encoding='utf-8')
    for i in range(count):(root/f'memes/happy/{i:02}.png').write_bytes(png(i))
    return MemeLibrary(root,tmp_path/'group.db',draw=draw,choose=lambda paths:paths[0])


def test_local_selection_base64_and_seven_day_dedup(tmp_path):
    lib=library(tmp_path,count=1)
    assert lib.categories(GROUP,NOW)==[dict(category='happy',description='开心')]
    image=lib.reserve(GROUP,'happy',NOW)
    assert base64.b64decode(image.image.split('://',1)[1])==png()
    assert lib.status(GROUP,NOW)['attempts']==1
    assert lib.reserve(GROUP,'happy',NOW+1801) is None
    assert MemeLibrary(lib.root,lib.db_path,draw=lambda:0).reserve(GROUP,'happy',NOW+86400) is None
    assert lib.reserve(GROUP,'happy',NOW+8*86400)


def test_atomic_cooldown_daily_cap_and_restart(tmp_path):
    lib=library(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        selected=list(pool.map(lambda _:lib.reserve(GROUP,'happy',NOW),range(4)))
    assert sum(x is not None for x in selected)==1
    restarted=MemeLibrary(lib.root,lib.db_path,draw=lambda:0,choose=lambda paths:paths[0])
    assert not restarted.categories(GROUP,NOW+1)
    for i in range(1,5):assert restarted.reserve(GROUP,'happy',NOW+i*1800)
    assert not restarted.reserve(GROUP,'happy',NOW+5*1800)
    assert restarted.status(GROUP,NOW+5*1800)['attempts']==5
    assert restarted.reserve(GROUP,'happy',NOW+86400)


def test_probability_group_and_category_allowlist(tmp_path):
    lib=library(tmp_path,draw=lambda:1)
    assert not lib.reserve(GROUP,'happy',NOW)
    assert not lib.reserve(123,'happy',NOW)
    assert not lib.reserve(GROUP,'../happy',NOW)
    assert not lib.reserve(GROUP,'unknown',NOW)
    assert category_key('\u200c_kg')=='_kg'


def test_corrupt_oversized_and_symlink_assets_are_not_sent(tmp_path):
    lib=library(tmp_path,count=0)
    directory=lib.root/'memes/happy'
    (directory/'bad.png').write_bytes(b'x'*100)
    (directory/'large.png').write_bytes(png()+b'x'*MAX_BYTES)
    outside=tmp_path/'outside.png';outside.write_bytes(png())
    (directory/'link.png').symlink_to(outside)
    assert lib.reserve(GROUP,'happy',NOW) is None
    (directory/'bad.png').unlink()
    assert not lib.inventory()
    assert not MemeLibrary(tmp_path/'missing',tmp_path/'db').categories(GROUP,NOW)


def test_manifest_descriptions_and_format_character_aliases(tmp_path):
    lib=library(tmp_path,count=1)
    (lib.root/'manifest.json').write_text(json.dumps({'categories':{'\u200chappy':{'description':'开心'},'../evil':{'description':'错误目录'}}}),encoding='utf-8')
    assert set(lib.inventory())=={'happy'}


def seed(store):
    for i in range(3):store.record(GROUP,i,111,'聊天测试样本')


@pytest.mark.parametrize('text',['短回复',''])
def test_one_generation_sends_image_with_optional_text_and_never_learns_it(tmp_path,monkeypatch,text):
    lib=library(tmp_path);store=GroupLearningStore(lib.db_path);seed(store)
    generate=AsyncMock(return_value=chat.GroupReply(text,'happy'))
    monkeypatch.setattr(chat,'generate_reply',generate)
    bot=FakeBot()
    asyncio.run(chat.GroupChatService(store,draw=lambda:0,meme_library=lib).observe(bot,event(mid=9)))
    assert generate.await_count==1 and len(bot.sent)==1
    assert [seg.type for seg in bot.sent[0]]==(['text','image'] if text else ['image'])
    assert store.status(GROUP)['count']==4 and store.status(GROUP)['sent']==1
    with closing(store.connect()) as db:
        assert db.execute('select count(*) from group_samples where text=?',(text,)).fetchone()[0]==0
    assert generate.call_args.args[5][0]['category']=='happy'


def test_image_cooldown_or_failure_falls_back_to_text(tmp_path,monkeypatch):
    lib=library(tmp_path);store=GroupLearningStore(lib.db_path);seed(store)
    def fail(*args):raise OSError('fixture IO error')
    monkeypatch.setattr(lib,'reserve',fail)
    monkeypatch.setattr(chat,'generate_reply',AsyncMock(return_value=chat.GroupReply('正常短句','happy')))
    bot=FakeBot()
    asyncio.run(chat.GroupChatService(store,draw=lambda:0,meme_library=lib).observe(bot,event(mid=9)))
    assert len(bot.sent)==1 and [seg.type for seg in bot.sent[0]]==['text']


@pytest.mark.parametrize('action',['clear','collect_off','chat_off','new_message'])
def test_inflight_image_only_is_invalidated(tmp_path,monkeypatch,action):
    lib=library(tmp_path);store=GroupLearningStore(lib.db_path);seed(store)
    async def generate(*args):
        if action=='new_message':store.record(GROUP,999,222,'新话题')
        else:
            store.configure(GROUP,action)
            store.configure(GROUP,'collect_on');store.configure(GROUP,'chat_on')
        return chat.GroupReply('','happy')
    monkeypatch.setattr(chat,'generate_reply',generate)
    bot=FakeBot()
    asyncio.run(chat.GroupChatService(store,draw=lambda:0,meme_library=lib).observe(bot,event(mid=9)))
    assert not bot.sent


@pytest.mark.parametrize('reply,category',[('hello','../../etc'),('@用户','happy'),('','happy')])
def test_client_validates_category_and_filtered_reply(monkeypatch,reply,category):
    real=httpx.AsyncClient
    def handle(request):return httpx.Response(200,json=dict(reply=reply,meme_category=category))
    monkeypatch.setattr(chat.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    result=asyncio.run(chat.generate_reply(GROUP,[dict(speaker='成员1',text='测试')],[],meme_categories=[dict(category='happy',description='开心')]))
    assert result.meme_category==('happy' if reply=='' else None)


def test_learning_status_adds_local_meme_counts(tmp_path,monkeypatch):
    import plugins.group_chat as plugin
    from test_rift_rag_qa import make_group_event
    lib=library(tmp_path);store=GroupLearningStore(lib.db_path)
    monkeypatch.setattr(plugin,'store',store);monkeypatch.setattr(plugin,'meme_library',lib)
    monkeypatch.setattr(plugin,'budget_status',AsyncMock(side_effect=RuntimeError()))
    value=make_group_event('@神人 群聊学习 状态');value.group_id=GROUP
    bot=FakeBot();asyncio.run(plugin.handle_control(bot,value))
    assert '表情库 8 张' in str(bot.sent[-1])
