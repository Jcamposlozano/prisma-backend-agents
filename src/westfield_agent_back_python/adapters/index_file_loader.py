"""
Adapter: carga del índice RAG desde disco.

Lee `data/maia-index.json` (o el path indicado por MAIA_INDEX_PATH o el
argumento explícito) y lo valida contra el modelo RagIndex de Pydantic.

Hace caché module-level por path para evitar releer el JSON de 2 MB en cada
request — si el path cambia, el caché se invalida solo.

Port de Westfield_agent/server/rag/index-loader.ts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from westfield_agent_back_python.domain.rag import RagIndex

_DEFAULT_PATH = "./data/maia-index.json"

# Caché module-level — patrón del Node, no hace falta thread-safe porque
# FastAPI corre single-event-loop por proceso.
_cached_index: RagIndex | None = None
_cached_path: str | None = None


def resolve_index_path(explicit: str | None = None) -> str:
    """Resuelve el path al índice. Orden: explícito → MAIA_INDEX_PATH → default."""
    if explicit:
        return explicit
    env_path = os.getenv("MAIA_INDEX_PATH")
    if env_path:
        return env_path
    return _DEFAULT_PATH


def load_index_from_disk(explicit_path: str | None = None) -> RagIndex:
    """
    Carga y valida el índice. Usa caché si el path es el mismo.

    raises FileNotFoundError si el archivo no existe.
    raises ValidationError (Pydantic) si el JSON no matchea RagIndex.
    """
    global _cached_index, _cached_path

    path_str = resolve_index_path(explicit_path)
    if _cached_index is not None and _cached_path == path_str:
        return _cached_index

    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Índice RAG no encontrado en {path}. "
            "Corre `npm run ingest` en el proyecto Westfield_agent (Node) "
            "y copia el JSON generado a este path."
        )

    raw = path.read_text(encoding="utf-8")
    parsed = RagIndex.model_validate_json(raw)

    _cached_index = parsed
    _cached_path = path_str
    return parsed


def clear_index_cache() -> None:
    """Útil en tests para forzar releer el archivo."""
    global _cached_index, _cached_path
    _cached_index = None
    _cached_path = None
