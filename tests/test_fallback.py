"""Tests del modo fallback offline."""

from __future__ import annotations

from westfield_agent_back_python.application.fallback import (
    FALLBACK_FOLLOWUPS,
    FALLBACK_OPENINGS,
    build_fallback_response,
)
from westfield_agent_back_python.domain.responses import MaiaTurn


def test_fallback_history_vacia_devuelve_opening_q1() -> None:
    res = build_fallback_response([])
    assert res.message == FALLBACK_OPENINGS[1]
    assert res.current_question == 1
    assert res.fallback is True
    assert res.advance_to_next_question is False


def test_fallback_avanza_de_pregunta_cada_4_turnos_estudiante() -> None:
    # 0 student turns → Q1
    res = build_fallback_response([MaiaTurn(role="maia", content="x")])
    assert res.current_question == 1

    # 4 student turns → Q2
    hist = [MaiaTurn(role="student", content=f"r{i}") for i in range(4)]
    res = build_fallback_response(hist)
    assert res.current_question == 2

    # 8 student turns → Q3
    hist = [MaiaTurn(role="student", content=f"r{i}") for i in range(8)]
    res = build_fallback_response(hist)
    assert res.current_question == 3

    # 20 student turns → siguen en Q3 (clamp en 3)
    hist = [MaiaTurn(role="student", content=f"r{i}") for i in range(20)]
    res = build_fallback_response(hist)
    assert res.current_question == 3


def test_fallback_ultimo_turn_student_devuelve_followup() -> None:
    hist = [MaiaTurn(role="student", content="algo")]
    res = build_fallback_response(hist)
    assert res.message in FALLBACK_FOLLOWUPS


def test_fallback_ultimo_turn_maia_devuelve_opening() -> None:
    hist = [
        MaiaTurn(role="student", content="x"),
        MaiaTurn(role="maia", content="y"),
    ]
    res = build_fallback_response(hist)
    assert res.message in FALLBACK_OPENINGS.values()
