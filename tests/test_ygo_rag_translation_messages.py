from services.ygo_rag_translation_api import (
    TranslationBlock,
    YgoRagTranslationResponse,
)
from services.ygo_rag_translation_messages import (
    build_translation_message_texts,
    extract_translation_request,
    extract_translation_text,
    get_translation_command_aliases,
)


class FakeSegment:
    def __init__(self, type_, text="", **data):
        self.type = type_
        self.data = data
        self._text = text

    def __str__(self):
        return self._text


def test_get_translation_command_aliases_uses_defaults():
    assert get_translation_command_aliases(None) == ["\u7ffb\u8bd1", "translate"]


def test_extract_translation_text_accepts_chinese_command():
    is_command, text = extract_translation_text(
        "\u7ffb\u8bd1 Once per turn: destroy it."
    )

    assert is_command is True
    assert text == "Once per turn: destroy it."


def test_extract_translation_text_accepts_colon_separator_and_translate_alias():
    is_command, text = extract_translation_text("translate: \u4f60\u597d")

    assert is_command is True
    assert text == "\u4f60\u597d"


def test_extract_translation_text_handles_empty_input():
    is_command, text = extract_translation_text("\u7ffb\u8bd1")

    assert is_command is True
    assert text == ""


def test_extract_translation_text_ignores_non_command_mentions():
    is_command, text = extract_translation_text(
        "\u6709\u6ca1\u6709\u6548\u679c\u7c7b\u4f3c\u6211\u8eab\u4f5c\u76fe\u7684\u5361\uff1f"
    )

    assert is_command is False
    assert text == "\u6709\u6ca1\u6709\u6548\u679c\u7c7b\u4f3c\u6211\u8eab\u4f5c\u76fe\u7684\u5361\uff1f"


def test_extract_translation_request_accepts_bot_at_mention():
    segments = [
        FakeSegment("at", qq="12345"),
        FakeSegment("text", " \u7ffb\u8bd1 Once per turn."),
    ]

    mentioned, is_command, text = extract_translation_request(segments, "12345")

    assert mentioned is True
    assert is_command is True
    assert text == "Once per turn."


def test_extract_translation_request_accepts_text_mention_fallback():
    segments = [
        FakeSegment("text", "@\u795e\u4eba \u7ffb\u8bd1 Once per turn."),
    ]

    mentioned, is_command, text = extract_translation_request(segments, "12345")

    assert mentioned is True
    assert is_command is True
    assert text == "Once per turn."


def test_extract_translation_request_accepts_nonebot_to_me_fallback():
    segments = [FakeSegment("text", " \u7ffb\u8bd1 Once per turn.")]

    mentioned, is_command, text = extract_translation_request(
        segments,
        "12345",
        plain_text=" \u7ffb\u8bd1 Once per turn.",
        to_me=True,
    )

    assert mentioned is True
    assert is_command is True
    assert text == "Once per turn."


def test_extract_translation_request_does_not_trigger_without_mention():
    segments = [FakeSegment("text", " \u7ffb\u8bd1 Once per turn.")]

    mentioned, is_command, text = extract_translation_request(
        segments,
        "12345",
        plain_text=" \u7ffb\u8bd1 Once per turn.",
        to_me=False,
    )

    assert mentioned is False
    assert is_command is False
    assert text == "\u7ffb\u8bd1 Once per turn."


def test_translation_command_can_be_used_to_prevent_rag_fallthrough():
    segments = [
        FakeSegment("at", qq="12345"),
        FakeSegment("text", " \u7ffb\u8bd1 Once per turn."),
    ]

    mentioned, is_command, _ = extract_translation_request(segments, "12345")

    assert mentioned is True
    assert is_command is True


def test_build_translation_message_texts_prefers_structured_blocks_and_warnings():
    response = YgoRagTranslationResponse(
        translation="\u603b\u7ffb\u8bd1",
        warnings=["slow llm"],
        blocks=[
            TranslationBlock(text="\u7b2c\u4e00\u6bb5", truncated=False),
            TranslationBlock(text="\u7b2c\u4e8c\u6bb5", truncated=True),
        ],
        source_lang="en",
        target_lang="zh-CN",
    )

    texts = build_translation_message_texts("Once per turn.", response)

    assert texts == [
        "\u7ffb\u8bd1\u8bf7\u6c42\uff1aOnce per turn.\n\u8b66\u544a\uff1a\nslow llm",
        "\u7b2c\u4e00\u6bb5",
        "\u7b2c\u4e8c\u6bb5\n\n\uff08\u6b64\u7ffb\u8bd1\u5757\u5df2\u622a\u65ad\uff09",
    ]


def test_build_translation_message_texts_falls_back_to_translation_chunks():
    response = YgoRagTranslationResponse(
        translation="abcdef",
        warnings=[],
        blocks=[],
        source_lang="en",
        target_lang="zh-CN",
    )

    texts = build_translation_message_texts(
        "abcdef",
        response,
        fallback_chunk_size=3,
    )

    assert texts == ["abc", "def"]
