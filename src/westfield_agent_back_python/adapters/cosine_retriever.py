"""
Adapter: retriever por similitud coseno en memoria.

Estrategia:
  1. Al construirlo, pre-arma una matriz numpy (N_chunks × dim) con los
     embeddings del índice — eso permite hacer el producto punto vectorizado.
  2. Por cada query, embebe el query (vía OpenAIEmbeddings), calcula
     `matrix @ query_vec`, ordena descendente y filtra por top_k +
     min_similarity (que vienen del manifest del índice).

Como los embeddings (chunks Y query) ya están L2-normalizados, el producto
punto ES la similitud coseno — no hace falta dividir por normas.

Port de Westfield_agent/server/rag/retriever.ts + runtime.ts.
"""

from __future__ import annotations

import logging

import numpy as np

from westfield_agent_back_python.adapters.openai_embeddings import OpenAIEmbeddings
from westfield_agent_back_python.domain.rag import RagIndex, RetrievedChunk

log = logging.getLogger(__name__)


class CosineRetriever:
    """Implementa Retriever (ver ports/retriever.py)."""

    def __init__(self, *, index: RagIndex, embeddings: OpenAIEmbeddings) -> None:
        self._index = index
        self._embeddings = embeddings
        # Pre-armar matriz para producto punto vectorizado. Si no hay chunks,
        # array vacío con shape (0, 0) — retrieve() lo cortocircuita.
        if index.chunks:
            self._matrix = np.asarray(
                [c.embedding for c in index.chunks],
                dtype=np.float32,
            )
        else:
            self._matrix = np.empty((0, 0), dtype=np.float32)

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        trimmed = (query or "").strip()
        if not trimmed:
            return []
        if not self._index.chunks:
            return []

        try:
            query_vec = await self._embeddings.embed_one(trimmed)
        except Exception:
            log.exception("RAG retrieve: falló embed_one, retornando []")
            return []

        q = np.asarray(query_vec, dtype=np.float32)
        sims = self._matrix @ q  # (N,) — producto punto = sim coseno con vectores normalizados

        top_k = self._index.retrieval.top_k
        min_sim = self._index.retrieval.min_similarity

        # Índices ordenados desc por similitud — `argsort` ascending + reverse.
        sorted_idx = np.argsort(-sims)  # descendente

        out: list[RetrievedChunk] = []
        for idx in sorted_idx:
            if len(out) >= top_k:
                break
            similarity = float(sims[idx])
            if similarity < min_sim:
                break  # como están ordenadas desc, nada más adelante puede pasar
            out.append(
                RetrievedChunk(
                    chunk=self._index.chunks[int(idx)],
                    similarity=similarity,
                )
            )
        return out
