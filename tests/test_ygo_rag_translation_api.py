import httpx
import pytest

from services.ygo_rag_translation_api import (
    TRANSLATION_HTTP_ERROR,
    TRANSLATION_INVALID_RESPONSE,
    TRANSLATION_NETWORK_ERROR,
    TRANSLATION_TIMEOUT,
    YgoRagTranslationSettings,
    build_translation_payload,
    map_translation_error,
    parse_translation_response,
)


def test_translation_settings_from_env_uses_defaults_when_unset(monkeypatch):
    for key in [
        "YGO_RAG_TRANSLATE_API_URL",
        "YGO_RAG_TRANSLATE_TIMEOUT_SECONDS",
        "YGO_RAG_TRANSLATE_SOURCE_LANG",
        "YGO_RAG_TRANSLATE_TARGET_LANG",
        "YGO_RAG_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = YgoRagTranslationSettings.from_env()

    assert settings.api_url == "http://127.0.0.1:7860/api/translate"
    assert settings.timeout_seconds == 120.0
    assert settings.source_lang == "auto"
    assert settings.target_lang == "zh-CN"
    assert settings.structured_max_block_chars == 1800


def test_build_translation_payload_includes_agent_contract_fields():
    settings = YgoRagTranslationSettings(
        api_url="http://x/api/translate",
        timeout_seconds=10,
        source_lang="en",
        target_lang="zh-CN",
        structured_max_block_chars=500,
    )

    payload = build_translation_payload("Once per turn", settings)

    assert payload == {
        "text": "Once per turn",
        "source_lang": "en",
        "target_lang": "zh-CN",
        "structured_max_block_chars": 500,
    }


def test_parse_translation_response_returns_translation_warnings_and_blocks():
    response = parse_translation_response(
        {
            "translation": "\u4e00\u56de\u5408\u4e00\u6b21",
            "source_lang": "en",
            "target_lang": "zh-CN",
            "warnings": ["fallback"],
            "structured": {
                "blocks": [
                    {
                        "type": "translation",
                        "text": "\u4e00\u56de\u5408\u4e00\u6b21",
                        "truncated": False,
                        "fields": {"part": 1, "total_parts": 2},
                    },
                    {
                        "type": "translation",
                        "text": "\u7834\u574f\u5b83",
                        "truncated": True,
                    },
                    {
                        "type": "card",
                        "text": "ignored",
                    },
                ]
            },
        }
    )

    assert response.translation == "\u4e00\u56de\u5408\u4e00\u6b21"
    assert response.source_lang == "en"
    assert response.target_lang == "zh-CN"
    assert response.warnings == ["fallback"]
    assert [block.text for block in response.blocks] == [
        "\u4e00\u56de\u5408\u4e00\u6b21",
        "\u7834\u574f\u5b83",
    ]
    assert response.blocks[1].truncated is True


def test_parse_translation_response_rejects_payload_without_translation_or_blocks():
    with pytest.raises(ValueError, match=TRANSLATION_INVALID_RESPONSE):
        parse_translation_response({"warnings": []})


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.TimeoutException("slow"), TRANSLATION_TIMEOUT),
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(500),
            ),
            TRANSLATION_HTTP_ERROR,
        ),
        (httpx.ConnectError("down"), TRANSLATION_NETWORK_ERROR),
        (ValueError(TRANSLATION_INVALID_RESPONSE), TRANSLATION_INVALID_RESPONSE),
    ],
)
def test_map_translation_error_returns_user_facing_messages(exc, message):
    assert map_translation_error(exc) == message
