"""Riftbound ruling endpoint over the pinned riftsim corpus and BGE-M3 index."""
import json
import os
import re
import sqlite3
import logging
from collections import defaultdict
from contextlib import closing, contextmanager
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal

import httpx
import numpy as np
import torch
from pydantic import BaseModel, Field, ValidationError
from transformers import AutoModel, AutoTokenizer

from rift_rag import index_store, rag_query
from rift_rag.card_resolver import CardResolver

ROOT = Path.cwd()
MODEL = "gpt-6.2-sol"
REF = re.compile(r"(?:\bR-[A-Z0-9.-]+\b|(?<![\w-])\d{3}(?:\.\d+[a-z]?)+\b|"
                 r"(?:规则|條文|条文|rule)\s*([0-9]{3})(?![\d.]))", re.I)
slot = Lock()


@contextmanager
def database(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        yield db


class Corpus:
    def __init__(self):
        rules = ROOT / "workspace/final/rules.db"
        self.cards = ROOT / "cards_bilingual.db"
        self.resolver = CardResolver(str(rules), str(self.cards))
        with database(rules) as db:
            self.rows = {r[0]: r for r in index_store.corpus_rows(db)}
            self.vectors, meta = index_store.load_index(db, ROOT / "workspace/rag")
            chunks = index_store.chunks(db)
            self.ids = [rid for rid, _ in chunks]
            if not meta or self.ids != meta["rule_ids"]:
                raise ValueError("Rule chunks and vector index differ")
            self.revision = meta["corpus_fingerprint"]
            self.parts = [text for _, text in chunks]
            self.positions = defaultdict(list)
            for i, rid in enumerate(self.ids):
                self.positions[rid].append(i)
            self.keywords = tuple(k for k, in db.execute("SELECT DISTINCT keyword FROM rule_keywords") if k)
        self.rules = rules
        path = os.environ["RIFT_BGE_MODEL"]
        torch.set_num_threads(2)
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.encoder = AutoModel.from_pretrained(path, local_files_only=True,
                                                 dtype=torch.bfloat16, use_safetensors=True).eval()

    @lru_cache(maxsize=64)
    def scores(self, query):
        with torch.inference_mode():
            tokens = self.tokenizer(query, truncation=True, max_length=512, return_tensors="pt")
            cls = self.encoder(**tokens).last_hidden_state[:, 0].float()
            return self.vectors @ torch.nn.functional.normalize(cls, dim=1)[0].numpy()

    def retrieve(self, query, resolved, top_k):
        scores = self.scores(query)
        dense = index_store.ranked_rules({"rule_ids": self.ids}, scores, 40)
        with database(self.rules) as db:
            terms = rag_query.extract_terms(query, self.keywords)
            lexical = rag_query.keyword_recall(db, terms, 40)
            order, _ = rag_query.fuse(dense, lexical, top_k)
            refs = (match.group(1) or match.group() for match in REF.finditer(query))
            direct = [row[0] for ref in list(refs)[:6] for row in rag_query.lookup_rule(db, ref)]
            for card in resolved[:6]:
                direct.extend(row[0] for row in rag_query.get_card_rules(db, card["card_id"], 5))
        evidence = {}
        for rid in dict.fromkeys(direct + order):
            positions = sorted(self.positions[rid], key=lambda i: -scores[i])[:2]
            evidence[rid] = {"topic": self.rows[rid][1], "text": "\n".join(self.parts[i] for i in positions)}
        with database(self.cards) as db:
            for card in resolved[:6]:
                cid = card["card_id"]
                row = db.execute("SELECT name_cn,name_en,errata_cn,text_cn,text_en,text_cn_filled "
                                 "FROM cards WHERE card_key=?", (cid,)).fetchone()
                if row:
                    cn, en, errata, printed, english, filled = row
                    text = "\n".join(f"{label}：{s}" for label, s in
                        (("勘误", errata), ("中文卡文", printed or filled), ("英文卡文", english)) if s)
                    if text:
                        evidence["CARD-" + cid] = {"topic": cn or en or cid, "text": text}
        return evidence


def health(corpus):
    return {"route": "rift_ruling", "corpus": corpus.revision, "rules": len(corpus.rows),
            "chunks": len(corpus.ids), "model": MODEL}


class Question(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=10, ge=1, le=40)
    mode: Literal["agent", "oneshot"] = "agent"
    trace: bool = False


def generate(question, identity, evidence, final, timeout):
    instructions = """你是符文战场 Riftbound 裁定员。依据提供的现行规则、FAQ和卡文作中文裁定，勘误优先。
先给结论，再解释费用、时点、适用条件和例外。只处理题面事实。卡名有歧义时说明需补充哪张卡。
返回 JSON 对象，answer 为中文答复。每个关键结论就近写 [证据ID]。
citations 为数组，每项含 id 和 quote，quote 必须是该条 text 的连续原文，最多 320 字。
如果资料不足，queries 给出最多两条不同的补查问题（英文规则术语或卡号），不要猜。证据充分时 queries 为空。"""
    if final:
        instructions += "本轮检索已结束。如仍不足，说明具体缺口，queries 为空。"
    payload = {"model": MODEL, "reasoning": {"effort": "high"}, "store": False,
               "input": instructions + "\n只输出 JSON。以下是待核实的问题和检索资料：\n" +
               json.dumps({"question": question, "card_resolution": identity,
                           "evidence": evidence}, ensure_ascii=False)}
    with httpx.Client(timeout=timeout) as client:
        reply = client.post("https://api.openai.com/v1/responses", json=payload, headers={
            "Authorization": "Bearer " + os.environ["YGO_RULING_OPENAI_API_KEY"]})
        reply.raise_for_status()
        body = reply.json()
    if body.get("status") != "completed" or body.get("model") != MODEL:
        raise ValueError("Incomplete model response")
    text = "".join(c["text"] for item in body["output"] for c in item.get("content", [])
                   if c.get("type") == "output_text")
    answer = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
    return answer, body["usage"]


def cited_sources(draft, evidence):
    answer = draft.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return []
    cited = re.findall(r"\[((?:R-|CARD-)[^\]\s]+)\]", answer)
    quotes = {}
    for item in draft.get("citations") or []:
        if not isinstance(item, dict):
            continue
        rid, quote = item.get("id"), item.get("quote")
        if isinstance(rid, str) and rid in evidence and isinstance(quote, str) and quote.strip() and quote in evidence[rid]["text"]:
            quotes[rid] = quote
    if not cited or not all(rid in quotes for rid in cited):
        return []
    return [{"rule_id": rid, "topic": evidence[rid]["topic"], "quote": quotes[rid]}
            for rid in dict.fromkeys(cited)]


def adjudicate(request: Question, corpus):
    if not slot.acquire(blocking=False):
        raise BlockingIOError("Ruling service busy")
    try:
        start = monotonic()
        question = request.query.strip()
        if not question:
            raise ValueError("Empty question")
        identity = corpus.resolver.resolve(question)
        evidence = corpus.retrieve(question, identity["resolved"], request.top_k)
        retrieval = monotonic() - start
        model_time = cost = 0.0
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        passes = 1 if request.mode == "oneshot" else 2
        for attempt in range(passes):
            tick = monotonic()
            remaining = 225 - (tick - start)
            if remaining < 1:
                raise TimeoutError("Ruling deadline exceeded")
            final = attempt + 1 == passes
            draft, tokens = generate(question, identity, evidence, final, remaining)
            model_time += monotonic() - tick
            for key in usage:
                usage[key] += tokens[key]
            details = tokens.get("input_tokens_details") or {}
            cached, written = details.get("cached_tokens", 0), details.get("cache_write_tokens", 0)
            long = tokens["input_tokens"] > 272000
            cost += ((tokens["input_tokens"] - cached - written) * (4 if long else 2)
                     + cached * (.2 if long else .1) + written * (5 if long else 2.5)
                     + tokens["output_tokens"] * (15 if long else 10)) / 1e6
            sources = cited_sources(draft, evidence)
            queries = [s.strip()[:260] for s in (draft.get("queries") or []) if isinstance(s, str) and s.strip()][:2]
            if final or (sources and not queries):
                break
            tick = monotonic()
            for extra in queries:
                for rid, item in corpus.retrieve(extra, identity["resolved"], request.top_k).items():
                    if rid not in evidence:
                        evidence[rid] = item
                    elif item["text"] not in evidence[rid]["text"]:
                        evidence[rid]["text"] += "\n" + item["text"]
            retrieval += monotonic() - tick
        warnings = [] if sources else ["现有证据未能支持带可核验引文的结论。"]
        return {"answer": draft["answer"] if sources else "请补充卡号、时点或具体场面，我暂时无法核实这个裁定。",
                "mode": request.mode, "exhausted": not sources,
                **({"trace": [{"pass_count": attempt + 1, "evidence_ids": list(evidence)}]} if request.trace else {}),
                "warnings": warnings, "sources": sources, "resolved_cards": identity["resolved"],
                "coverage": {"ambiguous_mentions": identity["ambiguous"], "unresolved_mentions": identity["unresolved"]},
                "corpus_revision": corpus.revision, "usage": usage, "estimated_cost_usd": cost,
                "timings_ms": {"retrieval": round(retrieval*1000), "model": round(model_time*1000),
                               "total": round((monotonic()-start)*1000)}, "passes": attempt+1}
    finally:
        slot.release()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, health(self.server.corpus))
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/query":
            return self.send_error(404)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 65536:
                return self.send_error(413)
            request = Question(**json.loads(self.rfile.read(size)))
            if not request.query.strip():
                return self.send_error(400)
        except (ValueError, TypeError, ValidationError):
            return self.send_error(400)
        try:
            response = adjudicate(request, self.server.corpus)
        except BlockingIOError:
            return self.send_error(503)
        except (TimeoutError, httpx.TimeoutException):
            return self.send_error(504)
        except httpx.HTTPStatusError as exc:
            logging.error("Rift model HTTP %s", exc.response.status_code)
            return self.send_error(502)
        except Exception as exc:
            logging.error("Rift query failed (%s)", type(exc).__name__)
            return self.send_error(502)
        self.send_json(200, response)


if __name__ == "__main__":
    corpus = Corpus()
    corpus.scores("规则")
    with ThreadingHTTPServer(("127.0.0.1", 7865), Handler) as server:
        server.corpus = corpus
        server.serve_forever()
