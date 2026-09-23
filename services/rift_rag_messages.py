import os

from services.rift_rag_api import RiftRagResponse
from services.ygo_rag_messages import extract_rag_question as extract_ygo_rag_question


FALLBACK_CHUNK_SIZE = 1800
DEFAULT_TEXT_MENTION_ALIASES = ("符文规则",)
TEXT_MENTION_ALIASES_ENV = "RIFT_RAG_TEXT_MENTION_ALIASES"


def get_text_mention_aliases(env_value: str | None = None) -> list[str]:
    raw_value = os.getenv(TEXT_MENTION_ALIASES_ENV) if env_value is None else env_value
    if raw_value is None:
        return list(DEFAULT_TEXT_MENTION_ALIASES)

    aliases = [alias.strip().lstrip("@＠") for alias in raw_value.split(",")]
    return [alias for alias in aliases if alias]


def extract_text_mention_question(
    text: str,
    aliases: list[str] | tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    """别名可带 @/＠ 前缀，也可裸用（消息以别名开头即触发）。"""
    stripped = text.strip()
    active_aliases = aliases if aliases is not None else get_text_mention_aliases()

    for alias in active_aliases:
        for marker in (f"@{alias}", f"＠{alias}", alias):
            if stripped.startswith(marker):
                return True, stripped[len(marker):].strip()

    return False, stripped


def is_rift_alias_message(
    plain_text: str,
    message,
    bot_id: str,
    *,
    to_me: bool = False,
) -> bool:
    """符文规则别名消息判定；命中游戏王提及流的消息不触发（避免双重应答）。"""
    ygo_mentioned, _ = extract_ygo_rag_question(
        message,
        bot_id,
        plain_text=plain_text,
        to_me=to_me,
    )
    if ygo_mentioned:
        return False

    matched, _ = extract_text_mention_question(plain_text)
    return matched


def chunk_text(text: str, size: int = FALLBACK_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    if size <= 0:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)]


def build_source_list_text(sources) -> str:
    lines = ["参考条目："]
    for source in sources:
        if source.topic:
            lines.append(f"{source.rule_id} — {source.topic}")
        else:
            lines.append(source.rule_id)
    return "\n".join(lines)


def build_rift_rag_message_texts(
    question: str,
    response: RiftRagResponse,
    *,
    fallback_chunk_size: int = FALLBACK_CHUNK_SIZE,
) -> list[str]:
    messages: list[str] = []

    head = f"问题：{question}"
    if response.warnings:
        head += "\n警告：\n" + "\n".join(response.warnings)
    messages.append(head)

    messages.extend(chunk_text(response.answer, fallback_chunk_size))

    if response.sources:
        messages.append(build_source_list_text(response.sources))

    return messages
