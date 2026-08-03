"""
Carga de un vector store (manifest.json + chunks.json + index.faiss) desde storage.

Es sync a propósito (el AgentRegistry lo envuelve en asyncio.to_thread).
El índice FAISS se deserializa directo desde los bytes de S3 — sin archivos
temporales — y queda en memoria dentro del LoadedVectorStore que cachea el
registry.

Validaciones de consistencia del contrato (ver README):
  - index.ntotal == len(chunks)   → chunks.json y .faiss de la misma versión
  - index.d == embedding_dimensions → el manifest describe a este índice
Cualquier mismatch → VectorStoreInvalidError (el registry degrada al agente
a modo sin-RAG, nunca sirve retrieval inconsistente).
"""

from __future__ import annotations

from dataclasses import dataclass

import faiss
import numpy as np

from westfield_agent_back_python.adapters.s3_object_storage import parse_s3_uri
from westfield_agent_back_python.domain.errors import VectorStoreInvalidError
from westfield_agent_back_python.domain.rag import (
    AlwaysIncludeDoc,
    ChunkMeta,
    ChunksFile,
    VectorStoreManifest,
)
from westfield_agent_back_python.ports.object_storage import ObjectStorage

MANIFEST_FILE = "manifest.json"
CHUNKS_FILE = "chunks.json"
INDEX_FILE = "index.faiss"


@dataclass
class LoadedVectorStore:
    """Vector store completo en memoria, listo para armar un FaissRetriever."""

    manifest: VectorStoreManifest
    chunks: list[ChunkMeta]
    always_include: list[AlwaysIncludeDoc]
    faiss_index: faiss.Index


def load_vector_store(storage: ObjectStorage, vector_store_s3_uri: str) -> LoadedVectorStore:
    """
    vector_store_s3_uri: prefijo de la versión, ej.
        "s3://bucket/agents/maia/vector_store/v1/"
    raises: ObjectNotFoundError si falta algún archivo,
            VectorStoreInvalidError si el contenido es inconsistente,
            pydantic.ValidationError si el JSON no cumple el contrato.
    """
    _, prefix = parse_s3_uri(vector_store_s3_uri)
    prefix = prefix.rstrip("/")

    manifest = VectorStoreManifest.model_validate_json(
        storage.get_text(f"{prefix}/{MANIFEST_FILE}")
    )
    chunks_file = ChunksFile.model_validate_json(storage.get_text(f"{prefix}/{CHUNKS_FILE}"))

    raw_index = storage.get_bytes(f"{prefix}/{INDEX_FILE}")
    try:
        index = faiss.deserialize_index(np.frombuffer(raw_index, dtype=np.uint8))
    except Exception as err:
        raise VectorStoreInvalidError(f"index.faiss no deserializa: {err}") from err

    if index.ntotal != len(chunks_file.chunks):
        raise VectorStoreInvalidError(
            f"index.ntotal={index.ntotal} != len(chunks)={len(chunks_file.chunks)} "
            f"— chunks.json e index.faiss no son de la misma versión"
        )
    if index.d != manifest.embedding_dimensions:
        raise VectorStoreInvalidError(
            f"index.d={index.d} != manifest.embedding_dimensions={manifest.embedding_dimensions}"
        )

    return LoadedVectorStore(
        manifest=manifest,
        chunks=chunks_file.chunks,
        always_include=chunks_file.always_include,
        faiss_index=index,
    )
