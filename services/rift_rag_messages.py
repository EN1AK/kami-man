"""Riftbound 规则 RAG 问答的消息构建：别名抽取 + 合并转发节点。"""
import os
from typing import Any

from services.qa_common import rift_rag_qa_base_url
from services.rift_rag_api import RiftRagResponse
from services.ygo_rag_messages import extract_rag_question as extract_ygo_rag_question

# 顺序即匹配优先级：先长后短，保证 "问下规则"/"问规则" 先于 "规则" 命中
DEFAULT_TEXT_MENTION_ALIASES = ("问下规则", "问规则", "规则")
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


def _card_display(card: dict[str, Any]) -> str:
    card_id = str(card.get("card_id") or "").strip()
    name = str(
        card.get("name_cn") or card.get("name_en") or card.get("mention") or ""
    ).strip()
    if name and card_id:
        return f"{name}（{card_id}）"
    return name or card_id


def build_coverage_lines(response: RiftRagResponse) -> list[str]:
    """识别/覆盖度提示行：识别卡牌、识别失败、卡名歧义、检索步数上限。"""
    lines: list[str] = []
    if response.resolved_cards:
        cards = "、".join(_card_display(card) for card in response.resolved_cards)
        lines.append(f"识别卡牌：{cards}")
    if response.unresolved_mentions:
        lines.append("识别失败：" + "、".join(response.unresolved_mentions))
    for item in response.ambiguous_mentions:
        mention = str(item.get("mention") or "").strip()
        if not mention:
            continue
        candidates = item.get("candidates")
        ids = [
            str(candidate.get("card_id")).strip()
            for candidate in (candidates if isinstance(candidates, list) else [])
            if isinstance(candidate, dict)
            and str(candidate.get("card_id") or "").strip()
        ]
        shown = "、".join(ids[:3])
        if not shown:
            lines.append(f"卡名歧义：{mention}")
        elif len(ids) > 3:
            lines.append(f"卡名歧义：{mention}（{shown} 等）")
        else:
            lines.append(f"卡名歧义：{mention}（{shown}）")
    if response.exhausted:
        lines.append("已达检索步数上限，答案基于部分证据")
    return lines


def make_forward_node(
    content: Any,
    *,
    name: str | None = None,
    uin: Any = None,
) -> dict:
    data: dict[str, Any] = {"content": content}
    if name:
        data["name"] = name
    if uin:
        data["uin"] = str(uin)
    return {"type": "node", "data": data}


def build_rift_rag_nodes(
    question: str,
    response: RiftRagResponse,
    *,
    sender_name: str | None = None,
    sender_user_id: Any = None,
    base_url: str | None = None,
) -> list[dict]:
    """问题（含识别/覆盖度行）→ 引用规则 → 回答（含来源页脚）的合并转发节点。"""
    source_url = (base_url or rift_rag_qa_base_url()).rstrip("/")
    identity = {"name": sender_name or None, "uin": sender_user_id or None}
    nodes: list[dict] = []

    question_lines = [f"问题：{question}"]
    question_lines.extend(build_coverage_lines(response))
    if response.warnings:
        question_lines.append("警告：")
        question_lines.extend(response.warnings)
    nodes.append(make_forward_node("\n".join(question_lines), **identity))

    for source in response.sources:
        rule_lines = [f"规则 {source.rule_id}"]
        if source.topic:
            rule_lines.append(f"主题 {source.topic}")
        nodes.append(make_forward_node("\n".join(rule_lines), **identity))

    if response.answer:
        answer_text = f"{response.answer}\n\n回答生成自 {source_url}"
        nodes.append(make_forward_node(answer_text, **identity))

    return nodes
