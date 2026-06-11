"""
Fakes compartidos por la suite — ningún test toca AWS ni la red.

  - FakeObjectStorage: ObjectStorage en memoria, instrumentado (cuenta gets,
    puede fallar por key) — reemplaza a S3 en registry/api tests.
  - FakeChatClient / FakeEmbeddings: ports fake con respuestas enlatadas.
  - register_fake_provider: registra el provider "fake" en la llm_factory
    (vía monkeypatch) — demuestra el punto de extensión de proveedores.
  - build_agent_fixture: publica en el fake storage un agente completo
    (config.json + system.md + vector store FAISS real serializado).
  - make_registry: AgentRegistry con defaults de test.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import faiss
import numpy as np

from westfield_agent_back_python.adapters import llm_factory
from westfield_agent_back_python.adapters.llm_factory import ProviderSettings
from westfield_agent_back_python.application.agent_registry import AgentRegistry
from westfield_agent_back_python.domain.errors import ObjectNotFoundError
from westfield_agent_back_python.ports.object_storage import ObjectStorage

TEST_BUCKET = "test-bucket"


class FakeObjectStorage:
    """ObjectStorage en memoria, instrumentado para asserts de caché/locks."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self._objects: dict[str, bytes] = dict(objects or {})
        self.get_attempts: dict[str, int] = {}
        self.fail_keys: set[str] = set()  # keys que tiran error de transporte

    # -- escritura (solo para armar fixtures) --
    def put_bytes(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    def put_text(self, key: str, text: str) -> None:
        self._objects[key] = text.encode("utf-8")

    def put_json(self, key: str, obj: Any) -> None:
        self.put_text(key, json.dumps(obj, ensure_ascii=False))

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    # -- port ObjectStorage --
    def get_bytes(self, key: str) -> bytes:
        self.get_attempts[key] = self.get_attempts.get(key, 0) + 1
        if key in self.fail_keys:
            raise RuntimeError(f"storage roto (fake): {key}")
        if key not in self._objects:
            raise ObjectNotFoundError(key)
        return self._objects[key]

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8")


class FakeChatClient:
    """ChatClient fake — devuelve `reply` o tira `error`. Registra los calls."""

    def __init__(self, reply: str = "ok", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.reply


class FakeEmbeddings:
    """Embeddings fake — devuelve siempre `vector` o tira `error`."""

    def __init__(
        self, vector: list[float] | None = None, error: Exception | None = None
    ) -> None:
        self.vector = vector if vector is not None else [1.0, 0.0, 0.0]
        self.error = error
        self.calls: list[str] = []

    async def embed_one(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return list(self.vector)


def register_fake_provider(
    monkeypatch,
    *,
    chat_client: FakeChatClient | None = None,
    embeddings: FakeEmbeddings | None = None,
) -> None:
    """Registra el provider 'fake' en la fábrica — el punto de extensión real."""
    if chat_client is not None:
        monkeypatch.setitem(llm_factory.CHAT_PROVIDERS, "fake", lambda cfg, st: chat_client)
    if embeddings is not None:
        monkeypatch.setitem(llm_factory.EMBEDDING_PROVIDERS, "fake", lambda model, st: embeddings)


def make_chunk(i: int, *, instructor_only: bool = False) -> dict:
    return {
        "id": f"doc.md#{i}",
        "doc_file": "doc.md",
        "doc_title": f"Doc {i}",
        "doc_tag": "case",
        "instructor_only": instructor_only,
        "text": f"texto del chunk {i}",
    }


def build_agent_fixture(
    storage: FakeObjectStorage,
    agent_id: str,
    *,
    prefix: str = "agents",
    system_prompt: str = "Sos un agente de prueba. Respondé en español.",
    vectors: list[list[float]] | None = None,
    chunks: list[dict] | None = None,
    always_include: list[dict] | None = None,
    config_overrides: dict | None = None,
    embedding_provider: str = "openai",
    embedding_model: str = "text-embedding-3-small",
) -> dict:
    """
    Publica un agente completo en el fake storage. Si `vectors` viene, arma
    un vector store FAISS REAL (IndexFlatIP serializado) consistente con el
    contrato — mismo camino de deserialización que producción.
    """
    prefix = f"{prefix.strip('/')}/{agent_id}"
    config: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_name": agent_id.title(),
        "prompt_id": "system-v1",
        "prompt_s3_uri": f"s3://{TEST_BUCKET}/{prefix}/prompts/system.md",
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
    }
    if vectors is not None:
        config["vector_store_id"] = "v1"
        config["vector_store_s3_uri"] = f"s3://{TEST_BUCKET}/{prefix}/vector_store/v1/"
    config.update(config_overrides or {})

    storage.put_json(f"{prefix}/config.json", config)
    storage.put_text(f"{prefix}/prompts/system.md", system_prompt)

    if vectors is not None:
        arr = np.asarray(vectors, dtype=np.float32)
        index = faiss.IndexFlatIP(arr.shape[1])
        index.add(arr)
        storage.put_bytes(
            f"{prefix}/vector_store/v1/index.faiss",
            faiss.serialize_index(index).tobytes(),
        )
        chunk_dicts = chunks if chunks is not None else [make_chunk(i) for i in range(len(vectors))]
        storage.put_json(
            f"{prefix}/vector_store/v1/chunks.json",
            {"chunks": chunk_dicts, "always_include": always_include or []},
        )
        storage.put_json(
            f"{prefix}/vector_store/v1/manifest.json",
            {
                "vector_store_id": "v1",
                "agent_id": agent_id,
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
                "embedding_dimensions": int(arr.shape[1]),
                "normalized": True,
                "metric": "inner_product",
                "generated_at": "2026-01-01T00:00:00Z",
                "chunk_count": len(chunk_dicts),
            },
        )
    return config


def make_registry(
    storage: ObjectStorage,
    *,
    prefix: str = "agents",
    api_keys: dict[str, str | None] | None = None,
    ttl: int = 300,
    negative_ttl: int = 30,
    clock: Callable[[], float] | None = None,
) -> AgentRegistry:
    return AgentRegistry(
        storage=storage,
        prefix=prefix,
        provider_settings=ProviderSettings(api_keys=api_keys or {}),
        embedding_model_fallback="text-embedding-3-small",
        ttl_seconds=ttl,
        negative_ttl_seconds=negative_ttl,
        clock=clock or time.monotonic,
    )
