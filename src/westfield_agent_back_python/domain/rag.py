"""
Modelos del vector store — shape de `vector_store/vN/` en S3.

Cada vector store son tres objetos generados por el servicio de ingesta
(repo Westfield_agent_ingest_python):

  manifest.json  → VectorStoreManifest (metadata + modelo de embeddings)
  chunks.json    → ChunksFile (textos; los embeddings viven en el .faiss)
  index.faiss    → índice FAISS IndexFlatIP serializado

Invariante del contrato: `chunks[i]` corresponde a la fila `i` del índice
FAISS. Los vectores están L2-normalizados → inner product = similitud coseno.

Si la ingesta cambia el formato sin actualizar este servicio, la validación
Pydantic falla al cargar con un error que indica exactamente qué campo está mal.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChunkMeta(BaseModel):
    """Metadata + texto de un chunk indexado. El embedding vive en index.faiss."""

    id: str
    doc_file: str
    doc_title: str
    doc_tag: str
    instructor_only: bool = False
    text: str


class AlwaysIncludeDoc(BaseModel):
    """Doc completo que se inyecta verbatim en el prompt cada turno (sin embedding)."""

    doc_file: str
    doc_title: str
    doc_tag: str
    instructor_only: bool = False
    text: str


class ChunksFile(BaseModel):
    """Shape de chunks.json."""

    chunks: list[ChunkMeta] = Field(default_factory=list)
    always_include: list[AlwaysIncludeDoc] = Field(default_factory=list)


class ChunkingParams(BaseModel):
    """Parámetros de chunking usados por la ingesta (informativo)."""

    chunk_size_chars: int = 0
    chunk_overlap_chars: int = 0


class RetrievalDefaults(BaseModel):
    """Sugerencia de la ingesta — el runtime usa top_k/min_similarity del config.json."""

    top_k: int = 4
    min_similarity: float = 0.2


class SourceDoc(BaseModel):
    """Doc fuente listado en el manifest (informativo)."""

    doc_file: str
    doc_title: str = ""
    doc_tag: str = "doc"
    instructor_only: bool = False


class VectorStoreManifest(BaseModel):
    """Shape de manifest.json."""

    vector_store_id: str
    agent_id: str
    # El runtime embebe las queries con ESTE provider/modelo — garantiza que
    # query y chunks vivan en el mismo espacio vectorial.
    embedding_provider: str = "openai"
    embedding_model: str
    embedding_dimensions: int
    normalized: bool = True
    metric: str = "inner_product"
    generated_at: str = ""
    chunk_count: int = 0
    chunking: ChunkingParams = Field(default_factory=ChunkingParams)
    retrieval_defaults: RetrievalDefaults = Field(default_factory=RetrievalDefaults)
    source_docs: list[SourceDoc] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    """Resultado de retrieval: chunk + similitud coseno con la query."""

    chunk: ChunkMeta
    similarity: float
