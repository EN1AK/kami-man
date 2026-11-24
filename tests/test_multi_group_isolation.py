from contextlib import closing

from services.group_conversation import GroupConversation
from services.group_learning import GroupLearningStore
from services.group_chat_store import ALLOWED_GROUPS

GROUPS = (819151070, 875615212)
NOW = 1900000000


def test_learning_summary_and_context_are_isolated(tmp_path):
    store = GroupLearningStore(tmp_path / 'chat.db')
    conversation = GroupConversation(store)
    assert ALLOWED_GROUPS == frozenset(GROUPS)
    for group, label in zip(GROUPS, ('苹果', '西瓜')):
        for index in range(200):
            assert store.record(group, index, index % 3, f'{label}今天真好吃{index}', NOW)
        summary = store.reserve_summary(group, NOW + 1)
        assert summary['previous_summary'] == ''
        assert summary['source_count'] == 200
        assert all(label in text for text in summary['style_samples'])
        assert store.finish_summary(summary, label + '群的独立语气', NOW + 2)
        job = store.reserve_learning(group, NOW + 3)
        assert all(label in sample['text'] for sample in job['samples'])
        source = job['samples'][0]
        assert store.finish_learning(job, [dict(source_id=source['source_id'],
            situation='讨论水果', expression=source['text'])], NOW + 4)
        conversation.record(group, 'same-id', 123, label + '当前话题', now=NOW + 5)
        conversation.record(group, 'bot-id', None, label + '机器人回答', bot=True,
                            reply_to='same-id', now=NOW + 6)

    for group, label in zip(GROUPS, ('苹果', '西瓜')):
        assert store.profile(group, NOW + 7)['summary'] == label + '群的独立语气'
        expressions = store.retrieve(group, [dict(text='水果')], NOW + 7)
        assert expressions and all(label in x['expression'] for x in expressions)
        context = conversation.context(group, 'bot-id', NOW + 7)
        assert len(context) == 2 and all(label in x['text'] for x in context)
        assert context[-1]['reply_to'] == context[0]['id']
        assert store.reserve(group, NOW + 8)
    # The same user has distinct anonymous identities in the two groups.
    with closing(store.connect()) as db:
        speakers = db.execute('SELECT DISTINCT speaker FROM group_samples WHERE message_id=?', ('0',)).fetchall()
        assert len(speakers) == 2
    store.configure(GROUPS[1], 'clear', NOW + 9)
    assert store.status(GROUPS[0], NOW + 10)['count'] == 200
    assert store.profile(GROUPS[0], NOW + 10)['summary'].startswith('苹果')
    assert store.retrieve(GROUPS[0], [dict(text='水果')], NOW + 10)
    assert len(conversation.context(GROUPS[0], now=NOW + 10)) == 2
    assert not store.status(GROUPS[1], NOW + 10)['collect']
    assert not store.profile(GROUPS[1], NOW + 10)['summary']
    assert not store.retrieve(GROUPS[1], [dict(text='水果')], NOW + 10)
    assert not conversation.context(GROUPS[1], now=NOW + 10)
