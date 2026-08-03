"""Tests del builder del system prompt (genérico, multi-agente)."""

from __future__ import annotations

from westfield_agent_back_python.application.prompt_builder import build_system_prompt
from westfield_agent_back_python.domain.rag import (
    AlwaysIncludeDoc,
    ChunkMeta,
    RetrievedChunk,
)

BASE = "# Identidad\nSos un agente de prueba."


def _chunk(*, instructor_only: bool = False) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=ChunkMeta(
            id="x#0",
            doc_file="x.pdf",
            doc_title="X Doc",
            doc_tag="case",
            instructor_only=instructor_only,
            text="contenido relevante",
        ),
        similarity=0.876,
    )


def test_prompt_arranca_con_el_base_prompt_del_agente() -> None:
    prompt = build_system_prompt(base_prompt=BASE)
    assert prompt.startswith("# Identidad")
    assert "Sos un agente de prueba." in prompt


def test_sin_always_include_no_imprime_bloque_de_contexto() -> None:
    prompt = build_system_prompt(base_prompt=BASE)
    assert "# Contexto siempre presente" not in prompt
    assert "# Contexto recuperado" not in prompt


def test_con_always_include_imprime_docs_con_header() -> None:
    doc = AlwaysIncludeDoc(
        doc_file="rubrica.docx",
        doc_title="Rúbrica",
        doc_tag="rubric",
        instructor_only=False,
        text="texto de la rúbrica",
    )
    prompt = build_system_prompt(base_prompt=BASE, always_include_docs=[doc])
    assert "# Contexto siempre presente" in prompt
    assert "## RUBRIC · Rúbrica" in prompt
    assert "texto de la rúbrica" in prompt
    assert "[instructor_only — PRIVADO]" not in prompt


def test_chunk_instructor_only_marcado_en_header() -> None:
    prompt = build_system_prompt(base_prompt=BASE, retrieved_chunks=[_chunk(instructor_only=True)])
    assert "[instructor_only — PRIVADO]" in prompt
    assert "sim=0.876" in prompt


def test_state_dict_se_renderiza_como_bloque_de_estado() -> None:
    prompt = build_system_prompt(
        base_prompt=BASE,
        state={"current_question": 2, "turns_for_current_question": 3},
    )
    assert "# Estado actual" in prompt
    assert "- current_question = 2" in prompt
    assert "- turns_for_current_question = 3" in prompt


def test_sin_state_no_imprime_bloque_estado() -> None:
    prompt = build_system_prompt(base_prompt=BASE)
    assert "# Estado actual" not in prompt


def test_state_vacio_no_imprime_bloque_estado() -> None:
    prompt = build_system_prompt(base_prompt=BASE, state={})
    assert "# Estado actual" not in prompt
