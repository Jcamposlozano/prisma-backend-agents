"""Tests del use case ChatWithAgent."""

from __future__ import annotations

import json

from tests.fakes import (
    FakeChatClient,
    FakeEmbeddings,
    FakeObjectStorage,
    build_agent_fixture,
    make_chunk,
    make_registry,
    register_fake_provider,
)
from westfield_agent_back_python.application.chat_with_agent import (
    DEFAULT_FALLBACK_MESSAGE,
    MAX_HISTORY_TURNS,
    MAX_MESSAGE_CHARS,
    ChatWithAgent,
)
from westfield_agent_back_python.domain.chat import ChatRequest, ChatTurn

VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
U = "westfield"


def _request(message: str = "hola", **kwargs) -> ChatRequest:
    return ChatRequest(conversation_id="c1", user_id="u1", message=message, **kwargs)


def _setup(
    monkeypatch,
    *,
    chat: FakeChatClient,
    embeddings: FakeEmbeddings | None = None,
    config_overrides: dict | None = None,
    chunks: list[dict] | None = None,
    with_rag: bool = True,
) -> ChatWithAgent:
    storage = FakeObjectStorage()
    register_fake_provider(
        monkeypatch, chat_client=chat, embeddings=embeddings or FakeEmbeddings()
    )
    build_agent_fixture(
        storage,
        "tutor",
        vectors=VECTORS if with_rag else None,
        chunks=chunks,
        config_overrides={"llm_provider": "fake", **(config_overrides or {})},
        embedding_provider="fake",
        embedding_model="fake-embeddings",
    )
    registry = make_registry(storage, api_keys={"fake": "x"})
    return ChatWithAgent(registry=registry)


async def test_happy_path_json_con_structured_passthrough(monkeypatch) -> None:
    reply = json.dumps({"message": "Hola estudiante", "rubric_level": "superior"})
    chat = FakeChatClient(reply=reply)
    use_case = _setup(monkeypatch, chat=chat, config_overrides={"response_format": "json"})

    res = await use_case(U, "tutor", _request())
    assert res.agent_id == "tutor"
    assert res.conversation_id == "c1"
    assert res.message == "Hola estudiante"
    assert res.structured == {"message": "Hola estudiante", "rubric_level": "superior"}
    assert res.fallback is False
    assert res.rag_used is True
    assert len(res.sources) == 1  # query [1,0,0] → solo el chunk 0 pasa min_similarity
    assert res.sources[0].doc_title == "Doc 0"


async def test_response_format_text_sin_structured(monkeypatch) -> None:
    chat = FakeChatClient(reply="respuesta plana")
    use_case = _setup(monkeypatch, chat=chat)

    res = await use_case(U, "tutor", _request())
    assert res.message == "respuesta plana"
    assert res.structured is None


async def test_retriever_roto_sigue_sin_rag(monkeypatch) -> None:
    chat = FakeChatClient(reply="ok")
    use_case = _setup(
        monkeypatch, chat=chat, embeddings=FakeEmbeddings(error=RuntimeError("api caída"))
    )

    res = await use_case(U, "tutor", _request())
    assert res.rag_used is False
    assert res.sources == []
    assert res.fallback is False
    assert res.message == "ok"


async def test_llm_roto_devuelve_fallback_del_agente(monkeypatch) -> None:
    chat = FakeChatClient(error=RuntimeError("boom"))
    use_case = _setup(
        monkeypatch, chat=chat, config_overrides={"fallback_message": "Volvé en un rato."}
    )

    res = await use_case(U, "tutor", _request())
    assert res.fallback is True
    assert res.message == "Volvé en un rato."
    assert res.rag_used is False


async def test_sin_chat_client_devuelve_fallback_default(monkeypatch) -> None:
    storage = FakeObjectStorage()
    build_agent_fixture(storage, "tutor")  # llm_provider openai, sin API key
    registry = make_registry(storage, api_keys={})
    use_case = ChatWithAgent(registry=registry)

    res = await use_case(U, "tutor", _request())
    assert res.fallback is True
    assert res.message == DEFAULT_FALLBACK_MESSAGE


