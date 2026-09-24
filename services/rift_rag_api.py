"""Riftbound 规则 RAG HTTP 客户端（contract v2，容忍旧版响应）。"""
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from services.qa_common import (
    RIFT_QA_EMPTY_RESULT,
    map_rag_qa_error,
    rift_rag_qa_base_url,
)

DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_TOP_K = 6
DEFAULT_MODE = "agent"
VALID_MODES = ("agent", "oneshot")


@dataclass(frozen=True)
class RiftRagSettings:
    base_url: str = field(default_factory=rift_rag_qa_base_url)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    top_k: int = DEFAULT_TOP_K
    mode: str = DEFAULT_MODE
    trace: bool = False

    @property
    def api_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/query"

    @classmethod
    def from_env(cls) -> "RiftRagSettings":
        return cls(
            base_url=rift_rag_qa_base_url(),
            timeout_seconds=_get_env_float(
                ("RIFT_RAG_TIMEOUT_SECONDS", "RIFT_QA_TIMEOUT_SECONDS"),
                DEFAULT_TIMEOUT_SECONDS,
            ),
            top_k=_get_env_int("RIFT_RAG_TOP_K", DEFAULT_TOP_K),
            mode=_get_env_mode("RIFT_RAG_MODE", DEFAULT_MODE),
            trace=_get_env_flag("RIFT_RAG_TRACE", False),
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
    resolved_cards: list[dict[str, Any]] = field(default_factory=list)
    unresolved_mentions: list[str] = field(default_factory=list)
    ambiguous_mentions: list[dict[str, Any]] = field(default_factory=list)
    exhausted: bool = False


def _get_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_env_float(names: str | tuple[str, ...], default: float) -> float:
    if isinstance(names, str):
        names = (names,)
    value = _get_env_value(*names)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _get_env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _get_env_mode(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    mode = value.strip().lower()
    return mode if mode in VALID_MODES else default


def build_rift_rag_payload(question: str, settings: RiftRagSettings) -> dict[str, Any]:
    return {
        "query": question,
        "top_k": settings.top_k,
        "mode": settings.mode,
        "trace": settings.trace,
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
        raise ValueError(RIFT_QA_EMPTY_RESULT)

    return RiftRagResponse(
        answer=answer,
        warnings=warnings,
        sources=sources,
        resolved_cards=_parse_resolved_cards(data.get("resolved_cards")),
        unresolved_mentions=_parse_string_list(
            _coverage_value(data, "unresolved_mentions")
        ),
        ambiguous_mentions=_parse_ambiguous_mentions(
            _coverage_value(data, "ambiguous_mentions")
        ),
        exhausted=_parse_exhausted(data.get("exhausted")),
    )


def _parse_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_string_list(value: Any) -> list[str]:
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
        topic = item.get("topic")
        topic = topic.strip() if isinstance(topic, str) else ""
        sources.append(RagSource(rule_id=rule_id, topic=topic))
    return sources


def _coverage_value(data: dict[str, Any], key: str) -> Any:
    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        return None
    return coverage.get(key)


def _parse_resolved_cards(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, dict) and str(item.get("card_id") or "").strip()
    ]


def _parse_ambiguous_mentions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _parse_exhausted(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def map_rift_rag_error(exc: Exception) -> str:
    return map_rag_qa_error(exc)
