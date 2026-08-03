"""
Port: cliente de embeddings para la query del usuario.

El FaissRetriever depende de esta interfaz, no del cliente concreto. Eso
permite tests con embeddings fake y swappear el proveedor (OpenAI, Cohere,
Bedrock, etc.) implementando la misma interfaz en adapters/ y registrándolo
en adapters/llm_factory.py.

NOTA HU-001: el runtime NO embebe documentos (eso es del servicio de
ingesta) — este port se usa únicamente para embeber la query de cada turno.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embeddings(Protocol):
    """Embebe textos en el mismo espacio vectorial del índice del agente."""

    async def embed_one(self, text: str) -> list[float]:
        """
        text:   query a embeber (max ~2000 chars).
        return: vector L2-normalizado, mismas dimensiones que el índice.
        raises: excepciones de transporte — el retriever degrada a [].
        """
        ...
