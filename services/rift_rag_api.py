import os
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_API_URL = "http://127.0.0.1:7862/api/query"
DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_TOP_K = 6

RIFT_RAG_TIMEOUT = "符文规则查询超时，请稍后再试。"
RIFT_RAG_HTTP_ERROR = "符文规则服务查询失败，请稍后再试。"
RIFT_RAG_NETWORK_ERROR = "无法连接符文规则服务，请确认服务已启动。"
RIFT_RAG_INVALID_RESPONSE = "符文规则服务返回了无效响应。"


@dataclass(frozen=True)
class RiftRagSettings:
    api_url: str = DEFAULT_API_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    top_k: int = DEFAULT_TOP_K

    @classmethod
    def from_env(cls) -> "RiftRagSettings":
        return cls(
            api_url=os.getenv("RIFT_RAG_API_URL", DEFAULT_API_URL),
            timeout_seconds=_get_env_float(
                "RIFT_RAG_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            top_k=_get_env_int("RIFT_RAG_TOP_K", DEFAULT_TOP_K),
        )


@dataclass(frozen=True)
class RagSource:
    rule_id: str
    topic: str


@dataclass(frozen=True)
class RiftRagResponse:
    answer: str
    warnings: list[str]
    sources: list[RagSource]


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


def build_rift_rag_payload(question: str, settings: RiftRagSettings) -> dict[str, Any]:
    return {
        "query": question,
        "top_k": settings.top_k,
    }


async def query_rift_rag(
    question: str,
    settings: RiftRagSettings | None = None,
) -> RiftRagResponse:
    active_settings = settings or RiftRagSettings.from_env()
    payload = build_rift_rag_payload(question, active_settings)

    async with httpx.AsyncClient(timeout=active_settings.timeout_seconds) as client:
        response = await client.post(active_settings.api_url, json=payload)
        response.raise_for_status()
        data = response.json()

    return parse_rift_rag_response(data)


def parse_rift_rag_response(data: dict[str, Any]) -> RiftRagResponse:
    answer = str(data.get("answer") or "").strip()
    warnings = _parse_warnings(data.get("warnings"))
    sources = _parse_sources(data.get("sources"))

    if not answer and not sources:
        raise ValueError(RIFT_RAG_INVALID_RESPONSE)

    return RiftRagResponse(
        answer=answer,
        warnings=warnings,
        sources=sources,
    )


def _parse_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_sources(value: Any) -> list[RagSource]:
    if not isinstance(value, list):
        return []
    sources: list[RagSource] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or "").strip()
        if not rule_id:
            continue
        topic = str(item.get("topic") or "").strip()
        sources.append(RagSource(rule_id=rule_id, topic=topic))
    return sources


def map_rift_rag_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return RIFT_RAG_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return RIFT_RAG_HTTP_ERROR
    if isinstance(exc, httpx.RequestError):
        return RIFT_RAG_NETWORK_ERROR
    if isinstance(exc, ValueError) and str(exc) == RIFT_RAG_INVALID_RESPONSE:
        return RIFT_RAG_INVALID_RESPONSE
    return RIFT_RAG_HTTP_ERROR
