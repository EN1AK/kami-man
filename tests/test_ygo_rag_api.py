import httpx
import pytest

from services.ygo_rag_api import (
    RAG_HTTP_ERROR,
    RAG_INVALID_RESPONSE,
    RAG_NETWORK_ERROR,
    RAG_TIMEOUT,
    YgoRagSettings,
    build_rag_payload,
    map_rag_error,
    parse_rag_response,
)


def test_settings_from_env_uses_defaults_when_unset(monkeypatch):
    for key in [
        "YGO_RAG_API_URL",
        "YGO_RAG_TIMEOUT_SECONDS",
        "YGO_RAG_TOP_K",
        "YGO_RAG_RERANK_CANDIDATES",
        "YGO_RAG_STRUCTURED_MAX_BLOCK_CHARS",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = YgoRagSettings.from_env()

    assert settings.api_url == "http://127.0.0.1:7860/api/query"
    assert settings.timeout_seconds == 120.0
    assert settings.top_k == 5
    assert settings.rerank_candidates == 5
    assert settings.structured_max_block_chars == 1800


def test_build_rag_payload_enables_llm_rerank_and_llm_by_default():
    settings = YgoRagSettings()

    payload = build_rag_payload("有没有效果类似我身作盾的卡", settings)

    assert payload == {
        "query": "有没有效果类似我身作盾的卡",
        "top_k": 5,
        "rerank_candidates": 5,
        "semantic": True,
        "rerank": False,
        "llm_rerank": True,
        "llm": True,
        "structured_max_block_chars": 1800,
    }


def test_parse_rag_response_returns_answer_warnings_and_card_blocks():
    response = parse_rag_response(
        {
            "answer": "总体回答",
            "warnings": ["llm rerank fallback"],
            "structured": {
                "blocks": [
                    {
                        "type": "card",
                        "text": "1. 我身作盾\n理由: ...",
                        "truncated": False,
                    },
                    {
                        "type": "note",
                        "text": "ignored",
                    },
                    {
                        "type": "card",
                        "text": "2. 神之宣告\n理由: ...",
                        "truncated": True,
                    },
                ]
            },
        }
    )

    assert response.answer == "总体回答"
    assert response.warnings == ["llm rerank fallback"]
    assert [block.text for block in response.card_blocks] == [
        "1. 我身作盾\n理由: ...",
        "2. 神之宣告\n理由: ...",
    ]
    assert response.card_blocks[1].truncated is True


def test_parse_rag_response_rejects_payload_without_answer_or_blocks():
    with pytest.raises(ValueError, match=RAG_INVALID_RESPONSE):
        parse_rag_response({"warnings": []})


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.TimeoutException("slow"), RAG_TIMEOUT),
        (httpx.HTTPStatusError("bad", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)), RAG_HTTP_ERROR),
        (httpx.ConnectError("down"), RAG_NETWORK_ERROR),
        (ValueError(RAG_INVALID_RESPONSE), RAG_INVALID_RESPONSE),
    ],
)
def test_map_rag_error_returns_user_facing_messages(exc, message):
    assert map_rag_error(exc) == message
