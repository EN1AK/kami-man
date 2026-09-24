import httpx
import pytest

import services
from services.qa_common import (
    RIFT_QA_CONNECT_ERROR,
    RIFT_QA_EMPTY_RESULT,
    RIFT_QA_FORMAT_ERROR,
    RIFT_QA_INTERNAL_ERROR,
    RIFT_QA_TIMEOUT,
    RIFT_QA_UPSTREAM_ERROR,
)
from services.rift_rag_api import (
    RiftRagSettings,
    build_rift_rag_payload,
    map_rift_rag_error,
    parse_rift_rag_response,
)

ENV_KEYS = [
    "RIFT_RAG_BASE_URL",
    "RIFT_QA_BASE_URL",
    "RIFT_RAG_TIMEOUT_SECONDS",
    "RIFT_QA_TIMEOUT_SECONDS",
    "RIFT_RAG_TOP_K",
    "RIFT_RAG_MODE",
    "RIFT_RAG_TRACE",
]


def clear_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_services_exposes_rift_rag_qa_base_url_default(monkeypatch):
    clear_env(monkeypatch)

    assert services.rift_rag_qa_base_url() == "http://127.0.0.1:7862"


def test_services_rift_rag_qa_base_url_from_env(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("RIFT_RAG_BASE_URL", "http://127.0.0.1:9000/")
    assert services.rift_rag_qa_base_url() == "http://127.0.0.1:9000"

    monkeypatch.delenv("RIFT_RAG_BASE_URL")
    monkeypatch.setenv("RIFT_QA_BASE_URL", "http://10.0.0.2:7862")
    assert services.rift_rag_qa_base_url() == "http://10.0.0.2:7862"


def test_settings_from_env_uses_defaults_when_unset(monkeypatch):
    clear_env(monkeypatch)

    settings = RiftRagSettings.from_env()

    assert settings.base_url == "http://127.0.0.1:7862"
    assert settings.api_url == "http://127.0.0.1:7862/api/query"
    assert settings.timeout_seconds == 240.0
    assert settings.top_k == 6
    assert settings.mode == "agent"
    assert settings.trace is False


def test_settings_from_env_reads_overrides(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("RIFT_RAG_BASE_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("RIFT_RAG_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("RIFT_RAG_TOP_K", "10")
    monkeypatch.setenv("RIFT_RAG_MODE", "oneshot")
    monkeypatch.setenv("RIFT_RAG_TRACE", "1")

    settings = RiftRagSettings.from_env()

    assert settings.api_url == "http://127.0.0.1:9000/api/query"
    assert settings.timeout_seconds == 60.0
    assert settings.top_k == 10
    assert settings.mode == "oneshot"
    assert settings.trace is True


def test_settings_timeout_falls_back_to_legacy_qa_key(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("RIFT_QA_TIMEOUT_SECONDS", "30")

    assert RiftRagSettings.from_env().timeout_seconds == 30.0


def test_settings_invalid_mode_falls_back_to_agent(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("RIFT_RAG_MODE", "weird")

    assert RiftRagSettings.from_env().mode == "agent"


def test_build_rift_rag_payload_contains_query_mode_and_trace(monkeypatch):
    clear_env(monkeypatch)

    payload = build_rift_rag_payload("伤害结算时守卫什么时候生效", RiftRagSettings())

    assert payload == {
        "query": "伤害结算时守卫什么时候生效",
        "top_k": 6,
        "mode": "agent",
        "trace": False,
    }


def test_parse_rift_rag_response_parses_full_v2_payload():
    response = parse_rift_rag_response(
        {
            "answer": "先给结论 [R-CR-465.2]",
            "warnings": ["向量召回失败，已退回关键词召回"],
            "sources": [
                {"rule_id": "R-CR-465.2", "topic": "465.2 Step 2"},
                {"rule_id": "", "topic": "缺少 rule_id 应被丢弃"},
                {"rule_id": "R-CR-814.1.d.1", "topic": 1234},
                "非对象条目应被丢弃",
            ],
            "mode": "agent",
            "exhausted": True,
            "resolved_cards": [
                {
                    "card_id": "OGN-242",
                    "mention": "海兽钓钩",
                    "name_cn": "海兽钓钩",
                    "name_en": "Baited Hook",
                    "confidence": "exact",
                    "source": "deterministic",
                },
                {"name_cn": "缺少 card_id 应被丢弃"},
                "非对象条目应被丢弃",
            ],
            "coverage": {
                "unresolved_mentions": ["某卡名", "  "],
                "ambiguous_mentions": [
                    {"mention": "蔚", "candidates": [{"card_id": "OGN-066a"}]},
                    "非对象条目应被丢弃",
                ],
            },
            "trace": [{"step": 1, "tool": "search_rules"}],
        }
    )

    assert response.answer == "先给结论 [R-CR-465.2]"
    assert response.warnings == ["向量召回失败，已退回关键词召回"]
    assert [(s.rule_id, s.topic) for s in response.sources] == [
        ("R-CR-465.2", "465.2 Step 2"),
        ("R-CR-814.1.d.1", ""),
    ]
    assert response.exhausted is True
    assert [card["card_id"] for card in response.resolved_cards] == ["OGN-242"]
    assert response.resolved_cards[0]["name_cn"] == "海兽钓钩"
    assert response.unresolved_mentions == ["某卡名"]
    assert response.ambiguous_mentions == [
        {"mention": "蔚", "candidates": [{"card_id": "OGN-066a"}]}
    ]


def test_parse_rift_rag_response_accepts_legacy_payload_without_v2_fields():
    response = parse_rift_rag_response(
        {
            "answer": "先给结论 [R-CR-465.2]",
            "warnings": [],
            "sources": [{"rule_id": "R-CR-465.2", "topic": "465.2 Step 2"}],
        }
    )

    assert response.answer == "先给结论 [R-CR-465.2]"
    assert response.resolved_cards == []
    assert response.unresolved_mentions == []
    assert response.ambiguous_mentions == []
    assert response.exhausted is False


def test_parse_rift_rag_response_tolerates_non_bool_exhausted():
    response = parse_rift_rag_response(
        {
            "answer": "结论",
            "warnings": [],
            "sources": [],
            "exhausted": "true",
        }
    )

    assert response.exhausted is False


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
    with pytest.raises(ValueError, match="RAG 服务返回了空结果"):
        parse_rift_rag_response({"warnings": []})


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.TimeoutException("slow"), RIFT_QA_TIMEOUT),
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(500),
            ),
            RIFT_QA_INTERNAL_ERROR,
        ),
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(400),
            ),
            RIFT_QA_UPSTREAM_ERROR,
        ),
        (httpx.ConnectError("down"), RIFT_QA_CONNECT_ERROR),
        (ValueError(RIFT_QA_EMPTY_RESULT), RIFT_QA_EMPTY_RESULT),
        (ValueError("bad json"), RIFT_QA_FORMAT_ERROR),
    ],
)
def test_map_rift_rag_error_returns_fixed_messages(exc, message):
    assert map_rift_rag_error(exc) == message
