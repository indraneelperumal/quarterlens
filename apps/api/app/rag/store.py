"""Qdrant CRUD for the financial_docs collection."""
from __future__ import annotations

import uuid
from typing import Any

import logging

log = logging.getLogger(__name__)

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.rag.chunker import Chunk

COLLECTION = "financial_docs"
DIM = 384


class VectorStore:
    def __init__(self, url: str) -> None:
        self._client = QdrantClient(url=url)

    def ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION not in existing:
            try:
                self._client.create_collection(
                    collection_name=COLLECTION,
                    vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
                )
            except Exception:
                # Another process may have created it between our check and create
                pass

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
        """Upsert chunk-embedding pairs; returns number of points written."""
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.accession_number}#{chunk.chunk_index}")),
                vector=vec,
                payload={
                    "text": chunk.text,
                    "ticker": chunk.ticker,
                    "form_type": chunk.form_type,
                    "date": chunk.date,
                    "accession_number": chunk.accession_number,
                    "source_url": chunk.source_url,
                    "chunk_index": chunk.chunk_index,
                },
            )
            for chunk, vec in zip(chunks, embeddings)
        ]
        result = self._client.upsert(collection_name=COLLECTION, points=points)
        if result.status.value != "completed":
            log.warning("Qdrant upsert status: %s", result.status)
        return len(points)

    def search(
        self,
        vector: list[float],
        limit: int = 8,
        ticker: str | None = None,
        form_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Top-k cosine search with optional ticker / form_type filters."""
        must: list[FieldCondition] = []
        if ticker:
            must.append(FieldCondition(key="ticker", match=MatchValue(value=ticker.upper())))
        if form_type:
            must.append(FieldCondition(key="form_type", match=MatchValue(value=form_type)))

        hits = self._client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=limit,
            query_filter=Filter(must=must) if must else None,
            with_payload=True,
        )
        return [{**hit.payload, "score": hit.score} for hit in hits]

    def count(self) -> int:
        return self._client.count(collection_name=COLLECTION).count
