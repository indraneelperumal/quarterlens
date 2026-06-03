"""Local sentence-transformers embeddings and cross-encoder re-ranking.

Two-stage retrieval:
  1. Bi-encoder (all-MiniLM-L6-v2) — fast approximate nearest-neighbour search.
     Fetches a wider candidate set from Qdrant (limit=20).
  2. Cross-encoder (ms-marco-MiniLM-L-6-v2) — slower but precise relevance
     scoring using the full query × chunk text pair.  Keeps top-k results.

Both models are lazy-loaded and process-cached via lru_cache so they are
downloaded once on first use and stay in memory for the lifetime of the worker.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from sentence_transformers import CrossEncoder, SentenceTransformer

EMBED_MODEL = "all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
VECTOR_DIM = 384


@lru_cache(maxsize=1)
def _embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


@lru_cache(maxsize=1)
def _reranker() -> CrossEncoder:
    return CrossEncoder(RERANK_MODEL)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return L2-normalised 384-dim float vectors for each text string."""
    vecs = _embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


def rerank(query: str, docs: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    """Re-rank *docs* by relevance to *query* using a cross-encoder model.

    Returns the top_k most relevant docs, or all docs if fewer than top_k exist.
    Each doc must have a "text" key; other keys are passed through unchanged.
    """
    if len(docs) <= top_k:
        return docs
    pairs = [(query, d.get("text", "")) for d in docs]
    scores = _reranker().predict(pairs, show_progress_bar=False)
    ranked = sorted(zip(scores, docs), key=lambda x: float(x[0]), reverse=True)
    return [d for _, d in ranked[:top_k]]
