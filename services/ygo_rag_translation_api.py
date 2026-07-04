import os
from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_TRANSLATE_API_URL = "http://127.0.0.1:7860/api/translate"
DEFAULT_TRANSLATE_TIMEOUT_SECONDS = 120.0
DEFAULT_TRANSLATE_SOURCE_LANG = "auto"
DEFAULT_TRANSLATE_TARGET_LANG = "zh-CN"
DEFAULT_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS = 1800

TRANSLATION_TIMEOUT = "\u7ffb\u8bd1\u8bf7\u6c42\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"
TRANSLATION_HTTP_ERROR = "\u7ffb\u8bd1\u670d\u52a1\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"
TRANSLATION_NETWORK_ERROR = "\u65e0\u6cd5\u8fde\u63a5\u7ffb\u8bd1\u670d\u52a1\uff0c\u8bf7\u786e\u8ba4\u670d\u52a1\u5df2\u542f\u52a8\u3002"
TRANSLATION_INVALID_RESPONSE = "\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6548\u54cd\u5e94\u3002"


@dataclass(frozen=True)
class YgoRagTranslationSettings:
    api_url: str = DEFAULT_TRANSLATE_API_URL
    timeout_seconds: float = DEFAULT_TRANSLATE_TIMEOUT_SECONDS
    source_lang: str = DEFAULT_TRANSLATE_SOURCE_LANG
    target_lang: str = DEFAULT_TRANSLATE_TARGET_LANG
    structured_max_block_chars: int = DEFAULT_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS

    @classmethod
    def from_env(cls) -> "YgoRagTranslationSettings":
        return cls(
            api_url=os.getenv("YGO_RAG_TRANSLATE_API_URL", DEFAULT_TRANSLATE_API_URL),
            timeout_seconds=_get_env_float(
                "YGO_RAG_TRANSLATE_TIMEOUT_SECONDS",
                DEFAULT_TRANSLATE_TIMEOUT_SECONDS,
            ),
            source_lang=os.getenv(
                "YGO_RAG_TRANSLATE_SOURCE_LANG",
                DEFAULT_TRANSLATE_SOURCE_LANG,
            ),
            target_lang=os.getenv(
                "YGO_RAG_TRANSLATE_TARGET_LANG",
                DEFAULT_TRANSLATE_TARGET_LANG,
            ),
            structured_max_block_chars=_get_env_int(
                "YGO_RAG_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS",
                DEFAULT_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS,
            ),
        )


@dataclass(frozen=True)
class TranslationBlock:
    text: str
    truncated: bool = False
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class YgoRagTranslationResponse:
    translation: str
    warnings: list[str]
    blocks: list[TranslationBlock]
    source_lang: str
    target_lang: str


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


def build_translation_payload(
    text: str,
    settings: YgoRagTranslationSettings,
) -> dict[str, Any]:
    return {
        "text": text,
        "source_lang": settings.source_lang,
        "target_lang": settings.target_lang,
        "structured_max_block_chars": settings.structured_max_block_chars,
    }


async def translate_with_ygo_rag(
    text: str,
    settings: YgoRagTranslationSettings | None = None,
) -> YgoRagTranslationResponse:
    active_settings = settings or YgoRagTranslationSettings.from_env()
    payload = build_translation_payload(text, active_settings)

    async with httpx.AsyncClient(timeout=active_settings.timeout_seconds) as client:
        response = await client.post(active_settings.api_url, json=payload)
        response.raise_for_status()
        data = response.json()

    return parse_translation_response(data)


def parse_translation_response(data: dict[str, Any]) -> YgoRagTranslationResponse:
    translation = str(data.get("translation") or "").strip()
    warnings = _parse_warnings(data.get("warnings"))
    blocks = _parse_translation_blocks(data)

    if not translation and not blocks:
        raise ValueError(TRANSLATION_INVALID_RESPONSE)

    return YgoRagTranslationResponse(
        translation=translation,
        warnings=warnings,
        blocks=blocks,
        source_lang=str(data.get("source_lang") or "").strip(),
        target_lang=str(data.get("target_lang") or "").strip(),
    )


def _parse_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_translation_blocks(data: dict[str, Any]) -> list[TranslationBlock]:
    structured = data.get("structured")
    if not isinstance(structured, dict):
        return []

    blocks = structured.get("blocks")
    if not isinstance(blocks, list):
        return []

    translation_blocks: list[TranslationBlock] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "translation":
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        fields = block.get("fields")
        translation_blocks.append(
            TranslationBlock(
                text=text,
                truncated=bool(block.get("truncated", False)),
                fields=fields if isinstance(fields, dict) else {},
            )
        )

    return translation_blocks


def map_translation_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return TRANSLATION_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return TRANSLATION_HTTP_ERROR
    if isinstance(exc, httpx.RequestError):
        return TRANSLATION_NETWORK_ERROR
    if isinstance(exc, ValueError) and str(exc) == TRANSLATION_INVALID_RESPONSE:
        return TRANSLATION_INVALID_RESPONSE
    return TRANSLATION_HTTP_ERROR
