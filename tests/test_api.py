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
    "service": {"host": "127.0.0.1", "port": 8000, "cors_origins": ["http://localhost:5173"]},
    "worker": {"enabled": False, "interval_seconds": 10},
    "s3": {"bucket": TEST_BUCKET, "region": "us-east-1", "prefix": "agents"},
    "registry": {"ttl_seconds": 300, "negative_ttl_seconds": 30},
    "openai": {
        "api_key": None,  # sin key → los agentes responden fallback (200 igual)
        "base_url": "https://api.openai.com/v1",
        "embedding_model_fallback": "text-embedding-3-small",
    },
    "rate_limit": {"window_seconds": 60, "max_requests": 100},
}

PAYLOAD = {"conversation_id": "c1", "user_id": "u1", "message": "hola", "history": []}


def _client(storage: FakeObjectStorage, cfg_overrides: dict | None = None) -> TestClient:
    cfg = deepcopy(TEST_CFG)
    for section, values in (cfg_overrides or {}).items():
        cfg[section].update(values)
    return TestClient(create_app(storage=storage, config=cfg))


def test_chat_agente_inexistente_404() -> None:
    client = _client(FakeObjectStorage())
    res = client.post("/api/agents/fantasma/chat", json=PAYLOAD)
    assert res.status_code == 404
    assert "fantasma" in res.json()["error"]


def test_chat_agente_valido_200_fallback_sin_api_key() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    client = _client(storage)

    res = client.post("/api/agents/maia/chat", json=PAYLOAD)
    assert res.status_code == 200
    body = res.json()
    assert body["agent_id"] == "maia"
    assert body["conversation_id"] == "c1"
    assert body["fallback"] is True  # sin OPENAI_API_KEY → fallback controlado
    assert body["message"]


def test_aislamiento_agente_roto_503_y_sano_200_en_la_misma_instancia() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "sano")
    storage.put_text("agents/roto/config.json", "{corrupto")  # config inválida
    client = _client(storage)

    res_roto = client.post("/api/agents/roto/chat", json=PAYLOAD)
    assert res_roto.status_code == 503
    assert "roto" in res_roto.json()["error"]

    res_sano = client.post("/api/agents/sano/chat", json=PAYLOAD)
    assert res_sano.status_code == 200  # criterio HU: el fallo no contagia


def test_rate_limit_429_por_ip_y_agente() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    build_agent_fixture(storage, "otro")
    client = _client(storage, {"rate_limit": {"max_requests": 2}})

    assert client.post("/api/agents/maia/chat", json=PAYLOAD).status_code == 200
    assert client.post("/api/agents/maia/chat", json=PAYLOAD).status_code == 200
    res = client.post("/api/agents/maia/chat", json=PAYLOAD)
    assert res.status_code == 429
    assert "error" in res.json()

    # La cuota es por IP+agente: otro agente no está agotado.
    assert client.post("/api/agents/otro/chat", json=PAYLOAD).status_code == 200


def test_health_global_lista_agentes_cargados() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    client = _client(storage)

    assert client.get("/api/health").json()["agents"] == []  # lazy: nada cargado aún
    client.post("/api/agents/maia/chat", json=PAYLOAD)

    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["s3_bucket"] == TEST_BUCKET
    assert [a["agent_id"] for a in body["agents"]] == ["maia"]


def test_health_por_agente_fuerza_carga() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    client = _client(storage)

    res = client.get("/api/agents/maia/health")
    assert res.status_code == 200
    body = res.json()
    assert body["agent_id"] == "maia"
    assert body["ok"] is True
    assert body["degraded"] is False
    assert body["vector_store_id"] is None  # fixture sin RAG

    assert client.get("/api/agents/fantasma/health").status_code == 404


def test_payload_invalido_422() -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "maia")
    client = _client(storage)

    res = client.post("/api/agents/maia/chat", json={"message": "sin ids"})
    assert res.status_code == 422
