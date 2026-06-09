"""Tests de los sanitizadores defensivos del response del LLM."""

from __future__ import annotations

import json

from westfield_agent_back_python.application.sanitizers import (
    clamp_question,
    is_rubric_level,
    looks_like_notes_leak,
    safe_parse_maia_json,
)


def test_looks_like_notes_leak_detecta_marcadores() -> None:
    assert looks_like_notes_leak("Mirá las Notas del instructor que te pasé.")
    assert looks_like_notes_leak("...notas del profesor sobre el caso...")
    assert looks_like_notes_leak("Te explico las Vías de Respuesta esperadas.")
    assert looks_like_notes_leak("Reflexiones que Puede Suscitar este tema.")


def test_looks_like_notes_leak_no_falsea_positivos() -> None:
    assert not looks_like_notes_leak("¿Qué evidencia respalda tu argumento?")
    assert not looks_like_notes_leak("")


def test_is_rubric_level() -> None:
    for level in ["muy_pobre", "pobre", "satisfactorio", "superior", "excelente"]:
        assert is_rubric_level(level)
    assert not is_rubric_level("excelentisimo")
    assert not is_rubric_level(None)
    assert not is_rubric_level(5)


def test_clamp_question() -> None:
    assert clamp_question(1) == 1
    assert clamp_question(2) == 2
    assert clamp_question(3) == 3
    assert clamp_question(0) == 1
    assert clamp_question(99) == 1
    assert clamp_question("2") == 1  # type mismatch → default
    assert clamp_question(None) == 1


def test_safe_parse_maia_json_happy_path() -> None:
    raw = json.dumps(
        {
            "message": "Hola",
            "rubric_level": "superior",
            "current_question": 2,
            "advance_to_next_question": True,
            "is_final_summary": False,
            "unresolved_points": ["a", "b"],
        }
    )
    res = safe_parse_maia_json(raw)
    assert res.message == "Hola"
    assert res.rubric_level == "superior"
    assert res.current_question == 2
    assert res.advance_to_next_question is True
    assert res.is_final_summary is False
    assert res.unresolved_points == ["a", "b"]


def test_safe_parse_maia_json_strippea_backticks() -> None:
    raw = '```json\n{"message": "Hi", "rubric_level": "satisfactorio", "current_question": 1, "advance_to_next_question": false, "is_final_summary": false, "unresolved_points": []}\n```'
    res = safe_parse_maia_json(raw)
    assert res.message == "Hi"
    assert res.rubric_level == "satisfactorio"


def test_safe_parse_maia_json_fallback_a_texto_crudo() -> None:
    raw = "Esto no es JSON válido — sólo texto."
    res = safe_parse_maia_json(raw)
    assert res.message == raw
    assert res.rubric_level == "satisfactorio"
    assert res.current_question == 1
    assert res.advance_to_next_question is False


def test_safe_parse_maia_json_clampea_rubric_invalido() -> None:
    raw = json.dumps({"message": "x", "rubric_level": "magnifico", "current_question": 7})
    res = safe_parse_maia_json(raw)
    assert res.rubric_level == "satisfactorio"
    assert res.current_question == 1


def test_safe_parse_maia_json_limita_unresolved_a_10() -> None:
    raw = json.dumps({"message": "x", "unresolved_points": [str(i) for i in range(20)]})
    res = safe_parse_maia_json(raw)
    assert len(res.unresolved_points) == 10
