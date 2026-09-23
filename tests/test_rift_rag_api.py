import httpx
import pytest

from services.rift_rag_api import (
    RIFT_RAG_HTTP_ERROR,
    RIFT_RAG_INVALID_RESPONSE,
    RIFT_RAG_NETWORK_ERROR,
    RIFT_RAG_TIMEOUT,
    RiftRagSettings,
    build_rift_rag_payload,
    map_rift_rag_error,
    parse_rift_rag_response,
)


def test_settings_from_env_uses_defaults_when_unset(monkeypatch):
    for key in [
        "RIFT_RAG_API_URL",
        "RIFT_RAG_TIMEOUT_SECONDS",
        "RIFT_RAG_TOP_K",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = RiftRagSettings.from_env()

    assert settings.api_url == "http://127.0.0.1:7862/api/query"
    assert settings.timeout_seconds == 240.0
    assert settings.top_k == 6


def test_settings_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("RIFT_RAG_API_URL", "http://127.0.0.1:9000/api/query")
    monkeypatch.setenv("RIFT_RAG_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("RIFT_RAG_TOP_K", "10")

    settings = RiftRagSettings.from_env()

    assert settings.api_url == "http://127.0.0.1:9000/api/query"
    assert settings.timeout_seconds == 60.0
    assert settings.top_k == 10


def test_build_rift_rag_payload():
    payload = build_rift_rag_payload("伤害结算时守卫什么时候生效", RiftRagSettings())

    assert payload == {
        "query": "伤害结算时守卫什么时候生效",
        "top_k": 6,
    }


def test_parse_rift_rag_response_returns_answer_warnings_and_sources():
    response = parse_rift_rag_response(
        {
            "answer": "先给结论 [R-CR-465.2]",
            "warnings": ["向量召回失败，已退回关键词召回"],
            "sources": [
                {"rule_id": "R-CR-465.2", "topic": "465.2 Step 2"},
                {"rule_id": "", "topic": "缺少 rule_id 应被丢弃"},
                {"rule_id": "R-CR-814.1.d.1"},
                "非对象条目应被丢弃",
            ],
        }
    )

    assert response.answer == "先给结论 [R-CR-465.2]"
    assert response.warnings == ["向量召回失败，已退回关键词召回"]
    assert [(s.rule_id, s.topic) for s in response.sources] == [
        ("R-CR-465.2", "465.2 Step 2"),
        ("R-CR-814.1.d.1", ""),
    ]


def test_parse_rift_rag_response_accepts_sources_without_answer():
    response = parse_rift_rag_response(
        {
            "answer": "",
            "warnings": ["仅检索模式"],
            "sources": [{"rule_id": "R-CR-465.2", "topic": "465.2"}],
        }
    )

    assert response.answer == ""
    assert response.warnings == ["仅检索模式"]
    assert response.sources[0].rule_id == "R-CR-465.2"


def test_parse_rift_rag_response_rejects_payload_without_answer_or_sources():
    with pytest.raises(ValueError, match=RIFT_RAG_INVALID_RESPONSE):
        parse_rift_rag_response({"warnings": []})


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.TimeoutException("slow"), RIFT_RAG_TIMEOUT),
        (httpx.HTTPStatusError("bad", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)), RIFT_RAG_HTTP_ERROR),
        (httpx.ConnectError("down"), RIFT_RAG_NETWORK_ERROR),
        (ValueError(RIFT_RAG_INVALID_RESPONSE), RIFT_RAG_INVALID_RESPONSE),
    ],
)
def test_map_rift_rag_error_returns_user_facing_messages(exc, message):
    assert map_rift_rag_error(exc) == message
