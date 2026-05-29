"""Local sentence-transformers embeddings — no API cost."""
from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_DIM = 384


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return L2-normalised 384-dim float vectors for each text string."""
    vecs = _model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()
