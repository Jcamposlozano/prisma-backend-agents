"""
Port: retriever de chunks RAG por query.

El use case ChatWithAgent depende de esta interfaz, no del retriever
concreto. Eso permite tests con un retriever fake en memoria, y permitiría
más adelante swappear FAISS in-memory por OpenSearch/pgvector/Pinecone sin
tocar el use case.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from westfield_agent_back_python.domain.rag import RetrievedChunk


@runtime_checkable
class Retriever(Protocol):
    """Encuentra los k chunks más similares al query."""

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        """
        query:  texto a embeber y buscar (típicamente: mensaje del usuario +
                último turno del asistente, max ~2000 chars).
        return: lista ordenada desc por similitud, filtrada por top_k y
                min_similarity del config del agente. Puede estar vacía.
        """
        ...
