from services.ygo_rag_api import RagCardBlock, YgoRagResponse
from services.ygo_rag_messages import (
    build_rag_message_texts,
    chunk_text,
    extract_mentioned_question,
    extract_text_mention_question,
)


class FakeSegment:
    def __init__(self, type_, text="", **data):
        self.type = type_
        self.data = data
        self._text = text

    def __str__(self):
        return self._text


def test_extract_mentioned_question_removes_bot_mentions_and_keeps_text():
    segments = [
        FakeSegment("at", qq="12345"),
        FakeSegment("text", " 有没有效果类似我身作盾的卡 "),
    ]

    mentioned, question = extract_mentioned_question(segments, "12345")

    assert mentioned is True
    assert question == "有没有效果类似我身作盾的卡"


def test_extract_mentioned_question_ignores_non_bot_mentions():
    segments = [
        FakeSegment("at", qq="99999"),
        FakeSegment("text", " 有没有效果类似我身作盾的卡 "),
    ]

    mentioned, question = extract_mentioned_question(segments, "12345")

    assert mentioned is False
    assert question == "有没有效果类似我身作盾的卡"


def test_extract_mentioned_question_handles_empty_question_after_mention():
    segments = [FakeSegment("text", "  "), FakeSegment("at", qq="12345")]

    mentioned, question = extract_mentioned_question(segments, "12345")

    assert mentioned is True
    assert question == ""


def test_extract_mentioned_question_accepts_text_nickname_prefix():
    segments = [
        FakeSegment(
            "text",
            "@\u795e\u4eba \u6709\u6ca1\u6709\u6548\u679c\u7c7b\u4f3c\u6211\u8eab\u4f5c\u76fe\u7684\u5361\uff1f",
        ),
    ]

    mentioned, question = extract_mentioned_question(segments, "12345")

    assert mentioned is True
    assert question == "\u6709\u6ca1\u6709\u6548\u679c\u7c7b\u4f3c\u6211\u8eab\u4f5c\u76fe\u7684\u5361\uff1f"


def test_extract_text_mention_question_handles_empty_text_question():
    mentioned, question = extract_text_mention_question("@\u795e\u4eba")

    assert mentioned is True
    assert question == ""


def test_extract_text_mention_question_ignores_unprefixed_text():
    mentioned, question = extract_text_mention_question(
        "\u6709\u6ca1\u6709\u6548\u679c\u7c7b\u4f3c\u6211\u8eab\u4f5c\u76fe\u7684\u5361\uff1f"
    )

    assert mentioned is False
    assert question == "\u6709\u6ca1\u6709\u6548\u679c\u7c7b\u4f3c\u6211\u8eab\u4f5c\u76fe\u7684\u5361\uff1f"


def test_build_rag_message_texts_prefers_structured_card_blocks_and_warnings():
    response = YgoRagResponse(
        answer="总体回答",
        warnings=["dense index skipped"],
        card_blocks=[
            RagCardBlock(text="1. 卡A\n理由: ...", truncated=False),
            RagCardBlock(text="2. 卡B\n理由: ...", truncated=True),
        ],
    )

    texts = build_rag_message_texts("原问题", response)

    assert texts == [
        "问题：原问题\n警告：\ndense index skipped",
        "1. 卡A\n理由: ...",
        "2. 卡B\n理由: ...\n\n（此卡片块已截断）",
    ]


def test_build_rag_message_texts_falls_back_to_answer_chunks_without_blocks():
    response = YgoRagResponse(answer="abcdef", warnings=[], card_blocks=[])

    texts = build_rag_message_texts("原问题", response, fallback_chunk_size=3)

    assert texts == ["abc", "def"]


def test_chunk_text_splits_without_empty_chunks():
    assert chunk_text("abcdef", 2) == ["ab", "cd", "ef"]
    assert chunk_text("", 2) == []
