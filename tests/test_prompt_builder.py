"""Tests del builder del system prompt."""

from __future__ import annotations

from westfield_agent_back_python.application.prompt_builder import (
    TurnState,
    build_system_prompt,
)
from westfield_agent_back_python.domain.rag import (
    AlwaysIncludeDoc,
    RagChunk,
    RetrievedChunk,
)


def _chunk(*, instructor_only: bool = False) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=RagChunk(
            id="x#0",
            doc_file="x.pdf",
            doc_title="X Doc",
            doc_tag="case",
            instructor_only=instructor_only,
            text="contenido relevante",
            embedding=[0.0, 1.0],
        ),
        similarity=0.876,
    )


def test_prompt_base_siempre_incluye_identidad() -> None:
    prompt = build_system_prompt()
    assert "# Identidad" in prompt
    assert "método socrático" in prompt
    assert "# Recordatorio final" in prompt


def test_sin_always_include_imprime_placeholder() -> None:
    prompt = build_system_prompt()
    assert "(vacío — corre `npm run ingest`" in prompt


def test_con_always_include_imprime_docs_con_header() -> None:
    doc = AlwaysIncludeDoc(
        doc_file="rubrica.docx",
        doc_title="Rúbrica",
        doc_tag="rubric",
        instructor_only=False,
        text="texto de la rúbrica",
    )
    prompt = build_system_prompt(always_include_docs=[doc])
    assert "## RUBRIC · Rúbrica" in prompt
    assert "texto de la rúbrica" in prompt
    assert "[instructor_only — PRIVADO]" not in prompt


def test_chunk_instructor_only_marcado_en_header() -> None:
    prompt = build_system_prompt(retrieved_chunks=[_chunk(instructor_only=True)])
    assert "[instructor_only — PRIVADO]" in prompt
    assert "sim=0.876" in prompt


def test_turn_state_inyecta_bloque_de_estado() -> None:
    prompt = build_system_prompt(
        turn_state=TurnState(current_question=2, turns_for_current_question=3)
    )
    assert "# Estado actual" in prompt
    assert "current_question = 2" in prompt
    assert "turn_count_for_current_question = 3" in prompt
    assert "regla de avance" in prompt


def test_sin_turn_state_no_imprime_bloque_estado() -> None:
    prompt = build_system_prompt()
    assert "# Estado actual" not in prompt
