from services.rift_rag_api import RagSource, RiftRagResponse
from services.rift_rag_messages import (
    build_rift_rag_message_texts,
    build_source_list_text,
    chunk_text,
    extract_text_mention_question,
    get_text_mention_aliases,
    is_rift_alias_message,
)


class FakeSegment:
    def __init__(self, type_, text="", **data):
        self.type = type_
        self.data = data
        self._text = text

    def __str__(self):
        return self._text


def test_get_text_mention_aliases_uses_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("RIFT_RAG_TEXT_MENTION_ALIASES", raising=False)

    assert get_text_mention_aliases() == ["符文规则"]


def test_get_text_mention_aliases_parses_comma_list_and_strips_at():
    aliases = get_text_mention_aliases("符文规则, @rf规则 ,＠规则问答，,")

    assert aliases == ["符文规则", "rf规则", "规则问答"]


def test_extract_text_mention_question_accepts_bare_alias():
    matched, question = extract_text_mention_question("符文规则 伤害怎么结算")

    assert matched is True
    assert question == "伤害怎么结算"


def test_extract_text_mention_question_accepts_at_prefixed_alias():
    matched, question = extract_text_mention_question("@符文规则 伤害怎么结算")

    assert matched is True
    assert question == "伤害怎么结算"


def test_extract_text_mention_question_accepts_fullwidth_at_prefixed_alias():
    matched, question = extract_text_mention_question("＠符文规则 伤害怎么结算")

    assert matched is True
    assert question == "伤害怎么结算"


def test_extract_text_mention_question_handles_empty_remainder():
    matched, question = extract_text_mention_question("符文规则")

    assert matched is True
    assert question == ""


def test_extract_text_mention_question_ignores_non_matching_text():
    matched, question = extract_text_mention_question("今天符文战场怎么组卡")

    assert matched is False
    assert question == "今天符文战场怎么组卡"


def test_is_rift_alias_message_accepts_alias_message():
    segments = [FakeSegment("text", "符文规则 伤害怎么结算")]

    assert is_rift_alias_message("符文规则 伤害怎么结算", segments, "12345") is True


def test_is_rift_alias_message_rejects_ygo_bot_mention():
    segments = [
        FakeSegment("at", qq="12345"),
        FakeSegment("text", " 符文规则 伤害怎么结算"),
    ]

    assert (
        is_rift_alias_message("符文规则 伤害怎么结算", segments, "12345") is False
    )


def test_is_rift_alias_message_rejects_ygo_text_alias():
    segments = [FakeSegment("text", "@神人 有没有效法我身作盾的卡")]

    assert is_rift_alias_message("@神人 有没有效法我身作盾的卡", segments, "12345") is False


def test_is_rift_alias_message_ignores_plain_text():
    segments = [FakeSegment("text", "随便聊聊")]

    assert is_rift_alias_message("随便聊聊", segments, "12345") is False


def test_build_rift_rag_message_texts_builds_question_answer_and_sources_nodes():
    response = RiftRagResponse(
        answer="结论 [R-CR-465.2]",
        warnings=["向量召回失败"],
        sources=[
            RagSource(rule_id="R-CR-465.2", topic="465.2 Step 2"),
            RagSource(rule_id="R-CR-814.1.d.1", topic="814.1.d.1 Shield"),
        ],
    )

    texts = build_rift_rag_message_texts("伤害怎么结算", response)

    assert texts == [
        "问题：伤害怎么结算\n警告：\n向量召回失败",
        "结论 [R-CR-465.2]",
        "参考条目：\nR-CR-465.2 — 465.2 Step 2\nR-CR-814.1.d.1 — 814.1.d.1 Shield",
    ]


def test_build_rift_rag_message_texts_chunks_long_answer():
    response = RiftRagResponse(answer="abcdef", warnings=[], sources=[])

    texts = build_rift_rag_message_texts("问题", response, fallback_chunk_size=4)

    assert texts == ["问题：问题", "abcd", "ef"]


def test_build_source_list_text_handles_missing_topic():
    text = build_source_list_text([RagSource(rule_id="R-CR-465.2", topic="")])

    assert text == "参考条目：\nR-CR-465.2"


def test_chunk_text_splits_without_empty_chunks():
    assert chunk_text("abcdef", 2) == ["ab", "cd", "ef"]
    assert chunk_text("", 2) == []
