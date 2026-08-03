"""Tests del evaluador de hard rules (mecánicas deterministas por agente)."""

from __future__ import annotations

from westfield_agent_back_python.application.hard_rules import apply_hard_rules
from westfield_agent_back_python.domain.agent import HardRule

# El set de reglas de Maia — el caso real que motivó la feature.
MAIA_RULES = [
    HardRule(
        when={
            "state.turns_for_current_question": {"gte": 3},
            "state.current_question": {"lte": 2},
        },
        set={"advance_to_next_question": True},
    ),
    HardRule(
        when={
            "state.turns_for_current_question": {"gte": 3},
            "state.current_question": {"eq": 3},
        },
        set={"is_final_summary": True},
    ),
    HardRule(
        when={
            "structured.rubric_level": {"in": ["superior", "excelente"]},
            "state.current_question": {"lte": 2},
        },
        set={"advance_to_next_question": True},
    ),
    HardRule(
        when={
            "structured.rubric_level": {"in": ["satisfactorio", "superior", "excelente"]},
            "state.turns_for_current_question": {"gte": 2},
            "state.current_question": {"lte": 2},
        },
        set={"advance_to_next_question": True},
    ),
    # En la última pregunta no existe "siguiente": avanzar = entregar el
    # resumen final (bug detectado en el replay de la entrevista 01, donde
    # el modelo avanzó a una Q4 inexistente).
    HardRule(
        when={
            "structured.advance_to_next_question": {"eq": True},
            "state.current_question": {"gte": 3},
        },
        set={"is_final_summary": True, "advance_to_next_question": False},
    ),
]


def test_n_alto_fuerza_avance_aunque_el_modelo_diga_que_no() -> None:
    structured = {"message": "...", "rubric_level": "pobre", "advance_to_next_question": False}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 1, "turns_for_current_question": 4},
        structured=structured,
    )
    assert overridden is True
    assert out["advance_to_next_question"] is True
    assert out["rubric_level"] == "pobre"  # el juicio del modelo no se toca


def test_q3_con_n_alto_fuerza_resumen_final() -> None:
    structured = {"is_final_summary": False, "advance_to_next_question": False}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 3, "turns_for_current_question": 4},
        structured=structured,
    )
    assert overridden is True
    assert out["is_final_summary"] is True
    assert out["advance_to_next_question"] is False  # la regla de avance pide Q <= 2


def test_rubric_superior_avanza_de_inmediato() -> None:
    structured = {"rubric_level": "superior", "advance_to_next_question": False}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 1, "turns_for_current_question": 0},
        structured=structured,
    )
    assert overridden is True
    assert out["advance_to_next_question"] is True


def test_satisfactorio_con_n2_avanza() -> None:
    structured = {"rubric_level": "satisfactorio", "advance_to_next_question": False}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 1, "turns_for_current_question": 2},
        structured=structured,
    )
    assert overridden is True
    assert out["advance_to_next_question"] is True


def test_avance_del_modelo_en_q3_se_convierte_en_resumen_final() -> None:
    # El modelo decidió avanzar estando en la última pregunta → se cierra.
    structured = {"rubric_level": "satisfactorio", "advance_to_next_question": True}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 3, "turns_for_current_question": 1},
        structured=structured,
    )
    assert overridden is True
    assert out["is_final_summary"] is True
    assert out["advance_to_next_question"] is False


def test_satisfactorio_con_n1_no_avanza() -> None:
    structured = {"rubric_level": "satisfactorio", "advance_to_next_question": False}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 1, "turns_for_current_question": 1},
        structured=structured,
    )
    assert overridden is False
    assert out["advance_to_next_question"] is False


def test_si_el_modelo_ya_avanzo_no_hay_override() -> None:
    structured = {"rubric_level": "excelente", "advance_to_next_question": True}
    out, overridden = apply_hard_rules(
        MAIA_RULES,
        state={"current_question": 1, "turns_for_current_question": 1},
        structured=structured,
    )
    assert overridden is False  # el valor ya era el requerido
    assert out["advance_to_next_question"] is True


def test_sin_state_las_reglas_de_state_no_aplican() -> None:
    structured = {"rubric_level": "pobre", "advance_to_next_question": False}
    out, overridden = apply_hard_rules(MAIA_RULES, state=None, structured=structured)
    assert overridden is False
    assert out == structured


def test_sin_structured_no_hay_nada_que_forzar() -> None:
    out, overridden = apply_hard_rules(MAIA_RULES, state={"x": 1}, structured=None)
    assert out is None
    assert overridden is False


def test_path_ausente_y_tipos_raros_no_rompen() -> None:
    rules = [
        HardRule(when={"state.faltante": {"gte": 1}}, set={"x": True}),
        HardRule(when={"structured.nivel": {"gte": 2}}, set={"x": True}),  # nivel es string
        HardRule(when={"sin_prefijo": {"eq": 1}}, set={"x": True}),
        HardRule(when={"state.n": {"operador_inventado": 1}}, set={"x": True}),
    ]
    structured = {"nivel": "alto"}
    out, overridden = apply_hard_rules(rules, state={"n": 5}, structured=structured)
    assert overridden is False
    assert "x" not in out


def test_regla_sin_condiciones_se_ignora() -> None:
    rules = [HardRule(when={}, set={"advance_to_next_question": True})]
    _out, overridden = apply_hard_rules(
        rules, state={}, structured={"advance_to_next_question": False}
    )
    assert overridden is False


def test_condiciones_se_evaluan_contra_snapshot_original() -> None:
    # La regla 2 lee un campo que la regla 1 modifica — debe ver el ORIGINAL.
    rules = [
        HardRule(when={"state.n": {"gte": 1}}, set={"flag": True}),
        HardRule(when={"structured.flag": {"eq": True}}, set={"otro": True}),
    ]
    out, _ = apply_hard_rules(rules, state={"n": 5}, structured={"flag": False})
    assert out["flag"] is True
    assert "otro" not in out  # no vio el flag ya modificado
