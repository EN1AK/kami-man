# Riftbound ruling service

`符文规则 问题`, `符文裁定 问题` and `@符文裁定查询 问题` use the dedicated worker. A QQ mention followed by the explicit command is also accepted. The dedicated command shares the daily agent quota. The general agent's `rift_rules` tool calls the same worker.

## Corpus

The deployed release uses riftsim commit `3e5a3a9d70398ecbbdb5d74bc6c6af260d2b28ef`. Copy its `src/rift_rag`, `workspace/final/rules.db` and `cards_bilingual.db` into the release directory. Copy Home's `workspace/rag/current.json` and its referenced directory containing `rules_index.json` and `rules_vectors.npy`. Verify the databases against the git blobs and both vector files against the export checksums. The worker validates the corpus fingerprint, current-edition rule IDs, chunk order and matrix dimensions before listening.

| Release item | Identifier |
| --- | --- |
| Rules database git blob | `4189e8adaf5a9a711cb5e0b0d63b895a4ef4daca` |
| Bilingual cards git blob | `3db21a6f034acf5e27dabed044b917d9eafdaa43` |
| Corpus fingerprint | `0da6a816dc2e52812bce6a89a1267ce1d0288fec5b7a24f5c14b6c40d1a49828` |
| Vector metadata SHA-256 | `0992968fbb22973cd31e6cd7f45abb816e536874a5209e08fe63d404c1e2cd32` |
| Vector matrix SHA-256 | `fce0690957e5501d3193b3e39b176791b3396266dbad6b7a5c2466651b2dee45` |

## Deployment

Install `rift_reference_ruling.py` in the versioned working directory in `rift-ruling.service`. The unit reads the existing private ruling environment file and uses the local BGE-M3 encoder. Start the service and check `GET http://127.0.0.1:7865/health`. Exercise `POST /api/query` with a rule number and a card erratum before switching consumers.

Apply `rift-ruling-gateway.patch` to the deployed ygo-rag checkout. Install `rift-reference-ruling.conf` as a systemd drop-in for both ygo-rag and kami-man. Install the bot changes in `plugins/rift_rag_qa.py`, `services/rift_rag_api.py` and `services/rift_rag_messages.py`. Reload systemd and restart the consumers. Disabling these two drop-ins and restarting the consumers restores their previous routing.

The worker combines current-edition rules, card-linked FAQ and errata, exact rule references, keyword recall and vector retrieval. It verifies each displayed quotation against the retrieved text. Agent mode can perform one additional search round. Oneshot mode uses a single model call. Request timings, token usage and estimated USD cost are included in the dedicated QQ reply.
