"""Build and query a searchable copy of the verified Home ruling corpus."""
import gzip
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unicodedata import normalize


CARD_REF = re.compile(r"<<(\d+)>>")
WORD = re.compile(r"[^\W_]+")
KINDS = ("faq", "rule_passage")


def verified_records(directory, filename, manifest):
    entry = next(item for item in manifest["sources"] if item["path"] == filename)
    path = directory / filename
    if filename == "evidence-index.json":
        with gzip.open(path.with_suffix(".json.gz"), "rb") as source:
            payload = source.read()
    else:
        payload = path.read_bytes()
    if len(payload) != entry["bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
        raise ValueError(f"Invalid snapshot file {filename}")
    return json.loads(payload)["records"]


def build_index(directory, output):
    manifest = json.loads((directory / "rag-data-revision-manifest.json").read_text(encoding="utf-8"))
    cards = {
        str(card["id"]): card
        for card in verified_records(directory, "cards.json", manifest)
    }
    index = output.with_suffix(".building")
    if output.exists() or index.exists():
        raise FileExistsError("Use a new index path")

    def expand(text):
        def card_name(match):
            card = cards.get(match[1], {})
            names = dict.fromkeys(
                name for name in (card.get("cnName"), card.get("jaName"), card.get("enName")) if name
            )
            return " / ".join(names) or match[0]
        return CARD_REF.sub(card_name, text)

    with closing(sqlite3.connect(index)) as db, db:
        db.execute("CREATE TABLE revision (id TEXT NOT NULL)")
        db.execute("INSERT INTO revision VALUES (?)", (manifest["revision"],))
        for kind in KINDS:
            db.execute(f"""CREATE VIRTUAL TABLE {kind} USING fts5(
                title, search_text, id UNINDEXED, source UNINDEXED,
                body UNINDEXED, tokenize='trigram'
            )""")

        records = verified_records(directory, "qa-index.json", manifest)
        if len(records) != manifest["counts"]["qaRecords"]:
            raise ValueError("Unexpected FAQ record count")
        current = {
            row["stableId"]: row
            for row in verified_records(directory, "evidence-index.json", manifest)
            if row["status"] == "current" and row["recordType"] in {"qa", "card-faq"}
        }
        for record in records:
            evidence = current.get(record["id"])
            if not evidence or not evidence.get("answer") or not evidence.get("sourceUrl"):
                continue
            title = expand(record["title"])
            body = "\n\n".join(expand(part) for part in dict.fromkeys(
                part for part in (evidence.get("rawDetailedQuestion"), evidence["answer"]) if part
            ))
            primary = evidence.get("questionCardIds") or CARD_REF.findall(record["title"])
            if record["recordType"] == "card-faq":
                primary = evidence["cardIds"]
            aliases = [
                alias for cid in primary for alias in cards.get(str(cid), {}).get("aliases", [])
            ]
            db.execute("INSERT INTO faq VALUES (?, ?, ?, ?, ?)", (
                normalize("NFKC", title), normalize("NFKC", " ".join(aliases) + "\n" + body),
                evidence["evidenceId"], evidence["sourceUrl"], title + "\n\n" + body,
            ))
        del records, current

        for record in verified_records(directory, "ocg-rule-corpus.json", manifest):
            if record.get("sourceRole") != "active-rule" or not record.get("docname", "").startswith(("c01/", "c02/", "c03/", "c04/")):
                continue
            # Keep overlapping adjacent text together for rule exceptions across paragraphs.
            text = record["text"]
            for start in range(0, len(text), 700):
                body = text[start:start + 950].strip()
                if not body:
                    continue
                db.execute("INSERT INTO rule_passage VALUES (?, ?, ?, ?, ?)", (
                    normalize("NFKC", record["title"]), normalize("NFKC", body),
                    f"{record['id']}:{start}", record["sourceUrl"], body,
                ))
        for kind in KINDS:
            count = db.execute(f"SELECT count(*) FROM {kind}").fetchone()[0]
            if not count:
                raise ValueError(f"Empty corpus: {kind}")
            print(kind, count)
    index.rename(output)


class CorpusRetriever:
    def __init__(self, path, kind, vectors=None, rule_documents=()):
        if kind not in KINDS:
            raise ValueError("Invalid corpus kind")
        self.uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        self.kind = kind
        self.vectors = vectors
        self.rule_documents = {item.evidence_id: item for item in rule_documents}
        self.qa_rows = {}
        self.rows = {}
        if kind == "faq":
            with closing(sqlite3.connect(self.uri, uri=True)) as db:
                self.rows = dict(db.execute("SELECT id, rowid FROM faq"))
                self.qa_rows = {
                    evidence_id.split("@", 1)[0].removeprefix("ygoresources-qa-"): row
                    for evidence_id, row in self.rows.items()
                    if evidence_id.startswith("ygoresources-qa-")
                }

    def refresh_qa_evidence(self, evidence):
        prefix = "ygocdb:faq:"
        with closing(sqlite3.connect(self.uri, uri=True)) as db:
            for item in evidence:
                row = self.qa_rows.get(item.evidence_id[len(prefix):]) if item.evidence_id.startswith(prefix) else None
                if row is None:
                    yield item
                    continue
                title, evidence_id, source, body = db.execute(
                    "SELECT title, id, source, body FROM faq WHERE rowid=?", (row,)
                ).fetchone()
                yield replace(
                    item, evidence_id=f"home:{evidence_id}", title=title,
                    source=source, text=f"{body}\n\n来源：{source}",
                )

    def search(self, query, *, card_ids=(), final_top_k=5):
        from rag_agent.ruling_index import RulingCandidate, RulingRetrievalResult

        words = WORD.findall(normalize("NFKC", query[:600]))
        terms = list(dict.fromkeys(
            word[i:i + 3] for word in words for i in range(len(word) - 2)
        ))[:96]
        with closing(sqlite3.connect(self.uri, uri=True)) as db:
            expression = " OR ".join(f'"{term}"' for term in terms)
            rows = db.execute(f"""SELECT title, id, source, body FROM {self.kind}
                WHERE {self.kind} MATCH ? AND rank MATCH 'bm25(4.0, 1.0)'
                ORDER BY rank LIMIT ?""", (expression, final_top_k)).fetchall() if terms else []
            sparse = [self.document_from_row(row) for row in rows]
            dense = []
            warnings = ()
            if self.vectors is not None:
                try:
                    ids = self.vectors.search(query, self.kind, final_top_k * 3)
                    if self.kind == "faq":
                        dense = [
                            self.document_from_row(db.execute(
                                "SELECT title, id, source, body FROM faq WHERE rowid=?", (self.rows[item],)
                            ).fetchone())
                            for item in ids if item in self.rows
                        ]
                    else:
                        dense = [self.rule_documents[item] for item in ids if item in self.rule_documents]
                except Exception as exc:
                    warnings = (f"Home vector retrieval unavailable ({type(exc).__name__}).",)
        ranked = {}
        for channel in (sparse, dense):
            for rank, document in enumerate(channel, 1):
                score, _ = ranked.get(document.evidence_id, (0, document))
                ranked[document.evidence_id] = (score + 1 / (60 + rank), document)
        relationship = "rule_document" if self.kind == "rule_passage" else "analogous"
        dense_ids = {document.evidence_id for document in dense}
        candidates = []
        for score, doc in sorted(ranked.values(), key=lambda pair: -pair[0])[:final_top_k]:
            channel = "home_corpus"
            if doc.evidence_id in dense_ids:
                channel = "home_dense"
                doc = replace(doc, metadata={**doc.metadata, "vector_match": True})
            candidates.append(RulingCandidate(doc.evidence_id, score, channel, doc, relationship))
        return RulingRetrievalResult(candidates=tuple(candidates), warnings=warnings)

    def document_from_row(self, row):
        from rag_agent.ruling_index import RulingDocument

        title, evidence_id, source, body = row
        return RulingDocument(
            evidence_id=f"home:{evidence_id}", kind=self.kind, source=source,
            title=title, text=f"{body}\n\n来源：{source}",
        )


if __name__ == "__main__":
    build_index(Path(sys.argv[1]), Path(sys.argv[2]))
