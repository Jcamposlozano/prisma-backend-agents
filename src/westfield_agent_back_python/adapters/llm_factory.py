"""
Fábrica de providers LLM — el punto de extensión hexagonal para cambiar de
modelo/proveedor sin tocar el core.

Cada agente declara `llm_provider` + `llm_model` en su config.json; el
AgentRegistry llama a esta fábrica para construir su ChatClient y el
Embeddings de queries de su vector store (según `embedding_provider` del
manifest). El use case y los handlers HTTP solo conocen los ports.

Para agregar un proveedor nuevo (Anthropic, Azure, Bedrock, ...):
  1. Implementar ports.ChatClient (y/o ports.Embeddings) en adapters/.
  2. Registrar el builder en CHAT_PROVIDERS / EMBEDDING_PROVIDERS.
  3. Exponer su API key en ProviderSettings (api_keys["nombre"]).
Nada más — ni el registry, ni el use case, ni la API cambian.

Semántica de errores:
  - provider desconocido → AgentLoadError (solo ese agente queda 503).
  - provider conocido pero sin API key → None (el agente arranca en
    fallback / sin RAG — modo degradado controlado, no error).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from westfield_agent_back_python.adapters.openai_chat_client import OpenAIChatClient
from westfield_agent_back_python.adapters.openai_embeddings import OpenAIEmbeddings
from westfield_agent_back_python.domain.agent import AgentConfig
from westfield_agent_back_python.domain.errors import AgentLoadError
from westfield_agent_back_python.ports.chat_client import ChatClient
from westfield_agent_back_python.ports.embeddings import Embeddings


@dataclass(frozen=True)
class ProviderSettings:
    """Credenciales/base_urls por proveedor — vienen de config/env, nunca de S3."""

    api_keys: dict[str, str | None] = field(default_factory=dict)
    base_urls: dict[str, str] = field(default_factory=dict)

    def api_key(self, provider: str) -> str | None:
        return self.api_keys.get(provider)

    def base_url(self, provider: str, default: str = "") -> str:
        return self.base_urls.get(provider, default)


ChatClientBuilder = Callable[[AgentConfig, ProviderSettings], ChatClient | None]
EmbeddingsBuilder = Callable[[str, ProviderSettings], Embeddings | None]


def _build_openai_chat(config: AgentConfig, settings: ProviderSettings) -> ChatClient | None:
    api_key = settings.api_key("openai")
    if not api_key:
        return None
    return OpenAIChatClient(
        api_key=api_key,
        model=config.llm_model,
        base_url=settings.base_url("openai", "https://api.openai.com/v1"),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        response_format=config.response_format,
    )


def _build_openai_embeddings(model: str, settings: ProviderSettings) -> Embeddings | None:
    api_key = settings.api_key("openai")
    if not api_key:
        return None
    return OpenAIEmbeddings(
        api_key=api_key,
        model=model,
        base_url=settings.base_url("openai", "https://api.openai.com/v1"),
    )


# Registries de proveedores — agregar acá la línea del proveedor nuevo.
CHAT_PROVIDERS: dict[str, ChatClientBuilder] = {
    "openai": _build_openai_chat,
}
EMBEDDING_PROVIDERS: dict[str, EmbeddingsBuilder] = {
    "openai": _build_openai_embeddings,
}


def build_chat_client(config: AgentConfig, settings: ProviderSettings) -> ChatClient | None:
    """
    raises AgentLoadError si el provider no está registrado.
    return None si el provider existe pero no tiene API key (fallback).
    """
    builder = CHAT_PROVIDERS.get(config.llm_provider)
    if builder is None:
        known = ", ".join(sorted(CHAT_PROVIDERS))
        raise AgentLoadError(
            config.agent_id,
            f"llm_provider desconocido: {config.llm_provider!r} (registrados: {known})",
        )
    return builder(config, settings)


def build_embeddings(provider: str, model: str, settings: ProviderSettings) -> Embeddings | None:
    """
    raises ValueError si el provider no está registrado (el registry lo
    captura y degrada al agente a modo sin-RAG — no es fatal).
    return None si el provider existe pero no tiene API key.
    """
    builder = EMBEDDING_PROVIDERS.get(provider)
    if builder is None:
        known = ", ".join(sorted(EMBEDDING_PROVIDERS))
        raise ValueError(f"embedding_provider desconocido: {provider!r} (registrados: {known})")
    return builder(model, settings)
