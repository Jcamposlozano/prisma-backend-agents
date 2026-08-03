"""Tests del FaissRetriever — port de los escenarios del CosineRetriever."""

from __future__ import annotations

import faiss
import numpy as np

from tests.fakes import FakeEmbeddings, make_chunk
from westfield_agent_back_python.adapters.faiss_retriever import FaissRetriever
from westfield_agent_back_python.domain.rag import ChunkMeta

# Tres vectores ortogonales (dim 3) → similitudes predecibles.
VECTORS = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
]


def _make_retriever(
    *,
    vectors: list[list[float]] | None = None,
    embeddings: FakeEmbeddings | None = None,
    top_k: int = 4,
    min_similarity: float = 0.2,
) -> FaissRetriever:
    vecs = vectors if vectors is not None else VECTORS
    arr = np.asarray(vecs, dtype=np.float32) if vecs else np.empty((0, 3), dtype=np.float32)
    index = faiss.IndexFlatIP(3)
    if len(arr):
        index.add(arr)
    chunks = [ChunkMeta(**make_chunk(i)) for i in range(len(vecs))]
    return FaissRetriever(
        index=index,
        chunks=chunks,
        embeddings=embeddings or FakeEmbeddings(vector=[1.0, 0.0, 0.0]),
        top_k=top_k,
        min_similarity=min_similarity,
    )


async def test_ordena_desc_por_similitud() -> None:
    retriever = _make_retriever(
        embeddings=FakeEmbeddings(vector=[0.8, 0.5, 0.1]), min_similarity=0.0
    )
    out = await retriever.retrieve("query")
    sims = [r.similarity for r in out]
    assert sims == sorted(sims, reverse=True)
    assert out[0].chunk.id == "doc.md#0"


async def test_respeta_top_k() -> None:
    retriever = _make_retriever(
        embeddings=FakeEmbeddings(vector=[0.8, 0.5, 0.1]), top_k=2, min_similarity=0.0
    )
    out = await retriever.retrieve("query")
    assert len(out) == 2


async def test_filtra_por_min_similarity() -> None:
    retriever = _make_retriever(
        embeddings=FakeEmbeddings(vector=[0.9, 0.3, 0.0]), min_similarity=0.5
    )
    out = await retriever.retrieve("query")
    assert len(out) == 1
    assert out[0].similarity >= 0.5


async def test_query_vacia_devuelve_lista_vacia() -> None:
    retriever = _make_retriever()
    assert await retriever.retrieve("") == []
    assert await retriever.retrieve("   ") == []


async def test_indice_vacio_devuelve_lista_vacia() -> None:
    retriever = _make_retriever(vectors=[])
    assert await retriever.retrieve("query") == []


async def test_falla_de_embedding_devuelve_lista_vacia() -> None:
    retriever = _make_retriever(embeddings=FakeEmbeddings(error=RuntimeError("api caída")))
    assert await retriever.retrieve("query") == []
