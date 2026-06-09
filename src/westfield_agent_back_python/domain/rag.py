"""
Modelos del índice RAG.

El índice (`data/maia-index.json`) se genera por la pipeline de ingesta del
proyecto Node (`npm run ingest`) y se persiste como JSON. Acá definimos su
shape para que Pydantic lo valide al cargarlo desde disco — si la pipeline
cambia el formato sin actualizar este servicio, la carga falla con un
ValidationError que indica exactamente qué campo está mal.

Port literal de Westfield_agent/server/rag/types.ts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ManifestRetrieval(BaseModel):
    """Parámetros del retriever que el manifest fija para este caso."""

    top_k: int
    min_similarity: float
    chunk_size_chars: int
    chunk_overlap_chars: int


class RagChunk(BaseModel):
    """Un chunk de doc indexado: texto + embedding L2-normalizado."""

    id: str
    doc_file: str
    doc_title: str
    doc_tag: str
    instructor_only: bool
    text: str
    embedding: list[float]


class AlwaysIncludeDoc(BaseModel):
    """Doc completo que se inyecta verbatim en el prompt cada turno (sin embedding)."""

    doc_file: str
    doc_title: str
    doc_tag: str
    instructor_only: bool
    text: str


class RetrievedChunk(BaseModel):
    """Resultado de retrieval: chunk + similitud coseno con la query."""

    chunk: RagChunk
    similarity: float


class RagIndex(BaseModel):
    """Índice completo persistido por la ingesta."""

    name: str
    embedding_model: str
    generated_at: str
    retrieval: ManifestRetrieval
    always_include: list[AlwaysIncludeDoc] = Field(default_factory=list)
    chunks: list[RagChunk] = Field(default_factory=list)
