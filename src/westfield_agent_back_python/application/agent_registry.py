"""
AgentRegistry — el corazón del runtime multi-agente.

Carga perezosa por agent_id al primer request, caché en memoria con TTL,
y aislamiento de fallos por agente:

  - config.json ausente        → AgentNotFoundError (404) + caché negativa
  - config corrupta / sin prompt / provider desconocido → AgentLoadError (503)
  - vector store roto/ausente  → agente DEGRADADO (responde sin RAG) —
    el "fallback controlado" que pide la HU, nunca un error al usuario
  - TTL expirado + recarga fallida con entrada previa → sirve stale
    (disponibilidad > consistencia) y reintenta tras un backoff corto

Un agente roto jamás toca las entradas de otros: cada carga es independiente
y las excepciones llevan el agent_id que falló.

Todo el I/O de storage (boto3, sync) corre en asyncio.to_thread — solo hay
I/O en cold-load o expiración de TTL, nunca en el camino caliente.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from westfield_agent_back_python.adapters.faiss_retriever import FaissRetriever
from westfield_agent_back_python.adapters.llm_factory import (
    ProviderSettings,
    build_chat_client,
    build_embeddings,
)
from westfield_agent_back_python.adapters.s3_object_storage import parse_s3_uri
from westfield_agent_back_python.adapters.vector_store_loader import load_vector_store
from westfield_agent_back_python.domain.agent import AgentConfig
from westfield_agent_back_python.domain.errors import (
    AgentLoadError,
    AgentNotFoundError,
    ObjectNotFoundError,
    UniversityNotFoundError,
)
from westfield_agent_back_python.domain.rag import AlwaysIncludeDoc
from westfield_agent_back_python.ports.chat_client import ChatClient
from westfield_agent_back_python.ports.object_storage import ObjectStorage
from westfield_agent_back_python.ports.retriever import Retriever
from westfield_agent_back_python.shared.logger import get_logger

log = get_logger("westfield_agent_back_python.agent_registry")

# Slugs válidos (university_code y agent_id): minúsculas/dígitos/guiones —
# evita path traversal en keys S3.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass
class AgentRuntime:
    """Todo lo que hace falta para atender un turno de este agente."""

    config: AgentConfig
    system_prompt: str
    chat_client: ChatClient | None  # None sin API key del provider → fallback
    retriever: Retriever | None  # None si el agente no tiene RAG o su carga falló
    always_include: list[AlwaysIncludeDoc] = field(default_factory=list)
    degraded: bool = False  # True si el vector store falló (responde sin RAG)
    chunk_count: int = 0
    loaded_at: float = 0.0  # epoch (para health/snapshot)


@dataclass
class _CacheEntry:
    runtime: AgentRuntime
    expires_at: float  # reloj monotónico


class AgentRegistry:
    """
    Caché de AgentRuntime por (university_code, agent_id), con TTL y locks.

    Multi-tenant: el `prefix` admite el placeholder {university_code}, que se
    sustituye POR REQUEST con el segmento de la ruta — cada universidad vive
    bajo su propio prefijo S3 (ej. org=westfield/agents). Un prefijo sin
    placeholder se comporta como single-tenant (todas las universidades
    comparten el mismo árbol).
    """

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        prefix: str = "agents",
        provider_settings: ProviderSettings,
        embedding_model_fallback: str = "text-embedding-3-small",
        ttl_seconds: int = 300,
        negative_ttl_seconds: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._storage = storage
        self._prefix_template = prefix.strip("/")
        self._settings = provider_settings
        self._embedding_model_fallback = embedding_model_fallback
        self._ttl = ttl_seconds
        self._negative_ttl = negative_ttl_seconds
        self._clock = clock

        # Todas las estructuras se indexan por "university:agent".
        self._entries: dict[str, _CacheEntry] = {}
        self._negative: dict[str, float] = {}  # key → expires_at
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ API

    async def get(self, university_code: str, agent_id: str) -> AgentRuntime:
        """
        Devuelve el runtime del agente de esa universidad, cargándolo desde
        S3 si hace falta.

        raises UniversityNotFoundError | AgentNotFoundError | AgentLoadError
        (solo de ESTE agente — jamás contagia a otros).
        """
        if not _SLUG_RE.match(university_code or ""):
            raise UniversityNotFoundError(university_code)
        if not _SLUG_RE.match(agent_id or ""):
            raise AgentNotFoundError(agent_id)

        key = f"{university_code}:{agent_id}"
        now = self._clock()

        entry = self._entries.get(key)
        if entry and entry.expires_at > now:
            return entry.runtime

        neg_expires = self._negative.get(key)
        if neg_expires and neg_expires > now:
            raise AgentNotFoundError(agent_id)

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Double-check: otro request pudo cargar mientras esperábamos el lock.
            now = self._clock()
            entry = self._entries.get(key)
            if entry and entry.expires_at > now:
                return entry.runtime
            neg_expires = self._negative.get(key)
            if neg_expires and neg_expires > now:
                raise AgentNotFoundError(agent_id)

            try:
                runtime = await asyncio.to_thread(self._load_sync, university_code, agent_id)
            except AgentNotFoundError:
                # El agente ya no existe — descartar stale y cachear en negativo.
                self._entries.pop(key, None)
                self._negative[key] = self._clock() + self._negative_ttl
                raise
            except Exception as err:
                if entry is not None:
                    # Recarga fallida con entrada previa → servir stale y
                    # reintentar pasado un backoff corto.
                    entry.expires_at = self._clock() + self._negative_ttl
                    log.warning(
                        f"🟡 Recarga de '{key}' falló ({err}) — sirviendo versión stale."
                    )
                    return entry.runtime
                if isinstance(err, AgentLoadError):
                    raise
                raise AgentLoadError(agent_id, str(err)) from err

            self._negative.pop(key, None)
            self._entries[key] = _CacheEntry(
                runtime=runtime, expires_at=self._clock() + self._ttl
            )
            return runtime

    def invalidate(self, university_code: str | None = None, agent_id: str | None = None) -> None:
        """Descarta entradas cacheadas (todas si no se pasa universidad+agente)."""
        if university_code is None or agent_id is None:
            self._entries.clear()
            self._negative.clear()
        else:
            key = f"{university_code}:{agent_id}"
            self._entries.pop(key, None)
            self._negative.pop(key, None)

    def snapshot(self) -> list[dict]:
        """Resumen de agentes cargados — para GET /api/v1/health."""
        now = self._clock()
        out = []
        for key, entry in sorted(self._entries.items()):
            university_code, _, agent_id = key.partition(":")
            rt = entry.runtime
            out.append(
                {
                    "university": university_code,
                    "agent_id": agent_id,
                    "agent_name": rt.config.agent_name,
                    "prompt_id": rt.config.prompt_id,
                    "vector_store_id": rt.config.vector_store_id,
                    "llm_provider": rt.config.llm_provider,
                    "llm_model": rt.config.llm_model,
                    "degraded": rt.degraded,
                    "chunks": rt.chunk_count,
                    "loaded_at": rt.loaded_at,
                    "ttl_remaining": max(0, round(entry.expires_at - now)),
                }
            )
        return out

    # ------------------------------------------------------------ carga sync

    def _prefix_for(self, university_code: str) -> str:
        return self._prefix_template.replace("{university_code}", university_code)

    def _load_sync(self, university_code: str, agent_id: str) -> AgentRuntime:
        """Carga completa de un agente desde storage. Corre en thread."""
        # 1) config.json — sin esto el agente no existe.
        config_key = f"{self._prefix_for(university_code)}/{agent_id}/config.json"
        try:
            raw_config = self._storage.get_text(config_key)
        except ObjectNotFoundError:
            raise AgentNotFoundError(agent_id) from None

        try:
            config = AgentConfig.model_validate_json(raw_config)
        except ValidationError as err:
            raise AgentLoadError(agent_id, f"config.json inválido: {err}") from err

        # 2) prompt activo — sin prompt el agente no es viable.
        try:
            _, prompt_key = parse_s3_uri(config.prompt_s3_uri)
            system_prompt = self._storage.get_text(prompt_key)
        except Exception as err:
            raise AgentLoadError(agent_id, f"prompt no disponible: {err}") from err
        if not system_prompt.strip():
            raise AgentLoadError(agent_id, "prompt vacío")

        # 3) chat client del provider configurado (vía fábrica).
        #    Provider desconocido → AgentLoadError; sin API key → None (fallback).
        chat_client = build_chat_client(config, self._settings)
        if chat_client is None:
            log.warning(
                f"🟡 Agente '{agent_id}': sin API key de '{config.llm_provider}' "
                f"— responderá su fallback_message."
            )

        # 4) vector store — best-effort: si falla, el agente queda degradado
        #    (responde sin RAG), JAMÁS rompe la carga. Fallback controlado (HU).
        retriever: Retriever | None = None
        always_include: list[AlwaysIncludeDoc] = []
        degraded = False
        chunk_count = 0
        if config.vector_store_s3_uri:
            try:
                store = load_vector_store(self._storage, config.vector_store_s3_uri)
                always_include = store.always_include
                chunk_count = len(store.chunks)
                embeddings = build_embeddings(
                    store.manifest.embedding_provider,
                    store.manifest.embedding_model or self._embedding_model_fallback,
                    self._settings,
                )
                if embeddings is not None:
                    retriever = FaissRetriever(
                        index=store.faiss_index,
                        chunks=store.chunks,
                        embeddings=embeddings,
                        top_k=config.top_k,
                        min_similarity=config.min_similarity,
                    )
                else:
                    degraded = True
                    log.warning(
                        f"🟡 Agente '{agent_id}': sin API key para embeddings "
                        f"'{store.manifest.embedding_provider}' — RAG desactivado."
                    )
            except Exception as err:
                degraded = True
                log.warning(
                    f"🟡 Agente '{agent_id}': vector store no cargó ({err}) "
                    f"— responde sin RAG (fallback controlado)."
                )

        log.info(
            f"🧠 Agente '{agent_id}' cargado: prompt={config.prompt_id} · "
            f"vector_store={config.vector_store_id or 'sin RAG'} · "
            f"{chunk_count} chunks · {config.llm_provider}/{config.llm_model}"
            f"{' · DEGRADADO' if degraded else ''}"
        )
        return AgentRuntime(
            config=config,
            system_prompt=system_prompt,
            chat_client=chat_client,
            retriever=retriever,
            always_include=always_include,
            degraded=degraded,
            chunk_count=chunk_count,
            loaded_at=time.time(),
        )
