import os

from services.ygo_rag_api import YgoRagResponse


FALLBACK_CHUNK_SIZE = 1800
DEFAULT_TEXT_MENTION_ALIASES = ("\u795e\u4eba",)
TEXT_MENTION_ALIASES_ENV = "YGO_RAG_TEXT_MENTION_ALIASES"


def get_text_mention_aliases(env_value: str | None = None) -> list[str]:
    raw_value = os.getenv(TEXT_MENTION_ALIASES_ENV) if env_value is None else env_value
    if raw_value is None:
        return list(DEFAULT_TEXT_MENTION_ALIASES)

    aliases = [alias.strip().lstrip("@\uff20") for alias in raw_value.split(",")]
    return [alias for alias in aliases if alias]


def extract_text_mention_question(
    text: str,
    aliases: list[str] | tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    stripped = text.strip()
    active_aliases = aliases if aliases is not None else get_text_mention_aliases()

    for prefix in ("@", "\uff20"):
        for alias in active_aliases:
            marker = f"{prefix}{alias}"
            if stripped.startswith(marker):
                return True, stripped[len(marker) :].strip()

    return False, stripped


def extract_mentioned_question(message, bot_id: str) -> tuple[bool, str]:
    mentioned = False
    parts: list[str] = []

    for seg in message:
        if seg.type == "at" and str(seg.data.get("qq")) == str(bot_id):
            mentioned = True
            continue
        if seg.type == "text":
            parts.append(str(seg))
        elif seg.type != "at":
            parts.append(str(seg))

    question = "".join(parts).strip()
    if mentioned:
        return True, question

    return extract_text_mention_question(question)


def chunk_text(text: str, size: int = FALLBACK_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    if size <= 0:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)]


def build_rag_message_texts(
    question: str,
    response: YgoRagResponse,
    *,
    fallback_chunk_size: int = FALLBACK_CHUNK_SIZE,
) -> list[str]:
    messages: list[str] = []

    if response.warnings:
        messages.append(f"问题：{question}\n警告：\n" + "\n".join(response.warnings))

    if response.card_blocks:
        for block in response.card_blocks:
            text = block.text
            if block.truncated:
                text += "\n\n（此卡片块已截断）"
            messages.append(text)
        return messages

    messages.extend(chunk_text(response.answer, fallback_chunk_size))
    return messages
