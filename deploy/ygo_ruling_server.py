"""Run the upstream OCG adjudicator with a dedicated OpenAI Responses model."""
import logging
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from openai import OpenAI
from rag_agent import adjudication_service
from rag_agent.deadline import remaining
from rag_agent.config import Settings
from rag_agent.ruling_index import load_rule_documents_from_epub, validate_manifest
from rag_agent.web import create_app
from ygo_ruling_corpus import CorpusRetriever
from ygo_ruling_vectors import RulingVectors


def estimate_cost_nanos(model, usage):
    if model != "gpt-6.2-sol" or usage is None:
        return None
    details = usage.input_tokens_details
    cached = getattr(details, "cached_tokens", 0) or 0
    written = getattr(details, "cache_write_tokens", 0) or 0
    ordinary = usage.input_tokens - cached - written
    if ordinary < 0:
        return None
    # OpenAI Standard pricing, in billionths of a US dollar per token.
    if usage.input_tokens > 272_000:
        return ordinary * 4_000 + cached * 200 + written * 5_000 + usage.output_tokens * 15_000
    return ordinary * 2_000 + cached * 100 + written * 2_500 + usage.output_tokens * 10_000


class RulingModel:
    def __init__(self, settings):
        self.timeout = settings.deepseek_timeout_seconds
        self.estimated_cost_nanos = 0
        self.client = OpenAI(
            api_key=os.environ["YGO_RULING_OPENAI_API_KEY"],
            base_url=os.getenv("YGO_RULING_OPENAI_BASE_URL"),
            max_retries=0,
        )

    def invoke(self, prompt: str):
        response = self.client.responses.create(
            model=os.getenv("YGO_RULING_MODEL", "gpt-6.2-sol"),
            reasoning={"effort": "high"},
            input=prompt,
            store=False,
            timeout=remaining(self.timeout),
        )
        usage = response.usage
        cost = estimate_cost_nanos(response.model, usage)
        if self.estimated_cost_nanos is not None:
            self.estimated_cost_nanos = None if cost is None else self.estimated_cost_nanos + cost
        return SimpleNamespace(
            content=response.output_text,
            usage_metadata={
                name: getattr(usage, name)
                for name in ("input_tokens", "output_tokens", "total_tokens")
            } if usage else None,
        )


def create_ruling_app():
    if not os.getenv("YGO_RULING_OPENAI_API_KEY"):
        raise RuntimeError("YGO_RULING_OPENAI_API_KEY is required")
    # This process uses the upstream adjudication path with its own model.
    adjudication_service.create_deepseek_chat_model = RulingModel
    original_answer = adjudication_service.answer_with_evidence_loop
    faq = None
    corpus_path = os.getenv("YGO_RULING_CORPUS")
    if corpus_path:
        path = Path(corpus_path)
        if not path.is_file():
            raise RuntimeError("Configured ruling corpus index is missing")
        original = adjudication_service.build_persistent_ruling_retrievers
        vector_dir = os.getenv("YGO_RULING_VECTOR_DIR")
        vectors = None
        rule_documents = ()
        if vector_dir:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                revision = db.execute("SELECT id FROM revision").fetchone()[0]
            vectors = RulingVectors(
                Path(vector_dir), revision, os.environ["YGO_RULING_VECTOR_MODEL"],
            )
            rule_documents, _ = load_rule_documents_from_epub(Settings.from_env().ocg_rules_epub_path)
            if set(vectors.ids["rule_passage"]) != {item.evidence_id for item in rule_documents}:
                raise ValueError("Rule vectors do not match the configured rule EPUB")

            def warm_vectors():
                logger = logging.getLogger("uvicorn.error")
                try:
                    vectors.search("游戏王裁定", "faq", 1)
                    vectors.search("游戏王裁定", "rule_passage", 1)
                    logger.info("Home ruling vector encoder ready")
                except Exception as exc:
                    logger.warning("Home ruling vector warmup failed (%s)", type(exc).__name__)

            Thread(target=warm_vectors, daemon=True).start()
        faq = CorpusRetriever(path, "faq", vectors)
        corpus = (faq, CorpusRetriever(path, "rule_passage", vectors, rule_documents))

        def build_retrievers(request, settings, cards, *, llm=None):
            # The upstream builder reads the entire FAQ cache before checking either manifest.
            manifests = (
                ("faq", settings.ruling_faq_manifest_path, settings.ruling_faq_collection_name),
                ("rules", settings.ruling_rules_manifest_path, settings.ruling_rules_collection_name),
            )
            if not any(
                validate_manifest(
                    path, index_kind=kind, collection_name=collection,
                    embedding_model=settings.embedding_model,
                ).usable
                for kind, path, collection in manifests
            ):
                return corpus
            return (*corpus, *original(request, settings, cards, llm=llm))

        adjudication_service.build_persistent_ruling_retrievers = build_retrievers
        logging.getLogger("uvicorn.error").info("Loaded ruling corpus from %s", path)

    def answer(base, llm, **kwargs):
        if faq is not None:
            base = replace(base, evidence=tuple(faq.refresh_qa_evidence(base.evidence)))
        response = original_answer(base, llm, **kwargs)
        if llm.estimated_cost_nanos is None:
            return response
        coverage = dict(response.agent_coverage or {})
        coverage["estimated_cost_usd"] = llm.estimated_cost_nanos / 1_000_000_000
        return replace(response, agent_coverage=coverage)

    adjudication_service.answer_with_evidence_loop = answer
    return create_app()
