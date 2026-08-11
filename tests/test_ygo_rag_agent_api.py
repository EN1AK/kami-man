import httpx
import pytest

from services.ygo_rag_agent_api import (
    AGENT_HTTP_ERROR,
    AGENT_INVALID_RESPONSE,
    AGENT_NETWORK_ERROR,
    AGENT_TIMEOUT,
    YgoRagAgentSettings,
    build_agent_payload,
    map_agent_error,
    parse_agent_response,
)


def test_agent_settings_from_env_uses_defaults_when_unset(monkeypatch):
    for key in [
        "YGO_RAG_AGENT_API_URL",
        "YGO_RAG_AGENT_TIMEOUT_SECONDS",
        "YGO_RAG_AGENT_MAX_STEPS",
        "YGO_RAG_AGENT_STRUCTURED_MAX_BLOCK_CHARS",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = YgoRagAgentSettings.from_env()

    assert settings.api_url == "http://127.0.0.1:7860/api/agent"
    assert settings.timeout_seconds == 240.0
    assert settings.max_steps == 6
    assert settings.structured_max_block_chars == 1800


def test_build_agent_payload_enables_unified_agent_defaults():
    settings = YgoRagAgentSettings(max_steps=4, structured_max_block_chars=900)

    payload = build_agent_payload("这个场景能不能发动？", settings)

    assert payload == {
        "text": "这个场景能不能发动？",
        "semantic": True,
        "rerank": False,
        "llm_rerank": True,
        "max_steps": 4,
        "structured_max_block_chars": 900,
    }


def test_parse_agent_response_returns_answer_warnings_and_tool_blocks():
    response = parse_agent_response(
        {
            "answer": "可以发动。",
            "warnings": ["evidence incomplete"],
            "exhausted": False,
            "structured": {
                "blocks": [
                    {
                        "type": "tool_result",
                        "tool": "adjudicate",
                        "ok": True,
                        "summary": "裁定完成。",
                        "result": {"natural_answer": "裁定依据..."},
                    },
                    {"type": "note", "tool": "ignored"},
                ]
            },
        }
    )

    assert response.answer == "可以发动。"
    assert response.warnings == ["evidence incomplete"]
    assert response.exhausted is False
    assert len(response.tool_blocks) == 1
    assert response.tool_blocks[0].tool == "adjudicate"
    assert response.tool_blocks[0].result["natural_answer"] == "裁定依据..."


def test_parse_agent_response_rejects_payload_without_answer_or_blocks():
    with pytest.raises(ValueError, match=AGENT_INVALID_RESPONSE):
        parse_agent_response({"warnings": []})


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.TimeoutException("slow"), AGENT_TIMEOUT),
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(500),
            ),
            AGENT_HTTP_ERROR,
        ),
        (httpx.ConnectError("down"), AGENT_NETWORK_ERROR),
        (ValueError(AGENT_INVALID_RESPONSE), AGENT_INVALID_RESPONSE),
    ],
)
def test_map_agent_error_returns_user_facing_messages(exc, message):
    assert map_agent_error(exc) == message
