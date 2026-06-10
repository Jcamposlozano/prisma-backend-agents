"""
Errores de dominio del runtime multi-agente.

La jerarquía permite que la capa HTTP mapee cada error a un status sin
inspeccionar strings: AgentNotFoundError → 404, AgentLoadError → 503.
El aislamiento por agente se apoya acá: un error de carga lleva SIEMPRE el
agent_id que falló y jamás se propaga a requests de otros agentes.
"""

from __future__ import annotations


class ObjectNotFoundError(Exception):
    """El objeto pedido no existe en el storage (S3 404 / NoSuchKey)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"objeto no encontrado en storage: {key}")
        self.key = key


class AgentNotFoundError(Exception):
    """No existe config.json para ese agent_id (o el id es inválido)."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"agente '{agent_id}' no encontrado")
        self.agent_id = agent_id


class AgentLoadError(Exception):
    """El agente existe pero su carga falló (config corrupta, prompt ausente, etc.)."""

    def __init__(self, agent_id: str, cause: str) -> None:
        super().__init__(f"agente '{agent_id}' falló al cargar: {cause}")
        self.agent_id = agent_id
        self.cause = cause


class VectorStoreInvalidError(Exception):
    """El vector store está corrupto o inconsistente (faiss vs chunks vs manifest)."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"vector store inválido: {detail}")
        self.detail = detail
