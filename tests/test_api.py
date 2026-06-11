"""Tests del entrypoint HTTP — TestClient + fakes, sin AWS ni red."""

from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from tests.fakes import (
    TEST_BUCKET,
    FakeObjectStorage,
    build_agent_fixture,
)
from westfield_agent_back_python.entrypoints.api import create_app

TEST_CFG = {
    "project": {"name": "test", "env": "test", "log_level": "INFO"},
    "service": {
        "host": "127.0.0.1",
        "port": 8000,
        "cors_origins": ["http://localhost:5173"],
    },
    "worker": {"enabled": False, "interval_seconds": 10},
    "s3": {
        "bucket": TEST_BUCKET,
        "region": "us-east-1",
        # Multi-tenant: cada universidad vive bajo su propio prefijo.
        "prefix": "org={university_code}/agents",
    },
    "registry": {"ttl_seconds": 300, "negative_ttl_seconds": 30},
    "openai": {
        "api_key": None,  # sin key → los agentes responden fallback (200 igual)
        "base_url": "https://api.openai.com/v1",
        "embedding_model_fallback": "text-embedding-3-small",
    },
    "rate_limit": {"window_seconds": 60, "max_requests": 100},
}

W_PREFIX = "org=westfield/agents"  # donde viven los fixtures de westfield
BASE = "/api/v1/universities/westfield"
PAYLOAD = {"conversation_id": "c1", "user_id": "u1", "message": "hola", "history": []}


def _client(storage: FakeObjectStorage, cfg_overrides: dict | None = None) -> TestClient:
    cfg = deepcopy(TEST_CFG)
    for section, values in (cfg_overrides or {}).items():
        cfg[section].update(values)
    return TestClient(create_app(storage=storage, config=cfg))


def test_universidad_con_slug_invalido_404() -> None:
    storage = FakeObjectStorage()
    client = _client(storage)

    res = client.post("/api/v1/universities/OTRA UNI/agents/maia/chat", json=PAYLOAD)
    assert res.status_code == 404
    assert "universidad" in res.json()["error"]
    assert storage.get_attempts == {}  # slug inválido ni toca el storage


def test_universidad_sin_agentes_404() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    client = _client(storage)

    # maia existe bajo org=westfield/ pero no bajo org=otra-uni/.
    res = client.post("/api/v1/universities/otra-uni/agents/maia/chat", json=PAYLOAD)
    assert res.status_code == 404


def test_multitenant_cada_universidad_resuelve_su_prefijo() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    build_agent_fixture(storage, "tutor", prefix="org=esic/agents")
    client = _client(storage)

    res_w = client.get(f"{BASE}/agents/maia/health")
    assert res_w.status_code == 200
    assert res_w.json()["university"] == "westfield"

    res_e = client.get("/api/v1/universities/esic/agents/tutor/health")
    assert res_e.status_code == 200
    assert res_e.json()["university"] == "esic"

    # Aislamiento entre tenants: el agente de esic no existe en westfield.
    assert client.get(f"{BASE}/agents/tutor/health").status_code == 404


def test_chat_agente_inexistente_404() -> None:
    client = _client(FakeObjectStorage())
    res = client.post(f"{BASE}/agents/fantasma/chat", json=PAYLOAD)
    assert res.status_code == 404
    assert "fantasma" in res.json()["error"]


def test_chat_agente_valido_200_fallback_sin_api_key() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    client = _client(storage)

    res = client.post(f"{BASE}/agents/maia/chat", json=PAYLOAD)
    assert res.status_code == 200
    body = res.json()
    assert body["agent_id"] == "maia"
    assert body["conversation_id"] == "c1"
    assert body["fallback"] is True  # sin OPENAI_API_KEY → fallback controlado
    assert body["message"]


def test_aislamiento_agente_roto_503_y_sano_200_en_la_misma_instancia() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "sano", prefix=W_PREFIX)
    storage.put_text(f"{W_PREFIX}/roto/config.json", "{corrupto")  # config inválida
    client = _client(storage)

    res_roto = client.post(f"{BASE}/agents/roto/chat", json=PAYLOAD)
    assert res_roto.status_code == 503
    assert "roto" in res_roto.json()["error"]

    res_sano = client.post(f"{BASE}/agents/sano/chat", json=PAYLOAD)
    assert res_sano.status_code == 200  # criterio HU: el fallo no contagia


def test_rate_limit_429_por_ip_y_agente() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    build_agent_fixture(storage, "otro", prefix=W_PREFIX)
    client = _client(storage, {"rate_limit": {"max_requests": 2}})

    assert client.post(f"{BASE}/agents/maia/chat", json=PAYLOAD).status_code == 200
    assert client.post(f"{BASE}/agents/maia/chat", json=PAYLOAD).status_code == 200
    res = client.post(f"{BASE}/agents/maia/chat", json=PAYLOAD)
    assert res.status_code == 429
    assert "error" in res.json()

    # La cuota es por IP+tenant+agente: otro agente no está agotado.
    assert client.post(f"{BASE}/agents/otro/chat", json=PAYLOAD).status_code == 200


def test_health_global_lista_agentes_cargados() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    client = _client(storage)

    assert client.get("/api/v1/health").json()["agents"] == []  # lazy: nada cargado aún
    client.post(f"{BASE}/agents/maia/chat", json=PAYLOAD)

    body = client.get("/api/v1/health").json()
    assert body["ok"] is True
    assert body["s3_bucket"] == TEST_BUCKET
    assert [(a["university"], a["agent_id"]) for a in body["agents"]] == [("westfield", "maia")]


def test_health_por_agente_fuerza_carga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    client = _client(storage)

    res = client.get(f"{BASE}/agents/maia/health")
    assert res.status_code == 200
    body = res.json()
    assert body["university"] == "westfield"
    assert body["agent_id"] == "maia"
    assert body["ok"] is True
    assert body["degraded"] is False
    assert body["vector_store_id"] is None  # fixture sin RAG

    assert client.get(f"{BASE}/agents/fantasma/health").status_code == 404


def test_payload_invalido_422() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia", prefix=W_PREFIX)
    client = _client(storage)

    res = client.post(f"{BASE}/agents/maia/chat", json={"message": "sin ids"})
    assert res.status_code == 422
