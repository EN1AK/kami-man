import os
from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_API_URL = "http://127.0.0.1:7860/api/query"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_TOP_K = 5
DEFAULT_RERANK_CANDIDATES = 5
DEFAULT_STRUCTURED_MAX_BLOCK_CHARS = 1800

RAG_TIMEOUT = "RAG 查询超时，请稍后再试。"
RAG_HTTP_ERROR = "RAG 服务查询失败，请稍后再试。"
RAG_NETWORK_ERROR = "无法连接 RAG 服务，请确认服务已启动。"
RAG_INVALID_RESPONSE = "RAG 服务返回了无效响应。"


@dataclass(frozen=True)
class YgoRagSettings:
    api_url: str = DEFAULT_API_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    top_k: int = DEFAULT_TOP_K
    rerank_candidates: int = DEFAULT_RERANK_CANDIDATES
    structured_max_block_chars: int = DEFAULT_STRUCTURED_MAX_BLOCK_CHARS

    @classmethod
    def from_env(cls) -> "YgoRagSettings":
        return cls(
            api_url=os.getenv("YGO_RAG_API_URL", DEFAULT_API_URL),
            timeout_seconds=_get_env_float(
                "YGO_RAG_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            top_k=_get_env_int("YGO_RAG_TOP_K", DEFAULT_TOP_K),
            rerank_candidates=_get_env_int(
                "YGO_RAG_RERANK_CANDIDATES",
                DEFAULT_RERANK_CANDIDATES,
            ),
            structured_max_block_chars=_get_env_int(
                "YGO_RAG_STRUCTURED_MAX_BLOCK_CHARS",
                DEFAULT_STRUCTURED_MAX_BLOCK_CHARS,
            ),
        )


@dataclass(frozen=True)
class RagCardBlock:
    text: str
    truncated: bool = False
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class YgoRagResponse:
    answer: str
    warnings: list[str]
    card_blocks: list[RagCardBlock]


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


def build_rag_payload(question: str, settings: YgoRagSettings) -> dict[str, Any]:
    return {
        "query": question,
        "top_k": settings.top_k,
        "rerank_candidates": settings.rerank_candidates,
        "semantic": True,
        "rerank": False,
        "llm_rerank": True,
        "llm": True,
        "structured_max_block_chars": settings.structured_max_block_chars,
    }


async def query_ygo_rag(
    question: str,
    settings: YgoRagSettings | None = None,
) -> YgoRagResponse:
    active_settings = settings or YgoRagSettings.from_env()
    payload = build_rag_payload(question, active_settings)

    async with httpx.AsyncClient(timeout=active_settings.timeout_seconds) as client:
        response = await client.post(active_settings.api_url, json=payload)
        response.raise_for_status()
        data = response.json()

    return parse_rag_response(data)


def parse_rag_response(data: dict[str, Any]) -> YgoRagResponse:
    answer = str(data.get("answer") or "").strip()
    warnings = _parse_warnings(data.get("warnings"))
    card_blocks = _parse_card_blocks(data)

    if not answer and not card_blocks:
        raise ValueError(RAG_INVALID_RESPONSE)

    return YgoRagResponse(
        answer=answer,
        warnings=warnings,
        card_blocks=card_blocks,
    )


def _parse_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_card_blocks(data: dict[str, Any]) -> list[RagCardBlock]:
    structured = data.get("structured")
    if not isinstance(structured, dict):
        return []

    blocks = structured.get("blocks")
    if not isinstance(blocks, list):
        return []

    card_blocks: list[RagCardBlock] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "card":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        fields = block.get("fields")
        card_blocks.append(
            RagCardBlock(
                text=text,
                truncated=bool(block.get("truncated", False)),
                fields=fields if isinstance(fields, dict) else {},
            )
        )

    return card_blocks


def map_rag_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return RAG_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return RAG_HTTP_ERROR
    if isinstance(exc, httpx.RequestError):
        return RAG_NETWORK_ERROR
    if isinstance(exc, ValueError) and str(exc) == RAG_INVALID_RESPONSE:
        return RAG_INVALID_RESPONSE
    return RAG_HTTP_ERROR
