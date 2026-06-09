"""
Tests del retriever de coseno.

Usamos un fake del embeddings client (no necesitamos respx para esto) que
devuelve vectores determinísticos. Eso es suficiente para verificar:
  - orden por similitud descendente,
  - filtro por top_k,
  - filtro por min_similarity.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from westfield_agent_back_python.adapters.cosine_retriever import CosineRetriever
from westfield_agent_back_python.domain.rag import (
    AlwaysIncludeDoc,
    ManifestRetrieval,
    RagChunk,
    RagIndex,
)


class _FakeEmbeddings:
    """Devuelve siempre el mismo vector. No toca la red."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed_one(self, _text: str) -> list[float]:
        return self._vector

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _ in texts]


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm else values


def _build_index(*, top_k: int = 4, min_similarity: float = 0.2) -> RagIndex:
    """Índice con 3 chunks: alta sim con [1,0,0], baja con [0,1,0], cero con [0,0,1]."""
    chunks = [
        RagChunk(
            id=f"doc#{i}",
            doc_file="d.pdf",
            doc_title=f"Doc {i}",
            doc_tag="case",
            instructor_only=False,
            text=f"chunk {i}",
            embedding=_unit(emb),
        )
        for i, emb in enumerate([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    ]
    return RagIndex(
        name="test",
        embedding_model="fake",
        generated_at="2026-01-01T00:00:00Z",
        retrieval=ManifestRetrieval(
            top_k=top_k,
            min_similarity=min_similarity,
            chunk_size_chars=1000,
            chunk_overlap_chars=100,
        ),
        always_include=[],
        chunks=chunks,
    )


@pytest.mark.asyncio
async def test_retrieve_ordena_por_similitud_descendente() -> None:
    # Query == [1,0,0] → matchea perfectamente el primer chunk.
    embeddings = _FakeEmbeddings(_unit([1.0, 0.0, 0.0]))
    retriever = CosineRetriever(index=_build_index(), embeddings=embeddings)  # type: ignore[arg-type]
    result = await retriever.retrieve("query")
    assert len(result) >= 1
    assert result[0].chunk.id == "doc#0"
    assert result[0].similarity == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_retrieve_filtra_por_top_k() -> None:
    embeddings = _FakeEmbeddings(_unit([1.0, 1.0, 1.0]))  # similar a los 3
    retriever = CosineRetriever(
        index=_build_index(top_k=2, min_similarity=0.0),
        embeddings=embeddings,  # type: ignore[arg-type]
    )
    result = await retriever.retrieve("query")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_retrieve_filtra_por_min_similarity() -> None:
    # Query [1,0,0] da sim 1.0 con doc#0, sim 0.0 con doc#1 y doc#2.
    embeddings = _FakeEmbeddings(_unit([1.0, 0.0, 0.0]))
    retriever = CosineRetriever(
        index=_build_index(top_k=10, min_similarity=0.5),
        embeddings=embeddings,  # type: ignore[arg-type]
    )
    result = await retriever.retrieve("query")
    assert len(result) == 1
    assert result[0].chunk.id == "doc#0"


@pytest.mark.asyncio
async def test_retrieve_query_vacia_devuelve_lista_vacia() -> None:
    embeddings = _FakeEmbeddings(_unit([1.0, 0.0, 0.0]))
    retriever = CosineRetriever(index=_build_index(), embeddings=embeddings)  # type: ignore[arg-type]
    assert await retriever.retrieve("") == []
    assert await retriever.retrieve("   ") == []


@pytest.mark.asyncio
async def test_retrieve_indice_vacio_devuelve_lista_vacia() -> None:
    embeddings = _FakeEmbeddings([1.0])
    empty_index = RagIndex(
        name="empty",
        embedding_model="fake",
        generated_at="2026-01-01T00:00:00Z",
        retrieval=ManifestRetrieval(
            top_k=4, min_similarity=0.2, chunk_size_chars=1000, chunk_overlap_chars=100
        ),
        always_include=[
            AlwaysIncludeDoc(
                doc_file="x", doc_title="X", doc_tag="t", instructor_only=False, text="x"
            )
        ],
        chunks=[],
    )
    retriever = CosineRetriever(index=empty_index, embeddings=embeddings)  # type: ignore[arg-type]
    assert await retriever.retrieve("hola") == []


@pytest.mark.asyncio
async def test_retrieve_si_embed_falla_devuelve_lista_vacia() -> None:
    class _BrokenEmbeddings:
        async def embed_one(self, _text: str) -> list[float]:
            raise RuntimeError("network down")

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return []

    retriever = CosineRetriever(index=_build_index(), embeddings=_BrokenEmbeddings())  # type: ignore[arg-type]
    assert await retriever.retrieve("hola") == []


# Suprime warning de tipos sólo para que mypy/pylance no se queje al pasar
# fakes que no derivan formalmente de OpenAIEmbeddings.
_ = Any
