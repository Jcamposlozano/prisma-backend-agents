"""Tests del AgentRegistry: carga, caché, TTL, locks y aislamiento."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes import FakeObjectStorage, build_agent_fixture, make_registry
from westfield_agent_back_python.domain.errors import AgentLoadError, AgentNotFoundError

VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
CONFIG_KEY = "agents/maia/config.json"


async def test_carga_ok_con_vector_store() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    rt = await registry.get("maia")
    assert rt.config.agent_id == "maia"
    assert rt.system_prompt.startswith("Sos un agente de prueba")
    assert rt.chat_client is not None
    assert rt.retriever is not None
    assert rt.degraded is False
    assert rt.chunk_count == 3


async def test_cache_hit_no_vuelve_a_storage() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    await registry.get("maia")
    await registry.get("maia")
    assert storage.get_attempts[CONFIG_KEY] == 1


async def test_agente_inexistente_404_y_cache_negativa() -> None:
    storage = FakeObjectStorage()
    registry = make_registry(storage)

    with pytest.raises(AgentNotFoundError):
        await registry.get("fantasma")
    with pytest.raises(AgentNotFoundError):
        await registry.get("fantasma")
    # La segunda vez NO golpea storage (caché negativa).
    assert storage.get_attempts["agents/fantasma/config.json"] == 1


async def test_agent_id_invalido_es_not_found_sin_tocar_storage() -> None:
    storage = FakeObjectStorage()
    registry = make_registry(storage)

    for bad_id in ["../evil", "MAYUS", "con espacios", "", "a/b"]:
        with pytest.raises(AgentNotFoundError):
            await registry.get(bad_id)
    assert storage.get_attempts == {}


async def test_config_corrupta_es_load_error() -> None:
    storage = FakeObjectStorage()
    storage.put_text(CONFIG_KEY, "{esto no es json valido")
    registry = make_registry(storage)

    with pytest.raises(AgentLoadError):
        await registry.get("maia")


async def test_prompt_ausente_es_load_error() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    storage.delete("agents/maia/prompts/system.md")
    registry = make_registry(storage)

    with pytest.raises(AgentLoadError):
        await registry.get("maia")


async def test_vector_store_ausente_degrada_sin_romper() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(
        storage,
        "maia",
        config_overrides={
            "vector_store_id": "v9",
            "vector_store_s3_uri": "s3://test-bucket/agents/maia/vector_store/v9/",
        },
    )
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    rt = await registry.get("maia")
    assert rt.degraded is True
    assert rt.retriever is None  # responde sin RAG — fallback controlado


async def test_sin_api_key_chat_client_none_pero_carga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    registry = make_registry(storage, api_keys={})

    rt = await registry.get("maia")
    assert rt.chat_client is None


async def test_ttl_expirado_recarga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    now = [0.0]
    registry = make_registry(storage, ttl=100, clock=lambda: now[0])

    await registry.get("maia")
    now[0] = 50.0
    await registry.get("maia")
    assert storage.get_attempts[CONFIG_KEY] == 1  # dentro del TTL

    now[0] = 150.0
    await registry.get("maia")
    assert storage.get_attempts[CONFIG_KEY] == 2  # expiró → recarga


async def test_recarga_fallida_sirve_stale() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    now = [0.0]
    registry = make_registry(storage, ttl=100, negative_ttl=30, clock=lambda: now[0])

    rt1 = await registry.get("maia")
    now[0] = 150.0
    storage.fail_keys.add(CONFIG_KEY)  # storage roto en la recarga

    rt2 = await registry.get("maia")
    assert rt2 is rt1  # sirvió la versión stale

    # Backoff: el próximo get inmediato no vuelve a intentar la recarga.
    attempts = storage.get_attempts[CONFIG_KEY]
    await registry.get("maia")
    assert storage.get_attempts[CONFIG_KEY] == attempts


async def test_gets_concurrentes_cargan_una_sola_vez() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    results = await asyncio.gather(*[registry.get("maia") for _ in range(10)])
    assert all(rt is results[0] for rt in results)
    assert storage.get_attempts[CONFIG_KEY] == 1


async def test_aislamiento_un_agente_roto_no_afecta_otros() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "sano")
    storage.put_text("agents/roto/config.json", "{corrupto")
    registry = make_registry(storage)

    with pytest.raises(AgentLoadError):
        await registry.get("roto")
    rt = await registry.get("sano")  # el sano sigue operando
    assert rt.config.agent_id == "sano"


async def test_invalidate_fuerza_recarga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    registry = make_registry(storage)

    await registry.get("maia")
    registry.invalidate("maia")
    await registry.get("maia")
    assert storage.get_attempts[CONFIG_KEY] == 2


async def test_snapshot_lista_agentes_cargados() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    build_agent_fixture(storage, "demo")
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    await registry.get("maia")
    await registry.get("demo")
    snap = registry.snapshot()
    assert [s["agent_id"] for s in snap] == ["demo", "maia"]
    maia = next(s for s in snap if s["agent_id"] == "maia")
    assert maia["chunks"] == 3
    assert maia["degraded"] is False
