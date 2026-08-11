import os
from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_AGENT_API_URL = "http://127.0.0.1:7860/api/agent"
DEFAULT_AGENT_TIMEOUT_SECONDS = 240.0
DEFAULT_AGENT_MAX_STEPS = 6
DEFAULT_AGENT_STRUCTURED_MAX_BLOCK_CHARS = 1800

AGENT_TIMEOUT = "RAG Agent 请求超时，请稍后再试。"
AGENT_HTTP_ERROR = "RAG Agent 服务请求失败，请稍后再试。"
AGENT_NETWORK_ERROR = "无法连接 RAG Agent 服务，请确认服务已启动。"
AGENT_INVALID_RESPONSE = "RAG Agent 服务返回了无效响应。"


@dataclass(frozen=True)
class YgoRagAgentSettings:
    api_url: str = DEFAULT_AGENT_API_URL
    timeout_seconds: float = DEFAULT_AGENT_TIMEOUT_SECONDS
    max_steps: int = DEFAULT_AGENT_MAX_STEPS
    structured_max_block_chars: int = DEFAULT_AGENT_STRUCTURED_MAX_BLOCK_CHARS

    @classmethod
    def from_env(cls) -> "YgoRagAgentSettings":
        return cls(
            api_url=os.getenv("YGO_RAG_AGENT_API_URL", DEFAULT_AGENT_API_URL),
            timeout_seconds=_get_env_float(
                "YGO_RAG_AGENT_TIMEOUT_SECONDS",
                DEFAULT_AGENT_TIMEOUT_SECONDS,
            ),
            max_steps=_get_env_int("YGO_RAG_AGENT_MAX_STEPS", DEFAULT_AGENT_MAX_STEPS),
            structured_max_block_chars=_get_env_int(
                "YGO_RAG_AGENT_STRUCTURED_MAX_BLOCK_CHARS",
                DEFAULT_AGENT_STRUCTURED_MAX_BLOCK_CHARS,
            ),
        )


@dataclass(frozen=True)
class AgentToolBlock:
    tool: str
    ok: bool
    summary: str
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class YgoRagAgentResponse:
    answer: str
    warnings: list[str]
    exhausted: bool
    tool_blocks: list[AgentToolBlock]


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def build_agent_payload(question: str, settings: YgoRagAgentSettings) -> dict[str, Any]:
    return {
        "text": question,
        "semantic": True,
        "rerank": False,
        "llm_rerank": True,
        "max_steps": settings.max_steps,
        "structured_max_block_chars": settings.structured_max_block_chars,
    }


async def query_ygo_rag_agent(
    question: str,
    settings: YgoRagAgentSettings | None = None,
) -> YgoRagAgentResponse:
    active_settings = settings or YgoRagAgentSettings.from_env()
    payload = build_agent_payload(question, active_settings)

    async with httpx.AsyncClient(timeout=active_settings.timeout_seconds) as client:
        response = await client.post(active_settings.api_url, json=payload)
        response.raise_for_status()
        data = response.json()

    return parse_agent_response(data)


def parse_agent_response(data: dict[str, Any]) -> YgoRagAgentResponse:
    answer = str(data.get("answer") or "").strip()
    warnings = _parse_warnings(data.get("warnings"))
    exhausted = bool(data.get("exhausted", False))
    tool_blocks = _parse_tool_blocks(data)

    if not answer and not tool_blocks:
        raise ValueError(AGENT_INVALID_RESPONSE)

    return YgoRagAgentResponse(
        answer=answer,
        warnings=warnings,
        exhausted=exhausted,
        tool_blocks=tool_blocks,
    )


def _parse_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_tool_blocks(data: dict[str, Any]) -> list[AgentToolBlock]:
    structured = data.get("structured")
    if not isinstance(structured, dict):
        return []

    blocks = structured.get("blocks")
    if not isinstance(blocks, list):
        return []

    tool_blocks: list[AgentToolBlock] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        tool = str(block.get("tool") or "").strip()
        if not tool:
            continue
        result = block.get("result")
        tool_blocks.append(
            AgentToolBlock(
                tool=tool,
                ok=bool(block.get("ok", False)),
                summary=str(block.get("summary") or "").strip(),
                result=result if isinstance(result, dict) else {},
            )
        )

    return tool_blocks


def map_agent_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return AGENT_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return AGENT_HTTP_ERROR
    if isinstance(exc, httpx.RequestError):
        return AGENT_NETWORK_ERROR
    if isinstance(exc, ValueError) and str(exc) == AGENT_INVALID_RESPONSE:
        return AGENT_INVALID_RESPONSE
    return AGENT_HTTP_ERROR
