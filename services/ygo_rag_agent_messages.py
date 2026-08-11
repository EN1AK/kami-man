from typing import Any

from services.ygo_rag_agent_api import AgentToolBlock, YgoRagAgentResponse
from services.ygo_rag_messages import FALLBACK_CHUNK_SIZE, chunk_text


def build_rag_agent_message_texts(
    question: str,
    response: YgoRagAgentResponse,
    *,
    fallback_chunk_size: int = FALLBACK_CHUNK_SIZE,
) -> list[str]:
    messages: list[str] = []
    header_parts = [f"问题：{question}"]

    if response.answer:
        header_parts.append(f"回答：{response.answer}")

    warning_lines = list(response.warnings)
    if response.exhausted:
        warning_lines.append("Agent 已达到最大工具轮次，以下结果可能不完整。")
    if warning_lines:
        header_parts.append("警告：\n" + "\n".join(dict.fromkeys(warning_lines)))

    detail_messages = _build_tool_detail_messages(response.tool_blocks)

    if response.answer or warning_lines:
        messages.append("\n".join(header_parts))

    if detail_messages:
        messages.extend(detail_messages)
        return messages

    if response.answer and not messages:
        messages.extend(chunk_text(response.answer, fallback_chunk_size))
    return messages


def _build_tool_detail_messages(blocks: list[AgentToolBlock]) -> list[str]:
    messages: list[str] = []
    for block in blocks:
        nested = _extract_nested_structured_texts(block.result)
        if nested:
            messages.extend(nested)
            continue

        text = _extract_tool_fallback_text(block)
        if text:
            messages.append(text)
    return messages


def _extract_nested_structured_texts(result: dict[str, Any]) -> list[str]:
    structured = result.get("structured")
    if not isinstance(structured, dict):
        return []
    blocks = structured.get("blocks")
    if not isinstance(blocks, list):
        return []

    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {"card", "translation"}:
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        if block.get("truncated"):
            text += "\n\n（此结果块已截断）"
        texts.append(text)
    return texts


def _extract_tool_fallback_text(block: AgentToolBlock) -> str:
    result = block.result
    if block.tool == "adjudicate":
        natural_answer = str(result.get("natural_answer") or "").strip()
        if natural_answer:
            return natural_answer
        answer = str(result.get("answer") or "").strip()
        if answer:
            return answer

    if block.tool == "translate_text":
        translation = str(result.get("translation") or "").strip()
        if translation:
            return translation

    answer = str(result.get("answer") or "").strip()
    if answer:
        return answer

    if block.summary:
        status = "成功" if block.ok else "失败"
        return f"{block.tool}（{status}）：{block.summary}"

    return ""
