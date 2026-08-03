"""
Adapter: retriever sobre un índice FAISS en memoria.

Misma semántica que tenía el CosineRetriever in-memory:
  - query vacía → []
  - índice vacío → []
  - falla del embedding → [] con log (best-effort, nunca rompe el turno)
  - resultados ordenados desc por similitud, filtrados por top_k + min_similarity

Como el índice es IndexFlatIP y los vectores (chunks Y query) están
L2-normalizados, el inner product ES la similitud coseno.

top_k/min_similarity vienen del config.json del agente (no del manifest) —
eso permite tunear el retrieval sin re-ingestar.
"""

from __future__ import annotations

import logging

import faiss
import numpy as np

from westfield_agent_back_python.domain.rag import ChunkMeta, RetrievedChunk
from westfield_agent_back_python.ports.embeddings import Embeddings

log = logging.getLogger(__name__)


class FaissRetriever:
    """Implementa Retriever (ver ports/retriever.py)."""

    def __init__(
        self,
        *,
        index: faiss.Index,
        chunks: list[ChunkMeta],
        embeddings: Embeddings,
        top_k: int,
        min_similarity: float,
    ) -> None:
        self._index = index
        self._chunks = chunks
        self._embeddings = embeddings
        self._top_k = top_k
        self._min_similarity = min_similarity

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        trimmed = (query or "").strip()
        if not trimmed:
            return []
        if not self._chunks or self._index.ntotal == 0:
            return []

        try:
            query_vec = await self._embeddings.embed_one(trimmed)
        except Exception:
            log.exception("RAG retrieve: falló embed_one, retornando []")
            return []

        q = np.asarray([query_vec], dtype=np.float32)
        k = min(self._top_k, self._index.ntotal)
        scores, ids = self._index.search(q, k)

        out: list[RetrievedChunk] = []
        for similarity, idx in zip(scores[0], ids[0], strict=True):
            if int(idx) < 0:
                continue  # FAISS rellena con -1 cuando no hay suficientes vecinos
            similarity = float(similarity)
            if similarity < self._min_similarity:
                break  # FAISS devuelve ordenado desc — nada más adelante pasa el filtro
            out.append(RetrievedChunk(chunk=self._chunks[int(idx)], similarity=similarity))
        return out
