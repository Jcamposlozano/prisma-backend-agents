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
    agent_env_suffix,
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


# ------------------------------------------- keys dedicadas por agente


def test_agent_env_suffix_normaliza_guiones_y_mayusculas() -> None:
    assert agent_env_suffix("maia") == "MAIA"
    assert agent_env_suffix("minerva_leadership") == "MINERVA_LEADERSHIP"
    # Los nombres de env var no admiten guiones: `-` y `_` colapsan al mismo sufijo.
    assert agent_env_suffix("student-services") == agent_env_suffix("student_services")


def test_for_agent_prefiere_la_key_dedicada() -> None:
    settings = ProviderSettings(
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia"}},
    )

    client = build_chat_client(_config(agent_id="maia"), settings.for_agent("maia"))
    assert client._api_key == "sk-maia"


def test_for_agent_cae_a_la_key_global_si_no_hay_dedicada() -> None:
    settings = ProviderSettings(
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia"}},
    )

    client = build_chat_client(_config(agent_id="westy"), settings.for_agent("westy"))
    assert client._api_key == "sk-global"


def test_for_agent_funciona_sin_key_global() -> None:
    """Un agente con key propia responde aunque no exista OPENAI_API_KEY."""
    settings = ProviderSettings(agent_api_keys={"openai": {"MAIA": "sk-maia"}})

    assert build_chat_client(_config(agent_id="maia"), settings.for_agent("maia"))._api_key == (
        "sk-maia"
    )
    # ...y el que no la tiene sigue sin cliente → fallback controlado.
    assert build_chat_client(_config(agent_id="westy"), settings.for_agent("westy")) is None


def test_for_agent_tambien_resuelve_los_embeddings() -> None:
    settings = ProviderSettings(
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia"}},
    )

    emb = build_embeddings("openai", "text-embedding-3-small", settings.for_agent("maia"))
    assert emb._api_key == "sk-maia"


def test_for_agent_sin_keys_por_agente_devuelve_el_mismo_objeto() -> None:
    settings = ProviderSettings(api_keys={"openai": "sk-global"})
    assert settings.for_agent("maia") is settings


def test_has_agent_key_detecta_dedicada() -> None:
    settings = ProviderSettings(agent_api_keys={"openai": {"STUDENT_SERVICES": "sk-ss"}})

    assert settings.has_agent_key("student_services") is True
    assert settings.has_agent_key("student-services") is True
    assert settings.has_agent_key("maia") is False
    assert settings.has_agent_key("student_services", provider="anthropic") is False


async def test_provider_fake_registrado_funciona_end_to_end(monkeypatch) -> None:
    """Registrar un provider nuevo = 1 builder en el dict. El registry lo usa solo."""
    fake_chat = FakeChatClient(reply="hola desde el provider fake")
    register_fake_provider(monkeypatch, chat_client=fake_chat)

    storage = FakeObjectStorage()
    build_agent_fixture(storage, "tutor", config_overrides={"llm_provider": "fake"})
    registry = make_registry(storage)

    rt = await registry.get("westfield", "tutor")
    assert rt.chat_client is fake_chat
    assert await rt.chat_client.chat([]) == "hola desde el provider fake"
