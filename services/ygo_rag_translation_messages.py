import os

from services.ygo_rag_messages import (
    chunk_text,
    extract_rag_question,
)
from services.ygo_rag_translation_api import YgoRagTranslationResponse


DEFAULT_TRANSLATION_COMMAND_ALIASES = ("\u7ffb\u8bd1", "translate")
TRANSLATION_COMMAND_ALIASES_ENV = "YGO_RAG_TRANSLATE_COMMAND_ALIASES"
DEFAULT_TRANSLATION_CHUNK_SIZE = 1800


def get_translation_command_aliases(env_value: str | None = None) -> list[str]:
    raw_value = (
        os.getenv(TRANSLATION_COMMAND_ALIASES_ENV)
        if env_value is None
        else env_value
    )
    if raw_value is None:
        return list(DEFAULT_TRANSLATION_COMMAND_ALIASES)

    aliases = [alias.strip().lower() for alias in raw_value.split(",")]
    return [alias for alias in aliases if alias]


def extract_translation_text(
    text: str,
    aliases: list[str] | tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    stripped = text.strip()
    lowered = stripped.lower()
    active_aliases = aliases if aliases is not None else get_translation_command_aliases()

    for alias in active_aliases:
        normalized_alias = alias.lower()
        if lowered == normalized_alias:
            return True, ""
        if lowered.startswith(normalized_alias):
            next_index = len(normalized_alias)
            if stripped[next_index : next_index + 1] in {"", " ", "\t", "\n", "\r", "\uff1a", ":"}:
                return True, stripped[next_index:].lstrip(" \t\r\n\uff1a:").strip()

    return False, stripped


def extract_translation_request(
    message,
    bot_id: str,
    *,
    plain_text: str | None = None,
    to_me: bool = False,
) -> tuple[bool, bool, str]:
    mentioned, text = extract_rag_question(
        message,
        bot_id,
        plain_text=plain_text,
        to_me=to_me,
    )
    if not mentioned:
        return False, False, text

    is_command, translation_text = extract_translation_text(text)
    return True, is_command, translation_text


def build_translation_message_texts(
    request_text: str,
    response: YgoRagTranslationResponse,
    *,
    fallback_chunk_size: int = DEFAULT_TRANSLATION_CHUNK_SIZE,
) -> list[str]:
    messages: list[str] = []

    if response.warnings:
        messages.append(
            f"\u7ffb\u8bd1\u8bf7\u6c42\uff1a{request_text}\n"
            + "\u8b66\u544a\uff1a\n"
            + "\n".join(response.warnings)
        )

    if response.blocks:
        for block in response.blocks:
            text = block.text
            if block.truncated:
                text += "\n\n\uff08\u6b64\u7ffb\u8bd1\u5757\u5df2\u622a\u65ad\uff09"
            messages.append(text)
        return messages

    messages.extend(chunk_text(response.translation, fallback_chunk_size))
    return messages
