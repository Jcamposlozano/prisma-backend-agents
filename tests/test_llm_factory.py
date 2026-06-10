"""Tests de la fábrica de providers LLM — el punto de extensión hexagonal."""

from __future__ import annotations

import pytest

from tests.fakes import (
    FakeChatClient,
    FakeObjectStorage,
    build_agent_fixture,
    make_registry,
    register_fake_provider,
)
from westfield_agent_back_python.adapters.llm_factory import (
    ProviderSettings,
    build_chat_client,
    build_embeddings,
)
from westfield_agent_back_python.adapters.openai_chat_client import OpenAIChatClient
from westfield_agent_back_python.adapters.openai_embeddings import OpenAIEmbeddings
from westfield_agent_back_python.domain.agent import AgentConfig
from westfield_agent_back_python.domain.errors import AgentLoadError


def _config(**overrides) -> AgentConfig:
    base = {
        "agent_id": "tutor",
        "agent_name": "Tutor",
        "prompt_id": "system-v1",
        "prompt_s3_uri": "s3://b/agents/tutor/prompts/system.md",
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
    }
    base.update(overrides)
    return AgentConfig(**base)


def test_provider_conocido_construye_cliente_con_params_del_config() -> None:
    config = _config(temperature=0.3, max_tokens=512, response_format="json")
    settings = ProviderSettings(api_keys={"openai": "sk-test"})

    client = build_chat_client(config, settings)
    assert isinstance(client, OpenAIChatClient)
    assert client._model == "gpt-4o-mini"
    assert client._temperature == 0.3
    assert client._max_tokens == 512
    assert client._response_format == "json"


def test_provider_sin_api_key_devuelve_none() -> None:
    client = build_chat_client(_config(), ProviderSettings(api_keys={}))
    assert client is None


def test_provider_desconocido_es_load_error_del_agente() -> None:
    config = _config(llm_provider="inexistente")
    with pytest.raises(AgentLoadError) as exc_info:
        build_chat_client(config, ProviderSettings())
    assert exc_info.value.agent_id == "tutor"
    assert "inexistente" in str(exc_info.value)


def test_build_embeddings_conocido_y_desconocido() -> None:
    settings = ProviderSettings(api_keys={"openai": "sk-test"})
    emb = build_embeddings("openai", "text-embedding-3-small", settings)
    assert isinstance(emb, OpenAIEmbeddings)

    assert build_embeddings("openai", "x", ProviderSettings()) is None  # sin key

    with pytest.raises(ValueError, match="inexistente"):
        build_embeddings("inexistente", "x", settings)


async def test_provider_fake_registrado_funciona_end_to_end(monkeypatch) -> None:
    """Registrar un provider nuevo = 1 builder en el dict. El registry lo usa solo."""
    fake_chat = FakeChatClient(reply="hola desde el provider fake")
    register_fake_provider(monkeypatch, chat_client=fake_chat)

    storage = FakeObjectStorage()
    build_agent_fixture(storage, "tutor", config_overrides={"llm_provider": "fake"})
    registry = make_registry(storage)

    rt = await registry.get("tutor")
    assert rt.chat_client is fake_chat
    assert await rt.chat_client.chat([]) == "hola desde el provider fake"
