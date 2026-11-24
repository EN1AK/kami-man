"""Export published Chroma vectors and query them with the matching BGE encoder."""
import json
import sys
from functools import lru_cache
from pathlib import Path
from threading import Lock


COLLECTIONS = {
    "faq": ("ocg_rag_ext4", "ocg_rag_rulings", "ocg_rag"),
    "rule_passage": ("rules", "ocg_rules", "rules"),
}


def export_vectors(source, destination):
    import chromadb
    import numpy as np

    release = json.loads((source / "release.json").read_text(encoding="utf-8"))
    destination.mkdir()
    for kind, (folder, collection_name, count_key) in COLLECTIONS.items():
        client = chromadb.PersistentClient(path=str(source / folder))
        collection = client.get_collection(collection_name, embedding_function=None)
        count = collection.count()
        if count != release[count_key]:
            raise ValueError(f"Unexpected {kind} collection size: {count}")
        vectors = np.lib.format.open_memmap(
            destination / f"{kind}.npy", mode="w+", dtype=np.float32,
            shape=(count, release["vector_dimensions"]),
        )
        ids = []
        for offset in range(0, count, 1024):
            page = collection.get(offset=offset, limit=1024, include=["embeddings"])
            batch = page["embeddings"]
            if not np.isfinite(batch).all() or not np.allclose(np.linalg.norm(batch, axis=1), 1, atol=0.002):
                raise ValueError(f"Invalid normalized vectors in {kind} at {offset}")
            vectors[offset:offset + len(batch)] = batch
            ids.extend(page["ids"])
        if len(ids) != count or len(set(ids)) != count:
            raise ValueError(f"Incomplete or duplicate IDs in {kind}")
        vectors.flush()
        (destination / f"{kind}.json").write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")
        print(kind, count, flush=True)
    (destination / "release.json").write_text(json.dumps(release), encoding="utf-8")


class RulingVectors:
    def __init__(self, root, revision, model_path):
        import numpy as np

        release = json.loads((root / "release.json").read_text(encoding="utf-8"))
        if release["upstream_revision"] != revision or release["embedding_model"] != "BAAI/bge-m3":
            raise ValueError("Vector release does not match the active ruling corpus")
        self.ids = {}
        self.vectors = {}
        for kind, (_, _, count_key) in COLLECTIONS.items():
            ids = json.loads((root / f"{kind}.json").read_text(encoding="utf-8"))
            vectors = np.load(root / f"{kind}.npy", mmap_mode="r", allow_pickle=False)
            if len(ids) != release[count_key] or vectors.shape != (len(ids), release["vector_dimensions"]):
                raise ValueError(f"Invalid {kind} vector dimensions")
            self.ids[kind] = ids
            self.vectors[kind] = vectors
        self.model_path = model_path
        self.model = None
        self.lock = Lock()

    @lru_cache(maxsize=32)
    def embed(self, query):
        import torch
        from transformers import AutoModel, AutoTokenizer

        with self.lock, torch.inference_mode():
            if self.model is None:
                torch.set_num_threads(2)
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
                self.model = AutoModel.from_pretrained(
                    self.model_path, local_files_only=True, dtype=torch.bfloat16,
                    use_safetensors=True,
                ).eval()
            inputs = self.tokenizer(query, truncation=True, max_length=512, return_tensors="pt")
            cls = self.model(**inputs).last_hidden_state[:, 0].float()
            return torch.nn.functional.normalize(cls, dim=1)[0].numpy()

    def search(self, query, kind, limit):
        scores = self.vectors[kind] @ self.embed(query)
        # Both the published vectors and the query are unit-length.
        return [self.ids[kind][i] for i in scores.argsort()[-limit:][::-1]]


if __name__ == "__main__":
    export_vectors(Path(sys.argv[1]), Path(sys.argv[2]))
