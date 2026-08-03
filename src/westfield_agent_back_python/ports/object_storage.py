"""
Port: storage de objetos (S3 en prod, fake en memoria en tests).

El AgentRegistry depende de esta interfaz, no de boto3. Es deliberadamente
SYNC (boto3 lo es): el registry la envuelve en `asyncio.to_thread` y solo
hay I/O de storage en cold-load o al expirar el TTL — nunca en el camino
caliente de un request ya cacheado.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStorage(Protocol):
    """Lectura de objetos por key (relativa al bucket configurado)."""

    def get_bytes(self, key: str) -> bytes:
        """
        key:    path del objeto, ej. "agents/maia/config.json".
        return: contenido crudo.
        raises: ObjectNotFoundError si no existe; otras excepciones de
                transporte se propagan (el registry decide cómo degradar).
        """
        ...

    def get_text(self, key: str) -> str:
        """Como get_bytes pero decodificado UTF-8."""
        ...

    def list_keys(self, prefix: str) -> list[str]:
        """
        prefix: prefijo de keys, ej. "agents/" o "org=westfield/agents/".
        return: lista de keys completas bajo ese prefijo (puede estar vacía).
                Usado para descubrir agentes (discovery), no en el camino
                caliente; el registry lo envuelve en asyncio.to_thread.
        """
        ...
