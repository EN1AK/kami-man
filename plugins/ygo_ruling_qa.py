import asyncio
import json
import os
import re
import sqlite3
from time import perf_counter

import httpx
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.rule import Rule

from services.agent_usage import is_exempt, usage_store
from services.onebot_forward import make_forward_node, send_group_forward_nodes
from services.ygo_rag_messages import chunk_text, extract_rag_question


TRIGGER = re.compile(r"^裁定查询(?:\s+|[：:]\s*|$)")


def extract_ruling_question(bot: Bot, event: MessageEvent) -> str | None:
    if not isinstance(event, GroupMessageEvent):
        return None
    plain_text = event.get_plaintext().strip()
    if plain_text.startswith(("@", "＠")) and TRIGGER.match(plain_text[1:]):
        return TRIGGER.sub("", plain_text[1:], count=1).strip()

    mentioned, text = extract_rag_question(
        event.message, str(bot.self_id), plain_text=plain_text, to_me=event.to_me,
    )
    if mentioned and TRIGGER.match(text):
        return TRIGGER.sub("", text, count=1).strip()
    return None


async def is_ruling_question(bot: Bot, event: MessageEvent) -> bool:
    return extract_ruling_question(bot, event) is not None


ruling_qa = on_message(rule=Rule(is_ruling_question), priority=4, block=True)


def format_token_usage(trace: list[dict]) -> str:
    keys = ("input_tokens", "output_tokens", "total_tokens")
    totals = dict.fromkeys(keys, 0)
    reported = 0
    for stage in trace:
        usage = stage.get("usage") or {}
        if not all(type(usage.get(key)) is int and usage[key] >= 0 for key in keys):
            continue
        reported += 1
        for key in keys:
            totals[key] += usage[key]
    if not reported:
        return "本次模型用量暂不可用。"
    label = "本次模型用量" if reported == len(trace) else "本次模型用量（已报告阶段）"
    return (
        f"{label}：输入 {totals['input_tokens']:,} · "
        f"输出 {totals['output_tokens']:,} · 合计 {totals['total_tokens']:,} tokens"
    )


def format_bounded_answer(result: dict) -> tuple[list[str], set[str]]:
    lines = []
    cited = set()
    for item in result.get("answers", []):
        conclusion = item.get("case_conclusion") or item.get("hypothetical_conclusion")
        if not conclusion:
            continue
        refs = list(dict.fromkeys(
            ref for step in item.get("reasoning", []) for ref in step.get("evidence_ids", [])
        ))
        cited.update(refs)
        reference_text = " ".join(f"[{ref}]" for ref in refs)
        lines.append(f"{item['question']}\n{conclusion} {reference_text}".rstrip())
    if not lines and result.get("conclusion"):
        lines.append(result["conclusion"])
    lines.extend(result.get("uncertainties", []))
    return lines, cited


def format_ruling(data: dict, elapsed_seconds: float) -> list[str]:
    coverage = data.get("agent_coverage", {})
    route = coverage.get("route")
    if coverage.get("status") == "failed":
        raise ValueError("Adjudication failed")
    evidence = data.get("evidence", [])
    if route == "bounded_evidence_loop":
        lines, cited = format_bounded_answer(json.loads(data["answer"]))
        evidence = [item for item in evidence if item["evidence_id"] in cited]
    elif route == "reference_rag_loop":
        lines = [data["answer"].strip()] if data["answer"].strip() else []
    else:
        raise ValueError("Unexpected adjudication route")
    if not lines:
        raise ValueError("Empty adjudication answer")
    usage = format_token_usage(data.get("agent_trace") or [])
    cost = coverage.get("estimated_cost_usd")
    estimate = f"估算 ${cost:.4f}" if cost is not None else "金额暂不可估算"
    lines.append(f"{usage}\n裁定耗时 {elapsed_seconds:.1f} 秒 · {estimate}")
    timings = data.get("timings_ms") or {}
    passes = [timings[k] for k in ("initialRetrieval", "supplementRetrieval") if k in timings]
    if any("crossCardPool" in step for step in passes):
        labels = {
            "crossCardPool": "候选池", "crossCardInitialRank": "初筛",
            "crossCardMechanismRank": "机制匹配", "crossCardQuestionRank": "问句匹配",
        }
        parts = [
            f"{label} {sum(step.get(key, 0) for step in passes) / 1000:.2f}s"
            for key, label in labels.items()
        ]
        lines.append("跨卡 FAQ：" + " · ".join(parts))
    texts = chunk_text("\n\n".join(lines))
    for item in evidence:
        texts.extend(chunk_text(
            f"[{item['evidence_id']}] {item['title']}\n{item['text']}"
        ))
    return texts


@ruling_qa.handle()
async def handle_ruling_question(bot: Bot, event: GroupMessageEvent):
    question = extract_ruling_question(bot, event)
    if not question or len(question) > 8000:
        await ruling_qa.finish("请发送 @裁定查询 问题，问题最多 8000 字。")

    try:
        ticket = await asyncio.to_thread(usage_store.reserve, event.user_id, exempt=is_exempt(event.user_id))
    except (sqlite3.Error, OSError):
        logger.exception("Ruling quota reservation failed")
        await ruling_qa.finish("用量记录暂时不可用，请稍后再试。")
    if ticket is None:
        await ruling_qa.finish("今天的问答额度已用完。发送 @神人 用量 可查看记录。")

    try:
        url = os.getenv("YGO_RULING_API_URL", "http://127.0.0.1:7863/api/adjudicate")
        started = perf_counter()
        async with httpx.AsyncClient(timeout=310) as client:
            response = await client.post(url, json={"scenario": question, "llm": True, "trace": True})
            response.raise_for_status()
        texts = format_ruling(response.json(), perf_counter() - started)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.warning("Ruling request failed ({})", type(exc).__name__)
        try:
            await asyncio.to_thread(usage_store.refund, ticket)
        except (sqlite3.Error, OSError):
            logger.exception("Ruling quota refund failed")
        await ruling_qa.finish("裁定查询暂时失败，请稍后再试。")

    nodes = [
        make_forward_node(int(bot.self_id), "裁定查询", Message(MessageSegment.text(text)))
        for text in texts
    ]
    await send_group_forward_nodes(bot, event, nodes, "合并转发失败，改为普通消息发送。")
