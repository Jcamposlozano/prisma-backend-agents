"""Tests del AgentRegistry: carga, caché, TTL, locks y aislamiento."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes import FakeObjectStorage, build_agent_fixture, make_registry
from westfield_agent_back_python.domain.errors import (
    AgentLoadError,
    AgentNotFoundError,
    UniversityNotFoundError,
)

VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
U = "westfield"
CONFIG_KEY = "agents/maia/config.json"


async def test_carga_ok_con_vector_store() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    rt = await registry.get(U, "maia")
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

    await registry.get(U, "maia")
    await registry.get(U, "maia")
    assert storage.get_attempts[CONFIG_KEY] == 1


async def test_agente_inexistente_404_y_cache_negativa() -> None:
    storage = FakeObjectStorage()
    registry = make_registry(storage)

    with pytest.raises(AgentNotFoundError):
        await registry.get(U, "fantasma")
    with pytest.raises(AgentNotFoundError):
        await registry.get(U, "fantasma")
    # La segunda vez NO golpea storage (caché negativa).
    assert storage.get_attempts["agents/fantasma/config.json"] == 1


async def test_slugs_invalidos_son_not_found_sin_tocar_storage() -> None:
    storage = FakeObjectStorage()
    registry = make_registry(storage)

    for bad_id in ["../evil", "MAYUS", "con espacios", "", "a/b"]:
        with pytest.raises(AgentNotFoundError):
            await registry.get(U, bad_id)
        with pytest.raises(UniversityNotFoundError):
            await registry.get(bad_id, "maia")
    assert storage.get_attempts == {}


async def test_prefijo_multitenant_resuelve_por_universidad() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix="org=westfield/agents")
    build_agent_fixture(storage, "tutor", prefix="org=esic/agents")
    registry = make_registry(storage, prefix="org={university_code}/agents")

    rt_w = await registry.get("westfield", "maia")
    assert rt_w.config.agent_id == "maia"
    rt_e = await registry.get("esic", "tutor")
    assert rt_e.config.agent_id == "tutor"

    # Los tenants están aislados: maia no existe bajo org=esic/.
    with pytest.raises(AgentNotFoundError):
        await registry.get("esic", "maia")


async def test_config_corrupta_es_load_error() -> None:
    storage = FakeObjectStorage()
    storage.put_text(CONFIG_KEY, "{esto no es json valido")
    registry = make_registry(storage)

    with pytest.raises(AgentLoadError):
        await registry.get(U, "maia")


async def test_prompt_ausente_es_load_error() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    storage.delete("agents/maia/prompts/system.md")
    registry = make_registry(storage)

    with pytest.raises(AgentLoadError):
        await registry.get(U, "maia")


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

    rt = await registry.get(U, "maia")
    assert rt.degraded is True
    assert rt.retriever is None  # responde sin RAG — fallback controlado


async def test_sin_api_key_chat_client_none_pero_carga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    registry = make_registry(storage, api_keys={})

    rt = await registry.get(U, "maia")
    assert rt.chat_client is None


# ----------------------------------- keys dedicadas por agente (gasto separado)


async def test_agente_usa_su_key_dedicada() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    registry = make_registry(
        storage,
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia"}},
    )

    rt = await registry.get(U, "maia")
    assert rt.dedicated_api_key is True
    assert rt.chat_client._api_key == "sk-maia"
    # La query de RAG también se factura contra la key del agente.
    assert rt.retriever._embeddings._api_key == "sk-maia"


async def test_agente_sin_key_dedicada_usa_la_global() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "westy")
    registry = make_registry(
        storage,
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia"}},
    )

    rt = await registry.get(U, "westy")
    assert rt.dedicated_api_key is False
    assert rt.chat_client._api_key == "sk-global"


async def test_aislamiento_de_keys_entre_agentes_de_la_misma_instancia() -> None:
    """Cada agente factura contra SU key — es el objetivo de todo el cambio."""
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    build_agent_fixture(storage, "westy")
    build_agent_fixture(storage, "student_services")
    registry = make_registry(
        storage,
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia", "STUDENT_SERVICES": "sk-ss"}},
    )

    maia = await registry.get(U, "maia")
    westy = await registry.get(U, "westy")
    services = await registry.get(U, "student_services")

    assert maia.chat_client._api_key == "sk-maia"
    assert services.chat_client._api_key == "sk-ss"
    assert westy.chat_client._api_key == "sk-global"  # sin dedicada → global
    assert len({maia.chat_client._api_key, services.chat_client._api_key}) == 2


async def test_agente_con_key_dedicada_responde_sin_key_global() -> None:
    """Sin OPENAI_API_KEY, el que tiene la suya funciona y el resto va a fallback."""
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    build_agent_fixture(storage, "westy")
    registry = make_registry(storage, agent_api_keys={"openai": {"MAIA": "sk-maia"}})

    assert (await registry.get(U, "maia")).chat_client._api_key == "sk-maia"
    assert (await registry.get(U, "westy")).chat_client is None


async def test_snapshot_reporta_origen_de_la_key_sin_exponerla() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    build_agent_fixture(storage, "westy")
    registry = make_registry(
        storage,
        api_keys={"openai": "sk-global"},
        agent_api_keys={"openai": {"MAIA": "sk-maia"}},
    )
    await registry.get(U, "maia")
    await registry.get(U, "westy")

    por_agente = {e["agent_id"]: e for e in registry.snapshot()}
    assert por_agente["maia"]["api_key"] == "dedicada"
    assert por_agente["westy"]["api_key"] == "global"
    assert "sk-maia" not in str(registry.snapshot())


async def test_ttl_expirado_recarga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    now = [0.0]
    registry = make_registry(storage, ttl=100, clock=lambda: now[0])

    await registry.get(U, "maia")
    now[0] = 50.0
    await registry.get(U, "maia")
    assert storage.get_attempts[CONFIG_KEY] == 1  # dentro del TTL

    now[0] = 150.0
    await registry.get(U, "maia")
    assert storage.get_attempts[CONFIG_KEY] == 2  # expiró → recarga


async def test_recarga_fallida_sirve_stale() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    now = [0.0]
    registry = make_registry(storage, ttl=100, negative_ttl=30, clock=lambda: now[0])

    rt1 = await registry.get(U, "maia")
    now[0] = 150.0
    storage.fail_keys.add(CONFIG_KEY)  # storage roto en la recarga

    rt2 = await registry.get(U, "maia")
    assert rt2 is rt1  # sirvió la versión stale

    # Backoff: el próximo get inmediato no vuelve a intentar la recarga.
    attempts = storage.get_attempts[CONFIG_KEY]
    await registry.get(U, "maia")
    assert storage.get_attempts[CONFIG_KEY] == attempts


async def test_gets_concurrentes_cargan_una_sola_vez() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    results = await asyncio.gather(*[registry.get(U, "maia") for _ in range(10)])
    assert all(rt is results[0] for rt in results)
    assert storage.get_attempts[CONFIG_KEY] == 1


async def test_aislamiento_un_agente_roto_no_afecta_otros() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "sano")
    storage.put_text("agents/roto/config.json", "{corrupto")
    registry = make_registry(storage)

    with pytest.raises(AgentLoadError):
        await registry.get(U, "roto")
    rt = await registry.get(U, "sano")  # el sano sigue operando
    assert rt.config.agent_id == "sano"


async def test_invalidate_fuerza_recarga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    registry = make_registry(storage)

    await registry.get(U, "maia")
    registry.invalidate(U, "maia")
    await registry.get(U, "maia")
    assert storage.get_attempts[CONFIG_KEY] == 2


async def test_list_agents_descubre_los_publicados() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)  # con RAG
    build_agent_fixture(storage, "demo")  # sin RAG
    registry = make_registry(storage)

    agents = await registry.list_agents(U)
    ids = {a["agent_id"] for a in agents}
    assert ids == {"maia", "demo"}
    maia = next(a for a in agents if a["agent_id"] == "maia")
    demo = next(a for a in agents if a["agent_id"] == "demo")
    assert maia["has_rag"] is True
    assert demo["has_rag"] is False
    assert maia["agent_name"]  # nombre presente


async def test_list_agents_sin_agentes_lista_vacia() -> None:
    registry = make_registry(FakeObjectStorage())
    assert await registry.list_agents(U) == []


async def test_list_agents_slug_invalido_es_error() -> None:
    registry = make_registry(FakeObjectStorage())
    with pytest.raises(UniversityNotFoundError):
        await registry.list_agents("MAYUS")


async def test_list_agents_omite_config_corrupta() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "sano")
    storage.put_text("agents/roto/config.json", "{corrupto")
    registry = make_registry(storage)

    agents = await registry.list_agents(U)
    assert [a["agent_id"] for a in agents] == ["sano"]  # el roto se omite, no rompe


async def test_snapshot_lista_agentes_cargados() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", vectors=VECTORS)
    build_agent_fixture(storage, "demo")
    registry = make_registry(storage, api_keys={"openai": "sk-test"})

    await registry.get(U, "maia")
    await registry.get(U, "demo")
    snap = registry.snapshot()
    assert [s["agent_id"] for s in snap] == ["demo", "maia"]
    maia = next(s for s in snap if s["agent_id"] == "maia")
    assert maia["university"] == U
    assert maia["chunks"] == 3
    assert maia["degraded"] is False
