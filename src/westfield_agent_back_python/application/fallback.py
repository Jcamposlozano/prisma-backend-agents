"""
Modo fallback offline — respuestas plantilladas cuando OpenAI no está
disponible (sin API key, error de red, índice no cargado, etc.).

Es intencional que el endpoint /api/maia NUNCA tire 500 por falta de OpenAI:
el showcase debe seguir funcional en demos sin internet. El frontend recibe
`fallback: true` para mostrar un banner discreto pero el chat sigue vivo.

Port literal de buildFallbackResponse en Westfield_agent/server/maia-core.ts.
"""

from __future__ import annotations

from westfield_agent_back_python.domain.responses import (
    CurrentQuestion,
    MaiaResponse,
    MaiaTurn,
)

# Aperturas plantilladas para cada una de las 3 preguntas de introspección.
# Genéricas — el caso real (Etsy) entra por RAG, no por estos textos.
FALLBACK_OPENINGS: dict[CurrentQuestion, str] = {
    1: "Empezamos. Para vos, ¿dónde está exactamente el problema central del caso, y cuáles son las alternativas reales?",
    2: "Pasemos a la segunda pregunta. ¿Qué aporta la plataforma a quienes participan, y cómo se puede aprovechar ese potencial?",
    3: "Última pregunta. Si la organización fuera 100 o 1.000 veces más grande, ¿habría un efecto positivo para el planeta y la comunidad? Defendelo.",
}

# Pool de seguimientos socráticos. Se rota por índice para no repetir el
# mismo follow-up dos veces seguidas.
FALLBACK_FOLLOWUPS: list[str] = [
    "¿Qué supuesto estás haciendo aquí? ¿Siempre se cumple?",
    "¿Qué evidencia del caso respalda eso? Dame fuente y página.",
    "¿Cómo conectas esa idea con tu conclusión? Hay un salto lógico.",
    "¿Qué pasaría si una de esas variables cambia? ¿La conclusión sigue?",
    "¿Cómo lo vería un crítico que no comparte tu tesis?",
    "¿Qué diferencia hay entre lo que estás describiendo y un síntoma del problema?",
]


def build_fallback_response(history: list[MaiaTurn]) -> MaiaResponse:
    """
    Construye una respuesta plantillada en función del estado del histórico.

    Heurística:
      - `current_question` avanza ~cada 4 turnos del estudiante (paridad Node).
      - Si el histórico está vacío → opening de Q1.
      - Si el último turno fue del estudiante → followup socrático.
      - Si el último turno fue de Maia → opening de la pregunta actual.
    """
    student_turns = sum(1 for h in history if h.role == "student")
    current_question_raw = min(3, student_turns // 4 + 1)
    # Garantiza el tipo Literal[1,2,3].
    if current_question_raw == 2:
        current_question: CurrentQuestion = 2
    elif current_question_raw == 3:
        current_question = 3
    else:
        current_question = 1

    if not history:
        return MaiaResponse(
            message=FALLBACK_OPENINGS[1],
            rubric_level="satisfactorio",
            current_question=1,
            advance_to_next_question=False,
            is_final_summary=False,
            unresolved_points=[],
            fallback=True,
        )

    last_was_student = history[-1].role == "student"
    followup_idx = (len(history) + student_turns) % len(FALLBACK_FOLLOWUPS)
    followup = FALLBACK_FOLLOWUPS[followup_idx]

    message = followup if last_was_student else FALLBACK_OPENINGS[current_question]

    return MaiaResponse(
        message=message,
        rubric_level="satisfactorio",
        current_question=current_question,
        advance_to_next_question=False,
        is_final_summary=False,
        unresolved_points=[],
        fallback=True,
    )