async def test_leak_marker_reemplaza_message_y_structured(monkeypatch) -> None:
    reply = json.dumps({"message": "Mirá las Notas del instructor", "rubric_level": "pobre"})
    chat = FakeChatClient(reply=reply)
    use_case = _setup(
        monkeypatch,
        chat=chat,
        config_overrides={
            "response_format": "json",
            "leak_markers": ["Notas del instructor"],
            "leak_replacement_message": "No comparto material interno.",
        },
    )

    res = await use_case(U, "tutor", _request())
    assert res.message == "No comparto material interno."
    assert res.structured["message"] == "No comparto material interno."
    assert res.structured["rubric_level"] == "pobre"  # el resto se preserva


async def test_sources_excluyen_chunks_instructor_only(monkeypatch) -> None:
    chat = FakeChatClient(reply="ok")
    chunks = [make_chunk(0, instructor_only=True), make_chunk(1), make_chunk(2)]
    use_case = _setup(monkeypatch, chat=chat, chunks=chunks)

    res = await use_case(U, "tutor", _request())
    assert res.rag_used is True  # el chunk sí se usó como contexto...
    assert res.sources == []  # ...pero no se expone su metadata


async def test_clamps_history_y_message(monkeypatch) -> None:
    chat = FakeChatClient(reply="ok")
    use_case = _setup(monkeypatch, chat=chat, with_rag=False)

    history = [
        ChatTurn(role="user" if i % 2 == 0 else "assistant", content=f"turno {i}")
        for i in range(50)
    ]
    res = await use_case(U, "tutor", _request(message="x" * 10_000, history=history))
    assert res.message == "ok"

    sent = chat.calls[0]
    # 1 system + MAX_HISTORY_TURNS de historial + 1 mensaje nuevo
    assert len(sent) == 1 + MAX_HISTORY_TURNS + 1
    assert sent[0]["role"] == "system"
    assert sent[1]["content"] == "turno 20"  # se conservan los ÚLTIMOS 30
    assert len(sent[-1]["content"]) == MAX_MESSAGE_CHARS


async def test_primer_turno_sin_mensaje_inyecta_apertura(monkeypatch) -> None:
    chat = FakeChatClient(reply="¡Bienvenido!")
    use_case = _setup(monkeypatch, chat=chat, with_rag=False)

    res = await use_case(U, "tutor", _request(message=""))
    assert res.message == "¡Bienvenido!"
    assert chat.calls[0][-1] == {"role": "user", "content": "Hola, vamos a empezar."}


async def test_hard_rules_fuerzan_flags_del_structured(monkeypatch) -> None:
    # El modelo dice "no avances"; la hard rule del config dice que con
    # N >= 3 se avanza igual — el server fuerza el flag.
    reply = json.dumps({"message": "Sigamos acá", "advance_to_next_question": False})
    chat = FakeChatClient(reply=reply)
    use_case = _setup(
        monkeypatch,
        chat=chat,
        with_rag=False,
        config_overrides={
            "response_format": "json",
            "hard_rules": [
                {
                    "when": {"state.turns_for_current_question": {"gte": 3}},
                    "set": {"advance_to_next_question": True},
                }
            ],
        },
    )

    res = await use_case(U, "tutor", _request(state={"turns_for_current_question": 4}))
    assert res.structured["advance_to_next_question"] is True

    # Con N bajo, la regla no aplica y manda lo que dijo el modelo.
    res2 = await use_case(U, "tutor", _request(state={"turns_for_current_question": 1}))
    assert res2.structured["advance_to_next_question"] is False


async def test_state_llega_al_system_prompt(monkeypatch) -> None:
    chat = FakeChatClient(reply="ok")
    use_case = _setup(monkeypatch, chat=chat, with_rag=False)

    await use_case(U, "tutor", _request(state={"current_question": 2}))
    system = chat.calls[0][0]["content"]
    assert "# Estado actual" in system
    assert "- current_question = 2" in system
