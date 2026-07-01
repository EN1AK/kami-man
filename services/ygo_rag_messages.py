from services.ygo_rag_api import YgoRagResponse


FALLBACK_CHUNK_SIZE = 1800


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

    return mentioned, "".join(parts).strip()


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
